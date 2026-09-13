"""
Unit Tests for Git Hook Generator & Management (core/git_hooks.py - Week 3 Day 5)
"""
import os
import tempfile
import subprocess
import pytest
from unittest.mock import patch
from core.git_hooks import (
    find_git_dir,
    install_git_hooks,
    uninstall_git_hooks,
    check_git_hooks_status,
    HOOK_MARKER,
)
from cli import main as cli_main


def test_git_hook_lifecycle(tmp_path):
    """Tests full lifecycle: find git dir, install hooks, check status, and uninstall hooks."""
    repo_dir = os.path.join(tmp_path, "dummy_repo")
    os.makedirs(repo_dir, exist_ok=True)

    # Initialize a git repo inside dummy_repo
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, text=True, check=True)

    git_dir = find_git_dir(repo_dir)
    assert git_dir is not None
    assert os.path.basename(git_dir) == ".git"

    # Initial status check before install
    st1 = check_git_hooks_status(repo_dir)
    assert st1["post-commit"] is False
    assert st1["post-merge"] is False

    # Install hooks
    ok_inst, msg_inst = install_git_hooks(repo_dir)
    assert ok_inst is True
    assert "Successfully installed" in msg_inst

    # Status check after install
    st2 = check_git_hooks_status(repo_dir)
    assert st2["post-commit"] is True
    assert st2["post-merge"] is True

    # Verify file contents
    post_commit = os.path.join(git_dir, "hooks", "post-commit")
    assert os.path.exists(post_commit)
    with open(post_commit, "r", encoding="utf-8") as f:
        content = f.read()
    assert HOOK_MARKER in content

    # Uninstall hooks
    ok_uninst, msg_uninst = uninstall_git_hooks(repo_dir)
    assert ok_uninst is True

    # Status check after uninstall
    st3 = check_git_hooks_status(repo_dir)
    assert st3["post-commit"] is False
    assert st3["post-merge"] is False


def test_cli_git_hooks_flags(tmp_path, capsys):
    """Tests CLI flags: --setup-hooks, --check-hooks, and --remove-hooks."""
    repo_dir = os.path.join(tmp_path, "cli_repo")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, text=True, check=True)

    # 1. Test --setup-hooks
    with patch("sys.argv", ["cli.py", str(repo_dir), "--setup-hooks"]):
        res = cli_main()
        assert res == 0

    captured = capsys.readouterr()
    assert "Successfully installed" in captured.out

    # 2. Test --check-hooks
    with patch("sys.argv", ["cli.py", str(repo_dir), "--check-hooks"]):
        res = cli_main()
        assert res == 0

    captured = capsys.readouterr()
    assert "post-commit: Installed" in captured.out

    # 3. Test --remove-hooks
    with patch("sys.argv", ["cli.py", str(repo_dir), "--remove-hooks"]):
        res = cli_main()
        assert res == 0

    captured = capsys.readouterr()
    assert "Uninstalled IntelliCodeX Git hooks" in captured.out
