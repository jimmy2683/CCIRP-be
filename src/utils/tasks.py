"""
Celery tasks for CCIRP background processing.

Each task uses asyncio.run() so the async business logic (Motor/MongoDB)
runs inside a fresh event loop per task invocation. A new DB connection
is established at the start and torn down at the end of every task.
"""
import asyncio
import logging

from src.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _with_db(body):
    """Open a MongoDB connection, run body(), then close the connection."""
    from src.database import close_mongo_connection, connect_to_mongo

    await connect_to_mongo()
    try:
        return await body()
    finally:
        await close_mongo_connection()


@celery_app.task(name="ccirp.dispatch_campaign", max_retries=3, default_retry_delay=60)
def dispatch_campaign_task(campaign_id: str) -> dict:
    """
    Enqueue recipients for a campaign and process the priority dispatch queue
    until all jobs are consumed. Publishes Kafka events on start and completion.
    """
    async def body():
        from src.communication.service import (
            enqueue_campaign_recipients,
            process_campaign_priority_queues_once,
        )
        from src.events import publish_campaign_event

        enqueued = await enqueue_campaign_recipients(campaign_id)
        if enqueued == 0:
            publish_campaign_event(
                "dispatch_skipped",
                campaign_id,
                {"reason": "no_recipients_enqueued"},
            )
            return {"campaign_id": campaign_id, "enqueued": 0, "processed": 0}

        publish_campaign_event("dispatch_started", campaign_id, {"enqueued": enqueued})

        processed = 0
        while True:
            batch = await process_campaign_priority_queues_once(campaign_id=campaign_id)
            processed += batch
            if batch == 0:
                break

        publish_campaign_event(
            "dispatch_completed",
            campaign_id,
            {"enqueued": enqueued, "processed": processed},
        )
        return {"campaign_id": campaign_id, "enqueued": enqueued, "processed": processed}

    try:
        return asyncio.run(_with_db(body))
    except Exception as exc:
        logger.error("dispatch_campaign_task failed for %s: %s", campaign_id, exc)
        raise


@celery_app.task(name="ccirp.scheduler_tick", max_retries=1)
def process_scheduler_tick_task() -> dict:
    """
    Run one scheduler iteration: prepare any pending campaign queues,
    requeue stale processing jobs, then process available queue items.
    Intended to be called periodically (e.g., via Celery Beat).
    """
    async def body():
        from src.communication.service import (
            _prepare_pending_campaign_queues_once,
            _requeue_stale_processing_jobs_once,
            process_campaign_priority_queues_once,
        )

        prepared = await _prepare_pending_campaign_queues_once()
        requeued = await _requeue_stale_processing_jobs_once()
        processed = await process_campaign_priority_queues_once()
        return {"prepared": prepared, "requeued": requeued, "processed": processed}

    return asyncio.run(_with_db(body))


@celery_app.task(name="ccirp.send_reminder", max_retries=3, default_retry_delay=30)
def send_reminder_task(reminder_id: str) -> dict:
    """
    Send a reminder notification. The reminder service is scaffolded;
    this task resolves the reminder document and updates its status.
    """
    async def body():
        from bson import ObjectId

        from src.database import get_database

        db = get_database()
        try:
            reminder = await db["reminders"].find_one({"_id": ObjectId(reminder_id)})
        except Exception:
            reminder = await db["reminders"].find_one({"_id": reminder_id})

        if not reminder:
            return {"reminder_id": reminder_id, "status": "not_found"}

        # Full reminder dispatch logic goes here when the reminders service is completed.
        return {"reminder_id": reminder_id, "status": "processed"}

    try:
        return asyncio.run(_with_db(body))
    except Exception as exc:
        logger.error("send_reminder_task failed for %s: %s", reminder_id, exc)
        raise
