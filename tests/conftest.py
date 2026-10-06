import os
import sys
import tempfile

# Ensure project root (intellicodex) is on sys.path regardless of where pytest is invoked from
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Isolate storage for tests so local .storage/ in project root is never modified
# Set these BEFORE any imports that might load config
test_storage_dir = os.path.join(tempfile.gettempdir(), "intellicodex_pytest_storage")
os.makedirs(test_storage_dir, exist_ok=True)
os.environ["STORAGE_DIR"] = test_storage_dir
os.environ["REPOS_DIR"] = os.path.join(test_storage_dir, "repos")
os.makedirs(os.environ["REPOS_DIR"], exist_ok=True)
os.environ["JWT_SECRET"] = "test-jwt-secret-key-at-least-32-chars-long-2026!!"

import pytest


@pytest.fixture(autouse=True)
def reset_rate_limits_and_db():
    from backend.auth import reset_all_rate_limits
    reset_all_rate_limits()
    yield
    reset_all_rate_limits()
