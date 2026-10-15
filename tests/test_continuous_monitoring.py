"""
End-to-End Verification and Integration Tests for Continuous Repository Monitoring (REQ-FUT-03).

Verifies:
1. Live watcher-triggered re-indexing on function modification.
2. File addition: new symbols become retrievable.
3. File deletion: stale chunks and references are purged.
4. File rename: new path indexed without duplicate old entries.
5. Ignored files: changes to .gitignore, hidden files, or ignored dirs do not pollute index.
6. Debounce coalescing: multiple rapid edits trigger a single consolidated update.
7. Query engine freshness: engine uses updated vector store and graph rather than stale state.
8. Multi-repo isolation: edits in Repo A do not affect Repo B's index or metadata.
9. Syntax error resilience: malformed code during watcher read does not crash daemon.
10. Watcher lifecycle: start/stop idempotency, thread cleanup, and REST API endpoints.
"""
import os
import shutil
import tempfile
import threading
import time
import pytest

from core.embedder import TfidfEmbedder
from core.pipeline import ingest_repository
from core.vectorstore import FaissVectorStore
from backend.services.incremental_indexer import (
    RepositoryWatcher,
    RepositoryEventHandler,
    is_ignored_path,
    WATCHDOG_AVAILABLE,
)
from rag.query_engine import QueryEngine
from backend.auth import User
from backend.api.repos import ACTIVE_REPOS, ACTIVE_WATCHERS, get_repo_engine
from fastapi.testclient import TestClient
from backend.main import app


