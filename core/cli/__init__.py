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
from core.cli.commands import (
    CommandHandler,
    CommandRegistry,
    create_default_registry,
    WatchHandler,
    RepoHandler,
    AuditHandler,
    FixHandler,
    QueryHandler,
)

__all__ = [
    "CLISessionState",
    "restore_terminal_mouse_modes",
    "cleanup_cli_resources",
    "register_active_watcher",
    "setup_terminal_signal_handlers",
    "MOUSE_DISABLE_SEQUENCES",
    "IntelliCodeXCompleter",
    "build_completer_commands",
    "CommandHandler",
    "CommandRegistry",
    "create_default_registry",
    "WatchHandler",
    "RepoHandler",
    "AuditHandler",
    "FixHandler",
    "QueryHandler",
]
