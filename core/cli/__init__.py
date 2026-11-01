"""IntelliCodeX CLI Subsystem."""

from core.cli.state import CLISessionState
from core.cli.terminal_safety import (
    restore_terminal_mouse_modes,
    cleanup_cli_resources,
    register_active_watcher,
    setup_terminal_signal_handlers,
    MOUSE_DISABLE_SEQUENCES,
)
from core.cli.completers import IntelliCodeXCompleter, build_completer_commands

__all__ = [
    "CLISessionState",
    "restore_terminal_mouse_modes",
    "cleanup_cli_resources",
    "register_active_watcher",
    "setup_terminal_signal_handlers",
    "MOUSE_DISABLE_SEQUENCES",
    "IntelliCodeXCompleter",
    "build_completer_commands",
]
