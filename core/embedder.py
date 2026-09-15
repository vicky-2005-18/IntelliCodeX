"""
Embedding Generation Module

Two backends:
- OllamaEmbedder: calls a local Ollama server (nomic-embed-text). Use this for
  real deployment — this is what the paper's "Local AI Server" refers to.
- TfidfEmbedder: pure-local fallback with no server dependency. Useful for
  offline development, unit tests, or environments without Ollama installed.
  Swap this out for OllamaEmbedder once your server is running.
"""
import os
import sqlite3
import hashlib
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
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


def _get_embedding_cache(cache_dir: str = ".storage") -> Optional[sqlite3.Connection]:
    """Retrieves or initializes the SQLite embedding cache database."""
    try:
        os.makedirs(cache_dir, exist_ok=True)
        db_path = os.path.join(cache_dir, "embedding_cache.db")
        conn = sqlite3.connect(db_path, timeout=30.0)
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_embeddings (
                    model TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    dim INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (model, text_hash)
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_model_hash ON chunk_embeddings(model, text_hash);")
        return conn
    except Exception:
        return None


class BaseEmbedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, texts: List[str]) -> np.ndarray:
        ...


class OllamaEmbedder(BaseEmbedder):
    def __init__(self, model: str = "nomic-embed-text", host: str = "http://localhost:11434", cache_dir: str = ".storage"):
        self.model = model
        self.host = host.rstrip("/")
        self.dim = 768  # nomic-embed-text output size
        self.cache_dir = cache_dir

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype="float32")

        total = len(texts)
        start_time = time.perf_counter()

        # Step 1: Compute hashes for caching and deduplication
        hashes = [hashlib.sha256(t[:4000].encode("utf-8", errors="ignore")).hexdigest() for t in texts]
        cached_map: Dict[str, np.ndarray] = {}

        # Step 2: Check SQLite persistent embedding cache
        conn = _get_embedding_cache(self.cache_dir)
        if conn:
            try:
                cur = conn.cursor()
                for chunk_start in range(0, len(hashes), 900):
                    batch_hashes = hashes[chunk_start : chunk_start + 900]
                    placeholders = ",".join("?" for _ in batch_hashes)
                    rows = cur.execute(
                        f"SELECT text_hash, vector FROM chunk_embeddings WHERE model = ? AND text_hash IN ({placeholders})",
                        [self.model] + batch_hashes
                    ).fetchall()
                    for h, blob in rows:
                        cached_map[h] = np.frombuffer(blob, dtype=np.float32)
            except Exception:
                pass

        missing_indices = [idx for idx, h in enumerate(hashes) if h not in cached_map]

        if total > 20:
            if len(missing_indices) == 0:
                total_elapsed = time.perf_counter() - start_time
                print(f"[*] Reused all {total} cached embeddings ({self.model}) in {_format_time(total_elapsed)}.")
                return np.array([cached_map[h] for h in hashes], dtype="float32")
            elif len(cached_map) > 0:
                print(f"[*] Found {len(cached_map)}/{total} cached embeddings ({self.model}). Resuming remaining {len(missing_indices)} chunks...")
            else:
                print(f"[*] Generating Ollama AI embeddings ({self.model}) for {total} code chunks...")

        # Step 3: Embed missing chunks in batches with auto-checkpointing
        batch_size = 64
        num_missing = len(missing_indices)
        processed_missing = 0

        for i in range(0, num_missing, batch_size):
            sub_indices = missing_indices[i : i + batch_size]
            batch = [texts[idx][:4000] for idx in sub_indices]

            processed_missing = min(i + batch_size, num_missing)
            overall_done = len(cached_map) + processed_missing
            elapsed = time.perf_counter() - start_time
            rate = processed_missing / elapsed if elapsed > 0.05 else 0.0
            eta = (num_missing - processed_missing) / rate if rate > 0 else 0.0

            if total > 20:
                pct = (overall_done / total) * 100
                print(
                    f"    -> Progress: {overall_done}/{total} chunks ({pct:.1f}%) | "
                    f"{rate:.1f} chunks/s | Elapsed: {_format_time(elapsed)} | ETA: {_format_time(eta)}   ",
                    end="\r",
                    flush=True,
                )

            batch_vectors = []
            try:
                # Try modern Ollama /api/embed endpoint with batching
                resp = requests.post(
                    f"{self.host}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=90,
                )
                if resp.status_code == 200 and "embeddings" in resp.json():
                    batch_vectors = resp.json()["embeddings"]
                else:
                    # Fallback to single item requests
                    for text in batch:
                        r = requests.post(
                            f"{self.host}/api/embeddings",
                            json={"model": self.model, "prompt": text},
                            timeout=60,
                        )
                        r.raise_for_status()
                        batch_vectors.append(r.json()["embedding"])
            except KeyboardInterrupt:
                print(f"\n[!] Embedding interrupted by user (Ctrl+C). {len(cached_map)} chunks preserved in cache.")
                raise
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
                            batch_vectors.append(r.json()["embeddings"][0])
                        else:
                            r2 = requests.post(
                                f"{self.host}/api/embeddings",
                                json={"model": self.model, "prompt": text},
                                timeout=60,
                            )
                            r2.raise_for_status()
                            batch_vectors.append(r2.json()["embedding"])
                    except KeyboardInterrupt:
                        print(f"\n[!] Embedding interrupted by user (Ctrl+C). {len(cached_map)} chunks preserved in cache.")
                        raise
                    except Exception:
                        batch_vectors.append([0.0] * self.dim)

            # Checkpoint new batch into SQLite cache immediately
            new_cache_rows = []
            for sub_idx, vec in zip(sub_indices, batch_vectors):
                h = hashes[sub_idx]
                vec_np = np.array(vec, dtype="float32")
                cached_map[h] = vec_np
                new_cache_rows.append((self.model, h, len(vec_np), vec_np.tobytes()))

            if conn and new_cache_rows:
                try:
                    with conn:
                        conn.executemany(
                            "INSERT OR REPLACE INTO chunk_embeddings (model, text_hash, dim, vector) VALUES (?, ?, ?, ?)",
                            new_cache_rows
                        )
                except Exception:
                    pass

        if total > 20:
            total_elapsed = time.perf_counter() - start_time
            avg_rate = total / total_elapsed if total_elapsed > 0 else 0.0
            print(f"\n[*] Embedding complete: {total}/{total} chunks in {_format_time(total_elapsed)} ({avg_rate:.1f} chunks/s)")

        # Step 4: Reconstruct full output array in original order
        return np.array([cached_map.get(h, np.zeros(self.dim, dtype="float32")) for h in hashes], dtype="float32")


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
