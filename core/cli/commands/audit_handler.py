"""
Audit Command Handler for IntelliCodeX CLI.

Manages security vulnerability scans, dependency graph impact analysis,
call graph symbol queries, architecture optimization reports, and centrality rankings.
"""

import logging
import os
import time
from typing import Any

from core.cli.commands.base import CommandHandler
from core.cli.state import CLISessionState

logger = logging.getLogger(__name__)


class AuditHandler(CommandHandler):
    """
    Handles security, architecture, dependency, caller, and centrality commands:
    security:, arch, deps:, callers:, top.
    """

    AUDIT_EXACT_COMMANDS = {
        "arch",
        "cycles",
        "optimize",
        "architecture",
        "top",
        "centrality",
        "hooks:status",
        "hooks:check",
        "hooks:install",
        "hooks:uninstall",
        "hooks",
    }

    AUDIT_PREFIX_COMMANDS = (
        "security:",
        "security ",
        "deps:",
        "deps ",
        "callers:",
        "callers ",
    )

    def can_handle(self, raw_input: str, state: CLISessionState) -> bool:
        low = raw_input.strip().lower()
        if low in self.AUDIT_EXACT_COMMANDS:
            return True
        if any(low.startswith(p) for p in self.AUDIT_PREFIX_COMMANDS):
            return True
        return False

    def handle(self, raw_input: str, state: CLISessionState) -> Any:
        low = raw_input.strip().lower()

        # 1. Security Scan: security:<file>
        if low.startswith("security:") or low.startswith("security "):
            sec_target = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
            from core.security_scanner import run_security_scan, format_security_report

            if sec_target in ("", ".", "repo", "all"):
                abs_sec = state.repo_path
            else:
                abs_sec = os.path.join(state.repo_path, sec_target) if not os.path.isabs(sec_target) else sec_target

            sec_result = run_security_scan(abs_sec, repo_root=state.repo_path, severity_threshold="HIGH")
            sec_report = format_security_report(sec_result, llm=state.llm)

            try:
                from rich.console import Console
                from rich.panel import Panel
                Console().print(Panel(sec_report, title=f"[bold red]Security Scan: {sec_target or '.'}[/bold red]", border_style="red"))
            except Exception:
                print(f"\n{sec_report}\n")
            return True

        # 2. Architecture Analysis: arch / cycles / optimize
        if low in ("arch", "cycles", "optimize", "architecture"):
            try:
                from core.architecture_optimizer import ArchitectureOptimizer
                optimizer = ArchitectureOptimizer()
                dep_graph = getattr(state.engine, "dep_graph", None)
                arch_report = optimizer.analyze(
                    dep_graph=dep_graph,
                    llm=state.llm,
                    repo_id=state.repo_id,
                    snapshot_id="cli_session",
                )
                md = arch_report.format_markdown() if hasattr(arch_report, "format_markdown") else str(arch_report)
                from core.cli.ui.streamer import render_markdown_panel
                render_markdown_panel(md, title="Architecture Optimization Report")
            except Exception as err:
                print(f"\n[*] Architecture Optimization Report:")
                print(f"  - Repository: {state.repo_path}")
                print(f"  - Status: {err}\n")
            return True

        # 3. Dependencies impact: deps:<target>
        if low.startswith("deps:") or low.startswith("deps "):
            target = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
            from core.dependency_graph import files_likely_affected_by
            dep_graph = getattr(state.engine, "dep_graph", None)
            affected = files_likely_affected_by(dep_graph, target) if dep_graph else []
            try:
                from cli import render_deps_panel
                render_deps_panel(target, affected, 0.0)
            except Exception:
                print(f"\n[*] Files likely affected by changes in '{target}' ({len(affected)}):")
                for af in affected:
                    print(f"  - {af}")
                print()
            return True

        # 4. Symbol Callers: callers:<symbol>
        if low.startswith("callers:") or low.startswith("callers "):
            symbol_target = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
            from core.call_graph import find_callers_of_symbol
            call_g = getattr(state.engine, "call_graph", None)
            callers = find_callers_of_symbol(call_g, symbol_target) if call_g else []
            try:
                from cli import render_callers_panel
                render_callers_panel(symbol_target, callers, 0.0)
            except Exception:
                print(f"\n[*] Callers of symbol '{symbol_target}' ({len(callers)}):")
                for c in callers:
                    print(f"  - {c}")
                print()
            return True

        # 5. Centrality Rankings: top / centrality
        if low in ("top", "centrality"):
            from core.dependency_graph import get_top_central_files
            from core.call_graph import get_top_central_symbols
            dep_g = getattr(state.engine, "dep_graph", None)
            call_g = getattr(state.engine, "call_graph", None)
            top_files = get_top_central_files(dep_g, top_n=5) if dep_g else []
            top_syms = get_top_central_symbols(call_g, top_n=5) if call_g else None
            try:
                from cli import render_centrality_tables
                render_centrality_tables(top_files, top_syms)
            except Exception:
                print(f"\n[*] Top Central Files (PageRank):")
                for fp, sc in top_files:
                    print(f"  - {fp}: {sc:.4f}")
                if top_syms:
                    print(f"[*] Top Central Symbols (Call Graph):")
                    for sym, sc in top_syms:
                        print(f"  - {sym}: {sc:.4f}")
                print()
            return True

        return False
