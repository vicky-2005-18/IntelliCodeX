"""
Contextual Suggestion Engine for IntelliCodeX CLI.

Provides at most two actionable, high-relevance next-step suggestions after ordinary Q&A
ONLY when an observable issue or workflow intent mismatch occurs:
1. No retrieved evidence (0 chunks found).
2. Unresolved target (@mention does not exist in repository).
3. Insufficient context or explicitly reported answer limitation.
4. Workflow intent mismatch (e.g. user asks how to run a file, how to create a file,
   or asks to identify bugs when an automated workflow command is available).

Invariants:
- At most two suggestions.
- Commands are strictly valid entries from the IntelliCodeX command registry.
- Targets are real repository paths; filenames with spaces are preserved with quotes (e.g. @"to do.java").
- Never automatically executes suggestions.
- Respects read-only constraints ("do not modify files").
- Never invents numeric confidence/quality scores.
- Returns empty list [] on normal successful answers with sufficient context.
"""

import os
import re
from typing import Any, List, Optional, Tuple


def format_suggested_target(file_path: str) -> str:
    """Formats file path for command suggestions, wrapping in quotes if spaces are present."""
    clean = file_path.replace("\\", "/").strip()
    if " " in clean:
        return f'@"{clean}"'
    return f"@{clean}"


