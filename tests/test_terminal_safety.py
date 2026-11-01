import sys
import signal
from unittest.mock import patch, MagicMock
import pytest

from core.cli.terminal_safety import (
    restore_terminal_mouse_modes,
    cleanup_cli_resources,
    register_active_watcher,
    setup_terminal_signal_handlers,
    MOUSE_DISABLE_SEQUENCES,
)


def test_mouse_disable_sequences_constant():
    """Verify standard ANSI disable sequences including cursor restoration and absence of alt-screen buffer."""
    expected = "\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?25h"
    assert MOUSE_DISABLE_SEQUENCES == expected
    # Ensure cursor show sequence is present
    assert "\x1b[?25h" in MOUSE_DISABLE_SEQUENCES
    # Must NOT switch screen buffers (\x1b[?1049l)
    assert "\x1b[?1049l" not in MOUSE_DISABLE_SEQUENCES


def test_restore_terminal_mouse_modes_emits_ansi_reset():
    """restore_terminal_mouse_modes writes MOUSE_DISABLE_SEQUENCES to stdout and flushes."""
    mock_stdout = MagicMock()
    with patch("sys.stdout", mock_stdout):
        restore_terminal_mouse_modes()
        mock_stdout.write.assert_called_with(MOUSE_DISABLE_SEQUENCES)
        mock_stdout.flush.assert_called_once()


def test_restore_terminal_mouse_modes_handles_none_or_closed_stdout():
    """restore_terminal_mouse_modes never crashes if stdout is None, closed, or throws an exception."""
    with patch("sys.stdout", None):
        # Should not raise
        restore_terminal_mouse_modes()

    closed_stdout = MagicMock()
    closed_stdout.closed = True
    with patch("sys.stdout", closed_stdout):
        restore_terminal_mouse_modes()
        closed_stdout.write.assert_not_called()

    failing_stdout = MagicMock()
    failing_stdout.write.side_effect = IOError("stdout write failed")
    with patch("sys.stdout", failing_stdout):
        # Should not raise exception
        restore_terminal_mouse_modes()


def test_cleanup_cli_resources_stops_registered_watcher():
    """cleanup_cli_resources stops registered watcher and clears reference."""
    mock_watcher = MagicMock()
    register_active_watcher(mock_watcher)
    with patch("core.cli.terminal_safety.restore_terminal_mouse_modes") as mock_restore:
        cleanup_cli_resources()
        mock_watcher.stop.assert_called_once()
        mock_restore.assert_called_once()

    # Second call should not stop the watcher again since reference was cleared
    mock_watcher.reset_mock()
    cleanup_cli_resources()
    mock_watcher.stop.assert_not_called()


def test_cleanup_cli_resources_with_explicit_watcher():
    """cleanup_cli_resources accepts an explicit watcher argument."""
    mock_watcher = MagicMock()
    with patch("core.cli.terminal_safety.restore_terminal_mouse_modes") as mock_restore:
        cleanup_cli_resources(mock_watcher)
        mock_watcher.stop.assert_called_once()
        mock_restore.assert_called_once()


def test_cleanup_cli_resources_tolerates_watcher_error():
    """Watcher stop failure should not prevent terminal restoration or crash."""
    mock_watcher = MagicMock()
    mock_watcher.stop.side_effect = RuntimeError("Watcher thread deadlocked")
    with patch("core.cli.terminal_safety.restore_terminal_mouse_modes") as mock_restore:
        cleanup_cli_resources(mock_watcher)
        mock_restore.assert_called_once()


def test_setup_terminal_signal_handlers_registers_signals():
    """setup_terminal_signal_handlers registers SIGINT and SIGTERM."""
    with patch("signal.signal") as mock_signal:
        setup_terminal_signal_handlers()
        registered_signals = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGINT in registered_signals
        assert signal.SIGTERM in registered_signals
        if hasattr(signal, "SIGBREAK"):
            assert signal.SIGBREAK in registered_signals


def test_signal_handler_invokes_cleanup_and_handles_sigint():
    """SIGINT should invoke cleanup and raise KeyboardInterrupt."""
    registered_handlers = {}

    def fake_signal(sig, handler):
        registered_handlers[sig] = handler

    with patch("signal.signal", side_effect=fake_signal), \
         patch("core.cli.terminal_safety.cleanup_cli_resources") as mock_cleanup:
        setup_terminal_signal_handlers()
        assert signal.SIGINT in registered_handlers
        sigint_handler = registered_handlers[signal.SIGINT]

        with pytest.raises(KeyboardInterrupt):
            sigint_handler(signal.SIGINT, None)

        mock_cleanup.assert_called_once()


def test_signal_handler_invokes_cleanup_and_exits_on_sigterm():
    """SIGTERM should invoke cleanup and exit with 128 + SIGTERM."""
    registered_handlers = {}

    def fake_signal(sig, handler):
        registered_handlers[sig] = handler

    with patch("signal.signal", side_effect=fake_signal), \
         patch("core.cli.terminal_safety.cleanup_cli_resources") as mock_cleanup:
        setup_terminal_signal_handlers()
        assert signal.SIGTERM in registered_handlers
        sigterm_handler = registered_handlers[signal.SIGTERM]

        with pytest.raises(SystemExit) as exc_info:
            sigterm_handler(signal.SIGTERM, None)

        assert exc_info.value.code == 128 + signal.SIGTERM
        mock_cleanup.assert_called_once()
