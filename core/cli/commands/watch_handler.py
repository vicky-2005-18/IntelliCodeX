"""
Watch Command Handler for IntelliCodeX CLI.

Manages the real-time repository filesystem watcher lifecycle
(status inspection, starting, stopping, pausing, and resuming).
"""

import logging
from typing import Any

from core.cli.commands.base import CommandHandler
from core.cli.state import CLISessionState

logger = logging.getLogger(__name__)


class WatchHandler(CommandHandler):
    """
    Handles filesystem watcher commands: watch, watch:status, watch:start, watch:stop.
    """

    WATCH_EXACT_COMMANDS = {
        "watch",
        "watch:status",
        "watcher",
        "watch:start",
        "watch:resume",
        "watch:stop",
        "watch:pause",
    }

    def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
        low = raw_input.strip().lower()
        if low in self.WATCH_EXACT_COMMANDS:
            return True
        if low.startswith("watch:") or low.startswith("watch "):
            return True
        return False

    def handle(self, raw_input: str, state: CLISessionState) -> Any:
        low = raw_input.strip().lower()

        # 1. Stop / Pause
        if low in ("watch:stop", "watch:pause"):
            watcher = state.watcher
            if watcher is not None and getattr(watcher, "is_alive", lambda: False)():
                try:
                    if callable(getattr(watcher, "stop", None)):
                        watcher.stop()
                except Exception as err:
                    logger.debug("Error stopping watcher: %s", err)
                state.set_watcher(None)
                print("\n[*] Real-Time Filesystem Watcher stopped.\n")
            else:
                print("\n[*] Real-Time Filesystem Watcher is already inactive.\n")
            return True

        # 2. Start / Resume
        if low in ("watch:start", "watch:resume"):
            watcher = state.watcher
            if watcher is not None and getattr(watcher, "is_alive", lambda: False)():
                print("\n[*] Real-Time Filesystem Watcher is already active.\n")
            else:
                try:
                    from backend.services.incremental_indexer import RepositoryWatcher

                    def _on_reindex(res):
                        print(f"\n[*] [Watcher] Incremental re-index complete: {getattr(res, 'num_files', 0)} files.")

                    new_watcher = RepositoryWatcher(
                        state.repo_path,
                        state.embedder,
                        on_reindex=_on_reindex,
                        debounce_delay=0.5,
                    )
                    started = new_watcher.start() if callable(getattr(new_watcher, "start", None)) else True
                    if started is not False:
                        state.set_watcher(new_watcher)
                        print(f"\n[*] Real-Time Filesystem Watcher started on '{state.repo_path}'.\n")
                    else:
                        print("\n[!] Watcher failed to start (watchdog package missing or unsupported).\n")
                except Exception as err:
                    print(f"\n[!] Error starting watcher: {err}\n")
            return True

        # 3. Status inspection
        watcher = state.watcher
        is_active = bool(watcher and getattr(watcher, "is_alive", lambda: False)())
        try:
            from rich.console import Console
            from rich.table import Table
            from rich.panel import Panel

            console = Console()
            grid = Table.grid(padding=(0, 2))
            grid.add_column(style="bold cyan", justify="right")
            grid.add_column(style="white")
            grid.add_row(
                "Status:",
                "[bold green]ACTIVE ●[/bold green]" if is_active else "[bold red]INACTIVE[/bold red]",
            )
            grid.add_row("Target:", state.repo_path)
            grid.add_row("Debounce:", "500 ms")
            grid.add_row("Auto-reindex:", "[green]Enabled[/green]" if is_active else "[dim]Disabled[/dim]")

            console.print(
                Panel(
                    grid,
                    title="[bold cyan]Filesystem Watcher Status[/bold cyan]",
                    border_style="cyan",
                )
            )
        except Exception:
            print(f"\n[*] Watcher Status: {'ACTIVE' if is_active else 'INACTIVE'} on '{state.repo_path}'\n")

        return True
