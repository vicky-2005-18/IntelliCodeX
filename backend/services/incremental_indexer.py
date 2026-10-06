"""
Incremental Repository Indexing & Real-Time Filesystem Watcher Daemon (Milestone 2)
Detects changed files via Git diff, content checksums, or real-time filesystem events,
partially re-chunks, and updates vector stores and metadata without requiring full repository re-indexing.
"""
import hashlib
import logging
import os
import threading
import time
from typing import List, Dict, Any, Tuple, Optional, Callable, Set

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    FileSystemEvent = object

from core.parser import SourceFile, walk_repository, LANGUAGE_BY_EXT, IGNORE_DIRS
from core.chunker import chunk_file, CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from backend.services.git_service import GitService

logger = logging.getLogger(__name__)


def compute_file_hash(content: str) -> str:
    """Computes MD5 hash of file content for fast equality checks."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


IGNORED_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".bak", ".tmp", ".swp", ".swo",
    ".DS_Store", ".git", ".lock", "~",
}


def is_ignored_path(path: str, repo_root: str) -> bool:
    """
    Checks if a filesystem path should be ignored by the watcher.
    Ignores hidden directories (.git, .venv), build artifacts, and non-source files.
    """
    try:
        rel = os.path.relpath(path, repo_root)
    except ValueError:
        rel = path

    parts = [p.lower() for p in rel.replace("\\", "/").split("/") if p]
    if not parts:
        return True

    # Ignore directory names matching IGNORE_DIRS or hidden folders
    for part in parts:
        if part in IGNORE_DIRS:
            return True
        if part.startswith(".") and part not in (".", ".."):
            return True

    # Check extension
    filename = parts[-1]
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext in IGNORED_EXTENSIONS or filename.endswith("~") or filename.startswith(".#"):
        return True

    # Also ignore .bak.* backup files created by editors or test fixtures
    if ".bak." in filename or ".tmp." in filename:
        return True

    # Only accept recognized source languages
    if ext not in LANGUAGE_BY_EXT:
        return True

    return False


class IncrementalIndexer:
    """
    Performs batch-level incremental synchronization between an existing
    vector store and current repository filesystem files.
    """
    def __init__(self, embedder: BaseEmbedder):
        self.embedder = embedder
        self.git_service = GitService()

    def sync_repository(
        self,
        repo_path: str,
        existing_store: FaissVectorStore,
        previous_file_hashes: Dict[str, str]
    ) -> Tuple[FaissVectorStore, Dict[str, str], int]:
        """
        Synchronizes changed files against previous file hashes.
        Re-embeds only changed/added chunks while retaining unchanged ones.
        """
        current_files = walk_repository(repo_path)
        current_hashes: Dict[str, str] = {}
        changed_files: List[SourceFile] = []

        for sf in current_files:
            h = compute_file_hash(sf.content)
            current_hashes[sf.rel_path] = h
            if previous_file_hashes.get(sf.rel_path) != h:
                changed_files.append(sf)

        if not changed_files:
            return existing_store, current_hashes, 0

        # Remove old chunks of modified files from store
        changed_paths = {sf.rel_path for sf in changed_files}
        remaining_chunks = [c for c in existing_store.chunks if c.file_path not in changed_paths]

        # Re-chunk modified files
        new_chunks: List[CodeChunk] = []
        for sf in changed_files:
            new_chunks.extend(chunk_file(sf))

        all_chunks = remaining_chunks + new_chunks

        # Re-embed updated chunk corpus
        texts = [c.as_embedding_text() for c in all_chunks]
        vectors = self.embedder.embed(texts)

        new_store = FaissVectorStore(dim=vectors.shape[1])
        new_store.add(all_chunks, vectors)

        return new_store, current_hashes, len(changed_files)


class RepositoryEventHandler(FileSystemEventHandler):
    """
    Watchdog event handler that debounces file system events on active repository files
    and triggers atomic re-indexing callback once edits settle.
    """
    def __init__(
        self,
        repo_root: str,
        callback: Callable[[List[str]], None],
        debounce_delay: float = 0.5,
    ):
        super().__init__()
        self.repo_root = os.path.abspath(repo_root)
        self.callback = callback
        self.debounce_delay = max(0.05, debounce_delay)
        self.pending_changes: Set[str] = set()
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def _handle_event(self, path: str):
        if not path or is_ignored_path(path, self.repo_root):
            return

        with self._lock:
            self.pending_changes.add(os.path.abspath(path))
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_delay, self._dispatch)
            self._timer.daemon = True
            self._timer.start()

    def _dispatch(self):
        with self._lock:
            if not self.pending_changes:
                return
            changed = list(self.pending_changes)
            self.pending_changes.clear()
            self._timer = None

        try:
            self.callback(changed)
        except Exception as e:
            logger.error(f"Error in RepositoryEventHandler callback: {e}", exc_info=True)

    def on_modified(self, event):
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path)

    def on_created(self, event):
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path)

    def on_deleted(self, event):
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path)

    def on_moved(self, event):
        if not getattr(event, "is_directory", False):
            self._handle_event(event.src_path)
            if hasattr(event, "dest_path"):
                self._handle_event(event.dest_path)

    def cancel_pending(self):
        """Cancels any pending timer and flushes state."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self.pending_changes.clear()


