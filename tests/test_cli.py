"""
Advanced Level Unit & Integration Tests for IntelliCodeX CLI (cli.py)
"""
import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from cli import (
    check_ollama_available,
    resolve_repo_path,
    create_components,
    print_banner,
    print_help,
    main,
)
from core.embedder import TfidfEmbedder, OllamaEmbedder
from core.llm_client import OllamaLLM


# ---------------------------------------------------------------------------
# 1. Helper Function Tests
# ---------------------------------------------------------------------------

def test_check_ollama_available_online():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    with patch("requests.get", return_value=mock_resp):
        assert check_ollama_available() is True


def test_check_ollama_available_offline():
    with patch("requests.get", side_effect=Exception("Connection refused")):
        assert check_ollama_available() is False


def test_resolve_repo_path_local_exist():
    with tempfile.TemporaryDirectory() as tmpdir:
        resolved = resolve_repo_path(tmpdir)
        assert os.path.isabs(resolved)
        assert os.path.exists(resolved)


def test_resolve_repo_path_local_not_found():
    with pytest.raises(FileNotFoundError):
        resolve_repo_path("non_existent_folder_xyz_12345")


def test_resolve_repo_path_git_clone_new():
    with patch("os.path.exists", side_effect=lambda p: False if ".repos" in p else os.path.exists(p)):
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0, stderr="")
            res = resolve_repo_path("https://github.com/vicky-2005-18/TB.git")
            assert "TB" in res
            mock_sub.assert_called_once()
            args = mock_sub.call_args[0][0]
            assert args[0] == "git"
            assert args[1] == "clone"


def test_resolve_repo_path_git_pull_existing():
    repo_dir = os.path.abspath(os.path.join(".repos", "TB_test_mock"))
    git_dir = os.path.join(repo_dir, ".git")
    os.makedirs(git_dir, exist_ok=True)
    try:
        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0)
            res = resolve_repo_path("https://github.com/vicky-2005-18/TB_test_mock")
            assert res == repo_dir
    finally:
        import shutil
        if os.path.exists(repo_dir):
            shutil.rmtree(repo_dir, ignore_errors=True)



def test_create_components_tfidf():
    embedder, llm, backend = create_components("tfidf")
    assert isinstance(embedder, TfidfEmbedder)
    assert llm is None
    assert backend == "tfidf"


def test_create_components_ollama_online():
    with patch("cli.check_ollama_available", return_value=True):
        embedder, llm, backend = create_components("ollama")
        assert isinstance(embedder, OllamaEmbedder)
        assert isinstance(llm, OllamaLLM)
        assert backend == "ollama"


def test_create_components_ollama_fallback():
    with patch("cli.check_ollama_available", return_value=False):
        embedder, llm, backend = create_components("ollama")
        assert isinstance(embedder, TfidfEmbedder)
        assert llm is None
        assert backend == "tfidf"


def test_print_banner_and_help(capsys):
    print_banner()
    captured = capsys.readouterr()
    assert "INTELLICODEX INTERACTIVE CLI ASSISTANT" in captured.out

    print_help()
    captured = capsys.readouterr()
    assert "Available Commands:" in captured.out


# ---------------------------------------------------------------------------
# 2. Main Interactive Loop & Command Tests
# ---------------------------------------------------------------------------

