from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from src.templates.schemas import TemplateCreate, TemplateUpdate, Template, TemplatePreviewRequest, TestSendRequest
from src.templates.service import TemplateService
from src.auth.dependencies import get_current_active_user
from src.pagination import PaginatedResponse

router = APIRouter(prefix="/templates", tags=["Templates"])

@router.post("/", response_model=Template)
async def create_template(template: TemplateCreate, current_user: dict = Depends(get_current_active_user)):
    return await TemplateService.create_template(template, current_user["id"])

@router.get("/", response_model=PaginatedResponse[Template])
async def list_templates(type: Optional[str] = None, skip: int = 0, limit: int = 100, current_user: dict = Depends(get_current_active_user)):
    return await TemplateService.get_templates(current_user["id"], type, skip=skip, limit=limit)

@router.get("/fields")
async def get_merge_fields():
    return await TemplateService.get_available_fields()

@router.get("/{id}", response_model=Template)
async def get_template(id: str, current_user: dict = Depends(get_current_active_user)):
    template = await TemplateService.get_template_by_id(id, current_user["id"])
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    # Check visibility: template is visible if it's common or created by current user
    is_common = template.get("is_common", False)
    is_creator = template.get("created_by") == current_user["id"]

    print(is_common, is_creator)
    
    if not (is_common or is_creator):
        raise HTTPException(status_code=403, detail="You don't have permission to view this template")
    
    return template

@router.put("/{id}", response_model=Template)
async def update_template(id: str, template: TemplateUpdate, current_user: dict = Depends(get_current_active_user)):
    existing = await TemplateService.get_template_by_id(id, current_user["id"])
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")

    is_general = existing.get("is_common") is not False
    is_owner = existing.get("created_by") == current_user["id"]

    if is_general or not is_owner:
        # Fork into a user-owned custom copy rather than mutating a shared template
        from src.templates.schemas import TemplateCreate
        fork = TemplateCreate(
            name=template.name or f"{existing['name']} (Custom)",
            subject=template.subject or existing.get("subject") or "",
            body_html=template.body_html or existing["body_html"],
            design_json=template.design_json if template.design_json is not None else existing.get("design_json"),
            category=existing.get("category", "custom"),
            channel=existing.get("channel", "email"),
            is_common=False,
        )
        return await TemplateService.create_template(fork, current_user["id"])

    updated = await TemplateService.update_template(id, template, current_user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="Template not found or no changes made")
    return updated

@router.delete("/{id}")
async def delete_template(id: str, current_user: dict = Depends(get_current_active_user)):
    success = await TemplateService.delete_template(id, current_user["id"])
    if not success:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"message": "Template deleted successfully"}

@router.post("/preview")
async def preview_template(request: TemplatePreviewRequest, current_user: dict = Depends(get_current_active_user)):
    rendered_body = await TemplateService.render_template(request.template_id, request.sample_data)
    if rendered_body is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"rendered_body": rendered_body}

@router.post("/{id}/test-send")
async def test_send_template(id: str, request: TestSendRequest, current_user: dict = Depends(get_current_active_user)):
    result = await TemplateService.test_send(id, current_user["id"], request.email, request.sample_data)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result

@router.get("/{id}/history")
async def get_template_history(id: str, current_user: dict = Depends(get_current_active_user)):
    return await TemplateService.get_template_history(id)

@router.post("/{id}/rollback/{version}", response_model=Template)
async def rollback_template(id: str, version: int, current_user: dict = Depends(get_current_active_user)):
    updated = await TemplateService.rollback_template(id, version, current_user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="Template or version not found")
    return updated
