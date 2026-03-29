# Celery Setup and Usage

This document explains how to use Celery for background tasks in the CCIRP-be project.

## Configuration
Celery is configured in `src/config.py` and initialized in `src/celery_app.py`.
- **Broker**: Redis (default: `redis://localhost:6373/1`)
- **Backend**: Redis (default: `redis://localhost:6373/1`)

## Running Celery Worker
To start the Celery worker, run the following command from the root directory:
```bash
celery -A src.celery_app worker --loglevel=info
```

## Defining Tasks
You can define tasks in any module that is included in `autodiscover_tasks`. Currently, it scans:
- `src.utils`
- `src.communication`
- `src.reminders`

Example of defining a task in `src/utils/tasks.py`:
```python
from src.celery_app import celery_app

@celery_app.task(name="send_notification_task")
def send_notification_task(user_id, message):
    # Task logic here
    print(f"Sending notification to {user_id}: {message}")
    return {"status": "sent"}
```

## Calling Tasks
To call a task asynchronously:
```python
from src.utils.tasks import send_notification_task

send_notification_task.delay(user_id="123", message="Hello!")
```

## Monitoring
You can use **Flower** to monitor your Celery tasks:
```bash
pip install flower
celery -A src.celery_app flower
```
Access the dashboard at `http://localhost:5555`.
