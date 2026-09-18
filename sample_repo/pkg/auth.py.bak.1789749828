"""Authentication utilities for the sample application."""
import hashlib
from pkg.db import get_user_by_username


def hash_password(password: str, salt: str = "static_salt") -> str:
    """Hash a plaintext password with a salt using SHA-256."""
    return hashlib.sha256((password + salt).encode()).hexdigest()


def authenticate(username: str, password: str) -> bool:
    """Check a username/password pair against stored credentials."""
    user = get_user_by_username(username)
    if user is None:
        return False
    return user["password_hash"] == hash_password(password)


class SessionManager:
    """Tracks active user sessions in memory."""

    def __init__(self):
        self.sessions = {}

    def create_session(self, username: str) -> str:
        token = hashlib.sha256(username.encode()).hexdigest()[:16]
        self.sessions[token] = username
        return token

    def is_valid(self, token: str) -> bool:
        return token in self.sessions