def generate_contextual_suggestions(
    query: str,
    answer: str,
    retrieved_chunks: List[Any],
    effective_file_filter: Optional[str] = None,
    current_path: str = "",
    candidate_files: Optional[List[str]] = None,
    unverified_files: Optional[List[str]] = None,
    unverified_symbols: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """
    Evaluates ordinary Q&A interaction and returns at most two actionable command suggestions
    if an observable issue or workflow intent mismatch is detected.
    Returns [] if the query succeeded normally without any observable issues.
    """
    clean_query = query.strip()
    clean_answer = (answer or "").strip()
    suggestions: List[Tuple[str, str]] = []

    # Check for read-only constraint
    no_modify = bool(
        re.search(
            r"\b(?:do\s+not\s+modify|don\'t\s+modify|no\s+changes|read\s*only|dry\s*run|do\s+not\s+change|leave\s+unchanged)\b",
            clean_query,
            re.IGNORECASE,
        )
    )

    # -------------------------------------------------------------------------
    # 1. Workflow Intent Mismatch: Intent is clear but user used ordinary Q&A
    # -------------------------------------------------------------------------

    # 1A. Execution Intent: "How do I run this?", "how to run @file", "execute this"
    # Invariant: Must NOT automatically run the file. Offer run: command.
    is_run_query = bool(
        re.search(
            r"\b(?:how\s+(?:do\s+i|to|can\s+i|we)\s+run|how\s+to\s+execute|how\s+do\s+i\s+start|run\s+this|launch\s+this)\b",
            clean_query,
            re.IGNORECASE,
        )
    )
    if is_run_query:
        target_file = effective_file_filter
        if not target_file and candidate_files:
            # Check if query mentions a candidate file basename
            for f in candidate_files:
                base = os.path.basename(f)
                if base.lower() in clean_query.lower():
                    target_file = f
                    break

        if target_file:
            ext = os.path.splitext(target_file)[1].lower()
            if ext in (".java", ".py", ".js", ".mjs", ".cjs"):
                tgt_fmt = format_suggested_target(target_file)
                suggestions.append(
                    (f"run: {tgt_fmt}", "Interactively run this file inside isolated Docker container")
                )
                suggestions.append(
                    (f"info:{target_file}", "Inspect file size, chunks, and call graph centrality")
                )
                return suggestions[:2]

    # 1B. Review / Bug Identification Intent: "Identify bugs", "find bugs", "any bug in @file"
    # Invariant: Must NOT automatically run fix:. Distinguish review from repair.
    # If "do not modify files" is present, offer read-only security scan instead of fix:.
    is_bug_intent = bool(
        re.search(
            r"\b(?:identify\s+bugs?|find\s+bugs?|any\s+bugs?|check\s+for\s+bugs?|spot\s+bugs?|review\s+(?:code|for\s+bugs?))\b",
            clean_query,
            re.IGNORECASE,
        )
    )
    if is_bug_intent:
        target_file = effective_file_filter
        if target_file:
            tgt_fmt = format_suggested_target(target_file)
            if no_modify:
                suggestions.append(
                    (f"explain: review {tgt_fmt}", "Inspect retrieval context and prompt details for this file without making changes")
                )
                suggestions.append(
                    (f"chunks:{target_file}", "Inspect chunk-level index, line ranges & vector preview")
                )
            else:
                suggestions.append(
                    (f"explain: review {tgt_fmt}", "Inspect retrieval context and prompt details for this file without making changes")
                )
                suggestions.append(
                    (f"fix: {tgt_fmt}", "(Optional) Generate an automated sandbox code patch if you want to apply fixes")
                )
            return suggestions[:2]

    # 1C. Creation Intent: "create new TodoApp.java", "write a calculator in python"
    # Invariant: Offer create: workflow command with task and target.
    m_create = re.search(
        r"\b(?:create|write|implement|build)\s+(?:a\s+new\s+)?([A-Za-z0-9_\-\.\/ ]+\.(?:java|py))\b",
        clean_query,
        re.IGNORECASE,
    )
    if m_create and not no_modify:
        target_candidate = m_create.group(1).strip()
        task_text = re.sub(
            r"\b(?:create|write|implement|build)\s+(?:a\s+new\s+)?" + re.escape(target_candidate),
            "",
            clean_query,
            flags=re.IGNORECASE,
        ).strip()
        task_text = task_text or f"Implement {target_candidate}"
        suggestions.append(
            (f"create: {task_text} Target: {target_candidate}", "Explicit new-file creation workflow with sandbox validation")
        )
        suggestions.append(
            ("files", "List existing repository files to verify target does not already exist")
        )
        return suggestions[:2]

    # 1D. Search / Definition Lookup Intent: "where is function X", "find references to Y"
    is_search_intent = bool(
        re.search(
            r"\b(?:where\s+is|find\s+references\s+to|locate\s+definition\s+of|search\s+for)\b",
            clean_query,
            re.IGNORECASE,
        )
    )
    if is_search_intent and not clean_query.lower().startswith("search:"):
        m_sym = re.search(
            r"\b(?:where\s+is|references\s+to|definition\s+of|search\s+for)\s+([A-Za-z0-9_]+)",
            clean_query,
            re.IGNORECASE,
        )
        sym = m_sym.group(1) if m_sym else clean_query.split()[-1]
        suggestions.append(
            (f"search:{sym}", "Instant lexical & semantic search without LLM wait")
        )
        suggestions.append(
            (f"callers:{sym}", f"Find all AST call sites calling '{sym}' across repository")
        )
        return suggestions[:2]

    # -------------------------------------------------------------------------
    # 2. Observable Issue: No Retrieved Evidence (0 chunks found)
    # -------------------------------------------------------------------------
    if len(retrieved_chunks) == 0:
        if effective_file_filter:
            suggestions.append(
                ("files", "List all indexed repository source files to verify exact filename")
            )
            # Remove punctuation for clean search term
            clean_term = re.sub(r"[^\w\s]", " ", clean_query).strip()
            term = clean_term.split()[0] if clean_term else "code"
            suggestions.append(
                (f"search:{term}", "Run instant search for this keyword across indexed chunks")
            )
        else:
            clean_term = re.sub(r"[^\w\s]", " ", clean_query).strip()
            term = clean_term.split()[0] if clean_term else "code"
            suggestions.append(
                (f"search:{term}", "Run instant lexical search to find keyword occurrences")
            )
            suggestions.append(
                ("index-stats", "Display overall repository index statistics across files")
            )
        return suggestions[:2]

    # -------------------------------------------------------------------------
    # 3. Observable Issue: Unresolved Target
    # -------------------------------------------------------------------------
    if effective_file_filter and candidate_files:
        norm_filter = effective_file_filter.replace("\\", "/").lower()
        matched = [
            f for f in candidate_files
            if norm_filter == f.lower()
            or norm_filter == os.path.basename(f).lower()
            or f.lower().endswith("/" + norm_filter)
        ]
        if not matched:
            suggestions.append(
                ("files", f"List all indexed repository source files to locate '{effective_file_filter}'")
            )
            base_kw = os.path.splitext(os.path.basename(effective_file_filter))[0]
            suggestions.append(
                (f"search:{base_kw}", f"Search repository for references to '{base_kw}'")
            )
            return suggestions[:2]

    # -------------------------------------------------------------------------
    # 4. Observable Issue: Insufficient Context or Reported Answer Limitation
    # -------------------------------------------------------------------------
    limitation_patterns = [
        r"\bnot\s+(?:shown|found|available|provided)\s+in\s+the\s+(?:provided\s+)?context\b",
        r"\bcontext\s+does\s+not\s+(?:contain|show|include|provide)\b",
        r"\binsufficient\s+context\b",
        r"\bimplementation\s+is\s+not\s+(?:available|shown|provided)\b",
        r"\bonly\s+(?:shows|provides)\s+the\s+(?:declaration|signature|interface)\b",
        r"\bcannot\s+(?:determine|verify|confirm)\s+from\s+the\s+(?:given\s+)?context\b",
    ]
    has_reported_limitation = any(
        re.search(pat, clean_answer, re.IGNORECASE) for pat in limitation_patterns
    )

    if unverified_files:
        uv_file = unverified_files[0]
        base_uv = os.path.basename(uv_file)
        suggestions.append(
            (f"search:{base_uv}", f"Search repository for '{base_uv}' to locate true path")
        )
        suggestions.append(
            ("files", "List all indexed repository source files")
        )
        return suggestions[:2]

    if unverified_symbols:
        uv_sym = unverified_symbols[0]
        suggestions.append(
            (f"callers:{uv_sym}", f"Find AST call sites for unverified symbol '{uv_sym}'")
        )
        suggestions.append(
            (f"search:{uv_sym}", f"Search repository for occurrences of '{uv_sym}'")
        )
        return suggestions[:2]

    if has_reported_limitation:
        if effective_file_filter:
            suggestions.append(
                (f"chunks:{effective_file_filter}", "Inspect chunk-level index, line ranges & vector preview")
            )
            suggestions.append(
                (f"deps:{effective_file_filter}", "View direct & reverse dependencies for this file")
            )
        else:
            clean_term = re.sub(r"[^\w\s]", " ", clean_query).strip()
            term = clean_term.split()[0] if clean_term else "code"
            suggestions.append(
                (f"search:{term}", "Run instant lexical search to find additional occurrences")
            )
            suggestions.append(
                ("index-stats", "Inspect repository chunk distribution across files")
            )
        return suggestions[:2]

    # -------------------------------------------------------------------------
    # 5. Normal Successful Answer: Do NOT show suggestions on ordinary success
    # -------------------------------------------------------------------------
    return []
