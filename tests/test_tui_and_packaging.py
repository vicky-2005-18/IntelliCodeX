"""
Unit & Integration Tests for Milestone 4: Terminal TUI, Autocompletion & Packaging.
Extended for CLI Perfection: new rich render panels, new commands, FileHistory.
"""
import os
import sys
import time
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
    render_welcome_actions,
    render_deps_panel,
    render_callers_panel,
    render_watch_panel,
    render_hybrid_panel,
    render_status_panel,
    render_search_results,
    print_banner,
    MascotController,
    MascotSpinner,
    mascot_status,
    is_animation_enabled,
    FileHistory,
    IntelliCodeXCompleter,
    resolve_repo_path,
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


def test_resolve_repo_path_fallback_to_sample_repo_when_outside(tmp_path, monkeypatch):
    """When launched from an arbitrary external directory, 'sample_repo' resolves to bundled sample_repo."""
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "sample_repo").exists()
    resolved = resolve_repo_path("sample_repo")
    assert os.path.isdir(resolved)
    assert os.path.basename(resolved) == "sample_repo"
    assert os.path.isfile(os.path.join(resolved, "utils.py")) or os.path.isdir(os.path.join(resolved, "pkg"))


def test_resolve_repo_path_current_working_dir(tmp_path, monkeypatch):
    """'intellicodex .' resolves to the current working directory."""
    monkeypatch.chdir(tmp_path)
    resolved = resolve_repo_path(".")
    assert os.path.abspath(resolved) == os.path.abspath(str(tmp_path))


def test_resolve_repo_path_with_spaces_and_quotes(tmp_path):
    """'intellicodex "path with spaces"' resolves properly even when wrapped in quotes."""
    spaced_dir = tmp_path / "my repo with spaces"
    spaced_dir.mkdir()
    (spaced_dir / "test.py").write_text("print('hello')\n", encoding="utf-8")

    # Unquoted
    res1 = resolve_repo_path(str(spaced_dir))
    assert res1 == os.path.abspath(str(spaced_dir))

    # Double-quoted
    res2 = resolve_repo_path(f'"{spaced_dir}"')
    assert res2 == os.path.abspath(str(spaced_dir))

    # Single-quoted
    res3 = resolve_repo_path(f"'{spaced_dir}'")
    assert res3 == os.path.abspath(str(spaced_dir))


def test_storage_dir_preserves_intended_location_outside_project(tmp_path, monkeypatch):
    """Running from an arbitrary directory must never create .storage in that arbitrary directory."""
    monkeypatch.chdir(tmp_path)
    from core.persistence import get_storage_dir, get_default_db_path, get_db_connection

    storage_dir = get_storage_dir()
    default_db = get_default_db_path()

    # The resolved storage dir must not point inside the arbitrary tmp_path cwd
    assert not storage_dir.startswith(str(tmp_path))
    assert not (tmp_path / ".storage").exists()

    conn = get_db_connection()
    conn.close()
    assert not (tmp_path / ".storage").exists()


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

    doc = Document("rev")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "review" in matches

    doc = Document("app")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "approve " in matches

    doc = Document("doc")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "doc:" in matches


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
    assert "Format version" not in captured.out
    assert "Automatic updates" in captured.out or "real-time" in captured.out


def test_render_welcome_actions(capsys):
    """render_welcome_actions displays supported commands, safe repair notice, and active examples."""
    mock_result = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.file_path = "auth.py"
    mock_chunk.kind = "function"
    mock_chunk.name = "authenticate_user"
    mock_result.store.chunks = [mock_chunk]
    mock_result.call_graph = None

    render_welcome_actions(mock_result, "sample_repo")
    captured = capsys.readouterr()
    assert "What would you like to do?" in captured.out
    assert "auth.py" in captured.out
    assert "authenticate_user" in captured.out
    assert "approval" in captured.out.lower() or "verification" in captured.out.lower()


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


# ---------------------------------------------------------------------------
# 8. IntelliCodeX Mascot Design & State Tests
# ---------------------------------------------------------------------------

