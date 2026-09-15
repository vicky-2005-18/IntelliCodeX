"""
Embedding Generation Module

Two backends:
- OllamaEmbedder: calls a local Ollama server (nomic-embed-text). Use this for
  real deployment — this is what the paper's "Local AI Server" refers to.
- TfidfEmbedder: pure-local fallback with no server dependency. Useful for
  offline development, unit tests, or environments without Ollama installed.
  Swap this out for OllamaEmbedder once your server is running.
"""
import time
from abc import ABC, abstractmethod
from typing import List
import numpy as np
import requests


def _format_time(seconds: float) -> str:
    """Formats duration in human-readable format."""
    if seconds < 1.0:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60.0:
        return f"{seconds:.1f}s"
    else:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s:02d}s"


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
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")

        vectors = []
        batch_size = 64
        total = len(texts)
        start_time = time.perf_counter()

        if total > 20:
            print(f"[*] Generating Ollama AI embeddings ({self.model}) for {total} code chunks...")

        for i in range(0, total, batch_size):
            processed = min(i + batch_size, total)
            elapsed = time.perf_counter() - start_time
            rate = processed / elapsed if elapsed > 0.05 else 0.0
            eta = (total - processed) / rate if rate > 0 else 0.0

            if total > 20:
                pct = (processed / total) * 100
                print(
                    f"    -> Progress: {processed}/{total} chunks ({pct:.1f}%) | "
                    f"{rate:.1f} chunks/s | Elapsed: {_format_time(elapsed)} | ETA: {_format_time(eta)}   ",
                    end="\r",
                    flush=True,
                )

            batch = [t[:4000] for t in texts[i : i + batch_size]]
            try:
                # Try modern Ollama /api/embed endpoint with batching
                resp = requests.post(
                    f"{self.host}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=60,
                )
                if resp.status_code == 200 and "embeddings" in resp.json():
                    vectors.extend(resp.json()["embeddings"])
                    continue

                # Fallback to single item requests if batching fails
                for text in batch:
                    r = requests.post(
                        f"{self.host}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                        timeout=60,
                    )
                    r.raise_for_status()
                    vectors.append(r.json()["embedding"])
            except Exception:
                # Per-item fallback to ensure pipeline resilience
                for text in batch:
                    try:
                        r = requests.post(
                            f"{self.host}/api/embed",
                            json={"model": self.model, "input": text},
                            timeout=60,
                        )
                        if r.status_code == 200 and "embeddings" in r.json():
                            vectors.append(r.json()["embeddings"][0])
                        else:
                            r2 = requests.post(
                                f"{self.host}/api/embeddings",
                                json={"model": self.model, "prompt": text},
                                timeout=60,
                            )
                            r2.raise_for_status()
                            vectors.append(r2.json()["embedding"])
                    except Exception:
                        vectors.append([0.0] * self.dim)

        if total > 20:
            total_elapsed = time.perf_counter() - start_time
            avg_rate = total / total_elapsed if total_elapsed > 0 else 0.0
            print(f"\n[*] Embedding complete: {total}/{total} chunks in {_format_time(total_elapsed)} ({avg_rate:.1f} chunks/s)")

        return np.array(vectors, dtype="float32")


class TfidfEmbedder(BaseEmbedder):
    """Local, dependency-light fallback. Fit once on the corpus, then transform."""

    def __init__(self, dim: int = 512):
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        self.dim = dim
        self._vectorizer = TfidfVectorizer(max_features=20000, token_pattern=r"(?u)\b\w+\b")
        self._svd = TruncatedSVD(n_components=min(dim, 128))
        self._fitted = False

    def fit(self, corpus: List[str]):
        if not corpus or all(not text.strip() for text in corpus):
            self._fitted = True
            return

        try:
            tfidf = self._vectorizer.fit_transform(corpus)
            n_components = min(self.dim, max(1, tfidf.shape[1] - 1), max(1, tfidf.shape[0] - 1))
            from sklearn.decomposition import TruncatedSVD
            self._svd = TruncatedSVD(n_components=n_components)
            self._svd.fit(tfidf)
            self._fitted = True
        except Exception:
            self._fitted = True

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")

        if not self._fitted:
            self.fit(texts)

        try:
            tfidf = self._vectorizer.transform(texts)
            vecs = self._svd.transform(tfidf).astype("float32")
            if vecs.shape[1] < self.dim:
                padded = np.zeros((len(texts), self.dim), dtype="float32")
                padded[:, :vecs.shape[1]] = vecs
                return padded
            return vecs[:, :self.dim]
        except Exception:
            return np.zeros((len(texts), self.dim), dtype="float32")
