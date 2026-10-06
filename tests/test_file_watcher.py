"""
Unit & Integration Tests for Milestone 2: Real-Time Filesystem Watcher Daemon
Tests RepositoryEventHandler, RepositoryWatcher, debouncing, file filtering, and live re-indexing.
"""
import os
import time
import threading
import tempfile
import pytest
from unittest.mock import MagicMock

from backend.services.incremental_indexer import (
    RepositoryEventHandler,
    RepositoryWatcher,
    is_ignored_path,
    WATCHDOG_AVAILABLE,
)
from core.embedder import TfidfEmbedder
from core.pipeline import ingest_repository


def test_is_ignored_path():
    repo = os.path.abspath("temp_repo")

    # Ignored directories
    assert is_ignored_path(os.path.join(repo, ".git", "HEAD"), repo) is True
    assert is_ignored_path(os.path.join(repo, ".venv", "lib", "site.py"), repo) is True
    assert is_ignored_path(os.path.join(repo, "__pycache__", "mod.cpython-310.pyc"), repo) is True
    assert is_ignored_path(os.path.join(repo, "node_modules", "package", "index.js"), repo) is True
    assert is_ignored_path(os.path.join(repo, ".repos", "cloned", "app.py"), repo) is True

    # Ignored extensions & backup files
    assert is_ignored_path(os.path.join(repo, "auth.py.bak.12345"), repo) is True
    assert is_ignored_path(os.path.join(repo, "auth.py.tmp.999"), repo) is True
    assert is_ignored_path(os.path.join(repo, "test.swp"), repo) is True
    assert is_ignored_path(os.path.join(repo, "cache.lock"), repo) is True
    assert is_ignored_path(os.path.join(repo, "notes.txt"), repo) is True  # .txt is not in LANGUAGE_BY_EXT

    # Legitimate code files (must NOT be ignored)
    assert is_ignored_path(os.path.join(repo, "pkg", "auth.py"), repo) is False
    assert is_ignored_path(os.path.join(repo, "src", "index.ts"), repo) is False
    assert is_ignored_path(os.path.join(repo, "app.js"), repo) is False
    assert is_ignored_path(os.path.join(repo, "main.go"), repo) is False
    assert is_ignored_path(os.path.join(repo, "lib.rs"), repo) is False


def test_repository_event_handler_filtering(tmp_path):
    repo_dir = str(tmp_path)
    callback = MagicMock()
    handler = RepositoryEventHandler(repo_root=repo_dir, callback=callback, debounce_delay=0.1)

    class MockEvent:
        def __init__(self, src_path, is_directory=False):
            self.src_path = src_path
            self.is_directory = is_directory

    # Dispatch ignored events
    handler.on_modified(MockEvent(os.path.join(repo_dir, ".git", "index")))
    handler.on_created(MockEvent(os.path.join(repo_dir, "test.py.bak.123")))
    handler.on_modified(MockEvent(os.path.join(repo_dir, "__pycache__", "foo.pyc")))
    time.sleep(0.2)
    assert callback.call_count == 0

    handler.cancel_pending()


def test_repository_event_handler_debouncing(tmp_path):
    repo_dir = str(tmp_path)
    called_batches = []
    event_done = threading.Event()

    def on_batch(paths):
        called_batches.append(paths)
        event_done.set()

    handler = RepositoryEventHandler(repo_root=repo_dir, callback=on_batch, debounce_delay=0.15)

    class MockEvent:
        def __init__(self, src_path, is_directory=False):
            self.src_path = src_path
            self.is_directory = is_directory

    f1 = os.path.join(repo_dir, "app.py")
    f2 = os.path.join(repo_dir, "db.py")

    # Dispatch 5 rapid events in <50ms
    for _ in range(5):
        handler.on_modified(MockEvent(f1))
        handler.on_modified(MockEvent(f2))
        time.sleep(0.01)

    # Wait for debounce timer to fire
    event_done.wait(timeout=1.0)
    assert len(called_batches) == 1
    # Both modified files should be collected in the single batch
    batch = [os.path.abspath(p) for p in called_batches[0]]
    assert os.path.abspath(f1) in batch
    assert os.path.abspath(f2) in batch

    handler.cancel_pending()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not available")
def test_repository_watcher_lifecycle(tmp_path):
    repo_dir = str(tmp_path)
    embedder = TfidfEmbedder(dim=8)

    # Context manager test
    with RepositoryWatcher(repo_dir, embedder=embedder, debounce_delay=0.1) as watcher:
        assert watcher.is_alive() is True
    assert watcher.is_alive() is False

    # Manual start / stop
    watcher2 = RepositoryWatcher(repo_dir, embedder=embedder, debounce_delay=0.1)
    assert watcher2.start() is True
    assert watcher2.is_alive() is True
    # Double start should be idempotent
    assert watcher2.start() is True

    watcher2.stop()
    assert watcher2.is_alive() is False


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog not available")
def test_repository_watcher_live_incremental_reindex(tmp_path):
    repo_dir = str(tmp_path)
    app_file = os.path.join(repo_dir, "service.py")

    with open(app_file, "w", encoding="utf-8") as f:
        f.write("def start_service():\n    return 'initial'\n")

    embedder = TfidfEmbedder(dim=8)
    initial_res = ingest_repository(repo_dir, embedder, save_to_disk=True)
    assert initial_res.num_chunks >= 1

    reindex_event = threading.Event()
    reindexed_records = []

    def on_reindex(new_res, changed_paths, elapsed):
        reindexed_records.append((new_res, changed_paths, elapsed))
        reindex_event.set()

    watcher = RepositoryWatcher(
        repo_path=repo_dir,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.15,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.1)  # Let observer establish file system hooks

        # Modify service.py on disk
        with open(app_file, "a", encoding="utf-8") as f:
            f.write("\ndef stop_service():\n    return 'shutdown_complete'\n")

        # Wait for auto-reindex notification
        success = reindex_event.wait(timeout=3.0)
        assert success is True, "Watcher failed to trigger auto-reindex within timeout"
        assert len(reindexed_records) >= 1

        new_res, changed_paths, elapsed = reindexed_records[-1]
        assert new_res is not None
        assert any("stop_service" in c.code for c in new_res.store.chunks)
        assert elapsed > 0.0
    finally:
        watcher.stop()


def test_repository_watcher_trigger_reindex_direct(tmp_path):
    repo_dir = str(tmp_path)
    mod_file = os.path.join(repo_dir, "module.py")
    with open(mod_file, "w", encoding="utf-8") as f:
        f.write("def calculate(x, y):\n    return x + y\n")

    embedder = TfidfEmbedder(dim=8)
    reindex_called = []

    def on_reindex(res, changed, elapsed):
        reindex_called.append((res, changed))

    watcher = RepositoryWatcher(repo_dir, embedder=embedder, on_reindex=on_reindex)
    res = watcher.trigger_reindex([mod_file])

    assert res is not None
    assert len(reindex_called) == 1
    assert watcher.current_result == res
