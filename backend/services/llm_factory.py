"""
LLM & Embedder Factory
Centralizes creation of Ollama clients using enterprise configuration settings.
"""
from typing import Optional
from core.embedder import BaseEmbedder, OllamaEmbedder, TfidfEmbedder
from core.llm_client import OllamaLLM
from backend.config import settings


def create_embedder(backend: Optional[str] = None) -> BaseEmbedder:
    """Create an embedder instance based on backend preference."""
    backend = backend or settings.DEFAULT_EMBEDDER_BACKEND
    if backend == "ollama":
        return OllamaEmbedder(
            model=settings.OLLAMA_EMBED_MODEL,
            host=settings.OLLAMA_HOST,
        )
    return TfidfEmbedder()


def create_llm(backend: Optional[str] = None) -> Optional[OllamaLLM]:
    """Create an LLM client when Ollama backend is active; otherwise None."""
    backend = backend or settings.DEFAULT_EMBEDDER_BACKEND
    if backend != "ollama":
        return None
    return OllamaLLM(
        model=settings.OLLAMA_LLM_MODEL,
        host=settings.OLLAMA_HOST,
    )