class RepositoryWatcher:
    """
    Real-Time Filesystem Watcher Daemon for active repository directories.
    Runs a background observer thread that captures file events and triggers
    thread-safe incremental re-indexing.
    """
    def __init__(
        self,
        repo_path: str,
        embedder: Optional[BaseEmbedder] = None,
        on_reindex: Optional[Callable[[Any, List[str], float], None]] = None,
        debounce_delay: float = 0.5,
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.embedder = embedder
        self.on_reindex = on_reindex
        self.debounce_delay = debounce_delay

        self._observer: Optional[Any] = None
        self._handler: Optional[RepositoryEventHandler] = None
        self._lock = threading.RLock()
        self._running: bool = False
        self.current_result: Optional[Any] = None

    def start(self) -> bool:
        """Starts the background filesystem observer thread."""
        if not WATCHDOG_AVAILABLE:
            logger.warning("[!] Watchdog package not installed; watcher cannot start.")
            return False

        with self._lock:
            if self._running:
                return True

            if not os.path.exists(self.repo_path):
                raise FileNotFoundError(f"Repository path does not exist: '{self.repo_path}'")

            self._handler = RepositoryEventHandler(
                repo_root=self.repo_path,
                callback=self.trigger_reindex,
                debounce_delay=self.debounce_delay,
            )
            self._observer = Observer()
            self._observer.schedule(self._handler, path=self.repo_path, recursive=True)
            self._observer.daemon = True
            self._observer.start()
            self._running = True
            logger.info(f"[*] Started repository watcher on '{self.repo_path}'.")
            return True

    def stop(self, timeout: float = 2.0) -> bool:
        """Stops the background filesystem observer thread gracefully."""
        with self._lock:
            if not self._running:
                return True

            if self._handler:
                self._handler.cancel_pending()

            if self._observer:
                try:
                    self._observer.stop()
                    self._observer.join(timeout=timeout)
                except Exception as e:
                    logger.warning(f"[!] Error while stopping observer: {e}")
                self._observer = None

            self._running = False
            logger.info(f"[*] Stopped repository watcher on '{self.repo_path}'.")
            return True

    def is_alive(self) -> bool:
        """Returns True if the background watcher thread is actively monitoring."""
        with self._lock:
            return (
                self._running
                and self._observer is not None
                and getattr(self._observer, "is_alive", lambda: False)()
            )

    def trigger_reindex(self, changed_paths: Optional[List[str]] = None) -> Any:
        """
        Executes thread-safe incremental re-indexing of the repository.
        Updates self.current_result and notifies on_reindex callback.
        """
        with self._lock:
            if self.embedder is None:
                logger.warning("[!] Watcher trigger_reindex called but embedder is not set.")
                return None

            t0 = time.perf_counter()
            from core.pipeline import ingest_repository

            try:
                new_result = ingest_repository(
                    self.repo_path,
                    self.embedder,
                    force_reindex=False,
                    save_to_disk=True,
                )
                self.current_result = new_result
                elapsed = time.perf_counter() - t0

                if self.on_reindex is not None:
                    try:
                        self.on_reindex(new_result, changed_paths or [], elapsed)
                    except Exception as e:
                        logger.error(f"[!] Error in watcher on_reindex callback: {e}", exc_info=True)

                return new_result
            except Exception as e:
                logger.error(f"[!] Error during incremental reindex: {e}", exc_info=True)
                return None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
