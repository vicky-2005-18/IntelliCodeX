"""Terminal State Hygiene & Safety Subsystem for IntelliCodeX CLI.

Guarantees clean restoration of terminal mouse tracking, cursor visibility,
raw input buffers, and external watchers across normal exit, signals (SIGINT, SIGTERM),
and unhandled exceptions on Windows, Linux, and macOS.
"""

from __future__ import annotations

import atexit
import signal
import sys
import threading
from typing import Any, Callable, List, Optional

# Disable sequences:
# \x1b[?9l: X10 mouse tracking off
# \x1b[?1000l: VT200 normal mouse tracking off
# \x1b[?1001l: Hilite mouse tracking off
# \x1b[?1002l: Button event mouse tracking off
# \x1b[?1003l: Any event mouse tracking off
# \x1b[?1006l: SGR extended coordinates off
# \x1b[?25h: Cursor visible / show cursor
MOUSE_DISABLE_SEQUENCES: str = "\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?25h"

_active_watcher: Optional[Any] = None
_cleanup_hooks: List[Callable[[], Any]] = []


def register_active_watcher(watcher: Any) -> None:
    """Registers the active repository watcher for coordinated shutdown."""
    global _active_watcher
    _active_watcher = watcher


def register_cleanup_hook(hook: Callable[[], Any]) -> None:
    """Registers an arbitrary parameterless callback to invoke during CLI cleanup."""
    if hook not in _cleanup_hooks:
        _cleanup_hooks.append(hook)


def _restore_windows_console_modes() -> None:
    """Restores standard console input and output modes on Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        STD_INPUT_HANDLE = -10
        STD_OUTPUT_HANDLE = -11

        h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        h_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

        ENABLE_PROCESSED_INPUT = 0x0001
        ENABLE_LINE_INPUT = 0x0002
        ENABLE_ECHO_INPUT = 0x0004
        ENABLE_EXTENDED_FLAGS = 0x0080
        ENABLE_QUICK_EDIT_MODE = 0x0040

        default_in_mode = (
            ENABLE_PROCESSED_INPUT
            | ENABLE_LINE_INPUT
            | ENABLE_ECHO_INPUT
            | ENABLE_EXTENDED_FLAGS
            | ENABLE_QUICK_EDIT_MODE
        )

        if h_in and h_in != -1:
            in_mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(h_in, ctypes.byref(in_mode)):
                kernel32.SetConsoleMode(h_in, default_in_mode)

        ENABLE_PROCESSED_OUTPUT = 0x0001
        ENABLE_WRAP_AT_EOL_OUTPUT = 0x0002
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

        default_out_mode = (
            ENABLE_PROCESSED_OUTPUT
            | ENABLE_WRAP_AT_EOL_OUTPUT
            | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        )

        if h_out and h_out != -1:
            out_mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(h_out, ctypes.byref(out_mode)):
                kernel32.SetConsoleMode(h_out, default_out_mode)
    except Exception:
        pass


def restore_terminal_mouse_modes() -> None:
    """Restores native terminal mouse modes and cursor visibility.

    Ensures terminal mouse tracking (X10, button, SGR) is turned off cleanly
    so native terminal scrolling, mouse-wheel, and selection are never hijacked.
    Does NOT toggle screen buffers (\\x1b[?1049l) because the CLI runs exclusively
    in the normal terminal buffer.
    """
    try:
        if sys.stdout and getattr(sys.stdout, "closed", False) is not True:
            sys.stdout.write(MOUSE_DISABLE_SEQUENCES)
            sys.stdout.flush()
    except Exception:
        pass

    _restore_windows_console_modes()


def cleanup_cli_resources(watcher: Optional[Any] = None) -> None:
    """Ensures no animation, spinner thread, or filesystem watcher survives CLI shutdown.

    Cleanly restores terminal mouse tracking modes at lifecycle boundaries.
    """
    global _active_watcher

    # Execute custom registered hooks
    for hook in list(_cleanup_hooks):
        try:
            hook()
        except Exception:
            pass

    # Clean up mascot spinner / suspension if available in loaded modules
    try:
        for mod_name in ("cli", "core.cli.ui.banner"):
            if mod_name in sys.modules:
                mod = sys.modules[mod_name]
                if hasattr(mod, "MascotSpinner"):
                    getattr(mod.MascotSpinner, "stop_all", lambda: None)()
                if hasattr(mod, "suspend_mascot_rendering"):
                    getattr(mod, "suspend_mascot_rendering")()
    except Exception:
        pass

    # Stop active watcher if passed or registered
    w = watcher or _active_watcher
    if w is not None:
        try:
            w.stop()
        except Exception:
            pass
        _active_watcher = None

    restore_terminal_mouse_modes()


def _signal_handler(signum: int, frame: Any) -> None:
    """Handles terminal signals by restoring state before propagating or exiting."""
    cleanup_cli_resources()
    if signum == signal.SIGINT:
        raise KeyboardInterrupt()
    sys.exit(128 + signum)


def setup_terminal_signal_handlers() -> None:
    """Configures SIGINT, SIGTERM, and SIGBREAK handlers to safely restore terminal state."""
    if threading.current_thread() is not threading.main_thread():
        return

    try:
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError):
        pass

    try:
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, OSError):
        pass

    if hasattr(signal, "SIGBREAK"):
        try:
            signal.signal(signal.SIGBREAK, _signal_handler)
        except (ValueError, OSError):
            pass


# Ensure cleanup runs automatically at normal interpreter exit
atexit.register(cleanup_cli_resources)
