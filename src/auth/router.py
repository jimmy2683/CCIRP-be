from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt

from src.auth.security import verify_password, get_password_hash, create_access_token, create_refresh_token
from src.auth.dependencies import get_current_active_user
from src.users.schemas import ChangePasswordRequest, UserCreate, UserProfileUpdate, UserResponse, Token
from src.users.models import UserDB
from src.users.service import UserService
from src.database import get_database
from src.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserCreate):
    db = get_database()
    
    # Check if user already exists
    existing_user = await db["users"].find_one({"email": user_in.email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    if len(user_in.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters"
        )

    phone = str(user_in.phone).strip()
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is required"
        )
        
    # Hash password and save
    hashed_password = get_password_hash(user_in.password)
    user_db = UserDB(
        email=user_in.email,
        hashed_password=hashed_password,
        full_name=user_in.full_name,
        phone=phone,
    )
    
    user_dict = user_db.model_dump(by_alias=True, exclude_none=True)
    result = await db["users"].insert_one(user_dict)
    
    # Format for response
    user_dict["id"] = str(result.inserted_id)
    user_dict["_id"] = result.inserted_id
    await UserService.sync_user_recipient(user_dict)
    return user_dict

@router.post("/login", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    db = get_database()
    
    # Form_data.username is standard for OAuth2 fields, we use it for email
    user = await db["users"].find_one({"email": form_data.username})
    
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    refresh_token = create_refresh_token(data={"sub": user["email"]})
    
    return {
        "access_token": access_token, 
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

@router.post("/token/refresh", response_model=Token)
async def refresh_access_token(token_data: dict):
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refresh token is missing"
        )
    
    try:
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate refresh token"
        )
        
    db = get_database()
    user = await db["users"].find_one({"email": email})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
        
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["email"]}, expires_delta=access_token_expires
    )
    
    # We can also rotate the refresh token here if desired
    new_refresh_token = create_refresh_token(data={"sub": user["email"]})
    
    return {
        "access_token": access_token, 
        "refresh_token": new_refresh_token,
        "token_type": "bearer"
    }

@router.get("/me", response_model=UserResponse)
async def read_users_me(current_user: dict = Depends(get_current_active_user)):
    return current_user

@router.put("/me", response_model=UserResponse)
async def update_current_user_profile(
    profile_data: UserProfileUpdate,
    current_user: dict = Depends(get_current_active_user),
):
    update_data = {}
    if profile_data.full_name is not None:
        full_name = profile_data.full_name.strip()
        if not full_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full name is required")
        update_data["full_name"] = full_name

    if profile_data.phone is not None:
        phone = profile_data.phone.strip()
        if not phone:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone number is required")
        update_data["phone"] = phone

    if profile_data.tracking_consent is not None:
        update_data["tracking_consent"] = profile_data.tracking_consent

    if not update_data:
        return current_user

    db = get_database()
    await db["users"].update_one({"_id": current_user["_id"]}, {"$set": update_data})
    updated_user = await db["users"].find_one({"_id": current_user["_id"]})
    updated_user["id"] = str(updated_user["_id"])
    await UserService.sync_user_recipient(updated_user)

    # Sync tracking consent to the user's own recipient record
    if profile_data.tracking_consent is not None:
        await db["recipients"].update_many(
            {"user_id": updated_user["id"], "email": updated_user["email"]},
            {"$set": {"consent_flags.tracking": profile_data.tracking_consent}},
        )

    return updated_user

@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_active_user),
):
    if len(password_data.new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 6 characters")

    if not verify_password(password_data.current_password, current_user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    db = get_database()
    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"hashed_password": get_password_hash(password_data.new_password)}},
    )
    return {"message": "Password updated successfully"}
