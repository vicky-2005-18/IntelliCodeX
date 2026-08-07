"""
Auth API Router (Phase 11)
Endpoints for user registration, authentication, login, and current user info.
"""
import uuid
from fastapi import APIRouter, HTTPException, Depends, status
from backend.auth import (
    User, UserRegister, UserLogin, TokenResponse,
    hash_password, verify_password, create_access_token, get_current_user
)
from backend.database import db_manager

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
def register(req: UserRegister):
    existing = db_manager.find_one("users", {"username": req.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username is already registered.")

    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    hashed_pwd = hash_password(req.password)

    user_record = {
        "id": user_id,
        "username": req.username,
        "email": req.email,
        "role": req.role or "developer",
        "hashed_password": hashed_pwd,
    }
    db_manager.insert("users", user_record)

    user = User(id=user_id, username=req.username, email=req.email, role=user_record["role"])
    token = create_access_token(user)

    return TokenResponse(access_token=token, user=user)


@router.post("/login", response_model=TokenResponse)
def login(req: UserLogin):
    user_record = db_manager.find_one("users", {"username": req.username})
    if not user_record or not verify_password(req.password, user_record["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    user = User(
        id=user_record["id"],
        username=user_record["username"],
        email=user_record["email"],
        role=user_record.get("role", "developer")
    )
    token = create_access_token(user)

    return TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=User)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
