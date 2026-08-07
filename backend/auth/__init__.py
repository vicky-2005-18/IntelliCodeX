"""
Authentication Package
"""
from backend.auth.jwt_handler import (
    User, UserRegister, UserLogin, TokenResponse,
    hash_password, verify_password, create_access_token, decode_access_token,
    get_current_user, require_role
)
