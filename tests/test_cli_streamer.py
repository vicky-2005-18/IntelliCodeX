"""
Unit tests for flicker-free token streaming subsystem in IntelliCodeX CLI.
"""

from typing import Iterator
from unittest.mock import MagicMock, patch
from rich.console import Console

from core.cli.ui.streamer import TokenStreamer, render_markdown_panel
from core.cli.ui import TokenStreamer as ReexportedTokenStreamer


def test_token_streamer_accumulates_and_returns_full_text():
    """Verify that TokenStreamer accumulates streamed tokens and returns the complete text."""
    tokens = ["def ", "hello():\n", "    return 'world'"]
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)
    result = streamer.stream(iter(tokens), title="Test Answer")

    assert result == "def hello():\n    return 'world'"
    output = console.export_text()
    assert "Test Answer" in output
    assert "def hello" in output


def test_token_streamer_empty_stream():
    """Verify that an empty token generator returns an empty string without errors."""
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)
    result = streamer.stream(iter([]))
    assert result == ""


def test_token_streamer_incomplete_markdown():
    """Verify that streaming tokens containing incomplete markdown syntax does not crash."""
    incomplete_tokens = [
        "# Heading\n",
        "Here is some unfinished code:\n",
        "```python\n",
        "def broken_syntax(:",
    ]
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)
    result = streamer.stream(iter(incomplete_tokens), title="Markdown Safety")

    assert result == "".join(incomplete_tokens)
    output = console.export_text()
    assert "Markdown Safety" in output


def test_token_streamer_keyboard_interrupt_stops_cleanly():
    """Verify that KeyboardInterrupt stops streaming and returns accumulated text."""
    def interrupting_generator() -> Iterator[str]:
        yield "Initial response tokens."
        yield " More context here."
        raise KeyboardInterrupt()
        yield " This should never be reached."

    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)
    result = streamer.stream(interrupting_generator(), title="Interrupted Query")

    assert result == "Initial response tokens. More context here."
    assert "This should never be reached." not in result


def test_token_streamer_on_token_callback():
    """Verify that on_token callback is called for each token."""
    seen_tokens = []
    tokens = ["alpha ", "beta ", "gamma"]
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)

    result = streamer.stream(iter(tokens), on_token=seen_tokens.append)
    assert result == "alpha beta gamma"
    assert seen_tokens == ["alpha ", "beta ", "gamma"]


def test_token_streamer_cancel():
    """Verify that cancel() stops iteration cleanly and returns accumulated text."""
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)

    def cancelling_gen() -> Iterator[str]:
        yield "first "
        yield "second "
        streamer.cancel()
        yield "third"

    result = streamer.stream(cancelling_gen(), title="Cancelled Stream")
    assert result == "first second "
    assert "third" not in result


def test_render_markdown_panel_direct_call():
    """Verify render_markdown_panel method and module function render markdown cleanly."""
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)
    streamer.render_markdown_panel("**Bold Content**", title="Standalone Panel")

    output = console.export_text()
    assert "Standalone Panel" in output
    assert "Bold Content" in output


def test_render_markdown_panel_fallback_on_error():
    """Verify render_markdown_panel falls back gracefully if Markdown parsing fails."""
    console = Console(record=True, width=80)
    streamer = TokenStreamer(console=console)

    with patch("core.cli.ui.streamer.Markdown", side_effect=Exception("Simulated Markdown parsing failure")):
        streamer.render_markdown_panel("Fallback text", title="Fallback Test")

    output = console.export_text()
    assert "Fallback Test" in output
    assert "Fallback text" in output


def test_reexported_from_core_cli_ui():
    """Verify TokenStreamer and render_markdown_panel are exported from core.cli.ui."""
    from core.cli.ui import TokenStreamer as ImportedStreamer
    from core.cli.ui import render_markdown_panel as imported_render_md

    assert ImportedStreamer is TokenStreamer
    assert callable(imported_render_md)
