from celery import Celery
from src.config import settings

celery_app = Celery(
    "ccirp_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Autodiscover tasks from all registered apps in src
celery_app.autodiscover_tasks(["src.utils", "src.communication", "src.reminders"])

@celery_app.task(name="debug_task")
def debug_task():
    print("Celery debug task executed successfully!")
    return {"status": "success"}
