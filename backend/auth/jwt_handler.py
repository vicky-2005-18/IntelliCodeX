"""
Authentication & Authorization Module (Phase 11)
Handles JWT creation, verification via PyJWT, password hashing via argon2-cffi,
and Role-Based Access Control (RBAC).
"""
import time
from typing import Optional, Dict, Any, List
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from backend.config import settings

security_scheme = HTTPBearer(auto_error=False)

_hasher = PasswordHasher()

# In-memory login failure tracker: (username, client_ip) -> list of failure timestamps
_login_failures: Dict[tuple, List[float]] = {}
RATE_LIMIT_WINDOW_SECONDS = 300  # 5 minutes
MAX_FAILED_ATTEMPTS = 5


def _purge_expired_failures(now: float) -> None:
    """Removes all failure records older than the sliding window across all keys."""
    expired_keys = []
    for key, timestamps in list(_login_failures.items()):
        valid = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW_SECONDS]
        if not valid:
            expired_keys.append(key)
        else:
            _login_failures[key] = valid
    for key in expired_keys:
        _login_failures.pop(key, None)


def check_login_rate_limit(username: str, client_ip: str = "127.0.0.1") -> None:
    """
    Checks if too many failed login attempts have occurred for (username, client_ip).
    Raises HTTP 429 Too Many Requests if rate limit is exceeded.
    Purges expired entries on each check.
    """
    now = time.time()
    _purge_expired_failures(now)

    key = (username, client_ip)
    attempts = _login_failures.get(key, [])
    recent = [t for t in attempts if now - t < RATE_LIMIT_WINDOW_SECONDS]
    _login_failures[key] = recent

    if len(recent) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again after 5 minutes.",
        )


def record_failed_login(username: str, client_ip: str = "127.0.0.1") -> None:
    """Records a failed login attempt for (username, client_ip) and purges expired entries."""
    now = time.time()
    _purge_expired_failures(now)

    key = (username, client_ip)
    if key not in _login_failures:
        _login_failures[key] = []
    _login_failures[key].append(now)


def clear_login_rate_limit(username: str, client_ip: str = "127.0.0.1") -> None:
    """Clears failed login attempts upon successful login for (username, client_ip)."""
    key = (username, client_ip)
    _login_failures.pop(key, None)


def reset_all_rate_limits() -> None:
    """Resets all login rate limit records (useful for test fixtures)."""
    _login_failures.clear()


class User(BaseModel):
    id: str
    username: str
    email: str
    role: str = "developer"  # "admin" | "developer"
    created_at: float = Field(default_factory=time.time)


class UserRegister(BaseModel):
    username: str
    email: str
    password: str = Field(..., min_length=10, description="Minimum 10 characters required")


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


def hash_password(password: str) -> str:
    """Hash password using argon2-cffi with automatic per-user salt."""
    if len(password) < 10:
        raise ValueError("Password must be at least 10 characters long.")
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against argon2 hash.
    Legacy HMAC passwords are no longer supported; pre-existing users must re-register.
    """
    if hashed_password and hashed_password.startswith("$argon2"):
        try:
            return _hasher.verify(hashed_password, plain_password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
        except Exception:
            return False
    return False


def create_access_token(user: User, expires_delta_seconds: Optional[int] = None) -> str:
    """Creates a PyJWT signed token using HS256."""
    now = time.time()
    expire_seconds = (
        expires_delta_seconds
        if expires_delta_seconds is not None
        else (settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    )
    payload = {
        "sub": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "iat": int(now),
        "exp": int(now + expire_seconds),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Decodes and validates JWT token, pinning algorithms to HS256 and validating expiration."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.ALGORITHM],  # Explicitly pinned to ["HS256"]
            options={"require": ["exp", "sub"]},
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
) -> User:
    """
    Dependency to retrieve authenticated user from Bearer header.
    Loads the user from the database on each request to verify active existence and real role.
    Missing or invalid token raises 401 Unauthorized.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Load real user record from database on every request
    from backend.database import db_manager
    user_record = db_manager.find_one("users", {"id": user_id})
    if not user_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists or was deleted",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return User(
        id=user_record["id"],
        username=user_record["username"],
        email=user_record.get("email", ""),
        role=user_record.get("role", "developer"),
        created_at=user_record.get("created_at", 0.0),
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
