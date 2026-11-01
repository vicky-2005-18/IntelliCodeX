"""
Tests for Modular Command Handlers & Registry (Task 7).
"""

from unittest.mock import MagicMock, patch
import pytest

from core.cli.state import CLISessionState


def _make_dummy_state(**kwargs) -> CLISessionState:
    mock_engine = MagicMock()
    mock_store = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.file_path = "auth.py"
    mock_store.chunks = [mock_chunk]
    mock_engine.store = mock_store
    mock_engine.dep_graph = MagicMock()
    mock_engine.call_graph = MagicMock()
    mock_engine.ask.return_value = {"answer": "Dummy answer"}
    mock_engine.retrieve_expanded.return_value = [mock_chunk]

    mock_embedder = MagicMock()
    mock_llm = MagicMock()

    defaults = {
        "repo_path": "/fake/repo",
        "repo_id": "fake_repo",
        "backend": "tfidf",
        "model_name": "qwen2.5-coder:3b",
        "embedder": mock_embedder,
        "llm": mock_llm,
        "engine": mock_engine,
    }
    defaults.update(kwargs)
    return CLISessionState(**defaults)


def test_command_registry_dispatch_exit():
    from core.cli.commands import CommandRegistry

    state = _make_dummy_state()
    registry = CommandRegistry()

    assert registry.dispatch("exit", state) == "exit"
    assert registry.dispatch("quit", state) == "exit"
    assert registry.dispatch("q", state) == "exit"
    assert registry.dispatch("EXIT", state) == "exit"
    assert registry.dispatch("  Quit  ", state) == "exit"


def test_command_registry_dispatch_empty_input():
    from core.cli.commands import CommandRegistry

    state = _make_dummy_state()
    registry = CommandRegistry()

    assert registry.dispatch("", state) is False
    assert registry.dispatch("   ", state) is False
    assert registry.dispatch(None, state) is False


def test_command_registry_dispatch_watch_commands():
    from core.cli.commands import CommandRegistry, WatchHandler

    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True
    state = _make_dummy_state(watcher=mock_watcher)

    registry = CommandRegistry([WatchHandler()])

    res_status = registry.dispatch("watch:status", state)
    assert res_status is True

    res_watch = registry.dispatch("watch", state)
    assert res_watch is True

    res_stop = registry.dispatch("watch:stop", state)
    assert res_stop is True
    mock_watcher.stop.assert_called()

    # watch:start
    res_start = registry.dispatch("watch:start", state)
    assert res_start is True

    # watch:stop when watcher is None
    state_no_watcher = _make_dummy_state(watcher=None)
    assert registry.dispatch("watch:stop", state_no_watcher) is True


def test_command_registry_dispatch_repo_commands():
    from core.cli.commands import CommandRegistry, RepoHandler

    state = _make_dummy_state()
    registry = CommandRegistry([RepoHandler()])

    assert registry.dispatch("files", state) is True
    assert registry.dispatch("ls", state) is True
    assert registry.dispatch("index-stats", state) is True
    assert registry.dispatch("chunks: auth.py", state) is True
    assert registry.dispatch("repos", state) is True

    # Repo switch
    assert registry.dispatch("repo: /new/repo/path", state) is True
    assert state.repo_path == "/new/repo/path"


def test_command_registry_dispatch_audit_commands():
    from core.cli.commands import CommandRegistry, AuditHandler

    state = _make_dummy_state()
    registry = CommandRegistry([AuditHandler()])

    with patch("core.security_scanner.run_security_scan", return_value={"findings": []}), \
         patch("core.security_scanner.format_security_report", return_value="Clean"):
        assert registry.dispatch("security: auth.py", state) is True

    assert registry.dispatch("arch", state) is True
    assert registry.dispatch("cycles", state) is True
    assert registry.dispatch("optimize", state) is True
    assert registry.dispatch("deps: auth.py", state) is True
    assert registry.dispatch("callers: login", state) is True
    assert registry.dispatch("top", state) is True
    assert registry.dispatch("centrality", state) is True


