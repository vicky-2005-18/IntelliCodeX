"""
IntelliCodeX Dynamic Bottom Status Toolbar.

Provides formatted text tokens and plain-text summaries reflecting
active repository, backend/model status, file scope filter, watcher state,
and Prompt-Toolkit toolbar styling.
"""

import os
from typing import Dict, List, Optional, Tuple

from core.cli.state import CLISessionState


def get_status_toolbar_style() -> Dict[str, str]:
    """
    Returns default Prompt-Toolkit style dictionary for the bottom status bar.
    """
    return {
        "bottom-toolbar": "#ffffff bg:#1e1e1e",
        "toolbar.brand": "bold ansicyan",
        "toolbar.label": "bold #888888",
        "toolbar.repo": "bold ansicyan",
        "toolbar.backend": "ansiyellow",
        "toolbar.model": "bold ansimagenta",
        "toolbar.status.online": "bold ansigreen",
        "toolbar.status.offline": "ansiyellow",
        "toolbar.filter": "bold ansiyellow",
        "toolbar.watcher.on": "bold ansigreen",
        "toolbar.watcher.off": "#777777",
        "toolbar.persona": "ansicyan",
        "toolbar.separator": "#555555",
    }


def render_status_toolbar(state: CLISessionState) -> List[Tuple[str, str]]:
    """
    Renders status bar tokens as a list of (style, text) tuples
    compatible with prompt_toolkit.layout.FormattedTextToolbar.
    """
    with state.lock:
        raw_path = state.repo_path or ""
        repo_name = os.path.basename(raw_path.rstrip("/\\")) or raw_path or state.repo_id or "repo"

        file_count: Optional[int] = None
        if state.engine is not None:
            if callable(getattr(state.engine, "get_indexed_files", None)):
                try:
                    f_list = state.engine.get_indexed_files()
                    if isinstance(f_list, (list, tuple, set)):
                        file_count = len(f_list)
                except Exception:
                    pass
            elif hasattr(state.engine, "indexed_files"):
                try:
                    f_list = state.engine.indexed_files
                    if isinstance(f_list, (list, tuple, set)):
                        file_count = len(f_list)
                except Exception:
                    pass

        if file_count is not None and file_count > 0:
            repo_text = f"{repo_name} ({file_count} files)"
        else:
            repo_text = repo_name

        backend = state.backend or "tfidf"
        is_online = backend.lower() == "ollama" or (state.llm is not None and backend.lower() != "tfidf")
        model_name = state.model_name or "none"
        persona = state.persona or "general"
        file_filter = state.active_file_filter

        watcher_active = False
        if state.watcher is not None:
            try:
                if callable(getattr(state.watcher, "is_alive", None)):
                    watcher_active = bool(state.watcher.is_alive())
                else:
                    watcher_active = True
            except Exception:
                watcher_active = False

    tokens: List[Tuple[str, str]] = []

    # 1. Brand badge
    tokens.append(("class:toolbar.brand ansicyan bold", "[IntelliCodeX] "))

    # 2. Repo
    tokens.append(("class:toolbar.label bold", "Repo: "))
    tokens.append(("class:toolbar.repo ansicyan", repo_text))

    # 3. Backend & online/offline status
    tokens.append(("class:toolbar.separator", " | "))
    tokens.append(("class:toolbar.label bold", "Backend: "))
    tokens.append(("class:toolbar.backend ansiyellow", backend))
    if is_online:
        tokens.append(("class:toolbar.status.online ansigreen bold", " (online)"))
    else:
        tokens.append(("class:toolbar.status.offline ansiyellow", " (offline)"))

    # 4. Model
    tokens.append(("class:toolbar.separator", " | "))
    tokens.append(("class:toolbar.label bold", "Model: "))
    tokens.append(("class:toolbar.model ansimagenta bold", model_name))

    # 5. Persona (if defined)
    if persona:
        tokens.append(("class:toolbar.separator", " | "))
        tokens.append(("class:toolbar.label bold", "Persona: "))
        tokens.append(("class:toolbar.persona ansicyan", persona))

    # 6. File filter scope (only when set)
    if file_filter:
        tokens.append(("class:toolbar.separator", " | "))
        tokens.append(("class:toolbar.label bold", "Filter: "))
        tokens.append(("class:toolbar.filter ansiyellow bold", file_filter))

    # 7. Watcher status badge
    tokens.append(("class:toolbar.separator", " | "))
    tokens.append(("class:toolbar.label bold", "Watcher: "))
    if watcher_active:
        tokens.append(("class:toolbar.watcher.on ansigreen bold", "Active"))
    else:
        tokens.append(("class:toolbar.watcher.off ansiyellow", "Inactive"))

    return tokens


def format_status_summary(state: CLISessionState) -> str:
    """
    Returns plain text representation of the toolbar for headless testing and diagnostics.
    """
    tokens = render_status_toolbar(state)
    return "".join(text for _, text in tokens).strip()
