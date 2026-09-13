"""
Week 3 Comprehensive Milestone Verification Suite
Tests SQLite persistence, FAISS index serialization, fast SHA-256 change detection,
incremental re-indexing pipeline, Git hook generator, and zero-latency cached CLI startup.
"""
import os
import tempfile
import time
import subprocess
import pytest
from core.parser import SourceFile, walk_repository
from core.chunker import CodeChunk, chunk_repository
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.persistence import (
    get_db_connection,
    save_index,
    load_index,
    detect_repository_changes,
    compute_file_hash,
    get_repo_id,
)
from core.pipeline import ingest_repository
from core.git_hooks import install_git_hooks, uninstall_git_hooks, check_git_hooks_status
from core.benchmarking import run_benchmark


def test_week3_sqlite_metadata_db_verification(tmp_path):
    """1. Verifies SQLite metadata schema, SHA-256 hash calculation, and chunk persistence."""
    db_path = os.path.join(tmp_path, "metadata.db")
    conn = get_db_connection(db_path)

    sf = SourceFile(
        path="/repo/auth.py",
        rel_path="auth.py",
        language="python",
        content="def login(): return True\n",
        has_tree_sitter=True,
        line_count=1,
        size_bytes=24
    )
    chunk = CodeChunk(
        chunk_id="auth.py::login",
        file_path="auth.py",
        language="python",
        kind="function",
        name="login",
        start_line=1,
        end_line=1,
        code="def login(): return True",
        docstring="Auth login function",
        imports=["sys"]
    )

    repo_id = "test_wk3_db"
    from core.persistence import save_repo_metadata, load_repo_metadata, load_stored_chunks, load_stored_file_hashes
    save_repo_metadata(conn, repo_id, "/repo", "tfidf", [sf], [chunk])

    meta = load_repo_metadata(conn, repo_id)
    assert meta is not None
    assert meta["total_files"] == 1
    assert meta["total_chunks"] == 1

    hashes = load_stored_file_hashes(conn, repo_id)
    assert "auth.py" in hashes
    assert hashes["auth.py"] == compute_file_hash("def login(): return True\n")

    chunks = load_stored_chunks(conn, repo_id)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "auth.py::login"
    assert chunks[0].imports == ["sys"]
    conn.close()


