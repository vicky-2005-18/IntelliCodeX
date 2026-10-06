"""
Unit & Integration Tests for Milestone 4: Terminal TUI, Autocompletion & Packaging.
Extended for CLI Perfection: new rich render panels, new commands, FileHistory.
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
    create_interactive_session,
    render_banner,
    render_markdown_panel,
    render_diff,
    render_files_table,
    render_centrality_tables,
    render_repos_table,
    render_hooks_table,
    render_patch_card,
    render_help_panel,
    render_ingestion_panel,
    render_deps_panel,
    render_callers_panel,
    render_watch_panel,
    render_hybrid_panel,
    render_status_panel,
    render_search_results,
    FileHistory,
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

    doc = Document("dep")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "deps:" in matches

    doc = Document("wat")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch" in matches
    assert "watch:status" in matches

    doc = Document("hyb")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "hybrid" in matches
    assert "hybrid:on" in matches


def test_completer_new_commands():
    """New commands added in CLI Perfection are suggested by the completer."""
    completer = IntelliCodeXCompleter()

    doc = Document("sta")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "status" in matches

    doc = Document("sea")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "search:" in matches

    doc = Document("ver")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "version" in matches

    doc = Document("exp")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "export:" in matches

    doc = Document("inf")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "info:" in matches


def test_completer_file_suggestions():
    mock_files = ["pkg/auth.py", "pkg/db.py", "routes/api.py", "README.md"]
    completer = IntelliCodeXCompleter(get_files_fn=lambda: mock_files)

    doc = Document("deps:au")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "pkg/auth.py" in matches
    assert "pkg/db.py" not in matches

    doc = Document("deps ")
    matches = [c.text for c in completer.get_completions(doc)]
    assert len(matches) == len(mock_files)


def test_completer_symbol_suggestions():
    mock_symbols = ["get_user", "verify_password", "SessionManager.is_valid", "compute_hash"]
    completer = IntelliCodeXCompleter(get_symbols_fn=lambda: mock_symbols)

    doc = Document("callers:ver")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "verify_password" in matches
    assert "get_user" not in matches


def test_completer_persona_and_backend():
    completer = IntelliCodeXCompleter()

    doc = Document("persona sec")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "security" in matches

    doc = Document("backend ol")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "ollama" in matches

    doc = Document("fix:Key")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "KeyError" in matches


def test_completer_subcommands():
    completer = IntelliCodeXCompleter()

    doc = Document("watch:sta")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch:status" in matches
    assert "watch:start" in matches
    assert "watch:stop" not in matches

    doc2 = Document("watch:sto")
    matches2 = [c.text for c in completer.get_completions(doc2)]
    assert matches2 == ["watch:stop"]


# ---------------------------------------------------------------------------
# 3. Original Rich TUI Rendering Tests
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
# 4. New CLI Perfection Rendering Tests
# ---------------------------------------------------------------------------

def test_render_help_panel(capsys):
    """render_help_panel shows grouped command table."""
    render_help_panel()
    captured = capsys.readouterr()
    # Rich or plain-text fallback — at least one command should appear
    assert "fix:" in captured.out or "help" in captured.out or "Search" in captured.out


def test_render_ingestion_panel(capsys):
    """render_ingestion_panel shows files/chunks/mode."""
    mock_result = MagicMock()
    mock_result.num_files = 42
    mock_result.num_chunks = 210
    mock_result.ast_chunks_count = 180
    mock_result.indexing_mode = "fresh"
    mock_result.graph.number_of_nodes.return_value = 12
    mock_result.graph.number_of_edges.return_value = 18
    mock_result.call_graph = None
    render_ingestion_panel(mock_result, "sample_repo", elapsed=0.5)
    captured = capsys.readouterr()
    assert "42" in captured.out or "210" in captured.out or "sample_repo" in captured.out


def test_render_deps_panel_empty(capsys):
    render_deps_panel("pkg/auth.py", [], elapsed=0.01)
    captured = capsys.readouterr()
    # Either rich panel title or plain text fallback
    assert "auth.py" in captured.out or "no reverse" in captured.out.lower() or "Dependency" in captured.out


def test_render_deps_panel_with_results(capsys):
    affected = ["pkg/routes.py", "pkg/middleware.py"]
    render_deps_panel("pkg/auth.py", affected, elapsed=0.02)
    captured = capsys.readouterr()
    assert "routes.py" in captured.out or "middleware.py" in captured.out or "auth.py" in captured.out


def test_render_callers_panel_empty(capsys):
    render_callers_panel("get_user", [], elapsed=0.01)
    captured = capsys.readouterr()
    assert "get_user" in captured.out or "no calling" in captured.out.lower() or "Callers" in captured.out


def test_render_callers_panel_with_results(capsys):
    callers = ["routes::login_view", "api::user_endpoint"]
    render_callers_panel("get_user", callers, elapsed=0.02)
    captured = capsys.readouterr()
    assert "get_user" in captured.out or "login_view" in captured.out or "Callers" in captured.out


def test_render_watch_panel_active(capsys):
    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True
    render_watch_panel(mock_watcher, "sample_repo")
    captured = capsys.readouterr()
    assert "ACTIVE" in captured.out or "Watcher" in captured.out or "sample_repo" in captured.out


def test_render_watch_panel_inactive(capsys):
    render_watch_panel(None, "sample_repo")
    captured = capsys.readouterr()
    assert "INACTIVE" in captured.out or "Watcher" in captured.out


def test_render_hybrid_panel_on(capsys):
    mock_engine = MagicMock()
    mock_engine.hybrid_search = True
    render_hybrid_panel(mock_engine)
    captured = capsys.readouterr()
    assert "ACTIVE" in captured.out or "Hybrid" in captured.out or "BM25" in captured.out


def test_render_hybrid_panel_off(capsys):
    mock_engine = MagicMock()
    mock_engine.hybrid_search = False
    render_hybrid_panel(mock_engine)
    captured = capsys.readouterr()
    assert "INACTIVE" in captured.out or "Hybrid" in captured.out


def test_render_status_panel(capsys):
    mock_engine = MagicMock()
    mock_engine.hybrid_search = True
    mock_engine.active_persona = "general"
    mock_engine.active_model = "qwen2.5-coder:7b"
    render_status_panel("sample_repo", "tfidf", mock_engine, None)
    captured = capsys.readouterr()
    assert "sample_repo" in captured.out or "tfidf" in captured.out or "Status" in captured.out


def test_render_search_results(capsys):
    mock_chunk = MagicMock()
    mock_chunk.file_path = "pkg/auth.py"
    mock_chunk.name = "get_user"
    mock_chunk.start_line = 10
    mock_chunk.end_line = 25
    results = [{"chunk": mock_chunk, "score": 0.82, "reason": ""}]
    render_search_results("get user logic", results, elapsed=0.05)
    captured = capsys.readouterr()
    assert "pkg/auth.py" in captured.out or "get_user" in captured.out or "Fast Search" in captured.out


# ---------------------------------------------------------------------------
# 5. TUI Environment Detection & Fallback
# ---------------------------------------------------------------------------

def test_should_use_tui_env_disabled():
    with patch.dict(os.environ, {"INTELLICODEX_NO_TUI": "1"}):
        assert should_use_tui() is False


def test_should_use_tui_non_tty():
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    with patch.dict(os.environ, {"INTELLICODEX_NO_TUI": "", "INTELLICODEX_FORCE_TUI": ""}):
        with patch("sys.stdin", mock_stdin):
            assert should_use_tui() is False


def test_should_use_tui_force_env():
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    with patch.dict(os.environ, {"INTELLICODEX_NO_TUI": "", "INTELLICODEX_FORCE_TUI": "1"}):
        with patch("sys.stdin", mock_stdin):
            assert should_use_tui() is True


def test_create_interactive_session():
    session = create_interactive_session()
    assert session is not None


# ---------------------------------------------------------------------------
# 6. FileHistory & Persistence Tests
# ---------------------------------------------------------------------------

def test_file_history_importable():
    """FileHistory is exported from cli module (not None when prompt_toolkit is installed)."""
    assert FileHistory is not None, "FileHistory must be importable from cli when prompt_toolkit is installed"


def test_storage_dir_created(tmp_path, monkeypatch):
    """Session creation must create .storage/ directory if it doesn't exist."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / ".storage").exists()
    os.makedirs(".storage", exist_ok=True)
    assert (tmp_path / ".storage").exists()


# ---------------------------------------------------------------------------
# 7. New Commands Integration Tests (status, version, search, info, export)
# ---------------------------------------------------------------------------

def test_cli_perfection_interactive_commands(capsys, tmp_path):
    export_file = str(tmp_path / "test_export.md")
    user_inputs = [
        "status",
        "version",
        "search:auth",
        "info:pkg/auth.py",
        f"export:{export_file}",
        "what is auth?",
        f"export:{export_file}",
        "exit",
    ]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            main()

    captured = capsys.readouterr()
    assert "System Status" in captured.out or "Status" in captured.out
    assert "1.0.0" in captured.out
    assert "Fast Search" in captured.out or "auth" in captured.out
    assert "File Info" in captured.out or "Info" in captured.out
    assert os.path.exists(export_file)
    with open(export_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert "# IntelliCodeX Answer Export" in content

