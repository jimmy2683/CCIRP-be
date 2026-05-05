"""
Shared pytest fixtures for Celery and Kafka tests.
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def celery_eager():
    """
    Make Celery tasks execute synchronously in the current process.
    This allows testing task logic without a running worker.
    """
    from src.celery_app import celery_app

    celery_app.conf.update(
        task_always_eager=True,
        task_eager_propagates=True,
    )
    yield
    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
    )


@pytest.fixture()
def mock_db_connect():
    """Patch MongoDB connect/disconnect so tasks don't need a live DB."""
    with (
        patch("src.database.connect_to_mongo", new_callable=AsyncMock) as mock_connect,
        patch("src.database.close_mongo_connection", new_callable=AsyncMock) as mock_close,
    ):
        yield mock_connect, mock_close


@pytest.fixture()
def mock_kafka():
    """
    Patch the kafka_manager reference used by src.events so that published
    events are captured without hitting a real Kafka broker.
    """
    with patch("src.events.kafka_manager") as mock_mgr:
        mock_mgr.produce_message.return_value = True
        yield mock_mgr
