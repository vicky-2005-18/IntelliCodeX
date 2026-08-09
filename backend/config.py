"""
IntelliCodeX Enterprise Configuration Module
Centralized settings management using Pydantic BaseSettings / Settings models.
"""
import os
from pydantic import BaseModel


class Settings(BaseModel):
    PROJECT_NAME: str = "IntelliCodeX Enterprise"
    VERSION: str = "1.0.0"
    API_PREFIX: str = "/api"
    
    # Auth & JWT Settings
    JWT_SECRET: str = os.getenv("JWT_SECRET", "intellicodex-enterprise-secret-key-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    
    # Database & Persistence Settings
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "intellicodex_db")
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", os.path.abspath(".storage"))
    
    # LLM & Embedding Settings
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_LLM_MODEL: str = os.getenv("OLLAMA_LLM_MODEL", "qwen2.5-coder")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    DEFAULT_EMBEDDER_BACKEND: str = os.getenv("DEFAULT_EMBEDDER_BACKEND", "ollama")  # "ollama" or "tfidf"
    
    # Workspace & Repositories
    REPOS_DIR: str = os.getenv("REPOS_DIR", os.path.abspath(".repos"))


settings = Settings()

# Ensure local storage and repos directories exist
os.makedirs(settings.STORAGE_DIR, exist_ok=True)
os.makedirs(settings.REPOS_DIR, exist_ok=True)
