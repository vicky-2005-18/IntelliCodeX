"""
Unit Tests for FAISS Vector Store Disk Serialization and Database Manager (Phase 7)
"""
import os
from core.vectorstore import FaissVectorStore

from core.chunker import CodeChunk
from core.embedder import TfidfEmbedder
from backend.database import save_vector_store, load_vector_store, db_manager


def test_faiss_persistence(tmp_path):
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="db.py::connect",
        file_path="db.py",
        language="python",
        kind="function",
        name="connect",
        start_line=1,
        end_line=5,
        code="def connect(): pass\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    repo_id = "test_persistence_repo"
    save_vector_store(repo_id, store)

    reloaded_store = load_vector_store(repo_id)
    assert reloaded_store is not None
    assert len(reloaded_store.chunks) == 1
    assert reloaded_store.chunks[0].chunk_id == "db.py::connect"


def test_db_manager_fallback():
    db_manager.insert("users", {"id": "test_u1", "username": "test_user"})
    user = db_manager.find_one("users", {"id": "test_u1"})
    assert user is not None
    assert user["username"] == "test_user"
