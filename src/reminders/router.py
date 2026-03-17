from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from src.reminders.schemas import ReminderCreate, ReminderUpdate, Reminder
from src.reminders.service import ReminderService
from src.auth.dependencies import get_current_active_user

router = APIRouter(prefix="/reminders", tags=["Reminders"])

@router.post("/", response_model=Reminder)
async def create_reminder(reminder: ReminderCreate, current_user: dict = Depends(get_current_active_user)):
    return await ReminderService.create_reminder(reminder, current_user["id"])

@router.get("/", response_model=List[Reminder])
async def list_reminders(current_user: dict = Depends(get_current_active_user)):
    return await ReminderService.get_reminders(current_user["id"])

@router.get("/{id}", response_model=Reminder)
async def get_reminder(id: str, current_user: dict = Depends(get_current_active_user)):
    reminder = await ReminderService.get_reminder_by_id(id, current_user["id"])
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return reminder

@router.put("/{id}", response_model=Reminder)
async def update_reminder(id: str, reminder: ReminderUpdate, current_user: dict = Depends(get_current_active_user)):
    updated = await ReminderService.update_reminder(id, reminder, current_user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="Reminder not found or no changes made")
    return updated

@router.delete("/{id}")
async def delete_reminder(id: str, current_user: dict = Depends(get_current_active_user)):
    success = await ReminderService.delete_reminder(id, current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"message": "Reminder deleted successfully"}
