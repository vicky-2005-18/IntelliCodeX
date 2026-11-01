"""
Unit tests for core.cli.completers: Fuzzy Autocompleter & Command Palette.
"""
from unittest.mock import patch
import pytest

from prompt_toolkit.document import Document
from core.cli.completers import IntelliCodeXCompleter, build_completer_commands


def test_build_completer_commands():
    """build_completer_commands returns a populated list of (token, description) pairs."""
    cmds = build_completer_commands()
    assert isinstance(cmds, list)
    assert len(cmds) >= 40
    tokens = [tok for tok, _ in cmds]
    assert "explain:" in tokens
    assert "wave" in tokens
    assert "status" in tokens
    assert "search:" in tokens
    assert "fix:" in tokens
    assert "deps:" in tokens

    # IntelliCodeXCompleter class attribute matches
    assert IntelliCodeXCompleter.COMMANDS == cmds
    assert IntelliCodeXCompleter.build_completer_commands() == cmds


def test_completer_fuzzy_command_matching():
    """Completer matches commands via prefix, substring, and fuzzy matching."""
    completer = IntelliCodeXCompleter()

    # Prefix match
    doc = Document("exp")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "explain:" in matches
    assert "export:" in matches

    doc = Document("wat")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch" in matches
    assert "watch:status" in matches

    doc = Document("wave")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "wave" in matches

    # Substring match (e.g. typing 'stat' should match 'status', 'watch:status', 'hybrid:status')
    doc = Document("stat")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "status" in matches
    assert "watch:status" in matches
    assert "index-stats" in matches

    # Fuzzy subsequence matching (e.g. 'wst' matches 'watch:status' and 'watch:start')
    doc = Document("wst")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch:status" in matches or "watch:start" in matches


def test_completer_inline_description_display_meta():
    """All command completions have descriptive display_meta."""
    completer = IntelliCodeXCompleter()
    doc = Document("sea")
    completions = list(completer.get_completions(doc))
    assert len(completions) > 0

    search_comp = next((c for c in completions if c.text == "search:"), None)
    assert search_comp is not None
    assert search_comp.display_meta_text is not None
    assert "search" in search_comp.display_meta_text.lower() or "lexical" in search_comp.display_meta_text.lower()


def test_completer_at_mention_file_matching():
    """Completing @-mentions matches files by basename and path with display_meta='File'."""
    files = ["backend/auth.py", "core/embedder.py", "cli.py", "pkg/database.py"]
    completer = IntelliCodeXCompleter(get_files_fn=lambda: files)

    # Scoped @-mention in a query
    doc = Document("review @auth")
    completions = list(completer.get_completions(doc))
    matches = [c.text for c in completions]
    assert any("auth.py" in m for m in matches)
    auth_c = next(c for c in completions if "auth.py" in c.text)
    assert auth_c.display_meta_text == "File"

    # Direct @ with partial name
    doc2 = Document("@embed")
    matches2 = [c.text for c in completer.get_completions(doc2)]
    assert any("embedder.py" in m for m in matches2)

    # Direct @ empty lists all files
    doc3 = Document("@")
    matches3 = [c.text for c in completer.get_completions(doc3)]
    assert len(matches3) == len(files)


def test_completer_symbol_suggestions():
    """Completing symbols for callers: and #mentions provides matching symbols."""
    symbols = ["get_user_profile", "verify_jwt_token", "AuthService.login", "calculate_metrics"]
    completer = IntelliCodeXCompleter(get_symbols_fn=lambda: symbols)

    # callers: prefix
    doc = Document("callers:ver")
    completions = list(completer.get_completions(doc))
    matches = [c.text for c in completions]
    assert "verify_jwt_token" in matches
    assert "get_user_profile" not in matches
    assert completions[0].display_meta_text == "Symbol"

    # #mention completion
    doc2 = Document("what does #Auth")
    matches2 = [c.text for c in completer.get_completions(doc2)]
    assert "AuthService.login" in matches2

    # doc: prefix
    doc3 = Document("doc:calculate")
    matches3 = [c.text for c in completer.get_completions(doc3)]
    assert "calculate_metrics" in matches3


def test_completer_persona_and_backend():
    """Completes persona and backend configuration parameters."""
    completer = IntelliCodeXCompleter()

    # Persona completion
    doc = Document("persona sec")
    completions = list(completer.get_completions(doc))
    matches = [c.text for c in completions]
    assert "security" in matches
    sec_comp = next(c for c in completions if c.text == "security")
    assert sec_comp.display_meta_text == "Persona"

    doc = Document("persona rev")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "reviewer" in matches

    # Backend completion
    doc = Document("backend tf")
    completions = list(completer.get_completions(doc))
    matches = [c.text for c in completions]
    assert "tfidf" in matches
    tf_comp = next(c for c in completions if c.text == "tfidf")
    assert tf_comp.display_meta_text == "Backend"

    doc = Document("backend ol")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "ollama" in matches


def test_completer_error_and_run_and_subcommands():
    """Completes fix: errors, run: targets, and subcommands."""
    files = ["main.py", "TodoApp.java", "server.js", "README.md"]
    completer = IntelliCodeXCompleter(get_files_fn=lambda: files)

    # fix: error completion
    doc = Document("fix:Key")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "KeyError" in matches

    # run: target completion (only executable files with @ prefix)
    doc = Document("run: @")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "@main.py" in matches
    assert "@TodoApp.java" in matches
    assert "@server.js" in matches
    assert "@README.md" not in matches

    # Subcommands
    doc = Document("watch:sta")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "watch:status" in matches
    assert "watch:start" in matches
    assert "watch:stop" not in matches

    doc = Document("hybrid:togg")
    matches = [c.text for c in completer.get_completions(doc)]
    assert "hybrid:toggle" in matches


def test_completer_graceful_degradation_empty_document():
    """Completer degrades gracefully on empty document or None input."""
    completer = IntelliCodeXCompleter()

    assert list(completer.get_completions(Document(""))) == []
    assert list(completer.get_completions(Document("    "))) == []
    assert list(completer.get_completions(None)) == []


def test_completer_graceful_degradation_without_prompt_toolkit():
    """Completer handles absence of prompt_toolkit cleanly."""
    with patch("core.cli.completers.HAS_PROMPT_TOOLKIT", False), \
         patch("core.cli.completers.Completion", None):
        completer = IntelliCodeXCompleter()
        doc = Document("exp")
        assert list(completer.get_completions(doc)) == []


def test_core_cli_reexport():
    """IntelliCodeXCompleter and build_completer_commands are re-exported by core.cli."""
    from core.cli import IntelliCodeXCompleter as ExportedCompleter, build_completer_commands as exported_build
    assert ExportedCompleter is IntelliCodeXCompleter
    assert exported_build is build_completer_commands
