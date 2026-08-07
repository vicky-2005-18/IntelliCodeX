"""
Embedding Generation Module

Two backends:
- OllamaEmbedder: calls a local Ollama server (nomic-embed-text). Use this for
  real deployment — this is what the paper's "Local AI Server" refers to.
- TfidfEmbedder: pure-local fallback with no server dependency. Useful for
  offline development, unit tests, or environments without Ollama installed.
  Swap this out for OllamaEmbedder once your server is running.
"""
from abc import ABC, abstractmethod
from typing import List
import numpy as np
import requests


class BaseEmbedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        ...


class OllamaEmbedder(BaseEmbedder):
    def __init__(self, model: str = "nomic-embed-text", host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")
        self.dim = 768  # nomic-embed-text output size

    def embed(self, texts: List[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            resp = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=60,
            )
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"])
        return np.array(vectors, dtype="float32")


class TfidfEmbedder(BaseEmbedder):
    """Local, dependency-light fallback. Fit once on the corpus, then transform."""

    def __init__(self, dim: int = 512):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        self.dim = dim
        self._vectorizer = TfidfVectorizer(max_features=20000, token_pattern=r"(?u)\b\w+\b")
        self._svd = TruncatedSVD(n_components=dim)
        self._fitted = False

    def fit(self, corpus: List[str]):
        if not corpus or all(not text.strip() for text in corpus):
            self.dim = 512
            self._fitted = True
            return

        try:
            tfidf = self._vectorizer.fit_transform(corpus)
            n_components = min(self.dim, max(1, tfidf.shape[1] - 1), max(1, tfidf.shape[0] - 1))
            if n_components != self._svd.n_components:
                from sklearn.decomposition import TruncatedSVD
                self._svd = TruncatedSVD(n_components=n_components)
            self._svd.fit(tfidf)
            self.dim = n_components
            self._fitted = True
        except Exception:
            self.dim = 512
            self._fitted = True

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")

        if not self._fitted:
            self.fit(texts)

        try:
            tfidf = self._vectorizer.transform(texts)
            vecs = self._svd.transform(tfidf).astype("float32")
            return vecs
        except Exception:
            return np.zeros((len(texts), self.dim), dtype="float32")
