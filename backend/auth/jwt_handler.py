"""
Authentication & Authorization Module (Phase 11)
Handles JWT creation, verification, password hashing, and Role-Based Access Control (RBAC).
"""
import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from backend.config import settings

security_scheme = HTTPBearer(auto_error=False)


class User(BaseModel):
    id: str
    username: str
    email: str
    role: str = "developer"  # "admin" | "developer"
    created_at: float = Field(default_factory=time.time)


class UserRegister(BaseModel):
    username: str
    email: str
    password: str
    role: Optional[str] = "developer"


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


def hash_password(password: str) -> str:
    """Hash password using HMAC-SHA256 with JWT_SECRET as salt."""
    return hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def create_access_token(user: User) -> str:
    """Creates a basic signed JWT payload (standard header.payload.signature format)."""
    import base64
    import json

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "exp": time.time() + (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    h_b64 = b64url(json.dumps(header).encode("utf-8"))
    p_b64 = b64url(json.dumps(payload).encode("utf-8"))
    sig_input = f"{h_b64}.{p_b64}".encode("utf-8")
    sig = hmac.new(settings.JWT_SECRET.encode("utf-8"), sig_input, hashlib.sha256).digest()
    s_b64 = b64url(sig)

    return f"{h_b64}.{p_b64}.{s_b64}"


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decodes and validates JWT token."""
    import base64
    import json

    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token format",
        )

    h_b64, p_b64, s_b64 = parts

    def b64url_decode(s: str) -> bytes:
        padding = "=" * ((4 - len(s) % 4) % 4)
        return base64.urlsafe_b64decode(s + padding)

    sig_input = f"{h_b64}.{p_b64}".encode("utf-8")
    expected_sig = hmac.new(settings.JWT_SECRET.encode("utf-8"), sig_input, hashlib.sha256).digest()
    actual_sig = b64url_decode(s_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
        )

    payload = json.loads(b64url_decode(p_b64).decode("utf-8"))
    if payload.get("exp", 0) < time.time():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
        )

    return payload


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme)) -> User:
    """Dependency to retrieve authenticated user from Bearer header."""
    if not credentials or not credentials.credentials:
        # For development ease, if no token provided, return default guest user
        return User(id="user_guest", username="guest_developer", email="guest@intellicodex.local", role="admin")

    payload = decode_access_token(credentials.credentials)
    return User(
        id=payload.get("sub", "user_unknown"),
        username=payload.get("username", "developer"),
        email=payload.get("email", ""),
        role=payload.get("role", "developer")
    )


def require_role(role: str):
    """RBAC dependency checking user role."""
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role != role and user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires '{role}' role",
            )
        return user
    return role_checker