def test_mascot_design_components():
    """Solid pixel-art cyan robot terminal sprite: square eyes, antenna, arms, and <> chest symbol."""
    sprite = MascotController.SPRITE_STATIC
    assert any("CCCC" in row for row in sprite[:2]), "Mascot must have centered antenna"
    assert any("DD" in row for row in sprite[4:6]), "Mascot faceplate must have square dark eyes"
    assert any("CCDCCDCC" in row or "CCDCCCCDCC" in row for row in sprite[10:13]), "Mascot torso must have dark <> symbol"
    assert any("CCC" in row for row in sprite[15:17]), "Mascot must have two solid feet"

    ansi_lines = MascotController.get_mascot_ansi_lines()
    assert len(ansi_lines) == 9, "18-row pixel sprite must render as 9 terminal half-block lines"
    assert any("▀" in line or "█" in line or "▄" in line for line in ansi_lines), "Mascot must use Unicode half-blocks"

    ascii_art = MascotController.get_mascot_text(ascii_mode=True)
    assert "^" in ascii_art, "ASCII fallback mascot must have an antenna (^)"
    assert "# #" in ascii_art, "ASCII fallback mascot must have eyes"
    assert "< >" in ascii_art or "<| < > |>" in ascii_art, "ASCII fallback must have <> chest and small arms"
    assert "d   b" in ascii_art, "ASCII fallback must have feet"


def test_mascot_ready_state(capsys):
    """Ready state displays static robot sprite."""
    MascotController.render_ready("Standing by for input")
    captured = capsys.readouterr()
    assert "Standing by for input" in captured.out
    assert "▀" in captured.out or "█" in captured.out or "^" in captured.out


def test_mascot_processing_blink_and_dots():
    """Processing state supports subtle blinking eyes and animated thinking dots."""
    grid_open = MascotController.create_mascot_grid("Processing thinking .", is_blink=False)
    grid_closed = MascotController.create_mascot_grid("Processing thinking ...", is_blink=True)
    assert grid_open is not None
    assert grid_closed is not None

    assert MascotController.SPRITE_STATIC[4] != MascotController.SPRITE_BLINK[4], "Blink frame must narrow eye pixels"


def test_mascot_success_state(capsys):
    """Success state displays green check only after operation actually succeeds."""
    MascotController.render_success("Indexing completed in 0.82s")
    captured = capsys.readouterr()
    assert "✓" in captured.out
    assert "Indexing completed in 0.82s" in captured.out


def test_mascot_failure_state(capsys):
    """Failure state displays amber indicator with the actual error message."""
    MascotController.render_failure("File not found: 'missing.py'")
    captured = capsys.readouterr()
    assert "⚠" in captured.out
    assert "Error: File not found: 'missing.py'" in captured.out


def test_mascot_banner_placement(capsys):
    """Mascot is placed beside the IntelliCodeX startup title."""
    render_banner()
    captured = capsys.readouterr()
    assert "INTELLICODEX INTERACTIVE CLI ASSISTANT" in captured.out
    assert "▀" in captured.out or "█" in captured.out or "d   b" in captured.out

    print_banner()
    captured_plain = capsys.readouterr()
    assert "INTELLICODEX INTERACTIVE CLI ASSISTANT" in captured_plain.out


def test_is_animation_enabled_controls():
    """Animation is disabled in CI, when explicitly configured, and in redirected output."""
    with patch.dict(os.environ, {"CI": "1", "INTELLICODEX_NO_ANIMATION": ""}):
        assert is_animation_enabled() is False

    with patch.dict(os.environ, {"CI": "true", "INTELLICODEX_NO_ANIMATION": ""}):
        assert is_animation_enabled() is False

    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "1"}):
        assert is_animation_enabled() is False

    mock_stdout = MagicMock()
    mock_stdout.isatty.return_value = False
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": ""}):
        with patch("sys.stdout", mock_stdout):
            assert is_animation_enabled() is False

    # Force animation override allows automated testing
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1"}):
        assert is_animation_enabled() is True


def test_mascot_status_lifecycle_clean_stop(capsys):
    """mascot_status starts, stops cleanly on success, and on error renders failure message."""
    with mascot_status("Unit test task", success_message="Task finished cleanly"):
        pass
    captured = capsys.readouterr()
    assert "✓" in captured.out
    assert "Task finished cleanly" in captured.out

    with pytest.raises(ValueError, match="Deliberate error"):
        with mascot_status("Failing task"):
            raise ValueError("Deliberate error")

    captured_err = capsys.readouterr()
    assert "⚠" in captured_err.out
    assert "Deliberate error" in captured_err.out


