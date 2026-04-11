from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, status

from src.auth.dependencies import get_current_active_user
from src.groups.schemas import (
    DynamicGroupPreferenceResponse,
    DynamicGroupPreferenceUpsert,
    DynamicGroupResolvePayload,
    DynamicGroupResolveResponse,
    StaticGroupCreate,
    StaticGroupCsvImportResponse,
    StaticGroupResponse,
    StaticGroupUpdate,
)
from src.groups.service import (
    create_static_group,
    delete_static_group,
    import_static_group_csv,
    list_dynamic_group_preferences,
    get_static_group,
    list_static_groups,
    resolve_dynamic_group_payload,
    upsert_dynamic_group_preference,
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


@router.get("/dynamic/preferences", response_model=List[DynamicGroupPreferenceResponse])
async def list_dynamic_group_preferences_endpoint(current_user: dict = Depends(get_current_active_user)):
    return await list_dynamic_group_preferences(current_user["id"])


@router.post("/dynamic/preferences", response_model=DynamicGroupPreferenceResponse, status_code=status.HTTP_201_CREATED)
async def upsert_dynamic_group_preference_endpoint(
    payload: DynamicGroupPreferenceUpsert,
    current_user: dict = Depends(get_current_active_user),
):
    return await upsert_dynamic_group_preference(current_user["id"], payload)


@router.post("/dynamic/resolve", response_model=DynamicGroupResolveResponse)
async def resolve_dynamic_groups_endpoint(
    payload: DynamicGroupResolvePayload,
    current_user: dict = Depends(get_current_active_user),
):
    return {"groups": await resolve_dynamic_group_payload(current_user["id"], payload.groups)}


@router.post("/import-csv", response_model=StaticGroupCsvImportResponse)
async def import_static_group_csv_endpoint(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_active_user),
):
    if not file.filename or not file.filename.endswith(".csv"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="File must be a CSV")
    return await import_static_group_csv(current_user["id"], file)


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
