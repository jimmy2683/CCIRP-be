"""
Tests for Celery tasks (ccirp.dispatch_campaign, ccirp.scheduler_tick, ccirp.send_reminder).

Tasks are tested with task_always_eager=True so they execute synchronously
without a running worker. DB calls are mocked so no live MongoDB is needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch


# ── helpers ──────────────────────────────────────────────────────────────────

def _run_task(task_fn, *args, **kwargs):
    """Call a Celery task directly (eager mode makes .delay() equivalent)."""
    return task_fn(*args, **kwargs)


# ── dispatch_campaign_task ────────────────────────────────────────────────────

class TestDispatchCampaignTask:
    def test_registers_in_celery(self):
        from src.celery_app import celery_app
        from src.utils.tasks import dispatch_campaign_task

        assert "ccirp.dispatch_campaign" in celery_app.tasks

    def test_happy_path_returns_counts(self, mock_db_connect):
        """Enqueues 3 recipients, processes them in two batches (2 then 1), returns totals."""
        with (
            patch(
                "src.communication.service.enqueue_campaign_recipients",
                new_callable=AsyncMock,
                return_value=3,
            ) as mock_enqueue,
            patch(
                "src.communication.service.process_campaign_priority_queues_once",
                new_callable=AsyncMock,
                side_effect=[2, 1, 0],
            ) as mock_process,
            patch("src.events.publish_campaign_event", return_value=True),
        ):
            from src.utils.tasks import dispatch_campaign_task

            result = _run_task(dispatch_campaign_task, "campaign_abc")

        assert result == {"campaign_id": "campaign_abc", "enqueued": 3, "processed": 3}
        mock_enqueue.assert_called_once_with("campaign_abc")
        assert mock_process.call_count == 3  # [2, 1, 0] — stops on first zero

    def test_no_recipients_returns_zero_processed(self, mock_db_connect):
        """When enqueue returns 0 the task short-circuits without processing."""
        with (
            patch(
                "src.communication.service.enqueue_campaign_recipients",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.communication.service.process_campaign_priority_queues_once",
                new_callable=AsyncMock,
            ) as mock_process,
            patch("src.events.publish_campaign_event", return_value=True),
        ):
            from src.utils.tasks import dispatch_campaign_task

            result = _run_task(dispatch_campaign_task, "campaign_empty")

        assert result["enqueued"] == 0
        assert result["processed"] == 0
        mock_process.assert_not_called()

    def test_publishes_dispatch_started_and_completed(self, mock_db_connect):
        """Kafka events are published for dispatch_started and dispatch_completed."""
        published = []

        def capture_event(event_type, campaign_id, data=None):
            published.append((event_type, campaign_id, data))
            return True

        with (
            patch(
                "src.communication.service.enqueue_campaign_recipients",
                new_callable=AsyncMock,
                return_value=5,
            ),
            patch(
                "src.communication.service.process_campaign_priority_queues_once",
                new_callable=AsyncMock,
                side_effect=[5, 0],
            ),
            patch("src.events.publish_campaign_event", side_effect=capture_event),
        ):
            from src.utils.tasks import dispatch_campaign_task

            _run_task(dispatch_campaign_task, "campaign_xyz")

        event_types = [e[0] for e in published]
        assert "dispatch_started" in event_types
        assert "dispatch_completed" in event_types

        started = next(e for e in published if e[0] == "dispatch_started")
        assert started[2]["enqueued"] == 5

        completed = next(e for e in published if e[0] == "dispatch_completed")
        assert completed[2]["processed"] == 5

    def test_publishes_dispatch_skipped_when_no_recipients(self, mock_db_connect):
        """dispatch_skipped event is published when no recipients are enqueued."""
        published = []

        with (
            patch(
                "src.communication.service.enqueue_campaign_recipients",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.events.publish_campaign_event",
                side_effect=lambda *a, **kw: published.append(a[0]) or True,
            ),
        ):
            from src.utils.tasks import dispatch_campaign_task

            _run_task(dispatch_campaign_task, "campaign_skip")

        assert "dispatch_skipped" in published

    def test_raises_on_service_error(self, mock_db_connect):
        """If the dispatch service raises, the task propagates the exception."""
        with (
            patch(
                "src.communication.service.enqueue_campaign_recipients",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB gone"),
            ),
            patch("src.events.publish_campaign_event", return_value=True),
        ):
            from src.utils.tasks import dispatch_campaign_task

            with pytest.raises(RuntimeError, match="DB gone"):
                _run_task(dispatch_campaign_task, "campaign_err")

    def test_delay_dispatches_with_celery(self, mock_db_connect):
        """Calling .delay() with eager mode executes the task and returns an AsyncResult."""
        with (
            patch(
                "src.communication.service.enqueue_campaign_recipients",
                new_callable=AsyncMock,
                return_value=2,
            ),
            patch(
                "src.communication.service.process_campaign_priority_queues_once",
                new_callable=AsyncMock,
                side_effect=[2, 0],
            ),
            patch("src.events.publish_campaign_event", return_value=True),
        ):
            from src.utils.tasks import dispatch_campaign_task

            result = dispatch_campaign_task.delay("campaign_delay")

        assert result.get()["enqueued"] == 2


# ── process_scheduler_tick_task ───────────────────────────────────────────────

class TestSchedulerTickTask:
    def test_registers_in_celery(self):
        from src.celery_app import celery_app

        assert "ccirp.scheduler_tick" in celery_app.tasks

    def test_calls_all_three_scheduler_functions(self, mock_db_connect):
        """Scheduler tick must call prepare, requeue, and process in order."""
        with (
            patch(
                "src.communication.service._prepare_pending_campaign_queues_once",
                new_callable=AsyncMock,
                return_value=2,
            ) as mock_prepare,
            patch(
                "src.communication.service._requeue_stale_processing_jobs_once",
                new_callable=AsyncMock,
                return_value=1,
            ) as mock_requeue,
            patch(
                "src.communication.service.process_campaign_priority_queues_once",
                new_callable=AsyncMock,
                return_value=4,
            ) as mock_process,
        ):
            from src.utils.tasks import process_scheduler_tick_task

            result = _run_task(process_scheduler_tick_task)

        mock_prepare.assert_called_once()
        mock_requeue.assert_called_once()
        mock_process.assert_called_once()
        assert result == {"prepared": 2, "requeued": 1, "processed": 4}

    def test_returns_zero_counts_when_nothing_pending(self, mock_db_connect):
        with (
            patch(
                "src.communication.service._prepare_pending_campaign_queues_once",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.communication.service._requeue_stale_processing_jobs_once",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "src.communication.service.process_campaign_priority_queues_once",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            from src.utils.tasks import process_scheduler_tick_task

            result = _run_task(process_scheduler_tick_task)

        assert result == {"prepared": 0, "requeued": 0, "processed": 0}


# ── send_reminder_task ────────────────────────────────────────────────────────

class TestSendReminderTask:
    def test_registers_in_celery(self):
        from src.celery_app import celery_app

        assert "ccirp.send_reminder" in celery_app.tasks

    def test_returns_not_found_for_missing_reminder(self, mock_db_connect):
        mock_db = MagicMock()
        mock_db["reminders"].find_one = AsyncMock(return_value=None)

        with patch("src.database.get_database", return_value=mock_db):
            from src.utils.tasks import send_reminder_task

            result = _run_task(send_reminder_task, "nonexistent_id")

        assert result["status"] == "not_found"

    def test_returns_processed_for_existing_reminder(self, mock_db_connect):
        mock_db = MagicMock()
        mock_db["reminders"].find_one = AsyncMock(return_value={"_id": "rem1", "message": "hi"})

        with patch("src.database.get_database", return_value=mock_db):
            from src.utils.tasks import send_reminder_task

            result = _run_task(send_reminder_task, "rem1")

        assert result["status"] == "processed"


# ── Celery Beat schedule ──────────────────────────────────────────────────────

class TestCeleryBeatSchedule:
    def test_scheduler_tick_in_beat_schedule(self):
        from src.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert "scheduler-tick" in schedule
        assert schedule["scheduler-tick"]["task"] == "ccirp.scheduler_tick"
