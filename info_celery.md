# Celery Setup and Usage

This document explains how to use Celery for background tasks in the CCIRP-be project.

## Configuration
Celery is configured in `src/config.py` and initialized in `src/celery_app.py`.
- **Broker**: Redis (default: `redis://localhost:6379/1`)
- **Backend**: Redis (default: `redis://localhost:6379/1`)

## Running Celery Worker
To start the Celery worker, run the following command from the root directory:
```bash
celery -A src.celery_app worker --loglevel=info
```

## Running Celery Beat (Scheduler)
To start the periodic task scheduler:
```bash
celery -A src.celery_app beat --loglevel=info
```
Beat runs `ccirp.scheduler_tick` every `CAMPAIGN_SCHEDULER_INTERVAL_SECONDS` (configured in `.env`).

## Defining Tasks
You can define tasks in any module that is included in `autodiscover_tasks`. Currently, it scans:
- `src.utils`
- `src.communication`
- `src.reminders`

Tasks that use async MongoDB operations must bridge into sync Celery using `asyncio.run()`:
```python
import asyncio
from src.celery_app import celery_app
from src.database import connect_to_mongo, close_mongo_connection

async def _with_db(body):
    await connect_to_mongo()
    try:
        return await body()
    finally:
        await close_mongo_connection()

@celery_app.task(name="ccirp.my_task")
def my_task(campaign_id: str) -> dict:
    async def body():
        # async Motor/MongoDB logic here
        return {"status": "done"}
    return asyncio.run(_with_db(body))
```

### Registered Tasks
| Task name | Module | Trigger |
|---|---|---|
| `ccirp.dispatch_campaign` | `src/utils/tasks.py` | `dispatch_campaign_task.delay(campaign_id)` |
| `ccirp.scheduler_tick` | `src/utils/tasks.py` | Celery Beat (periodic) |
| `ccirp.send_reminder` | `src/utils/tasks.py` | `send_reminder_task.delay(reminder_id)` |

## Calling Tasks
To call a task asynchronously:
```python
from src.utils.tasks import dispatch_campaign_task

dispatch_campaign_task.delay("campaign_abc")
```

## Monitoring
You can use **Flower** to monitor your Celery tasks:
```bash
pip install flower
celery -A src.celery_app flower
```
Access the dashboard at `http://localhost:5555`.
