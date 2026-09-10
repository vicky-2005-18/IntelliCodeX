"""
Unit Tests for Fast Change Detection Engine (core/persistence.py - Week 3 Day 3)
"""
import os
import tempfile
import pytest
from core.parser import SourceFile
from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.persistence import (
    get_repo_id,
    get_db_connection,
    save_index,
    detect_repository_changes,
    delete_files_from_db,
    load_stored_file_hashes,
    load_stored_chunks,
)


def test_change_detection_fresh_index(tmp_path):
    """Tests that a repository with no existing DB records is flagged as fresh_index."""
    db_path = os.path.join(tmp_path, "metadata.db")
    sf1 = SourceFile(
        path=os.path.join(tmp_path, "main.py"),
        rel_path="main.py",
        language="python",
        content="print('hello')",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=14
    )

    delta = detect_repository_changes(str(tmp_path), [sf1], db_path=db_path)
    assert delta.is_fresh_index is True
    assert delta.has_changes() is True
    assert len(delta.added) == 1
    assert delta.added[0].rel_path == "main.py"
    assert len(delta.modified) == 0
    assert len(delta.deleted) == 0


def test_change_detection_lifecycle(tmp_path):
    """Tests added, modified, deleted, and unchanged file detection lifecycle."""
    storage_dir = os.path.join(tmp_path, ".storage")
    db_path = os.path.join(storage_dir, "metadata.db")
    repo_dir = os.path.join(tmp_path, "test_repo")
    os.makedirs(repo_dir, exist_ok=True)

    sf_auth = SourceFile(
        path=os.path.join(repo_dir, "auth.py"),
        rel_path="auth.py",
        language="python",
        content="def login(): return True",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=24
    )
    sf_db = SourceFile(
        path=os.path.join(repo_dir, "db.py"),
        rel_path="db.py",
        language="python",
        content="def connect(): pass",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=19
    )

    chunk_auth = CodeChunk(
        chunk_id="auth.py::login",
        file_path="auth.py",
        language="python",
        kind="function",
        name="login",
        start_line=1,
        end_line=1,
        code="def login(): return True",
    )
    chunk_db = CodeChunk(
        chunk_id="db.py::connect",
        file_path="db.py",
        language="python",
        kind="function",
        name="connect",
        start_line=1,
        end_line=1,
        code="def connect(): pass",
    )

    embedder = TfidfEmbedder(dim=8)
    vecs = embedder.embed([chunk_auth.as_embedding_text(), chunk_db.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk_auth, chunk_db], vecs)

    # Initial Index Save
    save_index(
        repo_path=repo_dir,
        backend="tfidf",
        source_files=[sf_auth, sf_db],
        chunks=[chunk_auth, chunk_db],
        store=store,
        db_path=db_path,
        storage_dir=storage_dir
    )

    # 1. Test unchanged repository
    delta1 = detect_repository_changes(repo_dir, [sf_auth, sf_db], db_path=db_path)
    assert delta1.is_fresh_index is False
    assert delta1.has_changes() is False
    assert len(delta1.unchanged) == 2

    # 2. Modify auth.py, delete db.py, and add utils.py
    sf_auth_mod = SourceFile(
        path=os.path.join(repo_dir, "auth.py"),
        rel_path="auth.py",
        language="python",
        content="def login(user): return True # modified!",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=42
    )
    sf_utils_add = SourceFile(
        path=os.path.join(repo_dir, "utils.py"),
        rel_path="utils.py",
        language="python",
        content="def helper(): pass",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=18
    )

    current_files = [sf_auth_mod, sf_utils_add] # db.py is omitted -> deleted!
    delta2 = detect_repository_changes(repo_dir, current_files, db_path=db_path)

    assert delta2.is_fresh_index is False
    assert delta2.has_changes() is True
    assert len(delta2.added) == 1
    assert delta2.added[0].rel_path == "utils.py"
    assert len(delta2.modified) == 1
    assert delta2.modified[0].rel_path == "auth.py"
    assert len(delta2.deleted) == 1
    assert delta2.deleted[0] == "db.py"


def test_delete_files_from_db(tmp_path):
    """Tests delete_files_from_db helper function."""
    db_path = os.path.join(tmp_path, "metadata.db")
    conn = get_db_connection(db_path)
    repo_id = "test_del_repo"

    sf = SourceFile(
        path="/tmp/del.py",
        rel_path="del.py",
        language="python",
        content="x = 1",
        has_tree_sitter=True
    )
    chunk = CodeChunk(
        chunk_id="del.py::x",
        file_path="del.py",
        language="python",
        kind="variable",
        name="x",
        start_line=1,
        end_line=1,
        code="x = 1"
    )

    from core.persistence import save_repo_metadata
    save_repo_metadata(conn, repo_id, "/tmp", "tfidf", [sf], [chunk])

    # Verify present before delete
    hashes_before = load_stored_file_hashes(conn, repo_id)
    chunks_before = load_stored_chunks(conn, repo_id)
    assert "del.py" in hashes_before
    assert len(chunks_before) == 1

    # Delete
    delete_files_from_db(conn, repo_id, ["del.py"])

    # Verify deleted
    hashes_after = load_stored_file_hashes(conn, repo_id)
    chunks_after = load_stored_chunks(conn, repo_id)
    assert "del.py" not in hashes_after
    assert len(chunks_after) == 0

    conn.close()
