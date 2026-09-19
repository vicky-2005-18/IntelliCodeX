"""
Unit & Integration Tests for Milestone 4: Terminal TUI, Autocompletion & Packaging.
"""
import os
import sys
import tomllib
from unittest.mock import patch, MagicMock
import pytest

from prompt_toolkit.document import Document
from cli import (
    VERSION,
    should_use_tui,
    render_banner,
    render_markdown_panel,
    render_diff,
    render_files_table,
    render_centrality_tables,
    render_repos_table,
    render_hooks_table,
    render_patch_card,
    IntelliCodeXCompleter,
    main,
)


# ---------------------------------------------------------------------------
# 1. Packaging & pyproject.toml Configuration Tests
# ---------------------------------------------------------------------------

def test_pyproject_toml_exists_and_valid():
    pyproject_path = os.path.abspath("pyproject.toml")
    assert os.path.isfile(pyproject_path), "pyproject.toml must exist in repo root"

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    # Check project metadata
    assert "project" in data
    assert data["project"]["name"] == "intellicodex"
    assert data["project"]["version"] == "1.0.0"
    assert "dependencies" in data["project"]

    deps = data["project"]["dependencies"]
    dep_str = " ".join(deps)
    assert "prompt_toolkit" in dep_str
    assert "rich" in dep_str
    assert "watchdog" in dep_str
    assert "faiss-cpu" in dep_str

    # Check entry point script
    assert "scripts" in data["project"]
    assert data["project"]["scripts"].get("intellicodex") == "cli:main"


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        with patch("sys.argv", ["cli.py", "--version"]):
            main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert f"IntelliCodeX CLI v{VERSION}" in captured.out or f"IntelliCodeX CLI v{VERSION}" in captured.err


# ---------------------------------------------------------------------------
# 2. Autocompleter Unit Tests
# ---------------------------------------------------------------------------

def test_completer_command_suggestions():
    completer = IntelliCodeXCompleter()

    # Suggest "deps:" when typing "dep"
    doc = Document("dep")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "deps:" in matches

    # Suggest "watch:*" when typing "wat"
    doc = Document("wat")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch" in matches
    assert "watch:status" in matches

    # Suggest "hybrid:*" when typing "hyb"
    doc = Document("hyb")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "hybrid" in matches
    assert "hybrid:on" in matches


def test_completer_file_suggestions():
    mock_files = ["pkg/auth.py", "pkg/db.py", "routes/api.py", "README.md"]
    completer = IntelliCodeXCompleter(get_files_fn=lambda: mock_files)

    # Typing "deps:au" should suggest "pkg/auth.py"
    doc = Document("deps:au")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "pkg/auth.py" in matches
    assert "pkg/db.py" not in matches

    # Typing "deps " should suggest all files
    doc = Document("deps ")
    matches = [c.text for c in completer.get_completions(doc)]
    assert len(matches) == len(mock_files)


def test_completer_symbol_suggestions():
    mock_symbols = ["get_user", "verify_password", "SessionManager.is_valid", "compute_hash"]
    completer = IntelliCodeXCompleter(get_symbols_fn=lambda: mock_symbols)

    # Typing "callers:ver" should suggest "verify_password"
    doc = Document("callers:ver")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "verify_password" in matches
    assert "get_user" not in matches


def test_completer_persona_and_backend():
    completer = IntelliCodeXCompleter()

    # Persona completions
    doc = Document("persona sec")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "security" in matches

    # Backend completions
    doc = Document("backend ol")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "ollama" in matches

    # Error completions on fix:
    doc = Document("fix:Key")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "KeyError" in matches


def test_completer_subcommands():
    completer = IntelliCodeXCompleter()

    # "watch:sta" matches "watch:status" and "watch:start", but NOT "watch:stop"
    doc = Document("watch:sta")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch:status" in matches
    assert "watch:start" in matches
    assert "watch:stop" not in matches

    # "watch:sto" matches only "watch:stop"
    doc2 = Document("watch:sto")
    matches2 = [c.text for c in completer.get_completions(doc2)]
    assert matches2 == ["watch:stop"]


