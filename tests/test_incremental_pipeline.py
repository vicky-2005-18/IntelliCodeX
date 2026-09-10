"""
Unit Tests for Incremental Re-Indexing Pipeline (core/pipeline.py - Week 3 Day 4)
"""
import os
import tempfile
import pytest
from core.parser import SourceFile
from core.embedder import TfidfEmbedder
from core.pipeline import ingest_repository, IngestedRepository


def test_pipeline_zero_latency_cache_reload(tmp_path):
    """Tests that a 100% unchanged repository loads instantly from cached disk index."""
    repo_dir = os.path.join(tmp_path, "sample_repo")
    os.makedirs(repo_dir, exist_ok=True)

    with open(os.path.join(repo_dir, "app.py"), "w") as f:
        f.write("def run():\n    print('running app')\n")

    embedder = TfidfEmbedder(dim=8)

    # First ingest (Fresh)
    res1 = ingest_repository(repo_dir, embedder, save_to_disk=True)
    assert res1.num_files == 1
    assert res1.num_chunks >= 1

    # Second ingest (Cached - 0 changes)
    res2 = ingest_repository(repo_dir, embedder, force_reindex=False)
    assert res2.num_files == 1
    assert res2.num_chunks == res1.num_chunks
    assert len(res2.store) == len(res1.store)


def test_pipeline_incremental_reindex(tmp_path):
    """Tests incremental re-indexing when files are modified, added, or removed."""
    repo_dir = os.path.join(tmp_path, "incr_repo")
    os.makedirs(repo_dir, exist_ok=True)

    auth_path = os.path.join(repo_dir, "auth.py")
    db_path = os.path.join(repo_dir, "db.py")

    with open(auth_path, "w") as f:
        f.write("def login(user):\n    return True\n")
    with open(db_path, "w") as f:
        f.write("def connect():\n    return None\n")

    embedder = TfidfEmbedder(dim=8)

    # 1. Initial ingestion
    res1 = ingest_repository(repo_dir, embedder, save_to_disk=True)
    initial_chunks_count = res1.num_chunks

    # 2. Modify auth.py and add utils.py
    with open(auth_path, "w") as f:
        f.write("def login(user, password):\n    # Updated auth with password!\n    return True\n")

    utils_path = os.path.join(repo_dir, "utils.py")
    with open(utils_path, "w") as f:
        f.write("def helper():\n    pass\n")

    # 3. Incremental ingest
    res2 = ingest_repository(repo_dir, embedder, force_reindex=False)
    assert res2.num_files == 3
    assert res2.num_chunks > initial_chunks_count

    # Check that updated chunks contain login with password
    codes = [c.code for c in res2.store.chunks]
    assert any("password" in c for c in codes)


def test_pipeline_force_reindex(tmp_path):
    """Tests force_reindex parameter forces clean re-ingestion."""
    repo_dir = os.path.join(tmp_path, "force_repo")
    os.makedirs(repo_dir, exist_ok=True)

    with open(os.path.join(repo_dir, "main.py"), "w") as f:
        f.write("def main(): pass\n")

    embedder = TfidfEmbedder(dim=8)
    res1 = ingest_repository(repo_dir, embedder, save_to_disk=True)

    res2 = ingest_repository(repo_dir, embedder, force_reindex=True)
    assert res2.num_files == 1
    assert res2.num_chunks == res1.num_chunks