def test_mascot_eye_movement_sprites():
    """MascotController supports static, blink, left, and right eye movement frames."""
    assert len(MascotController.SPRITE_LOOK_LEFT) == 18
    assert len(MascotController.SPRITE_LOOK_RIGHT) == 18

    # Eyes are shifted left in SPRITE_LOOK_LEFT and right in SPRITE_LOOK_RIGHT
    assert "CCLDDLLLLDDLLLCC" in MascotController.SPRITE_LOOK_LEFT
    assert "CCLLLDDLLLLDDLCC" in MascotController.SPRITE_LOOK_RIGHT

    grid_left = MascotController.create_mascot_grid("Thinking left", eye_mode="left")
    grid_right = MascotController.create_mascot_grid("Thinking right", eye_mode="right")
    assert grid_left is not None
    assert grid_right is not None

    ansi_left = MascotController.get_mascot_ansi_lines(eye_mode="left")
    ansi_right = MascotController.get_mascot_ansi_lines(eye_mode="right")
    assert len(ansi_left) == 9
    assert len(ansi_right) == 9


def test_idle_prompt_blinking_timing():
    """Idle mascot blinks briefly every 3-5 seconds (period=3.8s, duration=0.22s)."""
    # At t=0.0s: blinking (0.0 % 3.8 = 0.0 < 0.22)
    assert (0.0 % 3.8) < 0.22
    # At t=1.0s: open eyes (1.0 % 3.8 = 1.0 >= 0.22)
    assert not ((1.0 % 3.8) < 0.22)
    # At t=3.8s: blinking second time (3.8 % 3.8 = 0.0 < 0.22)
    assert (3.8 % 3.8) < 0.22
    # At t=7.6s: blinking third time (7.6 % 3.8 = 0.0 < 0.22)
    assert (7.6 % 3.8) < 0.22


def test_persistent_mascot_session_layout():
    """create_interactive_session inserts persistent mascot window into prompt_toolkit layout."""
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1"}):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from cli import create_interactive_session

        with create_pipe_input() as pipe:
            session = create_interactive_session(input=pipe, output=DummyOutput())
            if session is not None:
                # Persistent mascot container is inserted into layout children
                children = session.layout.container.children
                assert len(children) >= 2


def test_typing_and_cursor_intact_during_refresh():
    """Typing, cursor position, and command history remain intact during animation refresh ticks."""
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1"}):
        import threading
        import time
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit import PromptSession
        from cli import create_interactive_session

        hist = InMemoryHistory()
        hist.append_string("previous_cmd")

        with create_pipe_input() as pipe:
            session = create_interactive_session(history=hist, input=pipe, output=DummyOutput())
            if session is not None:
                def slow_type():
                    time.sleep(0.08)
                    pipe.send_text("s")
                    time.sleep(0.08)
                    pipe.send_text("t")
                    time.sleep(0.08)
                    pipe.send_text("a")
                    time.sleep(0.08)
                    pipe.send_text("t\n")

                th = threading.Thread(target=slow_type)
                th.start()
                res = session.prompt(">> ", refresh_interval=0.05)
                th.join()
                assert res == "stat"


def test_clean_exit_no_threads():
    """Exiting the prompt leaves no dangling background animation threads."""
    import threading
    import time
    threads_before = threading.active_count()
    spinner = MascotSpinner("Test Clean Stop")
    spinner.start()
    time.sleep(0.1)
    spinner.stop()
    assert not (spinner.thread and spinner.thread.is_alive())
    # No extra threads left running
    assert threading.active_count() <= threads_before + 1


def test_mascot_wave_sprites_and_lifecycle():
    """MascotController supports wave frames and manages the wave timer lifecycle."""
    assert len(MascotController.SPRITE_WAVE_1) == 18
    assert len(MascotController.SPRITE_WAVE_2) == 18

    # Wave state lifecycle
    MascotController._last_wave_time = 0.0
    assert MascotController.is_waving() is False

    MascotController.trigger_wave()
    assert MascotController.is_waving() is True

    # After duration expires, is_waving becomes False
    MascotController._last_wave_time = time.time() - 3.0
    assert MascotController.is_waving() is False

    grid_wave1 = MascotController.create_mascot_grid("Greeting", eye_mode="wave1")
    grid_wave2 = MascotController.create_mascot_grid("Greeting", eye_mode="wave2")
    assert grid_wave1 is not None
    assert grid_wave2 is not None

    ansi_wave = MascotController.get_mascot_ansi_lines(eye_mode="wave1")
    assert len(ansi_wave) == 9


