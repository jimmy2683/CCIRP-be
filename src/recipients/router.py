from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from src.auth.dependencies import get_current_user
from src.recipients.schemas import RecipientCreate, RecipientUpdate, RecipientResponse
from src.recipients.service import (
    create_recipient,
    get_recipients,
    get_recipient,
    update_recipient,
    delete_recipient
)

router = APIRouter(prefix="/recipients", tags=["recipients"])

@router.post("/", response_model=RecipientResponse, status_code=status.HTTP_201_CREATED)
async def create_recipient_endpoint(
    recipient: RecipientCreate,
    current_user: dict = Depends(get_current_user)
):
    return await create_recipient(current_user["id"], recipient)

@router.get("/", response_model=List[RecipientResponse])
async def read_recipients(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    return await get_recipients(current_user["id"], skip=skip, limit=limit)

@router.get("/{recipient_id}", response_model=RecipientResponse)
async def read_recipient(
    recipient_id: str,
    current_user: dict = Depends(get_current_user)
):
    return await get_recipient(current_user["id"], recipient_id)

@router.put("/{recipient_id}", response_model=RecipientResponse)
async def update_recipient_endpoint(
    recipient_id: str,
    update_data: RecipientUpdate,
    current_user: dict = Depends(get_current_user)
):
    return await update_recipient(current_user["id"], recipient_id, update_data)

@router.delete("/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient_endpoint(
    recipient_id: str,
    current_user: dict = Depends(get_current_user)
):
    await delete_recipient(current_user["id"], recipient_id)
    return None
