"""
Unit tests for interactive patch and unified diff reviewer subsystem in IntelliCodeX CLI.
"""

from unittest.mock import MagicMock, patch
import pytest
from rich.console import Console

from core.cli.ui.diff_viewer import (
    render_diff,
    render_patch_card,
    render_interactive_diff,
)


@pytest.fixture
def sample_patch():
    return {
        "target_file": "pkg/auth.py",
        "error_type": "KeyError",
        "confidence_score": 0.95,
        "status": "success",
        "explanation": "Added key existence guard before lookup.",
        "git_diff": (
            "--- a/pkg/auth.py\n"
            "+++ b/pkg/auth.py\n"
            "@@ -1,3 +1,4 @@\n"
            "-def old_lookup():\n"
            "+def new_lookup():\n"
            "+    pass\n"
        ),
        "sandbox_validation": {
            "test_status": "passed",
            "iterations_count": 1,
            "test_result": {
                "exit_code": 0,
                "passed_count": 5,
                "failed_count": 0,
            },
        },
    }


def test_render_diff_formats_unified_diff_with_syntax():
    """Verify render_diff formats unified diff with line numbers and Rich syntax highlighting."""
    sample_diff = (
        "--- a/auth.py\n"
        "+++ b/auth.py\n"
        "@@ -1,3 +1,4 @@\n"
        "-def old():\n"
        "+def new():\n"
    )
    console = Console(record=True, width=80)
    render_diff(sample_diff, console=console)

    output = console.export_text()
    assert "Unified Git Diff" in output
    assert "def new" in output or "def old" in output


def test_render_diff_empty_or_whitespace():
    """Verify render_diff handles empty or whitespace diff gracefully."""
    console = Console(record=True, width=80)
    render_diff("", console=console)
    output = console.export_text()
    assert "No diff" in output or "Unified Git Diff" in output or output.strip() == ""


def test_render_patch_card_extracts_target_explanation_validation(sample_patch):
    """Verify render_patch_card extracts target_file, explanation, and validation status."""
    console = Console(record=True, width=80)
    render_patch_card(sample_patch, fix_time=1.23, console=console)

    output = console.export_text()
    assert "INTELLICODEX AUTOMATED CODE PATCH" in output
    assert "pkg/auth.py" in output
    assert "KeyError" in output
    assert "Added key existence guard before lookup." in output
    assert "PASSED" in output


def test_render_interactive_diff_simulated_input_apply(sample_patch):
    """Verify render_interactive_diff with simulated input 'a' returns 'apply'."""
    console = Console(record=True, width=80)
    action = render_interactive_diff(
        sample_patch,
        prompt_fn=lambda _: "a",
        console=console,
    )
    assert action == "apply"


def test_render_interactive_diff_simulated_input_reject(sample_patch):
    """Verify render_interactive_diff with simulated input 'r' returns 'reject'."""
    console = Console(record=True, width=80)
    action = render_interactive_diff(
        sample_patch,
        prompt_fn=lambda _: "r",
        console=console,
    )
    assert action == "reject"


def test_render_interactive_diff_simulated_input_test_sandbox(sample_patch):
    """Verify render_interactive_diff with simulated input 't' invokes sandbox_test_fn, updates status, and accepts follow-up."""
    console = Console(record=True, width=80)
    inputs = ["t", "a"]

    def fake_prompt(_: str) -> str:
        return inputs.pop(0)

    sandbox_mock = MagicMock(return_value={
        "sandbox_validation": {
            "test_status": "passed",
            "iterations_count": 2,
            "test_result": {"exit_code": 0, "passed_count": 10, "failed_count": 0},
        },
        "status": "verified",
    })

    action = render_interactive_diff(
        sample_patch,
        prompt_fn=fake_prompt,
        sandbox_test_fn=sandbox_mock,
        console=console,
    )

    sandbox_mock.assert_called_once_with(sample_patch)
    assert sample_patch["sandbox_validation"]["iterations_count"] == 2
    assert sample_patch["status"] == "verified"
    assert action == "apply"


def test_render_interactive_diff_simulated_input_toggle_view(sample_patch):
    """Verify render_interactive_diff with simulated input 'v' toggles diff display."""
    console = Console(record=True, width=80)
    inputs = ["v", "a"]

    def fake_prompt(_: str) -> str:
        return inputs.pop(0)

    action = render_interactive_diff(
        sample_patch,
        prompt_fn=fake_prompt,
        console=console,
    )
    assert action == "apply"
    output = console.export_text()
    assert "Diff" in output


def test_render_interactive_diff_keyboard_interrupt_returns_cancel(sample_patch):
    """Verify KeyboardInterrupt in prompt returns 'cancel'."""
    console = Console(record=True, width=80)

    def interrupting_prompt(_: str) -> str:
        raise KeyboardInterrupt()

    action = render_interactive_diff(
        sample_patch,
        prompt_fn=interrupting_prompt,
        console=console,
    )
    assert action == "cancel"


def test_render_interactive_diff_eof_error_returns_cancel(sample_patch):
    """Verify EOFError in prompt returns 'cancel'."""
    console = Console(record=True, width=80)

    def eof_prompt(_: str) -> str:
        raise EOFError()

    action = render_interactive_diff(
        sample_patch,
        prompt_fn=eof_prompt,
        console=console,
    )
    assert action == "cancel"


def test_render_interactive_diff_with_patched_input(sample_patch):
    """Verify render_interactive_diff works with standard builtins.input patching."""
    console = Console(record=True, width=80)
    with patch("builtins.input", return_value="a"):
        action = render_interactive_diff(sample_patch, console=console)
        assert action == "apply"


def test_reexported_from_core_cli_ui():
    """Verify render_diff, render_patch_card, and render_interactive_diff are re-exported in core.cli.ui."""
    from core.cli.ui import (
        render_diff as imported_render_diff,
        render_patch_card as imported_render_patch_card,
        render_interactive_diff as imported_render_interactive_diff,
    )
    assert imported_render_diff is render_diff
    assert imported_render_patch_card is render_patch_card
    assert imported_render_interactive_diff is render_interactive_diff