# ---------------------------------------------------------------------------
# 3. Rich TUI Rendering Tests
# ---------------------------------------------------------------------------

def test_render_banner(capsys):
    render_banner()
    captured = capsys.readouterr()
    assert "INTELLICODEX INTERACTIVE CLI ASSISTANT" in captured.out


def test_render_markdown_panel(capsys):
    render_markdown_panel("# Header 1\nThis is a *markdown* test.", title="Custom Title")
    captured = capsys.readouterr()
    assert "Custom Title" in captured.out
    assert "Header 1" in captured.out or "This is a" in captured.out


def test_render_diff(capsys):
    sample_diff = (
        "--- a/auth.py\n"
        "+++ b/auth.py\n"
        "@@ -1,3 +1,4 @@\n"
        "-def old():\n"
        "+def new():\n"
    )
    render_diff(sample_diff)
    captured = capsys.readouterr()
    assert "Unified Git Diff" in captured.out
    assert "def new" in captured.out or "old" in captured.out


def test_render_files_table(capsys):
    render_files_table(["auth.py", "db.py", "config.json"])
    captured = capsys.readouterr()
    assert "Indexed Source Files" in captured.out
    assert "auth.py" in captured.out
    assert "db.py" in captured.out


def test_render_centrality_tables(capsys):
    top_files = [("pkg/auth.py", 0.452), ("pkg/db.py", 0.312)]
    top_syms = [("get_user", 0.512), ("hash_password", 0.288)]
    render_centrality_tables(top_files, top_syms)
    captured = capsys.readouterr()
    assert "Top Central Files" in captured.out
    assert "pkg/auth.py" in captured.out
    assert "Top Central Symbols" in captured.out
    assert "get_user" in captured.out


def test_render_repos_table(capsys):
    available = [("sample_repo", "C:/repos/sample_repo"), ("flask_app", "C:/repos/flask_app")]
    render_repos_table(available, active_path="C:/repos/sample_repo")
    captured = capsys.readouterr()
    assert "Available Repositories" in captured.out
    assert "sample_repo" in captured.out
    assert "flask_app" in captured.out


def test_render_hooks_table(capsys):
    hooks_st = {"post-commit": True, "post-merge": False}
    render_hooks_table(hooks_st, target_path="sample_repo")
    captured = capsys.readouterr()
    assert "Git Hook Status" in captured.out
    assert "post-commit" in captured.out


def test_render_patch_card(capsys):
    patch_rec = {
        "target_file": "pkg/auth.py",
        "error_type": "KeyError",
        "confidence_score": 0.92,
        "status": "success",
        "explanation": "Added key existence guard before lookup.",
        "git_diff": "--- a/auth.py\n+++ b/auth.py\n+guard check\n",
        "sandbox_validation": {
            "test_status": "passed",
            "iterations_count": 1,
        }
    }
    render_patch_card(patch_rec, fix_time=1.23)
    captured = capsys.readouterr()
    assert "INTELLICODEX AUTOMATED CODE PATCH" in captured.out
    assert "pkg/auth.py" in captured.out
    assert "KeyError" in captured.out
    assert "PASSED" in captured.out


# ---------------------------------------------------------------------------
# 4. TUI Environment Detection & Fallback
# ---------------------------------------------------------------------------

def test_should_use_tui_env_disabled():
    with patch.dict(os.environ, {"INTELLICODEX_NO_TUI": "1"}):
        assert should_use_tui() is False


def test_should_use_tui_non_tty():
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    with patch.dict(os.environ, {"INTELLICODEX_NO_TUI": ""}):
        with patch("sys.stdin", mock_stdin):
            assert should_use_tui() is False