def test_cli_main_help_and_exit(capsys):
    user_inputs = ["help", "?", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "Available Commands:" in captured.out or "fix:" in captured.out or "Command" in captured.out
    assert "Goodbye!" in captured.out


def test_cli_main_files_ls(capsys):
    user_inputs = ["files", "ls", "quit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "Indexed Source Files" in captured.out
    assert "auth.py" in captured.out or "db.py" in captured.out


def test_cli_main_deps_command(capsys):
    user_inputs = ["deps:db.py", "callers:get_user", "top", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert ("Dependency Analysis for 'db.py'" in captured.out or 
            ("Dependency" in captured.out and "db.py" in captured.out))
    assert ("Symbol Callers for 'get_user'" in captured.out or 
            ("Callers" in captured.out and "get_user" in captured.out))
    assert "Top Central Files" in captured.out


def test_cli_main_backend_switch(capsys):
    user_inputs = ["backend --tfidf", "backend invalid_engine", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "Re-indexing repository with 'tfidf' backend" in captured.out
    assert "Invalid backend" in captured.out


def test_cli_main_repo_switch(capsys):
    user_inputs = ["repo sample_repo", "repo /non_existent_path_xyz", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "Successfully switched active repository" in captured.out
    assert "Error switching repository" in captured.out


def test_cli_main_prompt_stripping_and_query(capsys):
    user_inputs = [">> how does authentication work?", "$ clear", "cls", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            with patch("os.system") as mock_sys:
                main()
                assert mock_sys.called

    captured = capsys.readouterr()
    assert "Retrieved" in captured.out
    assert "Answer" in captured.out


def test_cli_main_keyboard_interrupt(capsys):
    with patch("builtins.input", side_effect=KeyboardInterrupt):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "Exiting IntelliCodeX CLI. Goodbye!" in captured.out


def test_cli_main_watch_commands(capsys):
    user_inputs = ["watch", "watch:status", "watch:stop", "watch:start", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "Real-Time Filesystem Watcher" in captured.out
    assert "stopped" in captured.out.lower()
    assert "started" in captured.out.lower()


def test_cli_remote_server_batch(capsys):
    """Test non-interactive batch query forwarded to remote server over REST API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"answer": "Remote answered successfully.", "confidence_score": 0.95}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        with patch("sys.argv", ["cli.py", "my_remote_repo", "--server", "http://127.0.0.1:8000", "--token", "test-token", "-q", "how does auth work?"]):
            ret = main()
            assert ret == 0
            mock_post.assert_called_once()
            url = mock_post.call_args[0][0]
            assert "http://127.0.0.1:8000/api/chat/ask" in url
            assert mock_post.call_args[1]["headers"]["Authorization"] == "Bearer test-token"
            assert mock_post.call_args[1]["json"]["repo_id"] == "my_remote_repo"

    captured = capsys.readouterr()
    assert "Connected to Remote Server" in captured.out
    assert "Remote answered successfully." in captured.out


def test_cli_remote_server_interactive(capsys):
    """Test interactive remote session commands."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"answer": "Interactive remote answer.", "confidence_score": 0.88}

    with patch("requests.post", return_value=mock_resp):
        with patch("builtins.input", side_effect=["where is login?", "exit"]):
            with patch("sys.argv", ["cli.py", "my_remote_repo", "--server", "http://127.0.0.1:8000"]):
                ret = main()
                assert ret == 0

    captured = capsys.readouterr()
    assert "Remote IntelliCodeX session ready" in captured.out
    assert "Interactive remote answer." in captured.out
    assert "Exiting Remote Session." in captured.out


def test_resolve_repo_path_shallow_clone_default():
    """Verify resolve_repo_path uses --depth 1 by default when cloning."""
    from cli import resolve_repo_path
    import subprocess
    from unittest.mock import patch, MagicMock

    with patch("subprocess.run") as mock_run, patch("os.path.exists", return_value=False):
        mock_run.return_value = MagicMock(returncode=0)
        resolve_repo_path("https://github.com/example/repo.git")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        env = mock_run.call_args[1].get("env", {})
        assert "git" in cmd
        assert "clone" in cmd
        assert "--depth" in cmd
        depth_idx = cmd.index("--depth")
        assert cmd[depth_idx + 1] == "1"
        assert "--" in cmd
        dash_idx = cmd.index("--")
        assert cmd[dash_idx + 1] == "https://github.com/example/repo.git"
        assert env.get("GIT_ALLOW_PROTOCOL") == "https"
        assert env.get("GIT_TERMINAL_PROMPT") == "0"


def test_resolve_repo_path_full_history_flag():
    """Verify resolve_repo_path omits --depth when full_history=True."""
    from cli import resolve_repo_path
    import subprocess
    from unittest.mock import patch, MagicMock

    with patch("subprocess.run") as mock_run, patch("os.path.exists", return_value=False):
        mock_run.return_value = MagicMock(returncode=0)
        resolve_repo_path("https://github.com/example/repo.git", full_history=True)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "clone" in cmd
        assert "--depth" not in cmd
        assert "--" in cmd


def test_validate_git_url_cli():
    """Verify CLI validate_git_url enforces https only, rejects leading '-', rejects whitespace, and rejects embedded credentials."""
    from cli import validate_git_url

    # Valid HTTPS URL accepted
    valid_url = "https://github.com/example/repo.git"
    assert validate_git_url(valid_url) == valid_url

    # Reject empty URL
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_git_url("")

    # Reject leading '-'
    with pytest.raises(ValueError, match="cannot start with '-'"):
        validate_git_url("--upload-pack=touch /tmp/x")

    with pytest.raises(ValueError, match="cannot start with '-'"):
        validate_git_url("-malicious-flag")

    # Reject whitespace
    with pytest.raises(ValueError, match="cannot contain whitespace"):
        validate_git_url("https://github.com/example /repo.git")

    with pytest.raises(ValueError, match="cannot contain whitespace"):
        validate_git_url("https://github.com/example/repo.git\n")

    # Reject embedded credentials
    with pytest.raises(ValueError, match="embedded credentials"):
        validate_git_url("https://user:password@github.com/example/repo.git")

    with pytest.raises(ValueError, match="embedded credentials"):
        validate_git_url("https://token@github.com/example/repo.git")

    # Reject non-https protocols
    with pytest.raises(ValueError, match="https:// protocol only"):
        validate_git_url("http://github.com/example/repo.git")

    with pytest.raises(ValueError, match="https:// protocol only"):
        validate_git_url("git@github.com:example/repo.git")

    with pytest.raises(ValueError, match="https:// protocol only"):
        validate_git_url("ssh://user@server/repo.git")

    with pytest.raises(ValueError, match="https:// protocol only"):
        validate_git_url("file:///etc/passwd")



