"""
Unit Tests for FAISS Vector Index Disk Persistence & Unified Index Persistence (Week 3 Day 2)
"""
import os
import tempfile
import numpy as np
import pytest
from core.parser import SourceFile
from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.persistence import (
    get_repo_id,
    get_faiss_index_path,
    save_faiss_index,
    load_faiss_index,
    save_index,
    load_index,
    get_db_connection,
    load_stored_chunks,
)


def test_faiss_vector_store_save_load(tmp_path):
    """Tests direct save and load methods on FaissVectorStore."""
    embedder = TfidfEmbedder(dim=16)
    c1 = CodeChunk(
        chunk_id="auth.py::login",
        file_path="auth.py",
        language="python",
        kind="function",
        name="login",
        start_line=1,
        end_line=5,
        code="def login(): return True\n",
        docstring="User login function",
        imports=["os", "sys"]
    )
    c2 = CodeChunk(
        chunk_id="db.py::connect",
        file_path="db.py",
        language="python",
        kind="function",
        name="connect",
        start_line=1,
        end_line=4,
        code="def connect(): return None\n",
        imports=["sqlite3"]
    )

    chunks = [c1, c2]
    vecs = embedder.embed([c.as_embedding_text() for c in chunks])

    store = FaissVectorStore(dim=vecs.shape[1])
    store.add(chunks, vecs)
    assert len(store) == 2

    # Query before save
    q_vec = embedder.embed(["user authentication login"])
    orig_results = store.search(q_vec, top_k=2)

    # Save to disk
    faiss_filepath = os.path.join(tmp_path, "test_repo.faiss")
    saved_path = store.save(faiss_filepath)
    assert os.path.exists(saved_path)

    # Reload from disk
    loaded_store = FaissVectorStore.load(saved_path, chunks=chunks)
    assert len(loaded_store) == 2
    assert loaded_store.dim == vecs.shape[1]

    # Query after reload
    reloaded_results = loaded_store.search(q_vec, top_k=2)
    assert len(reloaded_results) == len(orig_results)
    assert reloaded_results[0][0].chunk_id == orig_results[0][0].chunk_id
    assert abs(reloaded_results[0][1] - orig_results[0][1]) < 1e-5


def test_unified_save_load_index(tmp_path):
    """Tests high-level unified save_index and load_index functions."""
    storage_dir = os.path.join(tmp_path, ".storage")
    db_path = os.path.join(storage_dir, "metadata.db")

    sf = SourceFile(
        path=os.path.join(tmp_path, "pkg", "auth.py"),
        rel_path="pkg/auth.py",
        language="python",
        content="def authenticate(): return True",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=31
    )

    chunk = CodeChunk(
        chunk_id="pkg/auth.py::authenticate",
        file_path="pkg/auth.py",
        language="python",
        kind="function",
        name="authenticate",
        start_line=1,
        end_line=1,
        code="def authenticate(): return True",
        imports=[]
    )

    embedder = TfidfEmbedder(dim=8)
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    repo_path = os.path.join(tmp_path, "my_sample_repo")
    saved_db, saved_faiss = save_index(
        repo_path=repo_path,
        backend="tfidf",
        source_files=[sf],
        chunks=[chunk],
        store=store,
        db_path=db_path,
        storage_dir=storage_dir
    )

    assert os.path.exists(saved_db)
    assert os.path.exists(saved_faiss)
    assert saved_faiss.endswith(".faiss")

    # Load back using unified load_index
    loaded_data = load_index(repo_path, db_path=db_path, storage_dir=storage_dir)
    assert loaded_data is not None
    meta, loaded_chunks, loaded_store = loaded_data

    assert meta["total_files"] == 1
    assert meta["total_chunks"] == 1
    assert len(loaded_chunks) == 1
    assert loaded_chunks[0].chunk_id == "pkg/auth.py::authenticate"
    assert len(loaded_store) == 1


def test_repo_id_generation():
    """Tests deterministic and clean repo_id generation."""
    id1 = get_repo_id("/path/to/my-repo")
    id2 = get_repo_id("/path/to/my-repo")
    id3 = get_repo_id("https://github.com/user/my-repo.git")

    assert id1 == id2
    assert "my-repo" in id1
    assert "my-repo" in id3
