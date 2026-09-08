"""
Unit Tests for SQLite Persistence Manager (core/persistence.py)
"""
import os
import tempfile
import pytest
from core.parser import SourceFile
from core.chunker import CodeChunk
from core.persistence import (
    get_db_connection,
    save_repo_metadata,
    load_stored_file_hashes,
    load_stored_chunks,
    load_repo_metadata,
    compute_file_hash,
)


def test_sqlite_persistence_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "metadata.db")
        conn = get_db_connection(db_path)

        sf1 = SourceFile(
            path="/tmp/main.py",
            rel_path="main.py",
            language="python",
            content="def main(): pass",
            has_tree_sitter=True,
            line_count=1,
            size_bytes=16
        )

        chunk1 = CodeChunk(
            chunk_id="main.py::main",
            file_path="main.py",
            language="python",
            kind="function",
            name="main",
            start_line=1,
            end_line=1,
            code="def main(): pass",
            docstring="Main function",
            imports=["os"]
        )

        repo_id = "test_repo_1"
        save_repo_metadata(
            conn=conn,
            repo_id=repo_id,
            repo_path="/tmp",
            backend="tfidf",
            source_files=[sf1],
            chunks=[chunk1]
        )

        # 1. Verify repo metadata load
        meta = load_repo_metadata(conn, repo_id)
        assert meta is not None
        assert meta["repo_id"] == repo_id
        assert meta["total_files"] == 1
        assert meta["total_chunks"] == 1

        # 2. Verify stored file hash
        hashes = load_stored_file_hashes(conn, repo_id)
        assert "main.py" in hashes
        assert hashes["main.py"] == compute_file_hash("def main(): pass")

        # 3. Verify reloaded chunk objects
        stored_chunks = load_stored_chunks(conn, repo_id)
        assert len(stored_chunks) == 1
        assert stored_chunks[0].chunk_id == "main.py::main"
        assert stored_chunks[0].name == "main"
        assert stored_chunks[0].imports == ["os"]

        conn.close()
