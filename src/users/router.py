from fastapi import APIRouter, Depends
from typing import List
from src.users.schemas import UserResponse
from src.users.service import UserService
from src.auth.dependencies import get_current_active_user
from src.pagination import PaginatedResponse

router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/", response_model=PaginatedResponse[UserResponse])
async def list_users(skip: int = 0, limit: int = 100, current_user: dict = Depends(get_current_active_user)):
    return await UserService.list_users(skip=skip, limit=limit)
