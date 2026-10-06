"""
Authentication Package
"""
from backend.auth.jwt_handler import (
    User, UserRegister, UserLogin, TokenResponse,
    hash_password, verify_password,
    create_access_token, decode_access_token,
    get_current_user, require_role,
    check_login_rate_limit, record_failed_login, clear_login_rate_limit, reset_all_rate_limits
)