@pytest.fixture
def disposable_repo():
    """Creates a temporary repository directory with initial code files."""
    tmpdir = tempfile.mkdtemp(prefix="intellicodex_watch_")
    src_dir = os.path.join(tmpdir, "src")
    os.makedirs(src_dir, exist_ok=True)

    service_file = os.path.join(src_dir, "service.py")
    with open(service_file, "w", encoding="utf-8") as f:
        f.write(
            "def get_status():\n"
            "    \"\"\"Initial status function.\"\"\"\n"
            "    return 'system_offline_v1'\n"
        )

    config_file = os.path.join(tmpdir, "config.py")
    with open(config_file, "w", encoding="utf-8") as f:
        f.write("PORT = 8080\nDEBUG = True\n")

    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_watcher_modify_existing_function(disposable_repo):
    """
    Verifies that modifying an existing function triggers the watcher and
    makes the updated content retrievable through the application query engine.
    """
    embedder = TfidfEmbedder(dim=16)
    initial_res = ingest_repository(disposable_repo, embedder, save_to_disk=True)

    reindex_event = threading.Event()
    reindex_records = []

    def on_reindex(new_result, changed_paths, elapsed):
        reindex_records.append((new_result, changed_paths, elapsed))
        reindex_event.set()

    watcher = RepositoryWatcher(
        repo_path=disposable_repo,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.15,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.15)  # Let filesystem hook establish

        # 1. Modify function content
        service_file = os.path.join(disposable_repo, "src", "service.py")
        with open(service_file, "w", encoding="utf-8") as f:
            f.write(
                "def get_status():\n"
                "    \"\"\"Updated status function.\"\"\"\n"
                "    return 'system_online_v2_ready'\n"
            )

        # 2. Wait for watcher auto-reindex
        triggered = reindex_event.wait(timeout=3.0)
        assert triggered is True, "Watcher failed to trigger auto-reindex within 3.0s"
        assert len(reindex_records) >= 1

        new_result, changed_paths, elapsed = reindex_records[-1]
        assert new_result is not None
        assert elapsed > 0.0

        # 3. Query engine using the refreshed index
        engine = QueryEngine(
            store=new_result.store,
            embedder=embedder,
            dep_graph=new_result.graph,
            lexical_index=getattr(new_result, "lexical_index", None),
            hybrid_search=True,
        )
        results = engine.retrieve("system_online_v2_ready", top_k=3)
        assert len(results) > 0
        top_chunk, _ = results[0]
        assert "system_online_v2_ready" in top_chunk.code
        assert "system_offline_v1" not in top_chunk.code
    finally:
        watcher.stop()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_watcher_add_and_delete_source_file(disposable_repo):
    """
    Verifies that:
    1. Adding a new source file causes its symbols to become retrievable.
    2. Deleting the source file purges its chunks from the vector store and search results.
    """
    embedder = TfidfEmbedder(dim=16)
    initial_res = ingest_repository(disposable_repo, embedder, save_to_disk=True)
    initial_count = initial_res.num_chunks

    add_event = threading.Event()
    del_event = threading.Event()
    results_history = []

    def on_reindex(new_result, changed_paths, elapsed):
        results_history.append((new_result, changed_paths))
        if any("token_manager.py" in p for p in changed_paths):
            if os.path.exists(os.path.join(disposable_repo, "src", "token_manager.py")):
                add_event.set()
            else:
                del_event.set()

    watcher = RepositoryWatcher(
        repo_path=disposable_repo,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.15,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.15)

        # 1. ADD: Create token_manager.py
        new_file = os.path.join(disposable_repo, "src", "token_manager.py")
        with open(new_file, "w", encoding="utf-8") as f:
            f.write(
                "class TokenManager:\n"
                "    def issue_token(self, subject):\n"
                "        return f'jwt_secret_{subject}'\n"
            )

        assert add_event.wait(timeout=3.0) is True
        added_result, _ = results_history[-1]
        assert added_result.num_chunks > initial_count

        engine_add = QueryEngine(
            store=added_result.store,
            embedder=embedder,
            dep_graph=added_result.graph,
            lexical_index=getattr(added_result, "lexical_index", None),
        )
        res_add = engine_add.retrieve("issue_token jwt_secret", top_k=3)
        assert len(res_add) > 0
        assert any("TokenManager" in c.code for c, _ in res_add)

        # 2. DELETE: Remove token_manager.py
        os.remove(new_file)
        assert del_event.wait(timeout=3.0) is True
        deleted_result, _ = results_history[-1]

        # Verify chunks purged
        engine_del = QueryEngine(
            store=deleted_result.store,
            embedder=embedder,
            dep_graph=deleted_result.graph,
            lexical_index=getattr(deleted_result, "lexical_index", None),
        )
        assert not any("token_manager.py" in c.file_path for c in deleted_result.store.chunks)
        assert deleted_result.num_chunks == initial_count
    finally:
        watcher.stop()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_watcher_rename_file_no_duplicate_stale_entries(disposable_repo):
    """
    Verifies that renaming a file updates the index to use the new path,
    and removes the old path without leaving duplicate or stale entries.
    """
    embedder = TfidfEmbedder(dim=16)
    ingest_repository(disposable_repo, embedder, save_to_disk=True)

    # Create original file
    old_path = os.path.join(disposable_repo, "src", "calculator.py")
    with open(old_path, "w", encoding="utf-8") as f:
        f.write(
            "def calculate_tax(subtotal):\n"
            "    \"\"\"Tax computation routine.\"\"\"\n"
            "    return subtotal * 0.15\n"
        )

    # Let watcher handle reindex of created calculator.py
    reindex_event = threading.Event()
    latest_result = [None]

    def on_reindex(new_result, changed_paths, elapsed):
        latest_result[0] = new_result
        reindex_event.set()

    watcher = RepositoryWatcher(
        repo_path=disposable_repo,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.15,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.15)

        # Trigger initial add
        watcher.trigger_reindex([old_path])

        reindex_event.clear()
        # Rename calculator.py -> tax_service.py
        new_path = os.path.join(disposable_repo, "src", "tax_service.py")
        os.rename(old_path, new_path)

        assert reindex_event.wait(timeout=3.0) is True
        res = latest_result[0]
        assert res is not None

        file_paths = [c.file_path.replace("\\", "/") for c in res.store.chunks]
        assert any("tax_service.py" in p for p in file_paths)
        assert not any("calculator.py" in p for p in file_paths), "Old renamed file path must not remain in index"

        engine = QueryEngine(store=res.store, embedder=embedder, dep_graph=res.graph)
        q_res = engine.retrieve("calculate_tax", top_k=3)
        assert len(q_res) > 0
        assert q_res[0][0].file_path.replace("\\", "/").endswith("tax_service.py")
    finally:
        watcher.stop()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_watcher_ignores_excluded_files_and_directories(disposable_repo):
    """
    Verifies that edits to git metadata, temporary files, editor backups,
    and .gitignore patterns do NOT trigger auto-reindexing or alter the index.
    """
    embedder = TfidfEmbedder(dim=16)
    initial_res = ingest_repository(disposable_repo, embedder, save_to_disk=True)

    reindex_called = threading.Event()

    def on_reindex(new_result, changed_paths, elapsed):
        reindex_called.set()

    watcher = RepositoryWatcher(
        repo_path=disposable_repo,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.15,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.15)

        # 1. Create .gitignore
        with open(os.path.join(disposable_repo, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("ignored_folder/\n*.secret\n")

        # 2. Modify files that must be ignored
        git_dir = os.path.join(disposable_repo, ".git")
        os.makedirs(git_dir, exist_ok=True)
        with open(os.path.join(git_dir, "HEAD"), "w", encoding="utf-8") as f:
            f.write("ref: refs/heads/main\n")

        with open(os.path.join(disposable_repo, "notes.tmp.123"), "w", encoding="utf-8") as f:
            f.write("temporary buffer\n")

        ignored_dir = os.path.join(disposable_repo, "ignored_folder")
        os.makedirs(ignored_dir, exist_ok=True)
        with open(os.path.join(ignored_dir, "skip.py"), "w", encoding="utf-8") as f:
            f.write("def ignored_code(): pass\n")

        # Wait debounce window plus margin
        time.sleep(0.4)
        assert reindex_called.is_set() is False, "Watcher should not trigger on ignored files"
    finally:
        watcher.stop()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_watcher_debounce_coalesces_rapid_edits(disposable_repo):
    """
    Verifies that multiple rapid file edits in sub-debounce timeframes
    are coalesced into a single consolidated re-index event.
    """
    embedder = TfidfEmbedder(dim=16)
    ingest_repository(disposable_repo, embedder, save_to_disk=True)

    reindex_count = 0
    lock = threading.Lock()
    done_event = threading.Event()
    latest_res = [None]

    def on_reindex(new_result, changed_paths, elapsed):
        nonlocal reindex_count
        with lock:
            reindex_count += 1
            latest_res[0] = new_result
        done_event.set()

    # 300ms debounce
    watcher = RepositoryWatcher(
        repo_path=disposable_repo,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.30,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.15)

        service_file = os.path.join(disposable_repo, "src", "service.py")

        # 6 rapid edits in ~60ms
        for i in range(6):
            with open(service_file, "w", encoding="utf-8") as f:
                f.write(f"def get_status():\n    return 'rapid_edit_{i}'\n")
            time.sleep(0.01)

        # Wait for debounce to settle
        assert done_event.wait(timeout=2.0) is True
        time.sleep(0.2)  # Extra settling time to ensure no second fire

        with lock:
            assert reindex_count == 1, f"Expected 1 coalesced reindex, got {reindex_count}"
            assert latest_res[0] is not None
            # Final state must reflect the last rapid edit (rapid_edit_5)
            assert any("rapid_edit_5" in c.code for c in latest_res[0].store.chunks)
    finally:
        watcher.stop()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_multi_repository_isolation_under_monitoring(disposable_repo):
    """
    Verifies that monitoring Repo A never modifies or corrupts Repo B's index or metadata.
    """
    repo_b = tempfile.mkdtemp(prefix="intellicodex_watch_b_")
    try:
        with open(os.path.join(repo_b, "unique_b.py"), "w", encoding="utf-8") as f:
            f.write("def function_exclusive_to_b():\n    return 'repo_b_pristine'\n")

        embedder = TfidfEmbedder(dim=16)
        res_a = ingest_repository(disposable_repo, embedder, save_to_disk=True)
        res_b = ingest_repository(repo_b, embedder, save_to_disk=True)

        b_chunks_before = len(res_b.store.chunks)
        b_symbols = [c.name for c in res_b.store.chunks]

        # Watch Repo A only
        reindex_a_event = threading.Event()
        watcher_a = RepositoryWatcher(
            repo_path=disposable_repo,
            embedder=embedder,
            on_reindex=lambda r, c, e: reindex_a_event.set(),
            debounce_delay=0.15,
        )

        assert watcher_a.start() is True
        time.sleep(0.15)

        # Modify Repo A
        with open(os.path.join(disposable_repo, "src", "service.py"), "a", encoding="utf-8") as f:
            f.write("\ndef extra_func_in_a(): pass\n")

        assert reindex_a_event.wait(timeout=3.0) is True
        watcher_a.stop()

        # Load Repo B from disk and verify it was untouched
        res_b_after = ingest_repository(repo_b, embedder, force_reindex=False, save_to_disk=False)
        assert len(res_b_after.store.chunks) == b_chunks_before
        assert [c.name for c in res_b_after.store.chunks] == b_symbols
        assert not any("extra_func_in_a" in c.code for c in res_b_after.store.chunks)
    finally:
        shutil.rmtree(repo_b, ignore_errors=True)


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_syntax_error_resilience_during_watcher_sync(disposable_repo):
    """
    Verifies that writing a temporary syntax error does not crash the watcher
    or corrupt the index, and that subsequent fixes restore full index accuracy.
    """
    embedder = TfidfEmbedder(dim=16)
    initial_res = ingest_repository(disposable_repo, embedder, save_to_disk=True)

    reindex_event = threading.Event()

    def on_reindex(new_result, changed_paths, elapsed):
        reindex_event.set()

    watcher = RepositoryWatcher(
        repo_path=disposable_repo,
        embedder=embedder,
        on_reindex=on_reindex,
        debounce_delay=0.15,
    )

    try:
        assert watcher.start() is True
        time.sleep(0.15)

        service_file = os.path.join(disposable_repo, "src", "service.py")

        # 1. Write broken syntax
        reindex_event.clear()
        with open(service_file, "w", encoding="utf-8") as f:
            f.write("def broken_syntax(:\n  return\n")

        assert reindex_event.wait(timeout=3.0) is True
        # Watcher should still be alive
        assert watcher.is_alive() is True

        # 2. Write valid syntax
        reindex_event.clear()
        with open(service_file, "w", encoding="utf-8") as f:
            f.write("def repaired_syntax():\n    return 'fully_restored'\n")

        assert reindex_event.wait(timeout=3.0) is True
        assert watcher.is_alive() is True
        assert any("repaired_syntax" in c.code for c in watcher.current_result.store.chunks)
    finally:
        watcher.stop()


@pytest.mark.skipif(not WATCHDOG_AVAILABLE, reason="watchdog package unavailable")
def test_rest_api_watch_endpoints_lifecycle(disposable_repo):
    """
    Verifies FastAPI endpoints for repository monitoring:
    - POST /api/repos/{repo_id}/watch/start
    - GET  /api/repos/{repo_id}/watch/status
    - POST /api/repos/{repo_id}/watch/stop
    """
    client = TestClient(app)
    embedder = TfidfEmbedder(dim=16)
    ingest_repository(disposable_repo, embedder, save_to_disk=True)

    user = User(id="watch_user", username="watchman", email="watch@local.com", role="developer")
    from backend.database import db_manager
    db_manager.insert("users", {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "hashed_password": "dummy",
    })
    from backend.auth import create_access_token
    token = create_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}

    repo_id = "monitored-test-repo"
    ACTIVE_REPOS[repo_id] = {
        "engine": QueryEngine(FaissVectorStore(16), embedder),
        "store": FaissVectorStore(16),
        "meta": {"repo_id": repo_id, "repo_path": disposable_repo, "owner_id": user.id},
        "embedder": embedder,
    }

    try:
        # 1. Start watcher via API
        resp_start = client.post(f"/api/repos/{repo_id}/watch/start", headers=headers)
        assert resp_start.status_code == 200
        data_start = resp_start.json()
        assert data_start["active"] is True
        assert repo_id in ACTIVE_WATCHERS
        assert ACTIVE_WATCHERS[repo_id].is_alive() is True

        # 2. Duplicate start is idempotent
        resp_dup = client.post(f"/api/repos/{repo_id}/watch/start", headers=headers)
        assert resp_dup.status_code == 200
        assert resp_dup.json()["active"] is True

        # 3. Check status
        resp_st = client.get(f"/api/repos/{repo_id}/watch/status", headers=headers)
        assert resp_st.status_code == 200
        assert resp_st.json()["active"] is True

        # 4. Stop watcher via API
        resp_stop = client.post(f"/api/repos/{repo_id}/watch/stop", headers=headers)
        assert resp_stop.status_code == 200
        assert resp_stop.json()["active"] is False
        assert repo_id not in ACTIVE_WATCHERS

        # 5. Check status is now inactive
        resp_st2 = client.get(f"/api/repos/{repo_id}/watch/status", headers=headers)
        assert resp_st2.status_code == 200
        assert resp_st2.json()["active"] is False
    finally:
        if repo_id in ACTIVE_WATCHERS:
            ACTIVE_WATCHERS[repo_id].stop()
            ACTIVE_WATCHERS.pop(repo_id, None)
        ACTIVE_REPOS.pop(repo_id, None)
