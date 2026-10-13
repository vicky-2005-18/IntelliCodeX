"""
Core Filesystem Watcher Interface (REQ-FUT-03)
Provides canonical re-exports for repository filesystem event monitoring, debouncing,
and live incremental re-indexing daemons.
"""
from backend.services.incremental_indexer import (
    RepositoryWatcher,
    RepositoryEventHandler,
    IncrementalIndexer,
    is_ignored_path,
    compute_file_hash,
    WATCHDOG_AVAILABLE,
)

__all__ = [
    "RepositoryWatcher",
    "RepositoryEventHandler",
    "IncrementalIndexer",
    "is_ignored_path",
    "compute_file_hash",
    "WATCHDOG_AVAILABLE",
]
