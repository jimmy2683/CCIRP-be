from typing import List

from fastapi import APIRouter, Depends, status

from src.auth.dependencies import get_current_active_user
from src.groups.schemas import StaticGroupCreate, StaticGroupResponse, StaticGroupUpdate
from src.groups.service import (
    create_static_group,
    delete_static_group,
    get_static_group,
    list_static_groups,
    update_static_group,
)


router = APIRouter(prefix="/groups", tags=["Groups"])


@router.post("/", response_model=StaticGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_static_group_endpoint(
    group_data: StaticGroupCreate,
    current_user: dict = Depends(get_current_active_user),
):
    return await create_static_group(current_user["id"], group_data)


@router.get("/", response_model=List[StaticGroupResponse])
async def list_static_groups_endpoint(current_user: dict = Depends(get_current_active_user)):
    return await list_static_groups(current_user["id"])


@router.get("/{group_id}", response_model=StaticGroupResponse)
async def get_static_group_endpoint(
    group_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    return await get_static_group(current_user["id"], group_id)


@router.put("/{group_id}", response_model=StaticGroupResponse)
async def update_static_group_endpoint(
    group_id: str,
    group_data: StaticGroupUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    return await update_static_group(current_user["id"], group_id, group_data)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_static_group_endpoint(
    group_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    await delete_static_group(current_user["id"], group_id)
    return None
