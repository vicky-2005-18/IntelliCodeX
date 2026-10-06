"""
CLI Script to promote or seed an admin user in IntelliCodeX.
Usage:
    python scripts/promote_user.py <username> [admin|developer]
"""
import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.database import db_manager


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/promote_user.py <username> [role]")
        sys.exit(1)

    username = sys.argv[1]
    role = sys.argv[2] if len(sys.argv) > 2 else "admin"

    if role not in ("admin", "developer"):
        print(f"Error: Invalid role '{role}'. Must be 'admin' or 'developer'.")
        sys.exit(1)

    user = db_manager.find_one("users", {"username": username})
    if not user:
        print(f"Error: User '{username}' not found in database.")
        sys.exit(1)

    db_manager.update("users", {"username": username}, {"role": role})
    print(f"Successfully updated user '{username}' to role '{role}'.")


if __name__ == "__main__":
    main()