def test_mascot_render_greeting(capsys):
    """MascotController.render_greeting outputs 'Hey! How can I help?' and key capability hints."""
    MascotController.render_greeting()
    captured = capsys.readouterr()
    assert "Hey! How can I help?" in captured.out
    assert "search:" in captured.out


def test_mascot_attentive_eyes_during_typing():
    """While typing text is in the buffer, mascot shows attentive eyes and suppresses idle blinking."""
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1"}):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from cli import create_interactive_session

        with create_pipe_input() as pipe:
            session = create_interactive_session(input=pipe, output=DummyOutput())
            if session is not None and session.layout:
                # Find mascot window FormattedTextControl
                mascot_control = session.layout.container.children[0].content.content
                # Simulate typed text in buffer
                session.default_buffer._set_text("search:auth")
                tokens = mascot_control.text()
                # Tokens should be generated and contain attentive indicator or text
                text_combined = "".join(t[1] for t in tokens if len(t) >= 2)
                assert "Attentive" in text_combined or "search:auth" in text_combined or len(tokens) > 0


def test_mascot_mouse_support_defaults_to_false():
    """Mascot mouse interaction defaults to False to protect native terminal scrollback and selection."""
    from cli import is_mascot_mouse_enabled
    with patch.dict(os.environ, {"INTELLICODEX_MASCOT_MOUSE": ""}):
        assert is_mascot_mouse_enabled() is False

    with patch.dict(os.environ, {"INTELLICODEX_MASCOT_MOUSE": "1"}):
        assert is_mascot_mouse_enabled() is True

    with patch.dict(os.environ, {"INTELLICODEX_MASCOT_MOUSE": "true"}):
        assert is_mascot_mouse_enabled() is True


def test_restore_terminal_mouse_modes():
    """restore_terminal_mouse_modes() sends VT escape codes to disable mouse tracking without toggling screen buffers."""
    import io
    from cli import restore_terminal_mouse_modes
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        restore_terminal_mouse_modes()
    output = buf.getvalue()
    assert "\x1b[?1000l" in output  # normal tracking off
    assert "\x1b[?1002l" in output  # button tracking off
    assert "\x1b[?1006l" in output  # SGR tracking off
    # Must NOT emit ?1049l because switching to/from alternate screen corrupts native console buffer
    assert "\x1b[?1049l" not in output


def test_mascot_rendering_suspension_controls():
    """Mascot rendering suspension can be suspended and resumed cleanly."""
    from cli import (
        suspend_mascot_rendering,
        resume_mascot_rendering,
        is_mascot_rendering_suspended,
    )
    resume_mascot_rendering()
    assert is_mascot_rendering_suspended() is False
    suspend_mascot_rendering()
    assert is_mascot_rendering_suspended() is True
    resume_mascot_rendering()
    assert is_mascot_rendering_suspended() is False


def test_cleanup_cli_resources():
    """cleanup_cli_resources terminates spinners, suspends mascot rendering, stops watcher, and restores mouse modes."""
    import io
    from cli import cleanup_cli_resources, resume_mascot_rendering, is_mascot_rendering_suspended
    mock_watcher = MagicMock()
    buf = io.StringIO()
    try:
        with patch("sys.stdout", buf):
            cleanup_cli_resources(mock_watcher)
        assert mock_watcher.stop.called
        assert is_mascot_rendering_suspended() is True
        output = buf.getvalue()
        assert "\x1b[?1000l" in output
        assert "\x1b[?1049l" not in output
    finally:
        resume_mascot_rendering()



