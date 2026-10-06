"""In-memory fake database for the sample application."""

_USERS = {
    "vikii": {"username": "vikii", "password_hash": None},
}


def get_user_by_username(username: str):
    """Look up a user record by username. Returns None if not found."""
    return _USERS.get(username)


def add_user(username: str, password_hash: str):
    """Insert a new user record."""
    _USERS[username] = {"username": username, "password_hash": password_hash}
