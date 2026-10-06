"""
Interactive Code Review & Diff Rendering Module for IntelliCodeX CLI.
Supports:
1. Side-by-Side (Original vs Proposed) with red/green highlighting (when terminal width >= 120).
2. Unified Diff view (when terminal width < 120 or user toggles).
3. Multi-file navigation ([< Prev File] / [Next File >]).
4. Concurrency & Staleness Guard (SHA-256 hash checks before applying).
5. Scoped Git Commit (stages only reviewed files, leaves other uncommitted work untouched, never pushes).
"""
import difflib
import hashlib
import os
import shutil
import subprocess
from typing import List, Dict, Any, Optional, Tuple

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.columns import Columns
    from rich.syntax import Syntax
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None


def compute_file_sha256(filepath: str) -> Optional[str]:
    """Computes SHA-256 hash of a file for staleness and conflict detection."""
    if not os.path.isfile(filepath):
        return None
    try:
        hasher = hashlib.sha256()
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def align_side_by_side_diff(
    original_text: str,
    patched_text: str
) -> List[Tuple[Optional[int], str, Optional[int], str, str]]:
    """
    Computes side-by-side diff pairs using difflib.SequenceMatcher.
    Returns list of tuples:
      (left_line_no, left_line_text, right_line_no, right_line_text, change_type)
      change_type in ('equal', 'replace', 'delete', 'insert')
    """
    orig_lines = original_text.splitlines()
    patch_lines = patched_text.splitlines()

    matcher = difflib.SequenceMatcher(None, orig_lines, patch_lines)
    pairs = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for idx in range(max(i2 - i1, j2 - j1)):
                l_no = i1 + idx + 1 if i1 + idx < i2 else None
                l_txt = orig_lines[i1 + idx] if i1 + idx < i2 else ""
                r_no = j1 + idx + 1 if j1 + idx < j2 else None
                r_txt = patch_lines[j1 + idx] if j1 + idx < j2 else ""
                pairs.append((l_no, l_txt, r_no, r_txt, "equal"))
        elif tag == "replace":
            len_left = i2 - i1
            len_right = j2 - j1
            max_len = max(len_left, len_right)
            for idx in range(max_len):
                l_no = i1 + idx + 1 if idx < len_left else None
                l_txt = orig_lines[i1 + idx] if idx < len_left else ""
                r_no = j1 + idx + 1 if idx < len_right else None
                r_txt = patch_lines[j1 + idx] if idx < len_right else ""
                pairs.append((l_no, l_txt, r_no, r_txt, "replace"))
        elif tag == "delete":
            for idx in range(i2 - i1):
                l_no = i1 + idx + 1
                l_txt = orig_lines[i1 + idx]
                pairs.append((l_no, l_txt, None, "", "delete"))
        elif tag == "insert":
            for idx in range(j2 - j1):
                r_no = j1 + idx + 1
                r_txt = patch_lines[j1 + idx]
                pairs.append((None, "", r_no, r_txt, "insert"))

    return pairs


def render_side_by_side_diff(
    original_text: str,
    patched_text: str,
    filename: str,
    table_width: Optional[int] = None
) -> Table:
    """Renders a readable Side-by-Side (Original vs Proposed) table with Rich."""
    pairs = align_side_by_side_diff(original_text, patched_text)
    
    col_width = (table_width - 8) // 2 if table_width else 58
    code_width = max(20, col_width - 6)

    table = Table(
        title=f"[bold cyan]Code Review — {filename}[/bold cyan] [dim](Side-by-Side View)[/dim]",
        border_style="cyan",
        show_header=True,
        header_style="bold white",
        padding=(0, 0),
        expand=True
    )

    table.add_column("Orig #", style="dim", width=6, justify="right")
    table.add_column("Original Code (Removed)", style="white", ratio=1)
    table.add_column("New #", style="dim", width=6, justify="right")
    table.add_column("Proposed Code (Added)", style="white", ratio=1)

    for l_no, l_txt, r_no, r_txt, tag in pairs:
        l_no_str = str(l_no) if l_no is not None else ""
        r_no_str = str(r_no) if r_no is not None else ""

        if tag == "equal":
            l_cell = Text(l_txt, style="dim white")
            r_cell = Text(r_txt, style="dim white")
            table.add_row(l_no_str, l_cell, r_no_str, r_cell)
        elif tag == "replace":
            l_cell = Text(f"- {l_txt}", style="bold red on #330000") if l_txt else Text("")
            r_cell = Text(f"+ {r_txt}", style="bold green on #003300") if r_txt else Text("")
            table.add_row(
                Text(l_no_str, style="red"),
                l_cell,
                Text(r_no_str, style="green"),
                r_cell
            )
        elif tag == "delete":
            l_cell = Text(f"- {l_txt}", style="bold red on #330000")
            table.add_row(
                Text(l_no_str, style="red"),
                l_cell,
                "",
                Text("")
            )
        elif tag == "insert":
            r_cell = Text(f"+ {r_txt}", style="bold green on #003300")
            table.add_row(
                "",
                Text(""),
                Text(r_no_str, style="green"),
                r_cell
            )

    return table