def test_week3_faiss_persistence_verification(tmp_path):
    """2. Verifies FAISS binary index serialization, deserialization, and similarity search fidelity."""
    embedder = TfidfEmbedder(dim=12)
    chunk = CodeChunk(
        chunk_id="db.py::connect",
        file_path="db.py",
        language="python",
        kind="function",
        name="connect",
        start_line=1,
        end_line=2,
        code="def connect(): pass\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    faiss_path = os.path.join(tmp_path, "index.faiss")
    store.save(faiss_path)
    assert os.path.exists(faiss_path)

    reloaded_store = FaissVectorStore.load(faiss_path, chunks=[chunk])
    assert len(reloaded_store) == 1
    assert reloaded_store.dim == vecs.shape[1]

    # Verify query similarity
    res_orig = store.search(vecs[0], top_k=1)
    res_reload = reloaded_store.search(vecs[0], top_k=1)
    assert res_reload[0][0].chunk_id == res_orig[0][0].chunk_id
    assert abs(res_reload[0][1] - res_orig[0][1]) < 1e-5


def test_week3_fast_change_detection_verification(tmp_path):
    """3. Verifies fast SHA-256 change detection for added, modified, deleted, and untouched files."""
    db_path = os.path.join(tmp_path, "metadata.db")
    repo_dir = os.path.join(tmp_path, "repo")
    os.makedirs(repo_dir, exist_ok=True)

    sf_a = SourceFile(
        path=os.path.join(repo_dir, "a.py"),
        rel_path="a.py",
        language="python",
        content="a = 1",
        has_tree_sitter=True
    )
    sf_b = SourceFile(
        path=os.path.join(repo_dir, "b.py"),
        rel_path="b.py",
        language="python",
        content="b = 2",
        has_tree_sitter=True
    )

    c_a = CodeChunk(chunk_id="a.py::a", file_path="a.py", language="python", kind="variable", name="a", start_line=1, end_line=1, code="a = 1")
    c_b = CodeChunk(chunk_id="b.py::b", file_path="b.py", language="python", kind="variable", name="b", start_line=1, end_line=1, code="b = 2")

    embedder = TfidfEmbedder(dim=8)
    vecs = embedder.embed([c_a.as_embedding_text(), c_b.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([c_a, c_b], vecs)

    save_index(repo_dir, "tfidf", [sf_a, sf_b], [c_a, c_b], store, db_path=db_path, storage_dir=str(tmp_path))

    # Untouched
    delta1 = detect_repository_changes(repo_dir, [sf_a, sf_b], db_path=db_path)
    assert delta1.has_changes() is False
    assert len(delta1.unchanged) == 2

    # Modified a.py, deleted b.py, added c.py
    sf_a_mod = SourceFile(path=os.path.join(repo_dir, "a.py"), rel_path="a.py", language="python", content="a = 100", has_tree_sitter=True)
    sf_c_add = SourceFile(path=os.path.join(repo_dir, "c.py"), rel_path="c.py", language="python", content="c = 3", has_tree_sitter=True)

    delta2 = detect_repository_changes(repo_dir, [sf_a_mod, sf_c_add], db_path=db_path)
    assert delta2.has_changes() is True
    assert len(delta2.added) == 1 and delta2.added[0].rel_path == "c.py"
    assert len(delta2.modified) == 1 and delta2.modified[0].rel_path == "a.py"
    assert len(delta2.deleted) == 1 and delta2.deleted[0] == "b.py"


def test_week3_incremental_reindexing_verification(tmp_path):
    """4. Verifies end-to-end incremental re-indexing workflow."""
    repo_dir = os.path.join(tmp_path, "repo_inc")
    os.makedirs(repo_dir, exist_ok=True)

    file1 = os.path.join(repo_dir, "main.py")
    with open(file1, "w") as f:
        f.write("def main(): pass\n")

    embedder = TfidfEmbedder(dim=8)

    # Initial ingest
    res1 = ingest_repository(repo_dir, embedder, save_to_disk=True)
    assert res1.num_files == 1

    # Modify file1 and add file2
    with open(file1, "w") as f:
        f.write("def main():\n    print('v2')\n")
    with open(os.path.join(repo_dir, "utils.py"), "w") as f:
        f.write("def help(): pass\n")

    # Incremental ingest
    res2 = ingest_repository(repo_dir, embedder, force_reindex=False)
    assert res2.num_files == 2
    assert res2.num_chunks > res1.num_chunks


def test_week3_git_hooks_generator_verification(tmp_path):
    """5. Verifies Git hook generator installation and management."""
    repo_dir = os.path.join(tmp_path, "git_repo")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, text=True, check=True)

    # Install
    ok_inst, _ = install_git_hooks(repo_dir)
    assert ok_inst is True

    # Check
    st = check_git_hooks_status(repo_dir)
    assert st["post-commit"] is True and st["post-merge"] is True

    # Uninstall
    ok_uninst, _ = uninstall_git_hooks(repo_dir)
    assert ok_uninst is True
    st_after = check_git_hooks_status(repo_dir)
    assert st_after["post-commit"] is False and st_after["post-merge"] is False


def test_week3_benchmark_performance_verification():
    """6. Verifies zero-latency startup benchmarking on sample_repo."""
    report = run_benchmark("sample_repo")
    assert report.num_files >= 1
    assert report.num_chunks >= 1
    assert report.total_time_seconds > 0
    assert report.cached_time_seconds >= 0
    assert report.speedup_factor >= 1.0
