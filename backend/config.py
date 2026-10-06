"""
IntelliCodeX Configuration Module
Centralized settings management using Pydantic BaseSettings / Settings models.
"""
import os
import secrets
import logging
from typing import List
from pydantic import BaseModel, Field

logger = logging.getLogger("intellicodex.config")


def get_jwt_secret(storage_dir: str) -> str:
    """
    Read JWT_SECRET from environment only. If missing, generate a cryptographically
    secure random secret once and persist it atomically with O_CREAT|O_EXCL and 0o600
    for local dev, logging a warning. Refuse secrets shorter than 32 characters.
    """
    env_secret = os.getenv("JWT_SECRET")
    if env_secret:
        if len(env_secret) < 32:
            raise ValueError(
                f"JWT_SECRET is too short ({len(env_secret)} chars). Must be at least 32 characters."
            )
        return env_secret

    os.makedirs(storage_dir, exist_ok=True)
    secret_path = os.path.join(storage_dir, "jwt_secret.key")

    # If already exists, read it and validate
    if os.path.exists(secret_path):
        try:
            with open(secret_path, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    if len(saved) < 32:
                        raise ValueError(
                            f"Persisted JWT secret in {secret_path} is too short ({len(saved)} chars). Must be at least 32 characters."
                        )
                    return saved
        except ValueError:
            raise
        except Exception as e:
            logger.warning("Could not read persisted JWT secret: %s", e)

    secret = secrets.token_urlsafe(32)  # 43+ chars base64url string
    if len(secret) < 32:
        raise ValueError("Generated secret is unexpectedly short.")

    # Create atomically with O_CREAT | O_EXCL and 0o600
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        mode = 0o600
        fd = os.open(secret_path, flags, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secret)
    except FileExistsError:
        with open(secret_path, "r", encoding="utf-8") as f:
            saved = f.read().strip()
            if len(saved) < 32:
                raise ValueError(f"Persisted JWT secret in {secret_path} is too short.")
            return saved
    except Exception:
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(secret)
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass

    logger.warning(
        "JWT_SECRET environment variable not set. Generated random secret persisted to %s for local dev.",
        secret_path,
    )
    return secret


class Settings(BaseModel):
    PROJECT_NAME: str = "IntelliCodeX"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"

    # Database & Persistence Settings
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "intellicodex_db")
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", os.path.abspath(".storage"))

    # Auth & JWT Settings
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # Reduced to 60 minutes

    # LLM & Embedding Settings
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_LLM_MODEL: str = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5-coder:7b")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "8192"))  # Context window size
    DEFAULT_EMBEDDER_BACKEND: str = os.getenv("DEFAULT_EMBEDDER_BACKEND", "ollama")  # "ollama" or "tfidf"

    # Network & Proxy Security
    API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")  # Comma-separated list
    TRUSTED_PROXIES: str = os.getenv("TRUSTED_PROXIES", "")  # Comma-separated list of trusted proxy IPs

    # Sandbox Security
    SANDBOX_MODE: str = os.getenv("SANDBOX_MODE", "local")  # "local" or "docker"
    SANDBOX_DOCKER_IMAGE: str = os.getenv("SANDBOX_DOCKER_IMAGE", "python:3.11-slim")
    ALLOW_LOCAL_SANDBOX: bool = os.getenv("ALLOW_LOCAL_SANDBOX", "false").lower() == "true"  # Allow local sandbox in API mode

    # Workspace & Repositories
    REPOS_DIR: str = os.getenv("REPOS_DIR", os.path.abspath(".repos"))
    ALLOWED_INGEST_DIRS: List[str] = Field(
        default_factory=lambda: [
            os.path.abspath(os.getenv("REPOS_DIR", ".repos")),
            os.path.abspath("sample_repo"),
            os.path.abspath("."),
            os.path.abspath(r"C:\Users\vikas\Downloads\web ui"),
        ]
    )

    def get_trusted_proxies(self) -> List[str]:
        """Returns parsed list of trusted proxy IP strings."""
        if not self.TRUSTED_PROXIES:
            return []
        return [p.strip() for p in self.TRUSTED_PROXIES.split(",") if p.strip()]

    def get_cors_origins(self) -> List[str]:
        """Returns parsed list of CORS origin strings. Handles '*' wildcard."""
        if not self.CORS_ORIGINS:
            return []
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        return origins

    @property
    def JWT_SECRET(self) -> str:
        return get_jwt_secret(self.STORAGE_DIR)

    @JWT_SECRET.setter
    def JWT_SECRET(self, value: str):
        if value and len(value) < 32:
            raise ValueError(
                f"JWT_SECRET is too short ({len(value)} chars). Must be at least 32 characters."
            )
        os.environ["JWT_SECRET"] = value


settings = Settings()

# Ensure local storage and repos directories exist
os.makedirs(settings.STORAGE_DIR, exist_ok=True)
os.makedirs(settings.REPOS_DIR, exist_ok=True)
