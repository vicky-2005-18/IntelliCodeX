"""
Services Package
"""
from backend.services.git_service import GitService
from backend.services.incremental_indexer import (
    IncrementalIndexer,
    RepositoryWatcher,
    RepositoryEventHandler,
    is_ignored_path,
)
from backend.services.code_review import CodeReviewAssistant