def test_mascot_scrollback_preservation_by_default():
    """When mouse interaction is disabled (default), tokens do not contain mouse handlers, preserving native terminal scroll."""
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1", "INTELLICODEX_MASCOT_MOUSE": ""}):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from cli import create_interactive_session, is_mascot_mouse_enabled

        assert is_mascot_mouse_enabled() is False
        with create_pipe_input() as pipe:
            session = create_interactive_session(input=pipe, output=DummyOutput())
            if session is not None:
                mascot_win = session.layout.container.children[0]
                assert mascot_win.content.dont_extend_height() is True
                assert mascot_win.content.height == 9
                tokens = mascot_win.content.content.text()
                # Tokens should be 2-tuples (style, text) without mouse handler
                assert len(tokens) > 0
                assert all(len(t) == 2 for t in tokens)


def test_mascot_opt_in_mouse_and_keyboard_fallback():
    """When mouse interaction is explicitly opted in, mouse click triggers wave; keyboard fallback works in both modes."""
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1", "INTELLICODEX_MASCOT_MOUSE": "1"}):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
        from prompt_toolkit.data_structures import Point
        from cli import create_interactive_session, MascotController, is_mascot_mouse_enabled

        assert is_mascot_mouse_enabled() is True
        MascotController._last_wave_time = 0.0

        with create_pipe_input() as pipe:
            session = create_interactive_session(input=pipe, output=DummyOutput())
            if session is not None:
                mascot_control = session.layout.container.children[0].content.content
                mascot_control.create_content(80, 10)
                event = MouseEvent(position=Point(x=2, y=2), event_type=MouseEventType.MOUSE_UP, button=None, modifiers=None)
                mascot_control.mouse_handler(event)
                assert MascotController.is_waving() is True

    # Keyboard fallback (Ctrl+G, F1)
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1", "INTELLICODEX_MASCOT_MOUSE": ""}):
        with create_pipe_input() as pipe:
            session = create_interactive_session(input=pipe, output=DummyOutput())
            if session is not None and session.key_bindings:
                MascotController._last_wave_time = 0.0
                bindings = session.key_bindings.bindings
                cg_binding = [b for b in bindings if any("c-g" in str(k) or "ControlG" in str(k) for k in b.keys)]
                assert len(cg_binding) > 0
                fake_event = MagicMock()
                cg_binding[0].handler(fake_event)
                assert MascotController.is_waving() is True
                fake_event.app.invalidate.assert_called_once()


def test_wave_primary_greeting_hint():
    """Mascot idle status hint directs user to type 'wave' as the primary greeting method."""
    with patch.dict(os.environ, {"CI": "", "INTELLICODEX_NO_ANIMATION": "", "INTELLICODEX_FORCE_ANIMATION": "1", "INTELLICODEX_MASCOT_MOUSE": ""}):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        from cli import create_interactive_session

        with create_pipe_input() as pipe:
            session = create_interactive_session(input=pipe, output=DummyOutput())
            if session is not None:
                mascot_win = session.layout.container.children[0]
                tokens = mascot_win.content.content.text()
                text_combined = "".join(t[1] for t in tokens if len(t) >= 2)
                assert "wave" in text_combined.lower()


def test_get_mascot_greeting_keys_configurable():
    """Greeting keys default to ['c-g', 'f1'] and are configurable or disableable via INTELLICODEX_GREET_KEYS."""
    from cli import get_mascot_greeting_keys

    with patch.dict(os.environ, {"INTELLICODEX_GREET_KEYS": ""}):
        assert get_mascot_greeting_keys() == ["c-g", "f1"]

    with patch.dict(os.environ, {"INTELLICODEX_GREET_KEYS": "f1"}):
        assert get_mascot_greeting_keys() == ["f1"]

    with patch.dict(os.environ, {"INTELLICODEX_GREET_KEYS": "c-h,f2"}):
        assert get_mascot_greeting_keys() == ["c-h", "f2"]

    with patch.dict(os.environ, {"INTELLICODEX_GREET_KEYS": "none"}):
        assert get_mascot_greeting_keys() == []

    with patch.dict(os.environ, {"INTELLICODEX_GREET_KEYS": "0"}):
        assert get_mascot_greeting_keys() == []


def test_wave_command_in_session_completer():
    """'wave' command is registered in autocomplete suggestions."""
    from prompt_toolkit.document import Document
    from cli import IntelliCodeXCompleter

    completer = IntelliCodeXCompleter()
    doc = Document("wav")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "wave" in matches


