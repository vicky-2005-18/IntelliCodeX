"""
Query Command Handler for IntelliCodeX CLI.

Manages semantic search, explain retrieval inspections,
and natural-language Q&A reasoning against repository indexes.
"""

import logging
import re
import time
from typing import Any, Tuple

from core.cli.commands.base import CommandHandler
from core.cli.state import CLISessionState
from core.cli.ui.streamer import TokenStreamer, render_markdown_panel

logger = logging.getLogger(__name__)


def parse_mention(query: str) -> Tuple[str, str]:
    """Extracts @filename mention from query and returns (cleaned_query, filename)."""
    m_quoted = re.search(r'@["\']([^"\']+)["\']', query)
    if m_quoted:
        filename = m_quoted.group(1).replace("\\", "/")
        cleaned_query = query.replace(m_quoted.group(0), "").strip()
        cleaned_query = re.sub(r'\s+', ' ', cleaned_query)
        return cleaned_query, filename

    match = re.search(r'@([\w\-.\/\\]+)', query)
    if match:
        raw_token = match.group(1)
        filename = raw_token.rstrip(".,:;!?").replace("\\", "/")
        cleaned_query = query.replace(f"@{raw_token}", "").strip()
        cleaned_query = re.sub(r'\s+', ' ', cleaned_query)
        return cleaned_query, filename
    return query, ""


class QueryHandler(CommandHandler):
    """
    Handles search:, explain:, and natural-language Q&A questions.
    """

    QUESTION_STARTERS = {
        "what",
        "how",
        "why",
        "where",
        "who",
        "which",
        "when",
        "can",
        "could",
        "is",
        "are",
        "does",
        "do",
        "will",
        "would",
        "should",
        "tell",
        "explain",
        "describe",
        "show",
        "find",
    }

    def __init__(self, fallback: bool = False) -> None:
        self.fallback = fallback

    def _is_question(self, text: str) -> bool:
        t = text.strip()
        if not t:
            return False
        if t.endswith("?"):
            return True
        first_word = t.split()[0].lower().rstrip("?:,.")
        if first_word in self.QUESTION_STARTERS:
            return True
        if first_word.startswith("@") and len(t.split()) > 1:
            second_word = t.split()[1].lower().rstrip("?:,.")
            if second_word in self.QUESTION_STARTERS or t.endswith("?"):
                return True
        return False

    def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
        stripped = raw_input.strip()
        low = stripped.lower()

        if low.startswith("explain:") or low.startswith("explain "):
            return True
        if low.startswith("search:") or low.startswith("search "):
            return True
        if self._is_question(stripped):
            return True
        if self.fallback:
            return True
        return False

    def handle(self, raw_input: str, state: CLISessionState) -> Any:
        stripped = raw_input.strip()
        low = stripped.lower()

        # 1. Search command: search: <query>
        if low.startswith("search:") or low.startswith("search "):
            sq = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
            if not sq:
                print("[!] Usage: search:<query>\n")
                return True

            t0 = time.perf_counter()
            try:
                results = state.engine.retrieve_expanded(sq, top_k=8) if state.engine else []
                elapsed = time.perf_counter() - t0
                try:
                    from cli import render_search_results
                    render_search_results(sq, results, elapsed)
                except Exception:
                    print(f"\n[*] Search results for '{sq}' ({len(results)} found in {elapsed:.2f}s):")
                    for idx, c in enumerate(results[:5], 1):
                        print(f"  [{idx}] {getattr(c, 'file_path', '')}: {getattr(c, 'content', '')[:100]}...")
                    print()
            except Exception as err:
                print(f"[!] Search error: {err}\n")
            return True

        # 2. Explain command: explain: <query>
        if low.startswith("explain:") or low.startswith("explain "):
            eq = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
            try:
                from cli import execute_explain_command
                execute_explain_command(state.engine, getattr(state.engine, "result", None), eq, active_file_filter=state.active_file_filter)
            except Exception:
                try:
                    results = state.engine.retrieve_expanded(eq, top_k=5, file_filter=state.active_file_filter) if state.engine else []
                    print(f"\n[*] Explain Retrieval for '{eq}' ({len(results)} chunks):\n")
                    for idx, c in enumerate(results, 1):
                        print(f"  [{idx}] {getattr(c, 'file_path', '')}: {getattr(c, 'content', '')[:120]}...")
                    print()
                except Exception as err:
                    print(f"[!] Explain error: {err}\n")
            return True

        # 3. Question answering
        cleaned_query, mention_file = parse_mention(stripped)
        effective_file_filter = mention_file if mention_file else state.active_file_filter

        try:
            if state.engine is not None and callable(getattr(state.engine, "ask", None)):
                ans_dict = state.engine.ask(cleaned_query, file_filter=effective_file_filter)
                ans_text = ans_dict.get("answer", "") if isinstance(ans_dict, dict) else str(ans_dict)
                render_markdown_panel(ans_text, title=f"Answer ({state.model_name})")
            else:
                print(f"\n[*] Query processed for '{cleaned_query}'. (Engine offline)\n")
        except Exception as err:
            logger.error("Query answering error: %s", err, exc_info=True)
            print(f"[!] Error answering query: {err}\n")

        return True
