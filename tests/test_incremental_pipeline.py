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


def test_deleted_file_purged_and_subsequent_zero_latency(tmp_path):
    """Tests that deleting a file purges its metadata from SQLite, enabling zero-latency cache reload on next run."""
    repo_dir = os.path.join(tmp_path, "del_repo")
    os.makedirs(repo_dir, exist_ok=True)
    db_file = os.path.join(tmp_path, "meta.db")

    with open(os.path.join(repo_dir, "alpha.py"), "w") as f:
        f.write("def alpha(): return 1\n")
    with open(os.path.join(repo_dir, "beta.py"), "w") as f:
        f.write("def beta(): return 2\n")

    embedder = TfidfEmbedder(dim=8)

    # 1. Fresh ingest
    res1 = ingest_repository(repo_dir, embedder, save_to_disk=True, db_path=db_file)
    assert res1.num_files == 2
    assert res1.indexing_mode == "fresh"

    # 2. Delete beta.py
    os.remove(os.path.join(repo_dir, "beta.py"))

    # 3. Incremental ingest after deletion
    res2 = ingest_repository(repo_dir, embedder, save_to_disk=True, db_path=db_file)
    assert res2.num_files == 1
    assert res2.indexing_mode == "incremental"
    assert not any("beta" in c.file_path for c in res2.store.chunks)

    # 4. Subsequent run with NO changes - must be 100% cached (not falsely re-triggering deletion delta)
    res3 = ingest_repository(repo_dir, embedder, save_to_disk=True, db_path=db_file)
    assert res3.num_files == 1
    assert res3.indexing_mode == "cached"


def test_cache_invalidation_on_dimension_mismatch(tmp_path):
    """Tests that switching embedder dimensions invalidates cached index and triggers clean re-index."""
    repo_dir = os.path.join(tmp_path, "dim_repo")
    os.makedirs(repo_dir, exist_ok=True)
    db_file = os.path.join(tmp_path, "meta.db")

    with open(os.path.join(repo_dir, "main.py"), "w") as f:
        f.write("def calculate(): return 42\n")

    embedder8 = TfidfEmbedder(dim=8)
    res1 = ingest_repository(repo_dir, embedder8, save_to_disk=True, db_path=db_file)
    assert res1.store.dim == 8
    assert res1.indexing_mode == "fresh"

    # Now ingest with embedder having dim=16
    embedder16 = TfidfEmbedder(dim=16)
    res2 = ingest_repository(repo_dir, embedder16, save_to_disk=True, db_path=db_file)
    assert res2.store.dim == 16
    assert res2.indexing_mode == "fresh"


def test_sync_repository_handles_deleted_files(tmp_path):
    """Tests that IncrementalIndexer.sync_repository purges deleted file chunks."""
    from backend.services.incremental_indexer import IncrementalIndexer, compute_file_hash

    repo_dir = os.path.join(tmp_path, "sync_repo")
    os.makedirs(repo_dir, exist_ok=True)

    file_a = os.path.join(repo_dir, "a.py")
    file_b = os.path.join(repo_dir, "b.py")
    with open(file_a, "w") as f:
        f.write("def func_a(): pass\n")
    with open(file_b, "w") as f:
        f.write("def func_b(): pass\n")

    embedder = TfidfEmbedder(dim=8)
    indexer = IncrementalIndexer(embedder=embedder)

    res1 = ingest_repository(repo_dir, embedder, save_to_disk=False)
    hashes1 = {sf.rel_path: compute_file_hash(sf.content) for sf in res1.files}

    # Delete b.py
    os.remove(file_b)

    new_store, new_hashes, changed_count = indexer.sync_repository(
        repo_path=repo_dir,
        existing_store=res1.store,
        previous_file_hashes=hashes1,
    )

    assert changed_count == 1
    assert "b.py" not in new_hashes
    assert not any("b.py" in c.file_path for c in new_store.chunks)


def test_ivf_direct_map_safe_vector_reconstruction():
    """Tests that IVF approximate index can reconstruct vectors via make_direct_map without throwing."""
    import faiss
    import numpy as np
    from core.vectorstore import FaissVectorStore
    from core.chunker import CodeChunk

    dim = 8
    store = FaissVectorStore(dim=dim)
    n = 60
    vecs = np.random.randn(n, dim).astype("float32")
    chunks = [
        CodeChunk(chunk_id=f"c_{i}", file_path=f"f_{i}.py", language="python", kind="function", name=f"fn_{i}", start_line=1, end_line=2, code="pass")
        for i in range(n)
    ]
    quantizer = faiss.IndexFlatIP(dim)
    ivf = faiss.IndexIVFFlat(quantizer, dim, 4, faiss.METRIC_INNER_PRODUCT)
    ivf.train(vecs)
    ivf.add(vecs)
    ivf.make_direct_map()
    store.index = ivf
    store.chunks = chunks

    v0 = store.get_vector(0)
    assert v0 is not None
    assert len(v0) == dim

