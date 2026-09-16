"""
Vector Database Layer — FAISS-backed similarity search over CodeChunks.
"""
import os
from typing import List, Tuple, Optional
import numpy as np
import faiss
from core.chunker import CodeChunk

# Fix 5: IVF index kicks in above this chunk count for ~10x faster approximate search
_IVF_THRESHOLD = 5000


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
        # Fix 5: Auto-promote to IVF when crossing the large-repo threshold
        if len(self.chunks) >= _IVF_THRESHOLD and isinstance(self.index, faiss.IndexFlatIP):
            self.promote_to_ivf()

    def promote_to_ivf(self):
        """Promote the flat index to an IVFFlat approximate index for faster large-repo search.
        No-op if the index is already IVF or has fewer than _IVF_THRESHOLD vectors."""
        n = self.index.ntotal
        if n < _IVF_THRESHOLD or not isinstance(self.index, faiss.IndexFlatIP):
            return
        try:
            # Reconstruct all existing vectors from the flat index
            all_vecs = np.zeros((n, self.dim), dtype="float32")
            for i in range(n):
                all_vecs[i] = self.index.reconstruct(i)
            nlist = min(256, max(4, n // 50))
            quantizer = faiss.IndexFlatIP(self.dim)
            ivf = faiss.IndexIVFFlat(quantizer, self.dim, nlist, faiss.METRIC_INNER_PRODUCT)
            ivf.train(all_vecs)
            ivf.add(all_vecs)
            ivf.nprobe = min(32, nlist)  # search 32 cells for accuracy/speed balance
            self.index = ivf
        except Exception:
            pass  # keep flat index on any failure

    def search(self, query_vec: np.ndarray, top_k: int = 5) -> List[Tuple[CodeChunk, float]]:
        flat = query_vec.flatten()
        target_d = self.index.d
        if len(flat) != target_d:
            aligned = np.zeros((1, target_d), dtype="float32")
            min_len = min(len(flat), target_d)
            aligned[0, :min_len] = flat[:min_len]
            query_vec = aligned
        else:
            query_vec = flat.reshape(1, -1)

        query_vec = self._normalize(query_vec)
        if len(self.chunks) == 0 or self.index.ntotal == 0:
            return []

        scores, idxs = self.index.search(query_vec, min(top_k, self.index.ntotal))
        results = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx == -1 or idx >= len(self.chunks):
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

