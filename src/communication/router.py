import re
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from bson import ObjectId

from src.config import settings
from src.communication.tracking_utils import inject_tracking
from src.communication.schemas import CampaignCreate, CampaignResponse
from src.communication.models import CampaignDB
from src.communication.email_service import EmailService
from src.auth.dependencies import get_current_active_user
from src.database import get_database

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


def render_template(body_html: str, merge_data: dict, recipient_email: str, recipient_data: dict) -> str:
    """Replace all {{field}} merge fields in the template body."""
    rendered = body_html
    
    # Start with campaign-level merge data (organization_name, event_name, etc.)
    all_fields = dict(merge_data)
    
    # Add/override with recipient-specific fields
    all_fields["email"] = recipient_email
    all_fields["recipient_email"] = recipient_email
    full_name = recipient_data.get("full_name", recipient_email.split("@")[0])
    all_fields["name"] = full_name
    all_fields["full_name"] = full_name
    all_fields["recipient_name"] = full_name
    all_fields["first_name"] = full_name.split(" ")[0] if full_name else ""
    
    # Replace all {{field}} patterns
    for key, value in all_fields.items():
        rendered = re.sub(r"\{\{\s*" + re.escape(key) + r"\s*\}\}", str(value), rendered, flags=re.IGNORECASE)
    
    return rendered


async def dispatch_campaign_emails(campaign_id: str, owner_user_id: str, template: dict, recipients: List[str], subject: str, merge_data: dict):
    """Background task to send emails to all recipients and update campaign status."""
    db = get_database()
    body_html = template.get("body_html", "")
    
    # Look up recipient user data for merge fields
    recipient_data_map = {}
    if recipients:
        users_cursor = db["users"].find({"email": {"$in": recipients}})
        users_list = await users_cursor.to_list(length=1000)
        for u in users_list:
            recipient_data_map[u["email"]] = u

    failed = []
    for email in recipients:
        user_data = recipient_data_map.get(email, {})
        rendered_body = render_template(body_html, merge_data, email, user_data)
        tracked_body = inject_tracking(rendered_body, campaign_id, email, owner_user_id, settings.TRACKING_BASE_URL)
        success, msg = await EmailService.send_email([email], subject, tracked_body)
        if not success:
            print(f"Failed to send to {email}: {msg}")
            failed.append(email)
    
    # Update campaign status
    new_status = "sent" if not failed else ("partially_sent" if len(failed) < len(recipients) else "failed")
    try:
        await db["campaigns"].update_one(
            {"_id": ObjectId(campaign_id)},
            {"$set": {"status": new_status}}
        )
    except Exception:
        await db["campaigns"].update_one(
            {"_id": campaign_id},
            {"$set": {"status": new_status}}
        )
    print(f"Campaign {campaign_id} dispatch complete. Status: {new_status}. Failed: {len(failed)}/{len(recipients)}")


@router.post("/", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    campaign_in: CampaignCreate,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_active_user),
):
    db = get_database()
    
    try:
        # Verify template exists
        try:
            template = await db["templates"].find_one({"_id": ObjectId(campaign_in.template_id)})
        except Exception:
            template = await db["templates"].find_one({"_id": campaign_in.template_id})
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
            
        campaign_db = CampaignDB(
            **campaign_in.model_dump(),
            created_by=current_user["id"]
        )
        
        campaign_dict = campaign_db.model_dump(by_alias=True, exclude_none=True)
        result = await db["campaigns"].insert_one(campaign_dict)
        campaign_id = str(result.inserted_id)
        campaign_dict["id"] = campaign_id

        # Dispatch emails in background
        subject = campaign_in.subject or template.get("subject", "No Subject")
        if campaign_in.recipients:
            background_tasks.add_task(
                dispatch_campaign_emails,
                campaign_id,
                current_user["id"],
                template,
                campaign_in.recipients,
                subject,
                campaign_in.merge_data or {},
            )
        
        return campaign_dict
    except Exception as e:
        print(f"ERROR creating campaign: {str(e)}")
        import traceback
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", response_model=List[CampaignResponse])
async def list_campaigns(current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    cursor = db["campaigns"].find({"created_by": current_user["id"]})
    campaigns = await cursor.to_list(length=100)
    
    for camp in campaigns:
        camp["id"] = str(camp["_id"])
        
    return campaigns


@router.get("/stats", response_model=dict)
async def get_campaign_stats(current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    pipeline = [
        {"$match": {"created_by": current_user["id"]}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    results = await db["campaigns"].aggregate(pipeline).to_list(length=100)
    stats = {r["_id"]: r["count"] for r in results}
    stats["total"] = sum(stats.values())
    return stats


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: str, current_user: dict = Depends(get_current_active_user)):
    db = get_database()
    try:
        query = {"_id": ObjectId(campaign_id)}
    except Exception:
        query = {"_id": campaign_id}
        
    campaign = await db["campaigns"].find_one(query)
    
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
        
    if campaign["created_by"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to view this campaign")
        
    campaign["id"] = str(campaign["_id"])
    return campaign
