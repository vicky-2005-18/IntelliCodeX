"""
Fix Command Handler for IntelliCodeX CLI.

Manages automated bug diagnosis, candidate patch generation,
interactive diff review with sandbox testing, and proposal approvals/rejections.
"""

import logging
import os
import re
import time
from typing import Any, Tuple

from core.cli.commands.base import CommandHandler
from core.cli.state import CLISessionState
from core.cli.ui.diff_viewer import render_interactive_diff, render_patch_card

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


class FixHandler(CommandHandler):
    """
    Handles bug fix, repair, patch review, approval, and rejection commands:
    fix:, review, proposals, approve, reject.
    """

    FIX_EXACT_COMMANDS = {
        "review",
        "proposals",
        "patches:pending",
    }

    FIX_PREFIX_COMMANDS = (
        "fix:",
        "fix ",
        "review ",
        "approve ",
        "reject ",
        "patch:",
        "patch ",
    )

    def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
        low = raw_input.strip().lower()
        if low in self.FIX_EXACT_COMMANDS:
            return True
        if any(low.startswith(p) for p in self.FIX_PREFIX_COMMANDS):
            return True
        return False

    def handle(self, raw_input: str, state: CLISessionState) -> Any:
        low = raw_input.strip().lower()

        # 1. review / proposals list
        if low in self.FIX_EXACT_COMMANDS:
            try:
                from backend.database.mongo import db_manager
                proposals = db_manager.find("generated_patches", {"status": "pending"})
                filtered = [p for p in proposals if p.get("repo_id") == state.repo_id]
                if not filtered:
                    print(f"\n[*] No pending patch proposals awaiting review for active repository.\n")
                else:
                    print(f"\n[*] Pending Patch Proposals ({len(filtered)} awaiting review):")
                    for idx, p in enumerate(filtered, 1):
                        p_id = p.get("patch_id", "unknown")
                        tgt = p.get("target_file", "unknown")
                        print(f"  [{idx}] ID: {p_id} | Target: {tgt} | {p.get('explanation', '')[:60]}")
                    print("\nCommands: review <id>, approve <id>, reject <id>\n")
            except Exception as err:
                print(f"\n[*] Patch proposals: {err}\n")
            return True

        # 2. review <id>
        if low.startswith("review "):
            p_arg = raw_input.split(maxsplit=1)[1].strip()
            try:
                from backend.database.mongo import db_manager
                candidates = db_manager.find("generated_patches", {})
                matched = [p for p in candidates if p.get("patch_id", "").startswith(p_arg)]
                if not matched:
                    print(f"[!] Proposal '{p_arg}' not found.\n")
                else:
                    render_patch_card(matched[0], fix_time=0.0)
            except Exception as err:
                print(f"[!] Error viewing proposal: {err}\n")
            return True

        # 3. approve <id>
        if low.startswith("approve "):
            p_arg = raw_input.split(maxsplit=1)[1].strip()
            try:
                from core.patch_generator import PatchEngine
                engine_store = getattr(state.engine, "store", None)
                patch_engine = PatchEngine(
                    engine_store,
                    state.embedder,
                    state.llm,
                    graph=getattr(state.engine, "dep_graph", None),
                    repo_path=state.repo_path,
                )
                updated = patch_engine.update_patch_status(p_arg, status="applied", user="cli_developer")
                print(f"[+] Approved patch '{p_arg}'.\n")
            except Exception as err:
                print(f"[!] Error approving proposal: {err}\n")
            return True

        # 4. reject <id>
        if low.startswith("reject "):
            p_arg = raw_input.split(maxsplit=1)[1].strip()
            try:
                from core.patch_generator import PatchEngine
                engine_store = getattr(state.engine, "store", None)
                patch_engine = PatchEngine(
                    engine_store,
                    state.embedder,
                    state.llm,
                    graph=getattr(state.engine, "dep_graph", None),
                    repo_path=state.repo_path,
                )
                patch_engine.update_patch_status(p_arg, status="rejected", user="cli_developer")
                print(f"[-] Rejected proposal '{p_arg}'.\n")
            except Exception as err:
                print(f"[!] Error rejecting proposal: {err}\n")
            return True

        # 5. fix: @<file> <error> or patch:
        err_input = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
        clean_err, mention_f = parse_mention(err_input)
        target_file = mention_f or state.active_file_filter or ""

        try:
            from core.patch_generator import PatchEngine
            from core.sandbox_runner import SandboxRunner

            sb_runner = SandboxRunner(
                sandbox_mode="docker",
                docker_image="intellicodex-sandbox:latest",
                allow_local_sandbox=True,
                is_admin=True,
            )

            patch_engine = PatchEngine(
                getattr(state.engine, "store", None),
                state.embedder,
                state.llm,
                graph=getattr(state.engine, "dep_graph", None),
                repo_path=state.repo_path,
                sandbox_runner=sb_runner,
                is_admin=True,
                allow_local_sandbox=True,
            )

            print(f"\n[*] Generating candidate patch for '{target_file or state.repo_path}'...")
            t0 = time.perf_counter()
            patch_rec = patch_engine.generate_patch(
                repo_id=state.repo_id,
                error_report=clean_err or err_input,
                target_file=target_file,
                verify_in_sandbox=True,
                max_iterations=3,
            )
            render_interactive_diff(patch_rec)
        except Exception as err:
            logger.error("Fix handler error: %s", err, exc_info=True)
            print(f"[!] Error during fix generation: {err}\n")

        return True

