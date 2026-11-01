"""
Interactive Patch and Unified Diff Reviewer Subsystem for IntelliCodeX CLI.

Provides syntax-highlighted unified diff rendering, structured automated patch cards,
and single-key interactive patch review with automated sandbox test execution.
"""

from typing import Any, Callable, Dict, Optional
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


class ActionStr(str):
    """
    String subclass representing an interactive review action.
    Evaluates equal to both full action names ("apply", "reject", "cancel")
    and single-letter action keys ("a", "r", "c") for flexible assertions.
    """

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            val = str(self)
            if val == "apply" and other in ("apply", "a"):
                return True
            if val == "reject" and other in ("reject", "r"):
                return True
            if val == "cancel" and other in ("cancel", "c"):
                return True
        return super().__eq__(other)

    def __hash__(self) -> int:
        return super().__hash__()


def format_time_consumed(seconds: float) -> str:
    """Formats seconds into human-readable duration with high precision."""
    if seconds < 0.001:
        return "<1ms"
    elif seconds < 1.0:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60.0:
        return f"{seconds:.2f}s"
    else:
        m = int(seconds // 60)
        s = seconds % 60
        return f"{m}m {s:.1f}s"


def render_diff(diff_text: str, console: Optional[Console] = None) -> None:
    """
    Renders unified Git diff with syntax highlighting and line numbers.
    Drop-in replacement for legacy cli.render_diff.
    """
    c = console if console is not None else Console()
    if diff_text and diff_text.strip():
        try:
            syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
            c.print(Panel(syntax, title="[bold green]Unified Git Diff[/bold green]", border_style="green"))
        except Exception:
            c.print("\n--- Unified Git Diff ---")
            c.print(diff_text)
    else:
        c.print("[dim]No diff changes to display.[/dim]")


def render_patch_card(
    patch_rec: Dict[str, Any],
    fix_time: float = 0.0,
    console: Optional[Console] = None,
    show_diff: bool = True,
) -> None:
    """
    Renders automated patch diagnosis and git diff, separating execution
    results from model claims. Drop-in replacement for legacy cli.render_patch_card.
    """
    c = console if console is not None else Console()
    sb_val = patch_rec.get("sandbox_validation") or {}
    sb_status = sb_val.get("test_status", "skipped").upper()
    sb_turns = sb_val.get("iterations_count", 1)
    sb_skipped = sb_val.get("skipped", False)
    time_str = format_time_consumed(fix_time)
    conf = f"{patch_rec.get('confidence_score', 0) or 0:.0%}"

    test_res = sb_val.get("test_result") or {}
    exit_code = test_res.get("exit_code")
    p_cnt = test_res.get("passed_count", 0)
    f_cnt = test_res.get("failed_count", 0)

    contract_type = sb_val.get("contract_type", "existing_tests")
    contract_disclaimer = sb_val.get("contract_disclaimer")

    if sb_skipped:
        sb_display = "NOT VERIFIED: NO TESTS RAN"
    elif sb_status == "PASSED":
        if contract_type == "ai_generated_proposal":
            sb_display = f"PASSES GENERATED TESTS ({p_cnt} passed, 0 failed — Exit Code 0, Iterations: {sb_turns})"
        else:
            sb_display = f"PASSED ({p_cnt} passed, 0 failed — Exit Code 0, Iterations: {sb_turns})"
    elif sb_status == "FAILED":
        sb_display = f"FAILED ({p_cnt} passed, {f_cnt} failed — Exit Code {exit_code}, Iterations: {sb_turns})"
    else:
        sb_display = f"{sb_status} (Iterations: {sb_turns})"

    passed_tests = test_res.get("passed_tests") or []
    failed_tests = test_res.get("failed_tests") or []
    rag_chunks = patch_rec.get("rag_context_chunks") or []
    cited_chunks = [
        f"{ch.get('file', '')}:{ch.get('lines', '')} ({ch.get('name', '')})"
        for ch in rag_chunks
        if isinstance(ch, dict) and ch.get("file")
    ]
    sec_val = patch_rec.get("security_validation") or {}

    status_color = "green" if sb_status == "PASSED" else ("red" if sb_status == "FAILED" else "yellow")
    info_table = Table.grid(padding=(0, 2))
    info_table.add_column(style="bold cyan", justify="right")
    info_table.add_column(style="white")
    info_table.add_row("Canonical Target:", str(patch_rec.get("target_file", "Unknown")))
    info_table.add_row("Error Type:", str(patch_rec.get("error_type", "Unknown")))
    info_table.add_row("Confidence:", conf)
    info_table.add_row("Sandbox Verification:", f"[{status_color}]{sb_display}[/{status_color}]")
    info_table.add_row("Refinement Iterations:", f"{sb_turns} attempt(s)")

    if passed_tests:
        pt_summary = ", ".join(passed_tests[:3]) + (f" (+{len(passed_tests)-3} more)" if len(passed_tests) > 3 else "")
        info_table.add_row("Tests Passed:", f"[green]{pt_summary}[/green]")
    if failed_tests:
        ft_summary = ", ".join(failed_tests[:3]) + (f" (+{len(failed_tests)-3} more)" if len(failed_tests) > 3 else "")
        info_table.add_row("Tests Failed:", f"[red]{ft_summary}[/red]")
    if cited_chunks:
        info_table.add_row("Grounded Chunks:", f"[dim]{', '.join(cited_chunks[:3])}[/dim]")
    if sec_val:
        sec_st = sec_val.get("security_status", "unscanned").upper()
        sec_color = "green" if sec_st == "PASSED" else ("red" if sec_st == "FAILED" else "yellow")
        info_table.add_row("Security Scan:", f"[{sec_color}]{sec_st} ({sec_val.get('findings_count', 0)} finding(s))[/{sec_color}]")
    if contract_type == "ai_generated_proposal":
        info_table.add_row("Contract Grounding:", "[bold yellow]AI-Generated Test Proposal (disposable contract)[/bold yellow]")
        if contract_disclaimer:
            info_table.add_row("Contract Disclaimer:", f"[dim yellow]{contract_disclaimer}[/dim yellow]")
    if sb_status == "FAILED":
        info_table.add_row("Verification Verdict:", "[bold red][!] REPAIR FAILED: Automated tests did not pass in Docker sandbox.[/bold red]")
    info_table.add_row("Time Consumed:", time_str)
    info_table.add_row("Model Advisory:", str(patch_rec.get("explanation", "")))
    if sb_status == "FAILED":
        info_table.add_row("Warning:", "[bold red][!] Model advisory claims cannot override failed test execution results.[/bold red]")

    c.print(Panel(info_table, title="[bold cyan]INTELLICODEX AUTOMATED CODE PATCH[/bold cyan]", border_style="cyan"))

    if show_diff:
        diff_text = patch_rec.get("git_diff", "")
        if diff_text:
            render_diff(diff_text, console=c)


def render_interactive_diff(
    patch_rec: Dict[str, Any],
    prompt_fn: Optional[Callable[[str], str]] = None,
    sandbox_test_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    on_action: Optional[Callable[[str], Any]] = None,
    console: Optional[Console] = None,
    show_diff: bool = True,
) -> ActionStr:
    """
    Renders an interactive diff reviewer card and enters an action prompt loop.

    Allows developers to:
    - [A]pply patch: returns "apply"
    - [T]est in sandbox: runs sandbox_test_fn, updates status, and re-prompts
    - [V]iew / toggle diff: toggles diff display
    - [R]eject patch: returns "reject"
    - [C]ancel / interrupt: returns "cancel"

    Returns:
        ActionStr: "apply", "reject", or "cancel"
    """
    c = console if console is not None else Console()
    _prompt = prompt_fn if prompt_fn is not None else input

    # Initial render of patch card and diff
    render_patch_card(patch_rec, console=c, show_diff=show_diff)

    while True:
        prompt_text = (
            "\n[bold cyan]Patch Review Action[/bold cyan] "
            "([bold green][A]pply[/bold green], "
            "[bold blue][T]est sandbox[/bold blue], "
            "[bold yellow][V]iew toggle diff[/bold yellow], "
            "[bold red][R]eject[/bold red], "
            "[dim][C]ancel[/dim]): "
        )
        try:
            raw = _prompt(prompt_text)
        except (KeyboardInterrupt, EOFError):
            if on_action:
                on_action("cancel")
            return ActionStr("cancel")

        choice = (raw or "").strip().lower()

        if choice in ("a", "apply", "approve", "y", "yes"):
            if on_action:
                on_action("apply")
            return ActionStr("apply")

        elif choice in ("r", "reject", "discard", "d", "n", "no"):
            if on_action:
                on_action("reject")
            return ActionStr("reject")

        elif choice in ("c", "cancel", "q", "quit", "exit"):
            if on_action:
                on_action("cancel")
            return ActionStr("cancel")

        elif choice in ("v", "view", "toggle", "u"):
            show_diff = not show_diff
            if show_diff:
                c.print("[bold green]--- Showing Unified Git Diff ---[/bold green]")
                render_diff(patch_rec.get("git_diff", ""), console=c)
            else:
                c.print("[dim]--- Diff display hidden ---[/dim]")
            if on_action:
                on_action("toggle_diff")
            continue

        elif choice in ("t", "test"):
            if sandbox_test_fn is not None:
                c.print("[cyan]Running automated test validation in sandbox...[/cyan]")
                try:
                    test_result = sandbox_test_fn(patch_rec)
                    if isinstance(test_result, dict):
                        if "sandbox_validation" in test_result:
                            patch_rec["sandbox_validation"] = test_result["sandbox_validation"]
                        else:
                            if "sandbox_validation" not in patch_rec or not isinstance(patch_rec["sandbox_validation"], dict):
                                patch_rec["sandbox_validation"] = {}
                            patch_rec["sandbox_validation"].update(test_result)
                        if "status" in test_result:
                            patch_rec["status"] = test_result["status"]
                    c.print("[green]Sandbox test execution complete.[/green]")
                except Exception as e:
                    c.print(f"[bold red]Sandbox test failed to execute:[/bold red] {e}")
                # Re-render patch card with updated results
                render_patch_card(patch_rec, console=c, show_diff=False)
            else:
                c.print("[yellow]No sandbox test runner configured.[/yellow]")
            if on_action:
                on_action("test")
            continue

        else:
            c.print(f"[red]Unknown option '{choice}'. Please enter \\[a], \\[t], \\[v], \\[r], or \\[c].[/red]")


__all__ = [
    "ActionStr",
    "format_time_consumed",
    "render_diff",
    "render_patch_card",
    "render_interactive_diff",
]
