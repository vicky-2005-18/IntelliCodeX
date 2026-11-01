"""
Repo Command Handler for IntelliCodeX CLI.

Manages repository metadata, indexed file listings, chunk inspections,
index statistics, and repository switching.
"""

import logging
import os
from typing import Any, List

from core.cli.commands.base import CommandHandler
from core.cli.state import CLISessionState

logger = logging.getLogger(__name__)


class RepoHandler(CommandHandler):
    """
    Handles repository commands: files, ls, index-stats, chunks:, repos, repo:.
    """

    REPO_EXACT_COMMANDS = {
        "files",
        "ls",
        "index-stats",
        "index_stats",
        "indexstats",
        "stats",
        "repos",
        "list-repos",
        "list repos",
        "show repos",
    }

    REPO_PREFIX_COMMANDS = (
        "chunks:",
        "chunks ",
        "repo:",
        "repo ",
        "repo remove",
        "repo:remove",
        "use ",
        "ingest ",
    )

    def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
        low = raw_input.strip().lower()
        if low in self.REPO_EXACT_COMMANDS:
            return True
        if any(low.startswith(p) for p in self.REPO_PREFIX_COMMANDS):
            return True
        return False

    def handle(self, raw_input: str, state: CLISessionState) -> Any:
        low = raw_input.strip().lower()

        # 1. files / ls
        if low in ("files", "ls"):
            chunks = getattr(getattr(state.engine, "store", None), "chunks", [])
            indexed_files: List[str] = sorted(list(set(getattr(c, "file_path", str(c)) for c in chunks)))
            try:
                from cli import render_files_table
                render_files_table(indexed_files)
            except Exception:
                print(f"\n[*] Indexed files ({len(indexed_files)}):")
                for f in indexed_files:
                    print(f"  - {f}")
                print()
            return True

        # 2. index-stats
        if low in ("index-stats", "index_stats", "indexstats", "stats"):
            try:
                from cli import render_index_stats
                res = getattr(state.engine, "result", None)
                if res is None:
                    class _DummyResult:
                        store = getattr(state.engine, "store", None)
                    res = _DummyResult()
                render_index_stats(res, state.embedder)
            except Exception:
                chunks = getattr(getattr(state.engine, "store", None), "chunks", [])
                print(f"\n[*] Index Statistics:")
                print(f"  - Total chunks: {len(chunks)}")
                print(f"  - Active backend: {state.backend}")
                print(f"  - Model: {state.model_name}\n")
            return True

        # 3. chunks: <file>
        if low.startswith("chunks:") or low.startswith("chunks "):
            target_f = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
            try:
                from cli import render_chunks_view
                res = getattr(state.engine, "result", None)
                render_chunks_view(res, target_f, state.repo_path)
            except Exception:
                chunks = getattr(getattr(state.engine, "store", None), "chunks", [])
                matching = [c for c in chunks if target_f.lower() in getattr(c, "file_path", "").lower()]
                print(f"\n[*] Chunks for '{target_f}' ({len(matching)} found):\n")
                for idx, c in enumerate(matching[:5], 1):
                    content = getattr(c, "content", "")[:120].replace("\n", " ")
                    print(f"  [{idx}] {getattr(c, 'file_path', '')} -> {content}...")
                print()
            return True

        # 4. repos / list-repos
        if low in ("repos", "list-repos", "list repos", "show repos"):
            try:
                from cli import get_available_repos, render_repos_table
                avail = get_available_repos(state.repo_path)
                render_repos_table(avail, state.repo_path)
            except Exception:
                print(f"\n[*] Active Repository: {state.repo_path} ({state.repo_id})\n")
            return True

        # 5. repo remove
        if low.startswith("repo remove") or low.startswith("repo:remove"):
            target_arg = raw_input[len("repo remove"):].strip() if "remove " in raw_input else raw_input.split(":", 1)[-1].strip()
            try:
                from cli import handle_repo_remove
                handle_repo_remove(target_arg, state.repo_path)
            except Exception as err:
                print(f"[!] Error removing repository: {err}")
            return True

        # 6. repo <path_or_id> / use / ingest
        target = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
        if target:
            state.switch_repo(target)
            print(f"\n[*] Switched active repository to '{state.repo_path}'.\n")
        return True
