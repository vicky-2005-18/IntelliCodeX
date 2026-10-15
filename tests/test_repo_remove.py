"""
Unit & Integration Tests for IntelliCodeX CLI 'repo remove <number|name>' command.
"""
import os
import sys
import shutil
import tempfile
import sqlite3
import pytest
from unittest.mock import patch, MagicMock

from cli import (
    get_available_repos,
    handle_repo_remove,
    print_help,
    IntelliCodeXCompleter,
)
from core.persistence import (
    init_schema,
    save_repo_metadata,
    unregister_repo,
    clear_unregistered_repo,
    get_unregistered_repos,
    is_repo_unregistered,
    get_repo_id,
)
from core.parser import SourceFile
from core.chunker import CodeChunk


@pytest.fixture
def isolated_db_and_repos():
    """Sets up an isolated test sandbox with a test metadata.db and test repo folders."""
    sandbox_base = os.path.abspath(os.path.join("scratch", "test_repo_remove_sandbox"))
    os.makedirs(sandbox_base, exist_ok=True)
    import uuid
    tmpdir = os.path.join(sandbox_base, f"run_{uuid.uuid4().hex[:8]}")
    os.makedirs(tmpdir, exist_ok=True)

    db_path = os.path.join(tmpdir, "metadata.db")
    repo1 = os.path.join(tmpdir, "alpha_repo")
    repo2 = os.path.join(tmpdir, "beta_repo")
    repo3_dup = os.path.join(tmpdir, "alpha_dup_dir", "alpha_repo")
    os.makedirs(repo1, exist_ok=True)
    os.makedirs(repo2, exist_ok=True)
    os.makedirs(repo3_dup, exist_ok=True)

    # Put a sample source file in repo2
    sample_file = os.path.join(repo2, "main.py")
    with open(sample_file, "w", encoding="utf-8") as f:
        f.write("def hello(): return 'world'\n")

    # Put a dummy git folder in repo2
    git_dir = os.path.join(repo2, ".git")
    os.makedirs(git_dir, exist_ok=True)
    with open(os.path.join(git_dir, "config"), "w", encoding="utf-8") as f:
        f.write("[core]\n\trepositoryformatversion = 0\n")

    # Put a dummy cache file
    cache_file = os.path.join(tmpdir, f"{get_repo_id(repo2)}.faiss")
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write("dummy_faiss_cache_data")

    # Register repo1 and repo2 in the isolated SQLite database
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)

    sf = SourceFile(
        path=sample_file,
        rel_path="main.py",
        content="def hello(): return 'world'\n",
        language="python",
        size_bytes=28,
        line_count=1,
    )
    chunk = CodeChunk(
        chunk_id=f"{get_repo_id(repo2)}_chunk1",
        file_path="main.py",
        language="python",
        kind="function",
        name="hello",
        start_line=1,
        end_line=1,
        code="def hello(): return 'world'",
    )
    save_repo_metadata(conn, get_repo_id(repo1), repo1, "tfidf", [], [])
    save_repo_metadata(conn, get_repo_id(repo2), repo2, "tfidf", [sf], [chunk])
    conn.close()

    yield {
        "tmpdir": tmpdir,
        "db_path": db_path,
        "repo1": repo1,
        "repo2": repo2,
        "repo3_dup": repo3_dup,
        "sample_file": sample_file,
        "git_dir": git_dir,
        "cache_file": cache_file,
    }

    shutil.rmtree(tmpdir, ignore_errors=True)


def test_help_text_includes_repo_remove(capsys):
    """Verify help command displays documentation for repo remove."""
    print_help()
    captured = capsys.readouterr().out
    assert "repo remove" in captured


def test_autocomplete_includes_repo_remove():
    """Verify completer includes repo remove command and parameter suggestions."""
    completer = IntelliCodeXCompleter(
        get_repos_fn=lambda: [("repoA", "/path/a"), ("repoB", "/path/b")]
    )
    # Check COMMANDS table
    matching_cmds = [cmd for cmd, desc in completer.COMMANDS if "repo remove" in cmd]
    assert len(matching_cmds) > 0

    # Check typing 'repo ' suggests 'remove '
    doc = MagicMock()
    doc.text_before_cursor = "repo rem"
    completions = list(completer.get_completions(doc))
    displays = [getattr(c, "display_text", c.text) for c in completions]
    assert any("remove" in d for d in displays)

    # Check typing 'repo remove ' completes repo numbers and names
    doc.text_before_cursor = "repo remove "
    completions = list(completer.get_completions(doc))
    meta_types = [str(c.display_meta) for c in completions]
    assert any("Repo Number" in m for m in meta_types)
    assert any("Repo Name" in m for m in meta_types)


def test_repo_remove_active_repo_is_rejected(isolated_db_and_repos):
    """Verify that removing the currently active repository is rejected with a message to switch first."""
    env = isolated_db_and_repos
    active_path = env["repo2"]
    other_path = env["repo1"]

    outputs = []
    success, msg = handle_repo_remove(
        target_arg="beta_repo",
        current_path=active_path,
        db_path=env["db_path"],
        output_fn=outputs.append,
    )

    assert success is False
    assert "Cannot remove active repository" in msg
    out_text = " ".join(outputs)
    assert "Cannot remove the active repository" in out_text
    assert "switch to another repository first" in out_text


