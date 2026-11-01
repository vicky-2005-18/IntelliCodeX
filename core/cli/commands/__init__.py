"""
Modular Command Handlers and Registry Subsystem for IntelliCodeX CLI.
"""

from core.cli.commands.base import (
    CommandHandler,
    CommandRegistry,
    create_default_registry,
)
from core.cli.commands.watch_handler import WatchHandler
from core.cli.commands.repo_handler import RepoHandler
from core.cli.commands.audit_handler import AuditHandler
from core.cli.commands.fix_handler import FixHandler
from core.cli.commands.query_handler import QueryHandler

__all__ = [
    "CommandHandler",
    "CommandRegistry",
    "create_default_registry",
    "WatchHandler",
    "RepoHandler",
    "AuditHandler",
    "FixHandler",
    "QueryHandler",
]

