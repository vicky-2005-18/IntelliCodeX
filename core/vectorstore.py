"""
Vector Database Layer — FAISS-backed similarity search over CodeChunks.
"""
import os
from typing import List, Tuple, Optional
import numpy as np
import faiss
from core.chunker import CodeChunk


class FaissVectorStore:
    def __init__(self, dim: int):
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)  # cosine similarity via normalized vectors
        self.chunks: List[CodeChunk] = []

    @staticmethod
    def _normalize(vecs: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1e-8
        return vecs / norms

    def add(self, chunks: List[CodeChunk], vectors: np.ndarray):
        assert vectors.shape[1] == self.dim, f"expected dim {self.dim}, got {vectors.shape[1]}"
        vectors = self._normalize(vectors)
        self.index.add(vectors)
        self.chunks.extend(chunks)

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[CodeChunk, float]]:
        query_vec = self._normalize(query_vec.reshape(1, -1))
        scores, idxs = self.index.search(query_vec, min(top_k, len(self.chunks)))
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1:
                continue
            results.append((self.chunks[idx], float(score)))
        return results

    def save(self, filepath: str) -> str:
        """Saves the FAISS index to a binary file on disk."""
        abs_path = os.path.abspath(filepath)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        faiss.write_index(self.index, abs_path)
        return abs_path

    @classmethod
    def load(cls, filepath: str, chunks: Optional[List[CodeChunk]] = None) -> "FaissVectorStore":
        """Loads a FAISS index from a binary file on disk and binds provided code chunks."""
        abs_path = os.path.abspath(filepath)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"FAISS index file not found at '{abs_path}'")
        index = faiss.read_index(abs_path)
        store = cls(dim=index.d)
        store.index = index
        if chunks is not None:
            store.chunks = chunks
        return store

    def __len__(self):
        return len(self.chunks)

