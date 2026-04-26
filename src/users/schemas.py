from pydantic import BaseModel, EmailStr, field_serializer
from typing import Optional
from datetime import datetime

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    phone: str

class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    phone: Optional[str] = None
    role: str
    is_active: bool
    tracking_consent: bool = True
    created_at: Optional[datetime] = None

    @field_serializer('created_at')
    def serialize_created_at(self, v: Optional[datetime]) -> Optional[str]:
        return v.isoformat() if v else None

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    tracking_consent: Optional[bool] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    
class TokenData(BaseModel):
    email: Optional[str] = None
