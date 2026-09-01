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
    assert "Available Commands:" in captured.out
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
    assert "Dependency Analysis for 'db.py'" in captured.out
    assert "Symbol Callers for 'get_user'" in captured.out
    assert "Top Central Files" in captured.out


def test_cli_main_backend_switch(capsys):
    user_inputs = ["backend tfidf", "backend invalid_engine", "exit"]
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
