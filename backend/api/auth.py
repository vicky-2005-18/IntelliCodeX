"""
Auth API Router (Phase 11)
Endpoints for user registration, authentication, login, current user info,
and admin-only user promotion.
"""
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status, Request
from pydantic import BaseModel
from backend.auth import (
    User, UserRegister, UserLogin, TokenResponse,
    hash_password, verify_password,
    create_access_token, get_current_user, require_role,
    check_login_rate_limit, record_failed_login, clear_login_rate_limit
)
from backend.database import db_manager
from backend.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


class UserPromote(BaseModel):
    user_id: Optional[str] = None
    username: Optional[str] = None
    role: str = "admin"  # "admin" | "developer"


@router.post("/register", response_model=TokenResponse)
def register(req: UserRegister):
    if len(req.password) < 10:
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 10 characters long.",
        )

    existing = db_manager.find_one("users", {"username": req.username})
    if existing:
        raise HTTPException(status_code=400, detail="Username is already registered.")

    user_id = f"usr_{uuid.uuid4().hex[:8]}"
    hashed_pwd = hash_password(req.password)

    # Ignore any client-supplied role: always register as "developer"
    user_record = {
        "id": user_id,
        "username": req.username,
        "email": req.email,
        "role": "developer",
        "hashed_password": hashed_pwd,
    }
    db_manager.insert("users", user_record)

    user = User(id=user_id, username=req.username, email=req.email, role="developer")
    token = create_access_token(user)

    return TokenResponse(access_token=token, user=user)


@router.post("/login", response_model=TokenResponse)
def login(req: UserLogin, request: Request):
    peer_ip = request.client.host if request.client else "127.0.0.1"
    client_ip = peer_ip

    trusted_proxies = settings.get_trusted_proxies()
    if peer_ip in trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

    # Check rate limit before verifying credentials
    check_login_rate_limit(req.username, client_ip=client_ip)

    user_record = db_manager.find_one("users", {"username": req.username})
    if not user_record or not verify_password(req.password, user_record.get("hashed_password", "")):
        record_failed_login(req.username, client_ip=client_ip)
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    # Successful login: clear failure counter
    clear_login_rate_limit(req.username, client_ip=client_ip)

    user = User(
        id=user_record["id"],
        username=user_record["username"],
        email=user_record["email"],
        role=user_record.get("role", "developer"),
    )
    token = create_access_token(user)

    return TokenResponse(access_token=token, user=user)


@router.get("/me", response_model=User)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/promote", response_model=User)
def promote_user(req: UserPromote, current_user: User = Depends(require_role("admin"))):
    """Admin-only endpoint to promote or alter a user's role."""
    if req.role not in ("admin", "developer"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'developer'")

    query = {}
    if req.user_id:
        query["id"] = req.user_id
    elif req.username:
        query["username"] = req.username
    else:
        raise HTTPException(status_code=400, detail="user_id or username required")

    target = db_manager.find_one("users", query)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    db_manager.update("users", query, {"role": req.role})
    target["role"] = req.role

    return User(
        id=target["id"],
        username=target["username"],
        email=target["email"],
        role=req.role,
    )