def test_command_registry_dispatch_fix_commands():
    from core.cli.commands import CommandRegistry, FixHandler

    state = _make_dummy_state()
    registry = CommandRegistry([FixHandler()])

    with patch("core.patch_generator.PatchEngine.generate_patch", return_value={
        "status": "verified",
        "patch_id": "p123",
        "target_file": "auth.py",
        "git_diff": "diff",
        "explanation": "Fixed bug",
        "sandbox_validation": {"test_status": "passed", "verified": True},
    }), patch("core.cli.commands.fix_handler.render_interactive_diff", return_value="r"):
        assert registry.dispatch("fix: @auth.py ZeroDivisionError", state) is True

    with patch("backend.database.mongo.db_manager.find", return_value=[]):
        assert registry.dispatch("review", state) is True
        assert registry.dispatch("proposals", state) is True

    with patch("core.patch_generator.PatchEngine.update_patch_status", return_value={}):
        assert registry.dispatch("approve p123", state) is True
        assert registry.dispatch("reject p123", state) is True


def test_command_registry_dispatch_query_commands():
    from core.cli.commands import CommandRegistry, QueryHandler

    state = _make_dummy_state()
    registry = CommandRegistry([QueryHandler()])

    # Questions ending with question mark or question words
    assert registry.dispatch("Where is authentication handled?", state) is True
    assert registry.dispatch("How does the indexing pipeline work?", state) is True
    assert registry.dispatch("Why is this pattern used?", state) is True
    assert registry.dispatch("@auth.py what does this function do?", state) is True

    # explain: command
    assert registry.dispatch("explain: search pipeline", state) is True

    # search: command
    assert registry.dispatch("search: authenticate_user", state) is True


def test_command_registry_unknown_command():
    from core.cli.commands import CommandRegistry, create_default_registry

    state = _make_dummy_state()

    # Default registry without query fallback returns False for unknown command
    registry = create_default_registry(fallback_to_query=False)
    assert registry.dispatch("non_existent_command_xyz", state) is False
    assert registry.dispatch("invalid:foobar", state) is False

    # Registry with query fallback passes unknown command to query
    fallback_reg = create_default_registry(fallback_to_query=True)
    assert fallback_reg.dispatch("non_existent_command_xyz", state) is True


def test_command_registry_custom_handler_registration():
    from core.cli.commands import CommandRegistry, CommandHandler

    class CustomEchoHandler(CommandHandler):
        def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
            return raw_input.strip().startswith("echo:")

        def handle(self, raw_input: str, state: CLISessionState):
            msg = raw_input.split(":", 1)[1].strip()
            return f"ECHO: {msg}"

    state = _make_dummy_state()
    registry = CommandRegistry()
    registry.register(CustomEchoHandler())

    assert registry.dispatch("echo: hello world", state) == "ECHO: hello world"
    assert registry.dispatch("echo: test", state) == "ECHO: test"
    assert registry.dispatch("other_command", state) is False


def test_command_registry_handler_exception_safety():
    from core.cli.commands import CommandRegistry, CommandHandler

    class BrokenHandler(CommandHandler):
        def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
            return raw_input == "boom"

        def handle(self, raw_input: str, state: CLISessionState):
            raise RuntimeError("Handler failure!")

    state = _make_dummy_state()
    registry = CommandRegistry([BrokenHandler()])

    # Exception should be caught and logged, returning False rather than crashing
    assert registry.dispatch("boom", state) is False


def test_command_symbols_re_exported():
    import core.cli.commands as commands_pkg
    import core.cli as cli_pkg

    expected_symbols = [
        "CommandHandler",
        "CommandRegistry",
        "create_default_registry",
        "QueryHandler",
        "FixHandler",
        "RepoHandler",
        "WatchHandler",
        "AuditHandler",
    ]

    for sym in expected_symbols:
        assert hasattr(commands_pkg, sym), f"{sym} missing in core.cli.commands"
        assert hasattr(cli_pkg, sym), f"{sym} missing in core.cli"
        assert sym in commands_pkg.__all__
        assert sym in cli_pkg.__all__
