"""
IntelliCodeX Command Registry and Base Command Handler.

Provides the abstract CommandHandler interface and the CommandRegistry
that dispatches user inputs to specialized handlers with fallback and exit handling.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, List, Optional

from core.cli.state import CLISessionState

logger = logging.getLogger(__name__)


class CommandHandler(ABC):
    """
    Abstract base class for modular CLI command handlers.
    """

    @abstractmethod
    def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
        """
        Determines whether this handler can process the given raw input.

        Args:
            raw_input: Raw command or query string entered by the user.
            state: Active CLI session state.

        Returns:
            True if this handler can process the command, False otherwise.
        """
        pass

    @abstractmethod
    def handle(self, raw_input: str, state: CLISessionState) -> Any:
        """
        Executes the command.

        Args:
            raw_input: Raw command or query string entered by the user.
            state: Active CLI session state.

        Returns:
            Result of execution or True if successfully handled.
        """
        pass


class CommandRegistry:
    """
    Registry for managing and dispatching commands across modular handlers.
    """

    def __init__(
        self,
        handlers: Optional[List[CommandHandler]] = None,
        fallback_to_query: bool = False,
    ) -> None:
        """
        Initializes registry with optional list of handlers and fallback configuration.
        """
        self._handlers: List[CommandHandler] = list(handlers) if handlers else []
        self.fallback_to_query: bool = fallback_to_query

    @property
    def handlers(self) -> List[CommandHandler]:
        """Returns shallow copy of registered handlers."""
        return list(self._handlers)

    def register(self, handler: CommandHandler) -> None:
        """
        Registers a new command handler.
        """
        if handler not in self._handlers:
            self._handlers.append(handler)

    def dispatch(self, raw_input: str, state: CLISessionState) -> Any:
        """
        Dispatches input to appropriate handler or processes exit.

        Returns:
            "exit" on exit command,
            True or handler return value if handled,
            False if unhandled.
        """
        if not raw_input:
            return False

        stripped = raw_input.strip()
        if not stripped:
            return False

        # 1. Exit / Quit commands
        if stripped.lower() in ("exit", "quit", "q", "exit()", ":q"):
            try:
                from core.cli.terminal_safety import cleanup_cli_resources
                cleanup_cli_resources(getattr(state, "watcher", None))
            except Exception as err:
                logger.debug("Error during exit cleanup: %s", err)
            return "exit"

        # 2. Iterate registered handlers
        for handler in self._handlers:
            try:
                if handler.can_handle(stripped, state):
                    res = handler.handle(stripped, state)
                    return True if res is None else res
            except Exception as err:
                logger.error("Error executing handler %s: %s", handler.__class__.__name__, err, exc_info=True)
                return False

        # 3. Fallback to query handler if configured
        if self.fallback_to_query:
            for handler in self._handlers:
                if handler.__class__.__name__ == "QueryHandler":
                    res = handler.handle(stripped, state)
                    return True if res is None else res

            from core.cli.commands.query_handler import QueryHandler
            fallback_handler = QueryHandler(fallback=True)
            res = fallback_handler.handle(stripped, state)
            return True if res is None else res

        return False


def create_default_registry(fallback_to_query: bool = False) -> CommandRegistry:
    """
    Creates and returns a CommandRegistry pre-populated with standard handlers.
    """
    from core.cli.commands.watch_handler import WatchHandler
    from core.cli.commands.repo_handler import RepoHandler
    from core.cli.commands.audit_handler import AuditHandler
    from core.cli.commands.fix_handler import FixHandler
    from core.cli.commands.query_handler import QueryHandler

    handlers: List[CommandHandler] = [
        WatchHandler(),
        RepoHandler(),
        AuditHandler(),
        FixHandler(),
        QueryHandler(fallback=fallback_to_query),
    ]
    return CommandRegistry(handlers=handlers, fallback_to_query=fallback_to_query)
