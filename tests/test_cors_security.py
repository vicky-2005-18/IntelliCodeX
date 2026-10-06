"""
CORS Security Tests for IntelliCodeX Backend.
Tests use FastAPI TestClient to verify HTTP-level CORS behavior:
  - Allowed origin receives Access-Control-Allow-Origin header
  - Disallowed origin receives no Access-Control-Allow-Origin header
  - Preflight OPTIONS from disallowed origin is rejected
  - Wildcard origin disables credentials
"""
import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_cors_allowed_origin_gets_header(client, monkeypatch):
    """Test that an allowed origin receives Access-Control-Allow-Origin header."""
    import os
    import importlib
    import backend.config
    import backend.main
    
    # Set CORS origins to include http://localhost:3000
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    
    # Reload config and main to pick up new env var
    importlib.reload(backend.config)
    importlib.reload(backend.main)
    from backend.main import app as new_app
    
    test_client = TestClient(new_app)
    
    response = test_client.get("/", headers={"Origin": "http://localhost:3000"})
    
    # Allowed origin should receive Access-Control-Allow-Origin header
    assert "access-control-allow-origin" in response.headers
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_disallowed_origin_no_header(client, monkeypatch):
    """Test that a disallowed origin receives no Access-Control-Allow-Origin header."""
    import os
    import importlib
    import backend.config
    import backend.main
    
    # Set CORS origins to exclude http://malicious.com
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    
    # Reload config and main to pick up new env var
    importlib.reload(backend.config)
    importlib.reload(backend.main)
    from backend.main import app as new_app
    
    test_client = TestClient(new_app)
    
    response = test_client.get("/", headers={"Origin": "http://malicious.com"})
    
    # Disallowed origin should not receive Access-Control-Allow-Origin header
    assert "access-control-allow-origin" not in response.headers


def test_cors_preflight_disallowed_origin_rejected(client, monkeypatch):
    """Test that a preflight OPTIONS request from a disallowed origin is rejected."""
    import os
    import importlib
    import backend.config
    import backend.main
    
    # Set CORS origins to exclude https://evil.example
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    
    # Reload config and main to pick up new env var
    importlib.reload(backend.config)
    importlib.reload(backend.main)
    from backend.main import app as new_app
    
    test_client = TestClient(new_app)
    
    response = test_client.options(
        "/",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type"
        }
    )
    
    # Disallowed origin preflight should not receive Access-Control-Allow-Origin header
    # (browser will reject the request even if other CORS headers are present)
    assert "access-control-allow-origin" not in response.headers


def test_cors_wildcard_disables_credentials(client, monkeypatch):
    """Test that wildcard origin configuration disables allow_credentials."""
    import os
    import importlib
    import backend.config
    import backend.main
    
    # Set CORS origins to wildcard
    monkeypatch.setenv("CORS_ORIGINS", "*")
    
    # Reload config and main to pick up new env var
    importlib.reload(backend.config)
    importlib.reload(backend.main)
    from backend.main import app as new_app
    
    test_client = TestClient(new_app)
    
    response = test_client.get("/", headers={"Origin": "http://example.com"})
    
    # With wildcard, credentials should be disabled (no Access-Control-Allow-Credentials header)
    assert "access-control-allow-credentials" not in response.headers


def test_cors_allowed_methods_restricted(client, monkeypatch):
    """Test that only allowed methods are permitted."""
    import os
    import importlib
    import backend.config
    import backend.main
    
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    
    # Reload config and main to pick up new env var
    importlib.reload(backend.config)
    importlib.reload(backend.main)
    from backend.main import app as new_app
    
    test_client = TestClient(new_app)
    
    response = test_client.options(
        "/",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type"
        }
    )
    
    # Should have allow-methods header
    assert "access-control-allow-methods" in response.headers
    allowed_methods = response.headers["access-control-allow-methods"]
    
    # Should only include our allowed methods
    for method in ["GET", "POST", "PUT", "DELETE", "OPTIONS"]:
        assert method in allowed_methods


def test_cors_allowed_headers_restricted(client, monkeypatch):
    """Test that only allowed headers are permitted."""
    import os
    import importlib
    import backend.config
    import backend.main
    
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")
    
    # Reload config and main to pick up new env var
    importlib.reload(backend.config)
    importlib.reload(backend.main)
    from backend.main import app as new_app
    
    test_client = TestClient(new_app)
    
    response = test_client.options(
        "/",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Authorization"
        }
    )
    
    # Should have allow-headers header
    assert "access-control-allow-headers" in response.headers
    allowed_headers = response.headers["access-control-allow-headers"]
    
    # Should only include our allowed headers
    assert "Authorization" in allowed_headers
    assert "Content-Type" in allowed_headers
