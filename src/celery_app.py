from celery import Celery
from src.config import settings

celery_app = Celery(
    "ccirp_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Celery Beat schedule: run the scheduler tick every 15 seconds
    beat_schedule={
        "scheduler-tick": {
            "task": "ccirp.scheduler_tick",
            "schedule": settings.CAMPAIGN_SCHEDULER_INTERVAL_SECONDS,
        },
    },
)

# Autodiscover tasks from registered modules
celery_app.autodiscover_tasks(["src.utils", "src.communication", "src.reminders"])
