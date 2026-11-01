"""
IntelliCodeX Central CLI Session State Management.

Encapsulates active repository, model/backend status, query engine,
active file scope filter, watcher process references, and thread synchronization.
"""

from dataclasses import dataclass, field
import logging
import os
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class CLISessionState:
    """
    Central thread-safe session state for the interactive IntelliCodeX CLI.
    """
    repo_path: str
    repo_id: str
    backend: str
    model_name: str
    embedder: Any
    llm: Optional[Any]
    engine: Any
    watcher: Optional[Any] = None
    active_file_filter: Optional[str] = None
    persona: str = "general"
    memory: Optional[Any] = None
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.repo_id:
            try:
                from core.persistence import get_repo_id
                self.repo_id = get_repo_id(self.repo_path)
            except Exception:
                self.repo_id = os.path.basename(os.path.abspath(self.repo_path)) or "repo"

        if self.memory is None and self.engine is not None and hasattr(self.engine, "memory"):
            self.memory = getattr(self.engine, "memory")

    @property
    def lock(self) -> threading.RLock:
        """Returns reentrant thread lock for state synchronization."""
        return self._lock

    def switch_repo(
        self,
        new_path: str,
        new_repo_id: Optional[str] = None,
        engine: Optional[Any] = None,
        embedder: Optional[Any] = None,
        llm: Optional[Any] = None,
    ) -> None:
        """
        Dynamically switches active repository, tearing down active watcher and resetting filters.
        """
        with self._lock:
            if self.watcher is not None:
                try:
                    if callable(getattr(self.watcher, "stop", None)):
                        self.watcher.stop()
                except Exception as err:
                    logger.debug("Error stopping watcher during repo switch: %s", err)
                self.watcher = None

            self.repo_path = new_path
            if new_repo_id:
                self.repo_id = new_repo_id
            else:
                try:
                    from core.persistence import get_repo_id
                    self.repo_id = get_repo_id(new_path)
                except Exception:
                    self.repo_id = os.path.basename(os.path.abspath(new_path)) or "repo"

            if engine is not None:
                self.engine = engine
                if hasattr(engine, "memory"):
                    self.memory = engine.memory
            elif self.engine is not None and hasattr(self.engine, "repo_path"):
                self.engine.repo_path = new_path

            if embedder is not None:
                self.embedder = embedder

            if llm is not None:
                self.llm = llm

            self.active_file_filter = None

    def switch_backend(self, backend: str) -> None:
        """
        Switches LLM & embedder backend (e.g. 'ollama' vs 'tfidf').
        """
        with self._lock:
            self.backend = backend

    def switch_model(self, model_name: str) -> None:
        """
        Switches LLM model name and notifies downstream LLM driver if present.
        """
        with self._lock:
            self.model_name = model_name
            if self.llm is not None:
                if callable(getattr(self.llm, "set_model", None)):
                    self.llm.set_model(model_name)
                elif hasattr(self.llm, "model"):
                    self.llm.model = model_name

    def set_file_filter(self, filter_str: Optional[str]) -> None:
        """
        Sets or clears the active file filter scope.
        """
        with self._lock:
            if filter_str is not None:
                cleaned = filter_str.strip()
                self.active_file_filter = cleaned if cleaned else None
            else:
                self.active_file_filter = None

    def set_persona(self, persona: str) -> None:
        """
        Sets system persona ('general', 'security', 'optimizer', etc.) and updates engine.
        """
        with self._lock:
            self.persona = persona
            if self.engine is not None and callable(getattr(self.engine, "set_persona", None)):
                try:
                    self.engine.set_persona(persona)
                except Exception as err:
                    logger.debug("Error setting engine persona: %s", err)

    def set_watcher(self, watcher: Optional[Any]) -> None:
        """
        Safely registers new watcher instance, stopping any previous running watcher.
        """
        with self._lock:
            if self.watcher is not None and self.watcher is not watcher:
                try:
                    if callable(getattr(self.watcher, "stop", None)):
                        self.watcher.stop()
                except Exception as err:
                    logger.debug("Error stopping old watcher: %s", err)
            self.watcher = watcher
            if watcher is not None:
                try:
                    from core.cli.terminal_safety import register_active_watcher
                    register_active_watcher(watcher)
                except Exception:
                    pass

    def get_summary(self) -> Dict[str, Any]:
        """
        Returns a dictionary summary of active CLI session parameters.
        """
        with self._lock:
            if self.watcher is not None:
                if callable(getattr(self.watcher, "is_alive", None)):
                    watcher_active = bool(self.watcher.is_alive())
                else:
                    watcher_active = True
            else:
                watcher_active = False

            hybrid = getattr(self.engine, "hybrid_search", None)

            return {
                "repo_path": self.repo_path,
                "repo_id": self.repo_id,
                "backend": self.backend,
                "model_name": self.model_name,
                "active_file_filter": self.active_file_filter,
                "persona": self.persona,
                "watcher_active": watcher_active,
                "hybrid_search": hybrid,
                "has_llm": self.llm is not None,
                "has_embedder": self.embedder is not None,
                "has_engine": self.engine is not None,
            }
