"""
FAISS Vector Store Persistence Module (Phase 7)
Handles disk serialization and auto-reloading of FAISS vector indices and metadata.
"""
import os
import json
import faiss
import numpy as np
from typing import Optional, Tuple, List
from core.vectorstore import FaissVectorStore
from core.chunker import CodeChunk
from backend.config import settings


def get_index_paths(repo_id: str) -> Tuple[str, str]:
    indices_dir = os.path.join(settings.STORAGE_DIR, "indices")
    os.makedirs(indices_dir, exist_ok=True)
    faiss_path = os.path.join(indices_dir, f"{repo_id}.faiss")
    meta_path = os.path.join(indices_dir, f"{repo_id}.meta.json")
    return faiss_path, meta_path


def save_vector_store(repo_id: str, store: FaissVectorStore):
    """Serialize FAISS index and chunk metadata to disk."""
    faiss_path, meta_path = get_index_paths(repo_id)

    # Save FAISS index
    faiss.write_index(store.index, faiss_path)

    # Save chunk metadata
    chunks_meta = []
    for c in store.chunks:
        chunks_meta.append({
            "chunk_id": c.chunk_id,
            "file_path": c.file_path,
            "language": c.language,
            "kind": c.kind,
            "name": c.name,
            "start_line": c.start_line,
            "end_line": c.end_line,
            "code": c.code,
            "docstring": c.docstring,
            "imports": c.imports,
        })

    meta_data = {
        "repo_id": repo_id,
        "dim": store.dim,
        "chunks": chunks_meta,
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, indent=2)


def load_vector_store(repo_id: str) -> Optional[FaissVectorStore]:
    """Load FAISS index and chunk metadata from disk if available."""
    faiss_path, meta_path = get_index_paths(repo_id)

    if not os.path.exists(faiss_path) or not os.path.exists(meta_path):
        return None

    try:
        index = faiss.read_index(faiss_path)
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        dim = meta.get("dim", index.d)
        store = FaissVectorStore(dim=dim)
        store.index = index

        reconstructed_chunks = []
        for cm in meta.get("chunks", []):
            chunk = CodeChunk(
                chunk_id=cm["chunk_id"],
                file_path=cm["file_path"],
                language=cm["language"],
                kind=cm["kind"],
                name=cm["name"],
                start_line=cm["start_line"],
                end_line=cm["end_line"],
                code=cm["code"],
                docstring=cm.get("docstring"),
                imports=cm.get("imports", []),
            )
            reconstructed_chunks.append(chunk)

        store.chunks = reconstructed_chunks
        return store
    except Exception as e:
        print(f"Error auto-reloading FAISS store for repo '{repo_id}': {e}")
        return None