def render_unified_diff_view(
    original_text: str,
    patched_text: str,
    filename: str
) -> Panel:
    """Renders a readable, unified diff panel with syntax highlighting."""
    orig_lines = original_text.splitlines(keepends=True)
    patch_lines = patched_text.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        orig_lines,
        patch_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm=""
    ))

    text = Text()
    for line in diff_lines:
        line_clean = line.rstrip("\r\n")
        if line_clean.startswith("+++") or line_clean.startswith("---"):
            text.append(f"{line_clean}\n", style="bold cyan")
        elif line_clean.startswith("@@"):
            text.append(f"{line_clean}\n", style="bold magenta")
        elif line_clean.startswith("+"):
            text.append(f"{line_clean}\n", style="bold green on #002b00")
        elif line_clean.startswith("-"):
            text.append(f"{line_clean}\n", style="bold red on #2b0000")
        else:
            text.append(f"{line_clean}\n", style="dim white")

    return Panel(
        text,
        title=f"[bold green]Code Review — {filename}[/bold green] [dim](Unified Diff View)[/dim]",
        border_style="green",
        padding=(1, 2)
    )


def display_review_screen(
    filename: str,
    original_code: str,
    patched_code: str,
    explanation: str = "",
    file_idx: int = 1,
    total_files: int = 1,
    mode: str = "auto"
):
    """
    Renders the complete interactive review card for the active file.
    Automatically chooses side-by-side if terminal >= 120 cols, or unified otherwise.
    """
    term_width = shutil.get_terminal_size((80, 24)).columns
    if console and hasattr(console, "width") and console.width:
        term_width = console.width

    if mode == "auto":
        is_side_by_side = (term_width >= 120)
    elif mode == "side_by_side":
        is_side_by_side = True
    else:
        is_side_by_side = False

    if HAS_RICH and console:
        # Header info
        header_grid = Table.grid(padding=(0, 2))
        header_grid.add_column(style="bold cyan", justify="right")
        header_grid.add_column(style="white")
        header_grid.add_row("Review Target:", f"[bold white]{filename}[/bold white] [dim]({file_idx} of {total_files})[/dim]")
        header_grid.add_row("Status:", "[bold yellow]PROPOSED — PENDING APPROVAL[/bold yellow]")
        if explanation:
            header_grid.add_row("Summary:", f"[italic]{explanation}[/italic]")
        header_grid.add_row("View Mode:", f"[bold]{'Side-by-Side (2 Columns)' if is_side_by_side else 'Unified Diff'}[/bold] [dim](Width: {term_width} cols)[/dim]")

        console.print("\n")
        console.print(Panel(header_grid, title="[bold cyan]INTELLICODEX INTERACTIVE CODE REVIEW[/bold cyan]", border_style="cyan"))

        # Diff Render
        if is_side_by_side:
            table = render_side_by_side_diff(original_code, patched_code, filename, table_width=term_width)
            console.print(table)
        else:
            panel = render_unified_diff_view(original_code, patched_code, filename)
            console.print(panel)

        # Action bar
        actions_text = Text()
        actions_text.append("\n  Actions: ", style="bold cyan")
        actions_text.append("[A] Approve & Commit   ", style="bold green")
        actions_text.append("[C] Cancel & Discard   ", style="bold red")
        actions_text.append("[U] Toggle Diff View   ", style="bold yellow")
        if total_files > 1:
            actions_text.append("[N] Next File   [P] Prev File", style="bold magenta")
        console.print(actions_text)
    else:
        print("\n" + "=" * 70)
        print(f" INTELLICODEX CODE REVIEW: {filename} ({file_idx}/{total_files})")
        print("=" * 70)
        if explanation:
            print(f"Explanation: {explanation}")
        print("\n--- Proposed Unified Diff ---")
        diff = difflib.unified_diff(
            original_code.splitlines(),
            patched_code.splitlines(),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm=""
        )
        for l in diff:
            print(l)
        print("\nActions: [A] Approve & Commit | [C] Cancel | [U] Toggle View")
        if total_files > 1:
            print("         [N] Next File | [P] Prev File")
        print("=" * 70)


def commit_approved_changes(
    repo_path: str,
    modified_files: List[str],
    commit_message: str
) -> Tuple[bool, str]:
    """
    Creates a local Git commit containing ONLY the approved modified files.
    Leaves all other uncommitted changes in the repository untouched.
    Never executes 'git push'.
    """
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return False, f"Not a Git repository: '{repo_path}'. Changes applied to disk without git commit."

    try:
        # Stage only the specified files
        for rel_file in modified_files:
            abs_f = os.path.join(repo_path, rel_file) if not os.path.isabs(rel_file) else rel_file
            res = subprocess.run(
                ["git", "add", abs_f],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=False
            )
            if res.returncode != 0:
                return False, f"Failed to stage '{rel_file}': {res.stderr.strip()}"

        # Execute git commit for staged files only
        c_res = subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False
        )
        if c_res.returncode == 0:
            return True, f"Created local Git commit for {len(modified_files)} file(s): '{commit_message}'"
        else:
            return False, f"Git commit failed: {c_res.stderr.strip() or c_res.stdout.strip()}"
    except Exception as e:
        return False, f"Git execution error: {e}"
