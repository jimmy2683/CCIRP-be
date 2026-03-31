from typing import List, Optional
from bson import ObjectId
from datetime import datetime
from src.database import get_database
from src.templates.schemas import TemplateCreate, TemplateUpdate
from src.communication.email_service import EmailService

class TemplateService:
    @staticmethod
    async def create_template(template_data: TemplateCreate, created_by: str) -> dict:
        db = get_database()
        new_template = template_data.model_dump()
        new_template["created_by"] = created_by
        new_template["created_at"] = datetime.utcnow()
        new_template["updated_at"] = datetime.utcnow()
        new_template["version"] = 1
        
        result = await db.templates.insert_one(new_template)
        new_template["_id"] = str(result.inserted_id)
        return new_template

    @staticmethod
    async def get_templates(current_user_id: Optional[str] = None, type: Optional[str] = None) -> List[dict]:
        db = get_database()
        
        # Build filter: include common templates OR templates created by current user
        query_parts = []
        
        if type == "custom" and current_user_id:
            # Only user's private templates
            filter_query = {"created_by": current_user_id, "is_common": False}
        elif type == "general":
            # Only common templates (everything not explicitly private)
            filter_query = {"is_common": {"$ne": False}}
        else:
            # Fallback to current behavior: common OR user's templates
            if current_user_id:
                filter_query = {
                    "$or": [
                        {"is_common": {"$ne": False}},
                        {"created_by": current_user_id}
                    ]
                }
            else:
                filter_query = {"is_common": {"$ne": False}}
        
        cursor = db.templates.find(filter_query)
        documents = await cursor.to_list(length=100)
        templates = []
        for document in documents:
            document["_id"] = str(document["_id"])
            templates.append(document)
        return templates

    @staticmethod
    async def get_template_by_id(template_id: str, current_user_id: Optional[str] = None) -> Optional[dict]:
        db = get_database()
        if not ObjectId.is_valid(template_id):
            return None
        
        # Check if template exists
        template = await db.templates.find_one({"_id": ObjectId(template_id)})
        if not template:
            return None
            
        # Permission logic:
        # 1. If it's a common template (is_common is not False), anyone can see it
        # 2. If it's private, only the creator can see it
        is_common = template.get("is_common") != False
        if is_common or (current_user_id and template.get("created_by") == current_user_id):
            template["_id"] = str(template["_id"])
            return template
            
        return None

    @staticmethod
    async def update_template(template_id: str, template_data: TemplateUpdate, current_user_id: str) -> Optional[dict]:
        db = get_database()
        if not ObjectId.is_valid(template_id):
            return None
            
        # Strictly enforce that only the creator can update a template
        # If it's a general/system template (no created_by or is_common: true), 
        # regular users won't match this and thus cannot update it.
        template = await db.templates.find_one({
            "_id": ObjectId(template_id), 
            "created_by": current_user_id
        })
        
        if not template:
            return None

        update_data = {k: v for k, v in template_data.model_dump().items() if v is not None}
        if not update_data:
            return await TemplateService.get_template_by_id(template_id, current_user_id)
            
        update_data["updated_at"] = datetime.utcnow()
        
        # Increment version number
        result = await db.templates.update_one(
            {"_id": ObjectId(template_id)},
            {
                "$set": update_data,
                "$inc": {"version": 1}
            }
        )
        
        if result.matched_count:
            return await TemplateService.get_template_by_id(template_id, current_user_id)
        return None

    @staticmethod
    async def delete_template(template_id: str, current_user_id: str) -> bool:
        db = get_database()
        if not ObjectId.is_valid(template_id):
            return False
            
        # Strictly enforce that only the creator can delete a template
        # and ensure it's not a common/general template
        result = await db.templates.delete_one({
            "_id": ObjectId(template_id), 
            "created_by": current_user_id,
            "is_common": {"$ne": True}
        })
        return result.deleted_count > 0

    @staticmethod
    async def render_template(template_id: str, current_user_id: str, sample_data: dict) -> Optional[str]:
        template = await TemplateService.get_template_by_id(template_id, current_user_id)
        if not template:
            return None
        
        # Inject standard helpers
        data = sample_data.copy()
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().strftime("%B %d, %Y %H:%M")
            
        body = template["body_html"]
        # Simple regex-based merge field replacement
        import re
        for key, value in data.items():
            placeholder = r"\{\{\s*" + re.escape(key) + r"\s*\}\}"
            body = re.sub(placeholder, str(value), body)
        
        return body

    @staticmethod
    async def test_send(template_id: str, current_user_id: str, email: str, sample_data: Optional[dict] = None) -> dict:
        db = get_database()
        
        template = await TemplateService.get_template_by_id(template_id, current_user_id)
        if not template:
            return {"success": False, "message": "Template not found"}

        if sample_data:
            data = sample_data
        else:
            # Fetch from UserDB to resolve merge fields
            user = await db.users.find_one({"email": email})
            data = {
                "name": user.get("full_name", email.split('@')[0]) if user else email.split('@')[0],
                "email": email,
                "role": user.get("role", "Recipient") if user else "Recipient",
                "incident_type": "Mock Security Advisory",
                "location": "Main Campus",
            }

        rendered_html = await TemplateService.render_template(template_id, current_user_id, data)
        
        success, message = await EmailService.send_email(
            to_emails=[email],
            subject=template.get("subject", "Test Email"),
            body_html=rendered_html
        )
        
        return {"success": success, "message": message, "rendered_html": rendered_html}

    @staticmethod
    async def get_template_history(template_id: str) -> List[dict]:
        db = get_database()
        if not ObjectId.is_valid(template_id):
            return []
        
        cursor = db.template_history.find({"template_id": ObjectId(template_id)}).sort("version", -1)
        documents = await cursor.to_list(length=50)
        history = []
        for document in documents:
            document["_id"] = str(document["_id"])
            document["template_id"] = str(document["template_id"])
            history.append(document)
        return history

    @staticmethod
    async def rollback_template(template_id: str, version: int) -> Optional[dict]:
        db = get_database()
        if not ObjectId.is_valid(template_id):
            return None
        
        # Find the version in history
        history_entry = await db.template_history.find_one({
            "template_id": ObjectId(template_id),
            "version": version
        })
        
        if not history_entry:
            return None
        
        # Save current state to history before rolling back (to allow undoing rollback)
        current_template = await db.templates.find_one({"_id": ObjectId(template_id)})
        if current_template:
            await db.template_history.insert_one({
                "template_id": ObjectId(template_id),
                "version": current_template["version"],
                "name": current_template["name"],
                "subject": current_template.get("subject"),
                "body_html": current_template["body_html"],
                "design_json": current_template.get("design_json"),
                "updated_at": current_template["updated_at"],
                "rollback_from": version
            })

        # Update current template with history content
        rollback_data = {
            "name": history_entry["name"],
            "subject": history_entry.get("subject"),
            "body_html": history_entry["body_html"],
            "design_json": history_entry.get("design_json"),
            "updated_at": datetime.utcnow()
        }
        
        await db.templates.update_one(
            {"_id": ObjectId(template_id)},
            {
                "$set": rollback_data,
                "$inc": {"version": 1}
            }
        )
        
        return await TemplateService.get_template_by_id(template_id)

    @staticmethod
    async def get_available_fields() -> List[dict]:
        # Defined fields based on UserDB and typical CCIRP metadata
        return [
            {"key": "name", "label": "Full Name", "description": "Recipient's display name", "example": "John Doe"},
            {"key": "email", "label": "Email Address", "description": "Recipient's primary email", "example": "john@example.com"},
            {"key": "role", "label": "User Role", "description": "System role (e.g., student, faculty)", "example": "Student"},
            {"key": "incident_type", "label": "Incident Type", "description": "Type of alert (for security templates)", "example": "Weather Alert"},
            {"key": "location", "label": "Location", "description": "Relevant campus location", "example": "Main Plaza"},
            {"key": "timestamp", "label": "System Timestamp", "description": "Current date and time", "example": "March 20, 2024"},
        ]