def test_repo_remove_number_resolution_matches_repos_order(isolated_db_and_repos):
    """Verify numbers resolve using the exact ordering returned by get_available_repos."""
    env = isolated_db_and_repos
    available = get_available_repos(env["repo1"], db_path=env["db_path"])
    # Find index of repo2 in available list
    repo2_idx = None
    for idx, (lbl, p) in enumerate(available, start=1):
        if os.path.normcase(p) == os.path.normcase(env["repo2"]):
            repo2_idx = idx
            break
    assert repo2_idx is not None

    outputs = []
    # Confirm removal with 'y'
    success, msg = handle_repo_remove(
        target_arg=str(repo2_idx),
        current_path=env["repo1"],  # active is repo1
        db_path=env["db_path"],
        confirm_fn=lambda prompt: "y",
        output_fn=outputs.append,
    )

    assert success is True
    assert "Successfully unregistered" in msg

    # Verify repo2 is no longer in get_available_repos
    new_available = get_available_repos(env["repo1"], db_path=env["db_path"])
    new_paths = [os.path.normcase(p) for _, p in new_available]
    assert os.path.normcase(env["repo2"]) not in new_paths


def test_repo_remove_duplicate_names_require_disambiguation(isolated_db_and_repos):
    """Verify that duplicate repository names require disambiguation by number."""
    env = isolated_db_and_repos
    # Register duplicate alpha_repo from different folder
    conn = sqlite3.connect(env["db_path"])
    conn.row_factory = sqlite3.Row
    save_repo_metadata(conn, get_repo_id(env["repo3_dup"]), env["repo3_dup"], "tfidf", [], [])
    conn.close()

    outputs = []
    success, msg = handle_repo_remove(
        target_arg="alpha_repo",
        current_path=env["repo2"],
        db_path=env["db_path"],
        output_fn=outputs.append,
    )

    assert success is False
    assert "Multiple repositories named" in msg
    out_text = " ".join(outputs)
    assert "Please disambiguate by number" in out_text


def test_repo_remove_shows_details_and_handles_cancellation(isolated_db_and_repos):
    """Verify exact name and full path are shown before confirmation, and user can cancel."""
    env = isolated_db_and_repos
    outputs = []

    # Test user cancelling with 'n'
    success, msg = handle_repo_remove(
        target_arg="beta_repo",
        current_path=env["repo1"],
        db_path=env["db_path"],
        confirm_fn=lambda prompt: "n",
        output_fn=outputs.append,
    )

    assert success is False
    assert "cancelled" in msg
    out_text = "\n".join(outputs)
    assert "beta_repo" in out_text
    assert env["repo2"] in out_text

    # Verify repo2 is STILL registered
    available = get_available_repos(env["repo1"], db_path=env["db_path"])
    paths = [os.path.normcase(p) for _, p in available]
    assert os.path.normcase(env["repo2"]) in paths


def test_repo_remove_omitted_after_cli_restart(isolated_db_and_repos):
    """Verify repository registration is removed persistently and remains omitted after restart."""
    env = isolated_db_and_repos
    success, msg = handle_repo_remove(
        target_arg="beta_repo",
        current_path=env["repo1"],
        db_path=env["db_path"],
        confirm_fn=lambda prompt: "yes",
    )
    assert success is True

    # Check database: row in repos table should be gone
    conn = sqlite3.connect(env["db_path"])
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM repos WHERE repo_id = ?", (get_repo_id(env["repo2"]),)).fetchone()
    assert row is None
    conn.close()

    # Fresh session / fresh connection (simulating CLI restart)
    reloaded_available = get_available_repos(env["repo1"], db_path=env["db_path"])
    reloaded_paths = [os.path.normcase(p) for _, p in reloaded_available]
    assert os.path.normcase(env["repo2"]) not in reloaded_paths


def test_repo_remove_files_git_cache_remain_untouched(isolated_db_and_repos):
    """Verify that removing a repo NEVER deletes source files, Git history, or index/cache files."""
    env = isolated_db_and_repos
    success, _ = handle_repo_remove(
        target_arg="beta_repo",
        current_path=env["repo1"],
        db_path=env["db_path"],
        confirm_fn=lambda prompt: "y",
    )
    assert success is True

    # 1. Source files must exist and be identical
    assert os.path.exists(env["sample_file"])
    with open(env["sample_file"], "r", encoding="utf-8") as f:
        assert f.read() == "def hello(): return 'world'\n"

    # 2. Git folder and files must exist
    assert os.path.exists(os.path.join(env["git_dir"], "config"))

    # 3. Cache files must exist
    assert os.path.exists(env["cache_file"])


def test_readding_removed_repository_works(isolated_db_and_repos):
    """Verify that re-adding a previously removed repository makes it available again."""
    env = isolated_db_and_repos
    # Remove repo2
    handle_repo_remove(
        target_arg="beta_repo",
        current_path=env["repo1"],
        db_path=env["db_path"],
        confirm_fn=lambda prompt: "y",
    )
    assert os.path.normcase(env["repo2"]) not in [os.path.normcase(p) for _, p in get_available_repos(env["repo1"], db_path=env["db_path"])]

    # Re-add repo2 (e.g. user calls clear_unregistered_repo and saves metadata)
    clear_unregistered_repo(env["repo2"], db_path=env["db_path"])
    conn = sqlite3.connect(env["db_path"])
    conn.row_factory = sqlite3.Row
    save_repo_metadata(conn, get_repo_id(env["repo2"]), env["repo2"], "tfidf", [], [])
    conn.close()

    # Now it must be available again
    restored = get_available_repos(env["repo1"], db_path=env["db_path"])
    restored_paths = [os.path.normcase(p) for _, p in restored]
    assert os.path.normcase(env["repo2"]) in restored_paths
