from src.celery_app import celery_app

@celery_app.task(name="test_task")
def test_task(name: str):
    print(f"Executing test task for {name}")
    return {"status": "success", "name": name}
