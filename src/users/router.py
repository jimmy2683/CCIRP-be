from fastapi import APIRouter, Depends
from typing import List
from src.users.schemas import UserResponse
from src.users.service import UserService
from src.auth.dependencies import get_current_active_user

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/", response_model=List[UserResponse])
async def list_users(current_user: dict = Depends(get_current_active_user)):
    return await UserService.list_users()
