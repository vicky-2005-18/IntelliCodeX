"""
IntelliCodeX CLI — Ingest and query software repositories interactively.

Usage:
    python cli.py [repo_path_or_url] [--backend ollama|tfidf]

Examples:
    python cli.py sample_repo
    python cli.py https://github.com/vicky-2005-18/TB --backend ollama
"""
import argparse
import os
import re
import subprocess
import sys
import time
import requests

# Ensure console output handles unicode without crashing on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from core.pipeline import ingest_repository
from core.embedder import TfidfEmbedder, OllamaEmbedder
from core.llm_client import OllamaLLM
from rag.query_engine import QueryEngine
from core.dependency_graph import files_likely_affected_by, get_top_central_files
from core.call_graph import find_callers_of_symbol, get_top_central_symbols
from core.git_hooks import install_git_hooks, uninstall_git_hooks, check_git_hooks_status
from core.patch_generator import PatchEngine
from core.persistence import get_repo_id
from core.code_review import (
    display_review_screen,
    compute_file_sha256,
    commit_approved_changes,
)
from backend.services.incremental_indexer import RepositoryWatcher

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.text import Text
    from rich.columns import Columns
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False
    Columns = None

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory, FileHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False
    Completer = object
    Completion = None
    FileHistory = None
    InMemoryHistory = None


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
        return f"{m}m {s:04.1f}s"


def parse_mention(query: str) -> tuple[str, str]:
    """Extracts @filename mention from query and returns (cleaned_query, filename).
    
    If @filename is found, strips it from the query and returns the filename.
    If no @mention is found, returns (original_query, None).
    
    Examples:
        "any issue in @calculator_practice.py?" -> ("any issue in ?", "calculator_practice.py")
        "how does @auth.py work?" -> ("how does work?", "auth.py")
        "what is this?" -> ("what is this?", None)
    """
    # Match @filename pattern (supports @filename.ext or @filename or @path/to/file.py)
    # Match word characters, dots, underscores, hyphens, and forward slashes after @
    # Stop at whitespace or punctuation that's not part of a path
    match = re.search(r'@([\w\-.\/]+)', query)
    if match:
        filename = match.group(1)
        # Remove the @mention from the query (use exact match to avoid partial replacements)
        cleaned_query = query.replace(f"@{filename}", "").strip()
        # Clean up extra spaces that might be left
        cleaned_query = re.sub(r'\s+', ' ', cleaned_query)
        return cleaned_query, filename
    return query, None


def print_ingestion_summary(result, current_path: str, elapsed: float):
    """Prints repository ingestion results with elapsed time, throughput, and cache mode."""
    time_str = format_time_consumed(elapsed)
    mode = getattr(result, "indexing_mode", "fresh").lower()
    mode_badge = {
        "cached": "Instant Disk Cache",
        "incremental": "Incremental Update",
        "fresh": "Fresh Indexing"
    }.get(mode, "Fresh Indexing")
    speed_str = f" ({result.num_files / elapsed:.1f} files/sec)" if elapsed > 0.05 and mode != "cached" else ""
    print(f"[*] Indexed {result.num_files} files -> {result.num_chunks} code chunks ({result.ast_chunks_count} AST)")
    print(f"[*] Dependency graph: {result.graph.number_of_nodes()} nodes, {result.graph.number_of_edges()} edges")
    if getattr(result, "call_graph", None):
        print(f"[*] Call graph: {result.call_graph.number_of_nodes()} nodes, {result.call_graph.number_of_edges()} call edges")
    print(f"[*] [Time Consumed]: {time_str}{speed_str} [{mode_badge}]")


def check_ollama_available(host: str = "http://localhost:11434") -> bool:
    """Checks if local Ollama server is running and accessible."""
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def resolve_repo_path(repo_target: str) -> str:
    """Resolves local directory path or clones remote Git repository URL into .repos folder."""
    repo_target = repo_target.strip()
    if repo_target.startswith("http://") or repo_target.startswith("https://") or repo_target.startswith("git@"):
        repo_name = repo_target.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        target_dir = os.path.abspath(os.path.join(".repos", repo_name))

        if os.path.exists(target_dir) and os.path.exists(os.path.join(target_dir, ".git")):
            print(f"[*] Local clone found at '{target_dir}'. Syncing latest changes...")
            t_pull = time.perf_counter()
            try:
                subprocess.run(["git", "pull"], cwd=target_dir, capture_output=True, text=True, timeout=15)
                print(f"[*] Git sync finished in {format_time_consumed(time.perf_counter() - t_pull)}.")
            except subprocess.TimeoutExpired:
                print(f"[!] Warning: 'git pull' timed out after 15s. Using existing local files.")
            except Exception as e:
                print(f"[!] Warning: 'git pull' encountered an issue: {e}. Using existing local files.")
        else:
            os.makedirs(".repos", exist_ok=True)
            print(f"[*] Cloning remote Git repository '{repo_target}' into '{target_dir}'...")
            t_clone = time.perf_counter()
            try:
                res = subprocess.run(["git", "clone", "--depth", "50", repo_target, target_dir], capture_output=True, text=True, timeout=45)
                if res.returncode != 0:
                    raise RuntimeError(f"Git clone failed: {res.stderr.strip() or 'Unknown error or empty repository'}")
                print(f"[*] Git clone finished in {format_time_consumed(time.perf_counter() - t_clone)}.")
            except subprocess.TimeoutExpired:
                raise RuntimeError("Git clone operation timed out (45s). Please check repository URL or network connection.")
        return target_dir

    if not os.path.exists(repo_target):
        raise FileNotFoundError(f"Repository path or URL invalid / not found: '{repo_target}'")
    return os.path.abspath(repo_target)


def print_banner():
    banner = """
=======================================================================
               INTELLICODEX INTERACTIVE CLI ASSISTANT
  AI-Powered Repository Search, Dependency Analysis & Code Intelligence
=======================================================================
"""
    print(banner)


def print_help():
    help_text = """
Available Commands:
  fix:<err_or_file>      - Diagnose bug & generate automated code patch (e.g. 'fix:KeyError in auth.py')
  deps:<filepath>        - View direct & reverse dependencies for <filepath> (e.g. 'deps:pkg/db.py')
  callers:<func>         - Find all function call sites calling <func> (e.g. 'callers:fetch_user')
  top / centrality       - Show top central files and critical functions (PageRank score)
  repos / list-repos     - List all already-added repositories and switch by number
  repo <path_or_url>     - Switch/clone active repository (e.g. 'repo https://github.com/user/repo')
  repo <number>          - Switch to a previously added repo by its list number (e.g. 'repo 2')
  backend <ollama|tfidf> - Switch active backend engine dynamically
  persona <name>         - Switch AI persona (general, security, reviewer, refactor, fixer)
  model <model_name>     - Switch active Ollama model (e.g. 'model qwen2.5-coder:7b')
  history / clear-chat   - View or clear multi-turn chat memory
  reset / clear-memory  - Clear conversation history (useful before new @file scope)
  hooks / setup-hooks   - Install Git background re-indexing hooks for current repository
  hooks:status          - Check status of installed Git hooks
  hooks:remove          - Uninstall Git background re-indexing hooks
  watch / watch:status   - Check real-time file watcher status
  watch:stop / watch:start - Stop or restart real-time file watching
  hybrid / hybrid:status - Check hybrid search status (BM25 + Dense RRF)
  hybrid:on / hybrid:off - Enable or disable BM25 hybrid ranking
  search:<query>         - Instant lexical & semantic search without LLM wait
  chunks:<file>          - Inspect chunk-level index, start/end lines & vector preview
  index-stats            - Display overall index statistics (files, chunks, nodes, vocab, FAISS)
  explain:<query>        - Inspect RAG pipeline & prompt (--no-answer, --compare, --width, --json)
  clear / cls            - Clear terminal screen
  help / ?               - Show this help message
  exit / quit            - Exit IntelliCodeX CLI

File Scoping:
  @filename              - Scope query to a specific file (one-shot, e.g. 'any issue in @auth.py?')
  file:<filename>        - Set persistent file filter for all queries (e.g. 'file:auth.py')
  file:off               - Clear persistent file filter
"""
    print(help_text)


def get_available_repos(current_path: str) -> list:
    """Returns a list of (label, abs_path) tuples for all known local repositories.

    Scans:
    - Built-in sample_repo
    - All previously indexed repositories recorded in SQLite (.storage/metadata.db)
    - The .repos/ folder
    - The currently active repository
    """
    known: list = []  # list of (label, abs_path)
    seen_paths: set = set()

    def _add_repo(label: str, raw_path: str):
        if not raw_path or not os.path.isdir(raw_path):
            return
        abs_p = os.path.abspath(raw_path)
        norm_key = os.path.normcase(abs_p)
        if norm_key in seen_paths:
            return
        # Filter out pytest temporary directories
        if any(t in norm_key.lower() for t in ["temp", "pytest-of-", "intellicodex_pytest_storage"]):
            return
        known.append((label, abs_p))
        seen_paths.add(norm_key)

    # 1. Built-in sample_repo
    sample_abs = os.path.abspath("sample_repo")
    if os.path.isdir(sample_abs):
        _add_repo("sample_repo", sample_abs)

    # 2. Currently active repo
    if current_path and os.path.isdir(current_path):
        _add_repo(os.path.basename(os.path.abspath(current_path)) or current_path, current_path)

    # 3. Persistent SQLite registry (remembers any repo indexed on your local computer)
    try:
        from core.persistence import get_db_connection
        conn = get_db_connection()
        rows = conn.execute("SELECT repo_path FROM repos ORDER BY last_indexed_at DESC").fetchall()
        for r in rows:
            p = r["repo_path"]
            if p and os.path.isdir(p):
                label = os.path.basename(os.path.abspath(p)) or p
                _add_repo(label, p)
    except Exception:
        pass

    # 4. Repos cloned into .repos/
    repos_dir = os.path.abspath(".repos")
    if os.path.isdir(repos_dir):
        for entry in sorted(os.scandir(repos_dir), key=lambda e: e.name.lower()):
            if entry.is_dir():
                _add_repo(entry.name, entry.path)

    return known


def should_use_tui() -> bool:
    """Returns True if rich prompt_toolkit interactive session should be enabled."""
    if not HAS_PROMPT_TOOLKIT:
        return False
    if os.environ.get("INTELLICODEX_NO_TUI", "").strip() == "1":
        return False
    if os.environ.get("INTELLICODEX_FORCE_TUI", "").strip() == "1":
        return True
    try:
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False
    return True


def create_interactive_session(completer=None, history=None):
    """Creates a prompt_toolkit PromptSession with Windows fallback if raw console buffer fails."""
    if not HAS_PROMPT_TOOLKIT or PromptSession is None:
        return None
    try:
        return PromptSession(completer=completer, history=history)
    except Exception:
        pass

    # Windows fallback: when NoConsoleScreenBufferError occurs in modern terminals / ConPTY
    try:
        from prompt_toolkit.output.vt100 import Vt100_Output
        import shutil

        def get_size():
            sz = shutil.get_terminal_size((80, 24))
            return (sz.columns, sz.lines)

        out = Vt100_Output(sys.stdout, get_size)
        return PromptSession(completer=completer, history=history, output=out)
    except Exception:
        return None


def render_banner():
    """Renders interactive banner with rich styling if available."""
    if HAS_RICH and console:
        title_text = Text()
        title_text.append("INTELLICODEX INTERACTIVE CLI ASSISTANT\n", style="bold cyan")
        title_text.append("AI-Powered Repository Search, Dependency Analysis & Code Intelligence", style="dim white")
        console.print(Panel(title_text, border_style="cyan", padding=(1, 2)))
    else:
        print_banner()


def render_markdown_panel(md_text: str, title: str = "Answer", border_style: str = "cyan"):
    """Renders Markdown text inside a styled terminal panel."""
    if HAS_RICH and console:
        md = Markdown(md_text)
        console.print(Panel(md, title=f"[bold {border_style}]{title}[/bold {border_style}]", border_style=border_style, padding=(1, 2)))
    else:
        print(f"\n--- {title} ---\n{md_text}\n")


def render_diff(diff_text: str):
    """Renders unified Git diff with syntax highlighting."""
    if HAS_RICH and console and diff_text.strip():
        syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=True)
        console.print(Panel(syntax, title="[bold green]Unified Git Diff[/bold green]", border_style="green"))
    else:
        print("\n--- Unified Git Diff ---")
        print(diff_text)


def render_files_table(indexed_files: list):
    """Renders indexed file list in a rich formatted table."""
    if HAS_RICH and console:
        table = Table(title=f"Indexed Source Files ({len(indexed_files)})", border_style="bright_blue")
        table.add_column("#", style="dim", width=6)
        table.add_column("File Path", style="cyan")
        table.add_column("Type", style="yellow")
        for idx, f in enumerate(indexed_files, start=1):
            ext = os.path.splitext(f)[1] or "file"
            table.add_row(str(idx), f, ext)
        console.print(table)
        print()
    else:
        print(f"\n--- Indexed Source Files ({len(indexed_files)}) ---")
        for f in indexed_files:
            print(f"  - {f}")
        print()


def render_centrality_tables(top_files, top_syms):
    """Renders PageRank centrality rankings in structured tables."""
    if HAS_RICH and console:
        table_f = Table(title="Top Central Files (PageRank Score)", border_style="bright_blue")
        table_f.add_column("Rank", style="dim", width=6)
        table_f.add_column("File Path", style="cyan")
        table_f.add_column("PageRank Score", style="bold green", justify="right")
        if not top_files:
            table_f.add_row("-", "(no internal dependencies found)", "-")
        else:
            for idx, (fpath, score) in enumerate(top_files, start=1):
                table_f.add_row(str(idx), fpath, f"{score:.4f}")
        console.print(table_f)

        if top_syms is not None:
            table_s = Table(title="Top Central Symbols (PageRank Score)", border_style="magenta")
            table_s.add_column("Rank", style="dim", width=6)
            table_s.add_column("Symbol Identifier", style="magenta")
            table_s.add_column("PageRank Score", style="bold green", justify="right")
            if not top_syms:
                table_s.add_row("-", "(no function call edges found)", "-")
            else:
                for idx, (cid, score) in enumerate(top_syms, start=1):
                    table_s.add_row(str(idx), cid, f"{score:.4f}")
            console.print(table_s)
        print()
    else:
        print("\n--- Top Central Files (PageRank Score) ---")
        if not top_files:
            print("  (no internal dependencies found)")
        else:
            for idx, (fpath, score) in enumerate(top_files, start=1):
                print(f"  {idx}. {fpath} (score={score:.3f})")
        if top_syms is not None:
            print("\n--- Top Central Function Symbols (PageRank Score) ---")
            if not top_syms:
                print("  (no function call edges found)")
            else:
                for idx, (cid, score) in enumerate(top_syms, start=1):
                    print(f"  {idx}. {cid} (score={score:.3f})")
        print()


def render_repos_table(available: list, active_path: str):
    """Renders available repositories list in a formatted table."""
    active_abs = os.path.abspath(active_path)
    if HAS_RICH and console:
        table = Table(title=f"Available Repositories ({len(available)})", border_style="bright_blue")
        table.add_column("#", style="bold yellow", width=5)
        table.add_column("Name", style="bold cyan")
        table.add_column("Path", style="dim white")
        table.add_column("Status", style="bold green")
        for idx, (label, abs_p) in enumerate(available, start=1):
            is_act = (abs_p == active_abs)
            st = "[bold green]ACTIVE ✓[/bold green]" if is_act else "[dim]Available[/dim]"
            table.add_row(str(idx), label, abs_p, st)
        console.print(table)
        console.print("[dim]Tip: type 'repo <number>' or 'repo <name>' to switch[/dim]\n")
    else:
        print(f"\n--- Available Repositories ({len(available)}) ---")
        for idx, (label, abs_p) in enumerate(available, start=1):
            active_marker = " (active ✓)" if abs_p == active_abs else ""
            print(f"  [{idx}] {label:<25} {abs_p}{active_marker}")
        print("\n  Tip: type 'repo <number>' to switch, e.g. 'repo 2'\n")


def render_hooks_table(st_dict: dict, target_path: str):
    """Renders Git hook status table."""
    if HAS_RICH and console:
        table = Table(title=f"Git Hook Status for '{os.path.basename(target_path)}'", border_style="bright_blue")
        table.add_column("Hook Name", style="cyan")
        table.add_column("Status", style="bold")
        for hook, is_inst in st_dict.items():
            badge = "[bold green]Installed ✓[/bold green]" if is_inst else "[dim yellow]Not Installed[/dim yellow]"
            table.add_row(hook, badge)
        console.print(table)
        print()
    else:
        print(f"\n--- Git Hook Status for '{target_path}' ---")
        for hook, is_inst in st_dict.items():
            print(f"  - {hook}: {'Installed' if is_inst else 'Not Installed'}")
        print()


def render_patch_card(patch_rec: dict, fix_time: float):
    """Renders automated patch diagnosis and git diff."""
    sb_val = patch_rec.get("sandbox_validation", {})
    sb_status = sb_val.get("test_status", "skipped").upper()
    sb_turns = sb_val.get("iterations_count", 1)
    sb_skipped = sb_val.get("skipped", False)
    time_str = format_time_consumed(fix_time)
    conf = f"{patch_rec.get('confidence_score', 0):.0%}"
    
    # Show "not verified" message when tests were skipped
    if sb_skipped:
        sb_display = "NOT VERIFIED: NO TESTS RAN"
    else:
        sb_display = f"{sb_status} (Iterations: {sb_turns})"

    if HAS_RICH and console:
        status_color = "green" if sb_status == "PASSED" else ("red" if sb_status == "FAILED" else "yellow")
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="bold cyan", justify="right")
        info_table.add_column(style="white")
        info_table.add_row("Target File:", patch_rec.get("target_file", "Unknown"))
        info_table.add_row("Error Type:", str(patch_rec.get("error_type", "Unknown")))
        info_table.add_row("Confidence:", conf)
        info_table.add_row("Sandbox Tests:", f"[{status_color}]{sb_display}[/{status_color}]")
        info_table.add_row("Time Consumed:", time_str)
        info_table.add_row("Explanation:", patch_rec.get("explanation", ""))

        console.print(Panel(info_table, title="[bold cyan]INTELLICODEX AUTOMATED CODE PATCH[/bold cyan]", border_style="cyan"))
        render_diff(patch_rec.get("git_diff", ""))
    else:
        print("\n=======================================================================")
        print("                 INTELLICODEX AUTOMATED CODE PATCH")
        print("=======================================================================")
        print(f"Target File     : {patch_rec['target_file']}")
        print(f"Error Type      : {patch_rec.get('error_type', 'Unknown')}")
        print(f"Confidence      : {conf}")
        print(f"Sandbox Tests   : {sb_display}")
        print(f"Time Consumed   : {time_str}")
        print(f"Explanation     : {patch_rec['explanation']}")
        print("\n--- Unified Git Diff ---")
        print(patch_rec.get("git_diff", ""))
        print("=======================================================================\n")


# ---------------------------------------------------------------------------
# Rich TUI Helper Panels (Milestone 4 / CLI Perfection)
# ---------------------------------------------------------------------------

def render_help_panel():
    """Renders rich color-coded help table grouped by command category."""
    if HAS_RICH and console:
        groups = [
            ("Search & AI", "cyan", [
                ("search:<query>",  "Instant retrieval without LLM (fast, no AI wait)"),
                ("chunks:<file>",   "Inspect chunk-level index, line ranges & vectors"),
                ("index-stats",     "Show comprehensive index statistics across the repo"),
                ("explain:<query>", "Inspect RAG pipeline, prompt & compare (--compare, --width)"),
                ("<question>",      "Ask AI a question about the repository"),
                ("@filename",       "Scope query to a specific file (one-shot)"),
                ("fix:<error>",     "Diagnose error & generate automated sandbox patch"),
            ]),
            ("Code Analysis", "magenta", [
                ("deps:<file>",     "View reverse dependency impact for a file"),
                ("callers:<func>",  "Find all call sites of a function across the repo"),
                ("top / centrality","Show PageRank centrality rankings for files & symbols"),
                ("info:<file>",     "Show file stats: size, chunk count, centrality score"),
            ]),
            ("Repository", "green", [
                ("repo <path|url>", "Switch or clone a repository (local or GitHub URL)"),
                ("repo <number>",   "Switch to a previously added repo by list number"),
                ("repos",           "List all known repositories"),
                ("files / ls",      "List all indexed source files"),
            ]),
            ("Settings", "yellow", [
                ("backend <name>",  "Switch backend engine: ollama | tfidf"),
                ("persona <name>",  "Switch AI persona: general, security, reviewer, refactor, fixer"),
                ("model <name>",    "Set active Ollama LLM model (e.g. qwen2.5-coder:7b)"),
                ("file:<name>",     "Set persistent file filter for all queries"),
                ("file:off",        "Clear persistent file filter"),
                ("hybrid:on|off",   "Enable or disable BM25 lexical hybrid search"),
                ("hybrid:toggle",   "Toggle hybrid search on/off"),
            ]),
            ("Git & Watcher", "blue", [
                ("hooks",           "Install Git background re-indexing hooks"),
                ("hooks:status",    "Check Git hooks installation status"),
                ("hooks:remove",    "Uninstall Git background re-indexing hooks"),
                ("watch",           "Check real-time filesystem watcher status"),
                ("watch:start|stop","Start or stop the real-time file watcher"),
            ]),
            ("Session", "white", [
                ("status",          "Show full system status at a glance"),
                ("history",         "View multi-turn conversation history"),
                ("clear-chat",      "Clear conversation history"),
                ("export:<file>",   "Save last AI answer to a Markdown file"),
                ("version",         "Show IntelliCodeX version"),
                ("clear / cls",     "Clear terminal screen"),
                ("help / ?",        "Show this help message"),
                ("exit / quit",     "Exit IntelliCodeX CLI"),
            ]),
        ]
        for group_name, color, cmds in groups:
            table = Table(
                title=f"[bold {color}]{group_name}[/bold {color}]",
                border_style=color, show_header=True,
                header_style=f"bold {color}", padding=(0, 1),
            )
            table.add_column("Command", style=color, min_width=24)
            table.add_column("Description", style="white")
            for cmd, desc in cmds:
                table.add_row(cmd, desc)
            console.print(table)
        console.print("\n[dim]  ↑/↓ arrows recall command history · Tab for autocomplete[/dim]\n")
    else:
        print_help()


def render_ingestion_panel(result, current_path: str, elapsed: float):
    """Renders repository ingestion results with rich panel styling."""
    time_str = format_time_consumed(elapsed)
    mode = getattr(result, "indexing_mode", "fresh").lower()
    if HAS_RICH and console:
        mode_badge = {
            "cached":      "[bold green]Instant Disk Cache[/bold green]",
            "incremental": "[bold yellow]Incremental Update[/bold yellow]",
            "fresh":       "[bold cyan]Fresh Indexing[/bold cyan]",
        }.get(mode, "[bold cyan]Fresh Indexing[/bold cyan]")
        speed_str = (
            f" ({result.num_files / elapsed:.1f} files/sec)"
            if elapsed > 0.05 and mode != "cached" else ""
        )
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", justify="right")
        grid.add_column(style="white")
        grid.add_row(
            "[green]✓[/green] Files indexed:",
            f"[bold]{result.num_files}[/bold] → [bold]{result.num_chunks}[/bold] chunks ([dim]{result.ast_chunks_count} AST[/dim])",
        )
        grid.add_row(
            "[green]✓[/green] Dependency graph:",
            f"{result.graph.number_of_nodes()} nodes, {result.graph.number_of_edges()} edges",
        )
        call_g = getattr(result, "call_graph", None)
        if call_g:
            grid.add_row(
                "[green]✓[/green] Call graph:",
                f"{call_g.number_of_nodes()} nodes, {call_g.number_of_edges()} call edges",
            )
        grid.add_row("[green]✓[/green] Mode:", mode_badge)
        grid.add_row("[green]✓[/green] Time consumed:", f"[bold green]{time_str}[/bold green]{speed_str}")
        console.print(Panel(
            grid,
            title=f"[bold cyan]Repository Indexed — {os.path.basename(current_path)}[/bold cyan]",
            border_style="cyan", padding=(1, 2),
        ))
    else:
        print_ingestion_summary(result, current_path, elapsed)


def render_deps_panel(target: str, affected: list, elapsed: float):
    """Renders dependency impact as a rich tree-style panel."""
    if HAS_RICH and console:
        if not affected:
            content = Text("(no reverse dependencies found)", style="dim italic")
        else:
            content = Text()
            for i, aff in enumerate(affected):
                prefix = "└── " if i == len(affected) - 1 else "├── "
                content.append(f"{prefix}{aff}\n", style="cyan")
        console.print(Panel(
            content,
            title=f"[bold magenta]Dependency Impact — {target}[/bold magenta]",
            subtitle=f"[dim]{len(affected)} reverse dep(s) · {format_time_consumed(elapsed)}[/dim]",
            border_style="magenta", padding=(1, 2),
        ))
    else:
        print(f"\n--- Dependency Analysis for '{target}' ---")
        print("  Reverse Dependencies (Files affected if modified):")
        if not affected:
            print("    (none found)")
        else:
            for aff in affected:
                print(f"    ├── {aff}")
        print(f"\n[*] [Time Consumed]: {format_time_consumed(elapsed)}\n")


def render_callers_panel(symbol: str, callers: list, elapsed: float):
    """Renders function callers as a rich tree-style panel."""
    if HAS_RICH and console:
        if not callers:
            content = Text("(no calling function sites found)", style="dim italic")
        else:
            content = Text()
            for i, c_id in enumerate(callers):
                prefix = "└── " if i == len(callers) - 1 else "├── "
                content.append(f"{prefix}{c_id}\n", style="magenta")
        console.print(Panel(
            content,
            title=f"[bold magenta]Callers of '{symbol}'[/bold magenta]",
            subtitle=f"[dim]{len(callers)} call site(s) · {format_time_consumed(elapsed)}[/dim]",
            border_style="magenta", padding=(1, 2),
        ))
    else:
        print(f"\n--- Symbol Callers for '{symbol}' ---")
        if not callers:
            print("  (no calling function sites found)")
        else:
            for c_id in callers:
                print(f"  ├── {c_id}")
        print(f"\n[*] [Time Consumed]: {format_time_consumed(elapsed)}\n")


def render_watch_panel(watcher, current_path: str):
    """Renders real-time watcher status as a rich panel."""
    is_active = bool(watcher and watcher.is_alive())
    if HAS_RICH and console:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", justify="right")
        grid.add_column(style="white")
        grid.add_row("Status:", "[bold green]ACTIVE ✓[/bold green]" if is_active else "[bold red]INACTIVE[/bold red]")
        grid.add_row("Target:", current_path)
        grid.add_row("Debounce:", "500 ms")
        grid.add_row("Auto-reindex:", "[green]Enabled[/green]" if is_active else "[dim]Disabled[/dim]")
        console.print(Panel(
            grid, title="[bold blue]Real-Time Filesystem Watcher[/bold blue]",
            border_style="blue", padding=(1, 2),
        ))
    else:
        if is_active:
            print(f"\n[*] Real-Time Filesystem Watcher: ACTIVE")
            print(f"    Target Directory: '{current_path}'")
            print("    Debounce Window : 500ms")
            print("    Auto-reindex    : Enabled\n")
        else:
            print("\n[*] Real-Time Filesystem Watcher: INACTIVE / STOPPED\n")


def render_hybrid_panel(engine):
    """Renders hybrid search status as a rich panel."""
    is_on = getattr(engine, "hybrid_search", True)
    if HAS_RICH and console:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", justify="right")
        grid.add_column(style="white")
        grid.add_row("Hybrid Search:", "[bold green]ACTIVE ✓[/bold green]" if is_on else "[bold red]INACTIVE[/bold red]")
        grid.add_row("Algorithm:", "Reciprocal Rank Fusion (k=60)")
        grid.add_row("Lexical:", "BM25Okapi (sub-token identifier splitting)")
        grid.add_row("Dense:", "TF-IDF / Ollama nomic-embed-text vectors")
        grid.add_row("Commands:", "'hybrid:on'  'hybrid:off'  'hybrid:toggle'")
        console.print(Panel(
            grid, title="[bold cyan]Hybrid Search — BM25 + Dense RRF[/bold cyan]",
            border_style="cyan", padding=(1, 2),
        ))
    else:
        st = "ACTIVE (Dense + BM25 RRF)" if is_on else "INACTIVE (Dense only)"
        print(f"\n[*] Hybrid Search: {st}")
        print("    Algorithm: Reciprocal Rank Fusion (k=60)\n")


def render_status_panel(current_path: str, active_backend: str, engine, watcher):
    """Renders at-a-glance master system status panel."""
    if HAS_RICH and console:
        watcher_st = "[bold green]ON ✓[/bold green]" if (watcher and watcher.is_alive()) else "[bold red]OFF[/bold red]"
        hybrid_st  = "[bold green]ON ✓[/bold green]" if getattr(engine, "hybrid_search", True) else "[bold red]OFF[/bold red]"
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", justify="right")
        grid.add_column(style="white")
        grid.add_row("Repository:",   f"[bold]{os.path.basename(current_path)}[/bold]  [dim]{current_path}[/dim]")
        grid.add_row("Backend:",      f"[bold yellow]{active_backend}[/bold yellow]")
        grid.add_row("Persona:",      f"[bold green]{engine.active_persona}[/bold green]")
        if hasattr(engine, "active_model") and engine.active_model:
            grid.add_row("Model:",    str(engine.active_model))
        grid.add_row("Hybrid Search:", hybrid_st)
        grid.add_row("File Watcher:", watcher_st)
        grid.add_row("Version:",      f"[dim]{VERSION}[/dim]")
        console.print(Panel(
            grid, title="[bold cyan]IntelliCodeX — System Status[/bold cyan]",
            border_style="cyan", padding=(1, 2),
        ))
    else:
        print(f"\n[*] System Status:")
        print(f"    Repository : {current_path}")
        print(f"    Backend    : {active_backend}")
        print(f"    Persona    : {engine.active_persona}")
        print(f"    Hybrid     : {'ON' if getattr(engine, 'hybrid_search', True) else 'OFF'}")
        print(f"    Watcher    : {'ON' if (watcher and watcher.is_alive()) else 'OFF'}")
        print(f"    Version    : {VERSION}\n")


def render_search_results(query: str, results: list, elapsed: float):
    """Renders fast retrieval-only results (no LLM) in a styled rich table."""
    if HAS_RICH and console:
        table = Table(
            title=(
                f"[bold cyan]Fast Search — '{query}'[/bold cyan]  "
                f"[dim]({format_time_consumed(elapsed)}, no LLM)[/dim]"
            ),
            border_style="cyan", show_lines=False,
        )
        table.add_column("Score",  style="bold green", justify="right", width=7)
        table.add_column("File",   style="cyan")
        table.add_column("Symbol", style="magenta")
        table.add_column("Lines",  style="dim", width=12)
        table.add_column("Reason", style="dim")
        for item in results:
            chunk  = item["chunk"]
            score  = item["score"]
            reason = item.get("reason", "")
            lines_str = f"{chunk.start_line}–{chunk.end_line}"
            table.add_row(
                f"{score:.3f}", chunk.file_path, chunk.name or "—",
                lines_str, reason or "—",
            )
        console.print(table)
        console.print()
    else:
        print(f"\n--- Fast Search Results for '{query}' ({format_time_consumed(elapsed)}) ---")
        for item in results:
            chunk = item["chunk"]
            print(f"  [{item['score']:.3f}] {chunk.file_path} :: {chunk.name} (lines {chunk.start_line}-{chunk.end_line})")
        print()


def middle_truncate(text: str, max_len: int = 32) -> str:
    """Truncates text in the middle with '...' so start and end are preserved."""
    if not text or len(text) <= max_len:
        return text
    if max_len <= 5:
        return text[:max_len]
    head = (max_len - 3) // 2
    tail = max_len - 3 - head
    return f"{text[:head]}...{text[-tail:]}"


def render_retrieval_trace(trace, full_code: bool = False, no_answer: bool = False, width: Optional[int] = None, terminal_width: Optional[int] = None):
    """
    Renders RAG retrieval provenance trace in rich tables:
    1. Question and query terms
    2. Two side-by-side tables (BM25 | Dense)
    3. Merged ranking table with bm25_rank, dense_rank, rrf_score (middle-truncated files)
    4. Code previews section below table
    5. Graph additions with reasons
    6. Budget line
    7. Augmented prompt panel (instructions, labelled chunks [1], [2]..., question)
    8. Answer with sources rendered via rich Markdown (if not no_answer)
    """
    import shutil
    chosen_width = terminal_width or width
    term_width = chosen_width or (shutil.get_terminal_size((100, 24)).columns if hasattr(shutil, "get_terminal_size") else 100)
    trace_console = Console(width=term_width) if (HAS_RICH and console) else console

    if HAS_RICH and trace_console:
        trace_console.print()
        trace_console.print(Panel(
            f"[bold cyan]Question:[/bold cyan] {trace.question}\n"
            f"[bold yellow]Query Terms (BM25 tokenized):[/bold yellow] {trace.query_terms}\n"
            f"[dim]Timings (ms): embed={trace.timings_ms.get('embed', 0):.1f} | "
            f"bm25={trace.timings_ms.get('bm25', 0):.1f} | dense={trace.timings_ms.get('dense', 0):.1f} | "
            f"fuse={trace.timings_ms.get('fuse', 0):.1f} | expand={trace.timings_ms.get('expand', 0):.1f} | "
            f"llm={trace.timings_ms.get('llm', 0):.1f}[/dim]",
            title="[bold bright_blue]Retrieval Pipeline Provenance[/bold bright_blue]",
            border_style="bright_blue",
        ))

        t_bm25 = Table(title="BM25 Lexical Hits", border_style="yellow", padding=(0, 1))
        t_bm25.add_column("Rank", style="dim", width=5)
        t_bm25.add_column("File::Symbol", style="yellow", no_wrap=True, overflow="ellipsis")
        t_bm25.add_column("Lines", style="dim", width=10)
        t_bm25.add_column("Score", style="bold green", justify="right")
        if not trace.bm25_hits:
            t_bm25.add_row("-", "(no BM25 hits)", "-", "-")
        else:
            for idx, h in enumerate(trace.bm25_hits, start=1):
                sym = h[2] or "—"
                f_disp = middle_truncate(h[1], 28)
                s_disp = middle_truncate(sym, 18)
                t_bm25.add_row(str(idx), f"{f_disp}::{s_disp}", f"{h[3]}–{h[4]}", f"{h[5]:.4f}")

        t_dense = Table(title="Dense Vector Hits", border_style="cyan", padding=(0, 1))
        t_dense.add_column("Rank", style="dim", width=5)
        t_dense.add_column("File::Symbol", style="cyan", no_wrap=True, overflow="ellipsis")
        t_dense.add_column("Lines", style="dim", width=10)
        t_dense.add_column("Score", style="bold green", justify="right")
        if not trace.dense_hits:
            t_dense.add_row("-", "(no dense hits)", "-", "-")
        else:
            for idx, h in enumerate(trace.dense_hits, start=1):
                sym = h[2] or "—"
                f_disp = middle_truncate(h[1], 28)
                s_disp = middle_truncate(sym, 18)
                t_dense.add_row(str(idx), f"{f_disp}::{s_disp}", f"{h[3]}–{h[4]}", f"{h[5]:.4f}")

        if Columns:
            trace_console.print(Columns([t_bm25, t_dense]))
        else:
            trace_console.print(t_bm25)
            trace_console.print(t_dense)

        t_fused = Table(title="Merged RRF Ranking", border_style="bright_blue", padding=(0, 1))
        t_fused.add_column("Rank", style="dim", width=5)
        t_fused.add_column("File::Symbol", style="bold cyan", no_wrap=True, overflow="ellipsis")
        t_fused.add_column("Lines", style="dim", width=10)
        t_fused.add_column("BM25 Rank", style="yellow", justify="right")
        t_fused.add_column("Dense Rank", style="cyan", justify="right")
        t_fused.add_column("RRF Score", style="bold green", justify="right")

        if not trace.fused_hits:
            t_fused.add_row("-", "(no fused hits)", "-", "-", "-", "-")
        else:
            for idx, h in enumerate(trace.fused_hits, start=1):
                bm25_r = str(h[6]) if h[6] is not None else "-"
                dense_r = str(h[7]) if h[7] is not None else "-"
                rrf_s = f"{h[8]:.5f}"
                sym = h[2] or "—"
                f_disp = middle_truncate(h[1], 34)
                s_disp = middle_truncate(sym, 20)
                t_fused.add_row(str(idx), f"{f_disp}::{s_disp}", f"{h[3]}–{h[4]}", bm25_r, dense_r, rrf_s)
        trace_console.print(t_fused)

        # Code previews moved out of table into dedicated section below
        if trace.fused_hits:
            trace_console.print()
            trace_console.print("[bold bright_blue]── Code Previews (Top Fused Chunks) ──[/bold bright_blue]")
            for idx, h in enumerate(trace.fused_hits, start=1):
                sym = h[2] or "—"
                code_raw = trace.chunk_codes.get(h[0], "")
                if full_code:
                    preview = code_raw.strip()
                else:
                    lines = code_raw.strip().splitlines()
                    preview = "\n".join(lines[:3]) + ("\n..." if len(lines) > 3 else "")
                trace_console.print(f"[bold cyan][{idx}] {h[1]}::{sym}[/bold cyan] [dim](lines {h[3]}–{h[4]}, RRF: {h[8]:.5f})[/dim]")
                trace_console.print(Syntax(preview, "python", theme="monokai", line_numbers=False) if HAS_RICH else preview)

        t_graph = Table(title="Graph Context Additions", border_style="magenta", padding=(0, 1))
        t_graph.add_column("#", style="dim", width=4)
        t_graph.add_column("Target (Chunk / File)", style="magenta", no_wrap=True, overflow="ellipsis")
        t_graph.add_column("Reason", style="bold yellow")
        t_graph.add_column("Caused By (Fused Hit)", style="dim")
        if not trace.graph_additions:
            t_graph.add_row("-", "(no graph additions)", "-", "-")
        else:
            for idx, g in enumerate(trace.graph_additions, start=1):
                t_graph.add_row(str(idx), middle_truncate(str(g[0]), 40), str(g[1]), str(g[2] or "-"))
        trace_console.print(t_graph)

        b = trace.budget
        inc_count = len(b.included_chunk_ids)
        drop_detail = f" (Dropped: {', '.join(b.dropped_chunk_ids)})" if b.dropped_chunk_ids else " (0 dropped)"
        trace_console.print(f"[bold green]Budget:[/bold green] {inc_count} chunks, {b.used_tokens:,} / {b.max_tokens:,} tokens{drop_detail}")
        trace_console.print()

        # Augmented prompt panel (what the model actually reads)
        prompt_sections = getattr(trace, "prompt_sections", {}) or {}
        instructions = prompt_sections.get("instructions", "")
        if not instructions and hasattr(trace, "augmented_prompt") and trace.augmented_prompt:
            instructions = "Standard Repository Context Instructions"
        
        chunks_to_show = prompt_sections.get("context_chunks", [])
        if not chunks_to_show and trace.fused_hits:
            chunks_to_show = [
                {
                    "file": h[1],
                    "lines": f"{h[3]}-{h[4]}",
                    "symbol": h[2] or "—",
                    "code": trace.chunk_codes.get(h[0], ""),
                }
                for h in trace.fused_hits
            ]

        prompt_body_parts = []
        if instructions:
            prompt_body_parts.append(f"[bold yellow]── Instruction Block (Instructions) ──[/bold yellow]\n{instructions.strip()}\n")

        prompt_body_parts.append("[bold yellow]── Context Chunks ──[/bold yellow]")
        if not chunks_to_show:
            prompt_body_parts.append("[dim](no context chunks included)[/dim]\n")
        else:
            for idx, c_info in enumerate(chunks_to_show, start=1):
                fpath = c_info.get("file", "unknown")
                lines_r = c_info.get("lines", "")
                sym = c_info.get("symbol", "—")
                c_code = c_info.get("code", "")
                c_lines = c_code.splitlines()
                if not full_code and len(c_lines) > 12:
                    code_disp = "\n".join(c_lines[:12]) + "\n... [truncated to 12 lines, use --full to view all]"
                else:
                    code_disp = "\n".join(c_lines)
                prompt_body_parts.append(
                    f"[bold cyan][{idx}] {fpath}:{lines_r}[/bold cyan] [dim]({sym})[/dim]\n```python\n{code_disp}\n```\n"
                )

        q_disp = prompt_sections.get("question", trace.question) or trace.question
        prompt_body_parts.append(f"[bold yellow]── User Question ──[/bold yellow]\n{q_disp}")

        if prompt_sections.get("memory"):
            prompt_body_parts.append(f"\n[bold yellow]── Conversation Memory ──[/bold yellow]\n{prompt_sections['memory']}")

        augmented_panel_text = "\n".join(prompt_body_parts)
        trace_console.print(Panel(
            augmented_panel_text,
            title="[bold bright_blue]Augmented prompt (what the model actually reads)[/bold bright_blue]",
            border_style="bright_blue",
        ))
        trace_console.print()

        if not no_answer and trace.answer:
            src_str = ", ".join(trace.sources) if trace.sources else "None"
            md_ans = Markdown(trace.answer)
            trace_console.print(Panel(
                md_ans,
                subtitle=f"[dim]Sources: {src_str}[/dim]",
                title="[bold cyan]AI Answer & Sources[/bold cyan]",
                border_style="cyan",
            ))
            trace_console.print()
    else:
        print(f"\n--- Question: {trace.question} ---")
        print(f"Query terms: {trace.query_terms}")
        print("\n--- BM25 Hits ---")
        for idx, h in enumerate(trace.bm25_hits, start=1):
            print(f"  [{idx}] {h[1]}::{h[2]} (lines {h[3]}-{h[4]}, score={h[5]:.4f})")
        print("\n--- Dense Hits ---")
        for idx, h in enumerate(trace.dense_hits, start=1):
            print(f"  [{idx}] {h[1]}::{h[2]} (lines {h[3]}-{h[4]}, score={h[5]:.4f})")
        print("\n--- Merged RRF Ranking ---")
        for idx, h in enumerate(trace.fused_hits, start=1):
            print(f"  [{idx}] {h[1]}::{h[2]} (lines {h[3]}-{h[4]}, bm25_rank={h[6]}, dense_rank={h[7]}, rrf_score={h[8]:.5f})")
        if trace.fused_hits:
            print("\n--- Code Previews (Top Fused Chunks) ---")
            for idx, h in enumerate(trace.fused_hits, start=1):
                code_raw = trace.chunk_codes.get(h[0], "")
                lines = code_raw.strip().splitlines()
                preview = "\n".join(lines[:3]) if not full_code else code_raw
                print(f"[{idx}] {h[1]}::{h[2]} (lines {h[3]}-{h[4]}):")
                print(preview)
        print("\n--- Graph Additions ---")
        for idx, g in enumerate(trace.graph_additions, start=1):
            print(f"  [{idx}] {g[0]} reason={g[1]} caused_by={g[2]}")
        b = trace.budget
        print(f"\nBudget: {len(b.included_chunk_ids)} chunks, {b.used_tokens} / {b.max_tokens} tokens (Dropped: {len(b.dropped_chunk_ids)})")

        # Augmented prompt plain text
        prompt_sections = getattr(trace, "prompt_sections", {}) or {}
        instructions = prompt_sections.get("instructions", "")
        chunks_to_show = prompt_sections.get("context_chunks", [])
        print("\n=== Augmented prompt (what the model actually reads) ===")
        if instructions:
            print(f"Instructions:\n{instructions}\n")
        print("Context Chunks:")
        for idx, c_info in enumerate(chunks_to_show, start=1):
            c_code = c_info.get("code", "")
            c_lines = c_code.splitlines()
            c_preview = "\n".join(c_lines[:12]) if (not full_code and len(c_lines) > 12) else c_code
            print(f"[{idx}] {c_info.get('file')}:{c_info.get('lines')} ({c_info.get('symbol')})\n{c_preview}\n")
        print(f"Question: {trace.question}")
        if prompt_sections.get("memory"):
            print(f"Memory: {prompt_sections['memory']}")

        if not no_answer and trace.answer:
            print(f"\nAnswer:\n{trace.answer}\nSources: {trace.sources}")
        print()


def render_chunks_view(result, target_file: str, current_path: str):
    """
    Renders chunk-level indexing and vector inspection for a single file.
    Shows total lines, chunk count, symbol, line range, token estimate,
    first 3 lines of embedded text, embedding dimension, and vector preview.
    """
    if not target_file:
        print("[!] Usage: chunks: <filename>\n")
        return

    if not result or not getattr(result, "store", None) or not getattr(result.store, "chunks", []):
        print("[!] Repository index is empty (0 chunks). Ingest files first.\n")
        return

    # Match file in index
    norm_target = target_file.replace("\\", "/").lower().strip()
    matching_chunks = [
        c for c in result.store.chunks
        if norm_target == c.file_path.replace("\\", "/").lower()
        or norm_target == os.path.basename(c.file_path).lower()
        or c.file_path.replace("\\", "/").lower().endswith(norm_target)
    ]

    if not matching_chunks:
        print(f"[!] File '{target_file}' is not found in the index. (Run ingestion to index it.)\n")
        return

    rep_chunk = matching_chunks[0]
    total_lines = 0
    full_path = os.path.join(current_path, rep_chunk.file_path) if current_path else rep_chunk.file_path
    if os.path.isfile(full_path):
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                total_lines = len(f.readlines())
        except Exception:
            pass
    if total_lines == 0:
        total_lines = max(c.end_line for c in matching_chunks)

    num_chunks = len(matching_chunks)
    dim = getattr(result.store, "dim", 0)

    if HAS_RICH and console:
        import shutil
        term_width = shutil.get_terminal_size((120, 24)).columns if hasattr(shutil, "get_terminal_size") else 120
        c_console = Console(width=max(term_width, 100))

        c_console.print()
        c_console.print(Panel(
            f"[bold cyan]File:[/bold cyan] {rep_chunk.file_path}\n"
            f"[bold green]Total Lines:[/bold green] {total_lines} | [bold yellow]Indexed Chunks:[/bold yellow] {num_chunks} | [bold magenta]Embedding Dim:[/bold magenta] {dim}",
            title="[bold bright_blue]Chunk & Vector Index Inspection[/bold bright_blue]",
            border_style="bright_blue",
        ))

        t = Table(title=f"Chunks for {os.path.basename(rep_chunk.file_path)}", border_style="cyan", padding=(0, 1))
        t.add_column("Chunk", style="dim", width=7)
        t.add_column("Symbol", style="bold cyan", overflow="fold")
        t.add_column("Lines", style="yellow", width=10)
        t.add_column("Tokens", style="dim", width=8, justify="right")
        t.add_column("Embedded Text (First 3 Lines)", style="white")
        t.add_column("Dim", style="dim", width=6, justify="right")
        t.add_column("Vector Preview (First 6)", style="green")

        for idx, c in enumerate(matching_chunks, start=1):
            sym = c.name or "—"
            lines_str = f"{c.start_line}–{c.end_line}"
            token_est = int(len(c.code) / 3.5)
            emb_text = c.as_embedding_text()
            emb_3 = "\n".join(emb_text.splitlines()[:3])

            vec_idx = result.store.chunks.index(c)
            vec = result.store.get_vector(vec_idx) if hasattr(result.store, "get_vector") else None
            if vec is not None and len(vec) >= 6:
                v6 = [f"{float(x):.4f}" for x in vec[:6]]
                vec_str = "[" + ", ".join(v6) + ", ...]"
                v_dim = str(len(vec))
            elif vec is not None:
                vec_str = "[" + ", ".join(f"{float(x):.4f}" for x in vec) + "]"
                v_dim = str(len(vec))
            else:
                vec_str = "[...]"
                v_dim = str(dim)

            t.add_row(f"[{idx}]", sym, lines_str, str(token_est), emb_3, v_dim, vec_str)

        c_console.print(t)
        c_console.print()
    else:
        print(f"\n=== Chunk & Vector Index Inspection: {rep_chunk.file_path} ===")
        print(f"Total lines: {total_lines} | Number of chunks: {num_chunks} | Embedding dim: {dim}\n")
        for idx, c in enumerate(matching_chunks, start=1):
            sym = c.name or "—"
            lines_str = f"{c.start_line}-{c.end_line}"
            token_est = int(len(c.code) / 3.5)
            emb_text = c.as_embedding_text()
            emb_3 = " / ".join(emb_text.splitlines()[:3])

            vec_idx = result.store.chunks.index(c)
            vec = result.store.get_vector(vec_idx) if hasattr(result.store, "get_vector") else None
            if vec is not None and len(vec) >= 6:
                v6 = [f"{float(x):.4f}" for x in vec[:6]]
                vec_str = "[" + ", ".join(v6) + ", ...]"
                v_dim = len(vec)
            else:
                vec_str = "[...]"
                v_dim = dim

            print(f"[{idx}] symbol: {sym} | lines: {lines_str} | tokens: ~{token_est} | dim: {v_dim}")
            print(f"    embedded text: {emb_3}")
            print(f"    vector: {vec_str}\n")


def render_index_stats(result, embedder):
    """
    Renders comprehensive index statistics across the repository.
    Shows: files, chunks, graph nodes, embedder used, BM25 vocabulary size, FAISS vector count.
    """
    if not result or not getattr(result, "store", None):
        print("[!] Repository index is empty. Ingest files first.\n")
        return

    files_count = len(result.files) if getattr(result, "files", None) else len(set(c.file_path for c in result.store.chunks))
    chunks_count = len(result.store.chunks)
    graph_nodes = result.graph.number_of_nodes() if getattr(result, "graph", None) else 0
    embedder_name = getattr(result, "embedder_name", None) or type(embedder).__name__
    if embedder_name == "TfidfEmbedder":
        embedder_name = "TF-IDF (offline)"
    elif embedder_name == "OllamaEmbedder":
        embedder_name = "Ollama (dense)"

    bm25_vocab = len(result.lexical_index.inverted_index) if getattr(result, "lexical_index", None) else 0
    faiss_count = result.store.index.ntotal if hasattr(result.store, "index") else chunks_count

    if HAS_RICH and console:
        t = Table(title="Index & Pipeline Statistics", border_style="bright_blue", padding=(0, 2))
        t.add_column("Metric", style="bold cyan")
        t.add_column("Value", style="bold green", justify="right")
        t.add_row("Indexed Files", str(files_count))
        t.add_row("Code Chunks", str(chunks_count))
        t.add_row("Dependency Graph Nodes", str(graph_nodes))
        t.add_row("Embedder Used", str(embedder_name))
        t.add_row("BM25 Vocabulary Size", f"{bm25_vocab:,} terms")
        t.add_row("FAISS Vector Count", f"{faiss_count:,} vectors")
        console.print()
        console.print(t)
        console.print()
    else:
        print("\n=== Index Statistics ===")
        print(f"  Files: {files_count}")
        print(f"  Chunks: {chunks_count}")
        print(f"  Graph nodes: {graph_nodes}")
        print(f"  Embedder used: {embedder_name}")
        print(f"  BM25 vocabulary size: {bm25_vocab} terms")
        print(f"  FAISS vector count: {faiss_count} vectors\n")


def render_compare_panels(no_rag_ans: str, elapsed_no_rag: float, rag_ans: str, elapsed_rag: float):
    """
    Renders comparative views: without RAG vs. with RAG.
    """
    if HAS_RICH and console:
        console.print()
        console.print(Panel(
            Markdown(no_rag_ans or "*(no response)*"),
            title=f"[bold yellow]Without RAG (No Context)[/bold yellow] — [dim]{elapsed_no_rag:.2f}s[/dim]",
            border_style="yellow",
        ))
        console.print(Panel(
            Markdown(rag_ans or "*(no response)*"),
            title=f"[bold green]With RAG (Repository Context)[/bold green] — [dim]{elapsed_rag:.2f}s[/dim]",
            border_style="green",
        ))
        console.print()
    else:
        print(f"\n{'='*70}")
        print(f"WITHOUT RAG (No Context) — {elapsed_no_rag:.2f}s")
        print(f"{'='*70}\n{no_rag_ans}\n")
        print(f"{'='*70}")
        print(f"WITH RAG (Repository Context) — {elapsed_rag:.2f}s")
        print(f"{'='*70}\n{rag_ans}\n")


def execute_explain_command(engine, result, raw_input: str, active_file_filter: Optional[str] = None):
    """
    Unified execution handler for explain: commands across interactive and batch modes.
    """
    raw = raw_input.split(":", 1)[1].strip() if ":" in raw_input else raw_input.split(maxsplit=1)[1].strip()
    parts = raw.split()
    no_answer = False
    as_json = False
    full_code = False
    compare_mode = False
    cli_width = None
    top_k = 5
    clean_parts = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p == "--no-answer":
            no_answer = True
        elif p == "--json":
            as_json = True
        elif p == "--full":
            full_code = True
        elif p == "--compare":
            compare_mode = True
        elif p.startswith("--width="):
            try:
                cli_width = int(p.split("=", 1)[1])
            except ValueError:
                pass
        elif p == "--width" and i + 1 < len(parts):
            try:
                cli_width = int(parts[i + 1])
                i += 1
            except ValueError:
                pass
        elif p.startswith("--top-k="):
            try:
                top_k = int(p.split("=", 1)[1])
            except ValueError:
                pass
        elif p == "--top-k" and i + 1 < len(parts):
            try:
                top_k = int(parts[i + 1])
                i += 1
            except ValueError:
                pass
        else:
            clean_parts.append(p)
        i += 1

    explain_q = " ".join(clean_parts).strip()
    if not explain_q:
        print("[!] Usage: explain: <question> [--no-answer] [--json] [--full] [--compare] [--width N] [--top-k N]\n")
        return

    if not getattr(result, "store", None) or not getattr(result.store, "chunks", []):
        print("[!] Repository index is empty (0 chunks). Ingest files first.\n")
        return

    # Handle --compare validation
    no_rag_ans = None
    elapsed_no_rag = 0.0
    if compare_mode:
        if no_answer:
            print("[!] Note: --compare requires the LLM; ignored because --no-answer was specified.\n")
            compare_mode = False
        elif engine.llm is None:
            print("[!] Note: --compare requires an LLM backend (e.g. Ollama). Current backend has no LLM.\n")
            compare_mode = False

    cleaned_explain_q, mention_file = parse_mention(explain_q)
    effective_filter = mention_file if mention_file else active_file_filter
    search_query = cleaned_explain_q if cleaned_explain_q else (mention_file or explain_q)

    if compare_mode and engine.llm is not None:
        t0_no = time.perf_counter()
        no_rag_system = "Answer from your own knowledge, say if you cannot see the code."
        no_rag_prompt = f"Question: {search_query}\nAnswer:"
        no_rag_ans = engine.llm.generate(no_rag_prompt, system=no_rag_system)
        elapsed_no_rag = time.perf_counter() - t0_no

    from core.retrieval_trace import RetrievalTrace
    trace = RetrievalTrace()
    engine.ask(
        search_query,
        top_k=top_k,
        file_filter=effective_filter,
        trace=trace,
        no_answer=no_answer,
    )

    if as_json:
        import json
        trace_dict = trace.to_dict()
        if compare_mode and no_rag_ans is not None:
            trace_dict["compare"] = {
                "without_rag": {"answer": no_rag_ans, "elapsed_seconds": round(elapsed_no_rag, 3)},
                "with_rag": {"answer": trace.answer, "elapsed_seconds": round(trace.timings_ms.get("llm", 0.0) / 1000.0, 3)},
            }
        print(json.dumps(trace_dict, indent=2))
        print()
    else:
        render_retrieval_trace(trace, full_code=full_code, no_answer=no_answer, terminal_width=cli_width)
        if compare_mode and no_rag_ans is not None:
            elapsed_rag = trace.timings_ms.get("llm", 0.0) / 1000.0
            render_compare_panels(no_rag_ans, elapsed_no_rag, trace.answer or "", elapsed_rag)


class IntelliCodeXCompleter(Completer if HAS_PROMPT_TOOLKIT else object):
    """Context-aware autocompleter for commands, files, symbols, and settings."""

    COMMANDS = [
        ("explain:", "Inspect RAG retrieval, augmented prompt & fusion provenance"),
        ("chunks:", "Inspect index chunks and vector previews for a file"),
        ("index-stats", "Show comprehensive index statistics across the repository"),
        ("help", "Show available CLI commands"),
        ("?", "Show available CLI commands"),
        ("exit", "Exit IntelliCodeX CLI"),
        ("quit", "Exit IntelliCodeX CLI"),
        ("clear", "Clear terminal screen"),
        ("cls", "Clear terminal screen"),
        ("files", "List all indexed repository files"),
        ("ls", "List all indexed repository files"),
        ("top", "Show PageRank centrality rankings"),
        ("centrality", "Show PageRank centrality rankings"),
        ("repos", "List all known local & cloned repositories"),
        ("list-repos", "List all known repositories"),
        ("repo ", "Switch active repository by path, URL, or number"),
        ("backend ", "Switch backend engine (ollama | tfidf)"),
        ("persona ", "Switch AI persona (general, security, reviewer, refactor, fixer)"),
        ("model ", "Switch Ollama LLM model"),
        ("file:", "Set persistent file filter for all queries"),
        ("history", "View conversation history"),
        ("chat", "View conversation history"),
        ("clear-chat", "Clear conversation history"),
        ("hooks", "Install Git background re-indexing hooks"),
        ("setup-hooks", "Install Git background re-indexing hooks"),
        ("hooks:status", "Check Git hooks installation status"),
        ("hooks:remove", "Uninstall Git background re-indexing hooks"),
        ("watch", "Check real-time filesystem watcher status"),
        ("watch:status", "Check filesystem watcher status"),
        ("watch:stop", "Stop real-time filesystem watcher"),
        ("watch:start", "Start real-time filesystem watcher"),
        ("hybrid", "Check BM25 hybrid search status"),
        ("hybrid:status", "Check hybrid search status"),
        ("hybrid:on", "Enable hybrid BM25 lexical ranking"),
        ("hybrid:off", "Disable hybrid search (dense only)"),
        ("hybrid:toggle", "Toggle hybrid BM25 search on/off"),
        ("deps:", "Inspect reverse dependency impact for a file"),
        ("callers:", "Find all function callers across repository AST"),
        ("fix:", "Diagnose error and generate automated sandbox patch"),
        ("review", "List pending patch proposals awaiting developer review"),
        ("approve ", "Approve and apply a pending patch proposal (e.g. 'approve <id>')"),
        ("reject ", "Reject and discard a pending patch proposal (e.g. 'reject <id>')"),
        ("doc:", "Generate documentation for symbol or file using call graph (e.g. 'doc:login')"),
        ("security:", "Run Bandit AST security vulnerability scanner on target file (e.g. 'security:auth.py')"),
        ("search:", "Fast retrieval-only search (no LLM, instant results)"),
        ("info:", "Show indexed file details: size, chunk count, centrality"),
        ("export:", "Save last AI answer to a Markdown file"),
        ("status", "Show full system status at a glance"),
        ("version", "Show IntelliCodeX version"),
        ("@", "Scope query to a specific file (one-shot)"),
    ]

    PERSONAS = ["general", "security", "reviewer", "refactor", "fixer"]
    BACKENDS = ["ollama", "tfidf"]
    COMMON_ERRORS = [
        "KeyError", "IndexError", "TypeError", "ValueError",
        "ZeroDivisionError", "AttributeError", "FileNotFoundError"
    ]

    def __init__(self, get_files_fn=None, get_symbols_fn=None, get_repos_fn=None):
        self.get_files_fn = get_files_fn
        self.get_symbols_fn = get_symbols_fn
        self.get_repos_fn = get_repos_fn

    def get_completions(self, document, complete_event=None):
        if not HAS_PROMPT_TOOLKIT or Completion is None:
            return

        text = document.text_before_cursor
        stripped = text.lstrip(">").lstrip("$").lstrip()

        # 0. @mention completion: @filename
        if "@" in stripped:
            # Find the @ symbol and everything after it
            at_pos = stripped.rfind("@")
            arg = stripped[at_pos + 1:]
            if self.get_files_fn:
                files = self.get_files_fn() or []
                for f in files:
                    # Match against both full path and basename
                    basename = os.path.basename(f)
                    if arg.lower() in f.lower() or arg.lower() in basename.lower():
                        # Return the matching part for display, but complete with basename by default
                        # If user typed a path separator, complete with full path
                        if "/" in arg or "\\" in arg:
                            display_text = f.replace("\\", "/")
                            yield Completion(display_text, start_position=-len(arg), display=display_text, display_meta="File")
                        else:
                            yield Completion(basename, start_position=-len(arg), display=basename, display_meta="File")
            return

        # 0b. Parameter completion: chunks:<file> or chunks <file>
        for prefix in ("chunks:", "chunks "):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        if arg.lower() in f.lower():
                            yield Completion(f, start_position=-len(arg), display=f, display_meta="File")
                return

        # 1. Parameter completion: deps:<file> or deps <file>
        for prefix in ("deps:", "deps "):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        if arg.lower() in f.lower():
                            yield Completion(f, start_position=-len(arg), display=f, display_meta="File")
                return

        # 2. Parameter completion: fix:<file_or_err> or fix <file_or_err>
        for prefix in ("fix:", "fix "):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                for err in self.COMMON_ERRORS:
                    if arg.lower() in err.lower():
                        yield Completion(err, start_position=-len(arg), display=err, display_meta="Error")
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        if arg.lower() in f.lower():
                            yield Completion(f, start_position=-len(arg), display=f, display_meta="File")
                return

        # 3. Parameter completion: callers:<symbol> or callers <symbol>
        for prefix in ("callers:", "callers "):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_symbols_fn:
                    symbols = self.get_symbols_fn() or []
                    for sym in symbols:
                        if arg.lower() in sym.lower():
                            yield Completion(sym, start_position=-len(arg), display=sym, display_meta="Symbol")
                return

        # 4. Parameter completion: persona <name>
        if stripped.startswith("persona "):
            arg = stripped[len("persona "):]
            for p in self.PERSONAS:
                if p.lower().startswith(arg.lower()):
                    yield Completion(p, start_position=-len(arg), display=p, display_meta="Persona")
            return

        # 5. Parameter completion: backend <name>
        if stripped.startswith("backend "):
            arg = stripped[len("backend "):]
            for b in self.BACKENDS:
                if b.lower().startswith(arg.lower()):
                    yield Completion(b, start_position=-len(arg), display=b, display_meta="Backend")
            return

        # 6. Parameter completion: repo <name_or_number>
        if stripped.startswith("repo "):
            arg = stripped[len("repo "):]
            if self.get_repos_fn:
                repos = self.get_repos_fn() or []
                for idx, (lbl, p) in enumerate(repos, start=1):
                    s_idx = str(idx)
                    if s_idx.startswith(arg):
                        yield Completion(s_idx, start_position=-len(arg), display=f"[{s_idx}] {lbl}", display_meta="Repo Number")
                    if lbl.lower().startswith(arg.lower()):
                        yield Completion(lbl, start_position=-len(arg), display=lbl, display_meta="Repo Name")
            return

        # 7. Sub-command completions
        for group, options in (("hybrid:", ("status", "on", "off", "toggle")),
                               ("watch:", ("status", "start", "stop")),
                               ("hooks:", ("status", "remove", "install"))):
            if stripped.startswith(group):
                sub = stripped[len(group):]
                for opt in options:
                    if opt.startswith(sub.lower()):
                        full_cmd = f"{group}{opt}"
                        yield Completion(full_cmd, start_position=-len(stripped), display=full_cmd, display_meta="Command")
                return

        # 8. Top-level commands
        for cmd, desc in self.COMMANDS:
            if cmd.lower().startswith(stripped.lower()):
                yield Completion(cmd, start_position=-len(stripped), display=cmd, display_meta=desc)
def create_components(backend_choice: str):
    """Factory helper to instantiate embedder and LLM with automatic fallback."""
    if backend_choice == "ollama":
        if check_ollama_available():
            print("[*] Backend: Ollama AI (qwen2.5-coder + nomic-embed-text)")
            return OllamaEmbedder(), OllamaLLM(), "ollama"
        else:
            print("[!] Ollama server not detected at http://localhost:11434.")
            print("[*] Automatically falling back to offline TF-IDF mode.")
            return TfidfEmbedder(), None, "tfidf"
    else:
        print("[*] Backend: Offline TF-IDF Mode")
        return TfidfEmbedder(), None, "tfidf"


from core.benchmarking import run_benchmark

class RemoteClient:
    """Client for querying a remote IntelliCodeX FastAPI server over REST endpoints."""

    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def ask(self, repo_id: str, question: str, top_k: int = 5, file_filter: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/api/chat/ask"
        payload = {"repo_id": repo_id, "question": question, "top_k": top_k}
        if file_filter:
            payload["file_filter"] = file_filter
        resp = requests.post(url, json=payload, headers=self.headers, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def localize_bug(self, repo_id: str, error_report: str, top_k: int = 5) -> Dict[str, Any]:
        url = f"{self.base_url}/api/bugs/localize"
        resp = requests.post(url, json={"repo_id": repo_id, "error_report": error_report, "top_k": top_k}, headers=self.headers, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def generate_patch(self, repo_id: str, file_path: str, bug_description: str) -> Dict[str, Any]:
        url = f"{self.base_url}/api/patches/generate"
        resp = requests.post(url, json={"repo_id": repo_id, "file_path": file_path, "bug_description": bug_description}, headers=self.headers, timeout=120)
        resp.raise_for_status()
        return resp.json()

    def generate_docs(self, repo_id: str, target: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/api/docs/generate"
        params = {"repo_id": repo_id}
        if target:
            params["target"] = target
        resp = requests.post(url, params=params, headers=self.headers, timeout=120)
        resp.raise_for_status()
        return resp.json()


VERSION = "1.0.0"


def main():
    parser = argparse.ArgumentParser(description="IntelliCodeX CLI — AI Repository Intelligence")
    parser.add_argument("repo_path", nargs="?", default="sample_repo",
                        help="Local directory path or Git URL (default: sample_repo)")
    parser.add_argument("--server", type=str, default=None,
                        help="Remote IntelliCodeX server URL (e.g., http://localhost:8000)")
    parser.add_argument("--token", type=str, default=None,
                        help="JWT Bearer authentication token for remote server access")
    parser.add_argument("--backend", choices=["ollama", "tfidf"], default="tfidf",
                        help="LLM & Embedding backend (default: tfidf)")
    parser.add_argument("-q", "--query", type=str,
                        help="Execute a non-interactive query in batch mode and exit")
    parser.add_argument("--tui", action="store_true", default=False,
                        help="Force enable rich interactive TUI with auto-completion and toolbar")
    parser.add_argument("--no-tui", action="store_true", default=False,
                        help="Disable rich TUI and use standard terminal input")
    parser.add_argument("--benchmark", action="store_true",
                        help="Run performance benchmark on target repository and exit")
    parser.add_argument("--setup-hooks", action="store_true",
                        help="Install Git background re-indexing hooks for target repository")
    parser.add_argument("--check-hooks", action="store_true",
                        help="Check status of Git background re-indexing hooks")
    parser.add_argument("--remove-hooks", action="store_true",
                        help="Uninstall Git background re-indexing hooks")
    parser.add_argument("-v", "--version", action="version", version=f"IntelliCodeX CLI v{VERSION}")
    args = parser.parse_args()

    if args.benchmark:
        target = resolve_repo_path(args.repo_path)
        print(f"[*] Running IntelliCodeX Benchmark on '{target}'...")
        report = run_benchmark(target)
        print("=" * 65)
        print(f"Benchmark Target       : {report.repo_path}")
        print(f"Total Files Ingested   : {report.num_files}")
        print(f"Total Chunks Extracted : {report.num_chunks}")
        print(f"AST Chunks Count       : {report.ast_chunks_count} ({report.ast_ratio_percent}%)")
        print(f"Fresh Ingestion Time   : {report.total_time_seconds}s ({report.files_per_second} files/sec)")
        print(f"Cached Reload Time     : {report.cached_time_seconds}s ({report.speedup_factor}x faster)")
        print(f"Query Latency          : {report.query_latency_ms} ms")
        print(f"Graph Expansion Ratio  : {report.graph_expansion_ratio}x")
        print(f"RAM Memory Impact      : {report.memory_used_mb} MB")
        print("=" * 65)
        return 0

    # Handle direct hook CLI flags if requested
    if args.setup_hooks:
        target = resolve_repo_path(args.repo_path)
        ok, msg = install_git_hooks(target)
        print(f"[*] {msg}")
        return 0 if ok else 1

    if args.check_hooks:
        target = resolve_repo_path(args.repo_path)
        st = check_git_hooks_status(target)
        print(f"[*] Git Hook Status for '{target}':")
        for hook, is_inst in st.items():
            print(f"  - {hook}: {'Installed' if is_inst else 'Not Installed'}")
        return 0

    if args.remove_hooks:
        target = resolve_repo_path(args.repo_path)
        ok, msg = uninstall_git_hooks(target)
        print(f"[*] {msg}")
        return 0 if ok else 1

    render_banner()

    # Remote Server CLI Bridge Mode
    if args.server:
        client = RemoteClient(args.server, token=args.token)
        repo_id = os.path.basename(args.repo_path.rstrip("/\\")) or args.repo_path
        print(f"[*] Connected to Remote Server: {args.server}")
        print(f"[*] Remote Repository Target: {repo_id}")
        if args.query:
            cleaned_query, mention_file = parse_mention(args.query)
            t_batch = time.perf_counter()
            try:
                res = client.ask(repo_id, cleaned_query, file_filter=mention_file)
                total_batch = time.perf_counter() - t_batch
                render_markdown_panel(res.get("answer", ""), title=f"Remote Answer ({repo_id})")
                print(f"[*] [Time Consumed]: {format_time_consumed(total_batch)} (Confidence: {res.get('confidence_score', 0.0)})\n")
                return 0
            except Exception as e:
                print(f"[!] Remote query failed: {e}")
                return 1

        # Interactive loop for remote server
        print("\nRemote IntelliCodeX session ready. Type a question or 'exit' to quit.\n")
        while True:
            try:
                q = input("remote>> ").strip()
                if not q:
                    continue
                if q.lower() in ("exit", "quit", "q"):
                    print("[*] Exiting Remote Session.")
                    return 0
                cleaned_q, mention = parse_mention(q)
                t0 = time.perf_counter()
                res = client.ask(repo_id, cleaned_q, file_filter=mention)
                elapsed = time.perf_counter() - t0
                render_markdown_panel(res.get("answer", ""), title=f"Remote Answer ({repo_id})")
                print(f"[*] [Time Consumed]: {format_time_consumed(elapsed)} (Confidence: {res.get('confidence_score', 0.0)})\n")
            except (KeyboardInterrupt, EOFError):
                print("\n[*] Exiting Remote Session.")
                return 0
            except Exception as e:
                print(f"[!] Error: {e}\n")

    embedder, llm, active_backend = create_components(args.backend)

    try:
        current_path = resolve_repo_path(args.repo_path)
        print(f"[*] Ingesting repository: {current_path}")
        t0 = time.perf_counter()
        result = ingest_repository(current_path, embedder)
        elapsed = result.elapsed_seconds if getattr(result, "elapsed_seconds", 0) > 0 else (time.perf_counter() - t0)
    except KeyboardInterrupt:
        print("\n[!] Initial repository ingestion cancelled by user (Ctrl+C).")
        if args.repo_path != "sample_repo" and os.path.exists("sample_repo"):
            print("[*] Falling back to default 'sample_repo'...")
            try:
                current_path = "sample_repo"
                result = ingest_repository(current_path, embedder)
                elapsed = result.elapsed_seconds if getattr(result, "elapsed_seconds", 0) > 0 else 0.1
            except Exception as e_inner:
                print(f"[!] Fallback error: {e_inner}")
                return 1
        else:
            print("[*] Exiting.")
            return 0
    except Exception as e:
        print(f"[!] Error ingesting repository '{args.repo_path}': {e}")
        return 1

    render_ingestion_panel(result, current_path, elapsed)

    engine = QueryEngine(
        result.store,
        embedder,
        llm,
        dep_graph=result.graph,
        call_graph=getattr(result, "call_graph", None),
        lexical_index=getattr(result, "lexical_index", None),
        hybrid_search=True,
    )

    # Batch Query Non-Interactive Mode
    if args.query:
        bq = args.query.strip()
        if bq.lower().startswith("chunks:") or bq.lower().startswith("chunks "):
            target_f = bq.split(":", 1)[1].strip() if ":" in bq else bq.split(maxsplit=1)[1].strip()
            render_chunks_view(result, target_f, current_path)
            return 0

        if bq.lower() in ("index-stats", "index_stats", "indexstats", "stats"):
            render_index_stats(result, embedder)
            return 0

        if bq.lower().startswith("explain:") or bq.lower().startswith("explain "):
            execute_explain_command(engine, result, bq, active_file_filter=None)
            return 0

        # Parse @mention from batch query as well
        cleaned_query, mention_file = parse_mention(args.query)
        
        # Priority logic: @mention > active_file_filter > none
        active_file_filter = None  # Not applicable in batch mode
        effective_file_filter = mention_file if mention_file else active_file_filter
        
        # Visual feedback for batch mode
        if mention_file:
            print(f"[*] Scoping to file: '{mention_file}'")
        elif active_file_filter:
            print(f"[*] Using active file filter: '{active_file_filter}'")
        
        print(f"\n[*] Executing Batch Query: '{cleaned_query}'\n")
        t_batch = time.perf_counter()
        response = engine.ask(cleaned_query, file_filter=effective_file_filter)
        total_batch = response.get("elapsed_seconds", time.perf_counter() - t_batch)
        render_markdown_panel(response['answer'], title="Answer")
        print(f"[*] [Time Consumed]: {format_time_consumed(total_batch)} (Retrieval: {format_time_consumed(response.get('retrieval_seconds', 0.0))}, Generation: {format_time_consumed(response.get('llm_seconds', 0.0))})\n")
        return 0

    def on_auto_reindex(new_result, changed_paths, elapsed_s):
        nonlocal result, engine
        result = new_result
        engine = QueryEngine(
            result.store,
            embedder,
            llm,
            dep_graph=result.graph,
            call_graph=getattr(result, "call_graph", None),
            lexical_index=getattr(result, "lexical_index", None),
            hybrid_search=getattr(engine, "hybrid_search", True),
        )
        changed_names = [os.path.basename(p) for p in changed_paths[:3]]
        diff_desc = ", ".join(changed_names) if changed_names else "files"
        if len(changed_paths) > 3:
            diff_desc += f" (+{len(changed_paths)-3} more)"
        t_str = format_time_consumed(elapsed_s)
        # B4 fix: use rich console so the watchdog message doesn't corrupt the TUI prompt line
        if HAS_RICH and console:
            console.print(
                f"\n[bold yellow][[Watchdog]][/bold yellow] Detected changes in "
                f"[cyan]{diff_desc}[/cyan]. Auto-reindexed "
                f"([bold]{result.num_chunks}[/bold] chunks in [green]{t_str}[/green])."
            )
        else:
            sys.stdout.write(
                f"\n[*] [Watchdog] Detected changes in {diff_desc}. "
                f"Auto-reindexed ({result.num_chunks} chunks in {t_str}).\n"
            )
            sys.stdout.flush()

    watcher = None
    try:
        watcher = RepositoryWatcher(
            repo_path=current_path,
            embedder=embedder,
            on_reindex=on_auto_reindex,
            debounce_delay=0.5,
        )
        if watcher.start():
            print("[*] Real-Time Watcher: Active (background auto-reindex enabled)")
    except Exception:
        pass

    # Configure auto-completion and rich session
    def get_indexed_files():
        if result and getattr(result, "store", None) and result.store.chunks:
            return sorted(list(set(c.file_path for c in result.store.chunks)))
        return []

    def get_indexed_symbols():
        # B5 fix: preserve file::symbol format to avoid duplicate bare names
        syms = set()
        if result:
            call_g = getattr(result, "call_graph", None)
            if call_g:
                syms.update(call_g.nodes())
            if getattr(result, "store", None) and result.store.chunks:
                for c in result.store.chunks:
                    if c.name:
                        file_base = os.path.basename(c.file_path) if c.file_path else ""
                        if file_base:
                            syms.add(f"{file_base}::{c.name}")  # qualified for disambiguation
                        syms.add(c.name)  # bare name for quick completion
        return sorted(list(syms))

    completer = IntelliCodeXCompleter(
        get_files_fn=get_indexed_files,
        get_symbols_fn=get_indexed_symbols,
        get_repos_fn=lambda: get_available_repos(current_path),
    )

    if getattr(args, "no_tui", False):
        use_tui = False
    elif getattr(args, "tui", False):
        use_tui = HAS_PROMPT_TOOLKIT
    else:
        use_tui = should_use_tui()

    session = None
    if use_tui:
        _history_path = os.path.join(".storage", "cli_history")
        os.makedirs(".storage", exist_ok=True)
        try:
            _hist = FileHistory(_history_path) if FileHistory else InMemoryHistory()
        except Exception:
            _hist = InMemoryHistory() if InMemoryHistory else None
        session = create_interactive_session(completer=completer, history=_hist)
        if session is None:
            use_tui = False

    print("\nIntelliCodeX ready. Type a question or 'help' for options, 'exit' to quit.\n")

    _last_answer: str = ""  # tracks last AI answer for the export: command
    active_file_filter: Optional[str] = None  # tracks active file scope for queries

    while True:
        try:
            if session is not None and use_tui:
                def get_toolbar():
                    watcher_st = "ON" if (watcher and watcher.is_alive()) else "OFF"
                    hybrid_st = "ON" if getattr(engine, "hybrid_search", True) else "OFF"
                    repo_label = os.path.basename(current_path) or current_path
                    return HTML(
                        f" <b>Repo:</b> <ansicyan>{repo_label}</ansicyan> | "
                        f"<b>Backend:</b> <ansiyellow>{active_backend}</ansiyellow> | "
                        f"<b>Persona:</b> <ansigreen>{engine.active_persona}</ansigreen> | "
                        f"<b>Hybrid:</b> {hybrid_st} | "
                        f"<b>Watcher:</b> {watcher_st} "
                    )
                try:
                    query = session.prompt(">> ", bottom_toolbar=get_toolbar).strip()
                except Exception:
                    use_tui = False
                    query = input(">> ").strip()
            else:
                query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting IntelliCodeX CLI. Goodbye!")
            break

        while query.startswith(">") or query.startswith("$"):
            query = query.lstrip(">").lstrip("$").strip()

        if not query:
            continue

        if query.lower() in ("exit", "quit"):
            print("Exiting IntelliCodeX CLI. Goodbye!")
            break

        if query.lower() in ("help", "?"):
            render_help_panel()
            continue

        if query.lower() == "version":
            if HAS_RICH and console:
                console.print(Panel(
                    Text(f"IntelliCodeX CLI  v{VERSION}", style="bold cyan"),
                    border_style="cyan", padding=(0, 2),
                ))
            else:
                print(f"IntelliCodeX CLI v{VERSION}")
            continue

        if query.lower() in ("clear", "cls"):
            os.system("cls" if os.name == "nt" else "clear")
            render_banner()
            continue

        if query.lower() == "status":
            render_status_panel(current_path, active_backend, engine, watcher)
            continue

        if query.lower() in ("index-stats", "index_stats", "indexstats"):
            render_index_stats(result, embedder)
            continue

        if query.lower() in ("files", "ls"):
            indexed_files = sorted(list(set(c.file_path for c in result.store.chunks)))
            render_files_table(indexed_files)
            continue

        if query.lower() in ("top", "centrality"):
            t_top = time.perf_counter()
            top_files = get_top_central_files(result.graph, top_n=5)
            call_g = getattr(result, "call_graph", None)
            top_syms = get_top_central_symbols(call_g, top_n=5) if call_g else None
            render_centrality_tables(top_files, top_syms)
            print(f"[*] [Time Consumed]: Centrality computed in {format_time_consumed(time.perf_counter() - t_top)}\n")
            continue

        if query.lower().startswith("backend "):
            new_backend = query.split(maxsplit=1)[1].strip().lstrip("-").lower()
            if new_backend not in ("ollama", "tfidf"):
                print("[!] Invalid backend. Choose 'ollama' or 'tfidf'.\n")
                continue
            try:
                new_embedder, new_llm, new_active_backend = create_components(new_backend)
                print(f"[*] Re-indexing repository with '{new_active_backend}' backend...")
                t_sw = time.perf_counter()
                new_result = ingest_repository(current_path, new_embedder)
                elapsed_sw = new_result.elapsed_seconds if getattr(new_result, "elapsed_seconds", 0) > 0 else (time.perf_counter() - t_sw)
                embedder, llm, active_backend = new_embedder, new_llm, new_active_backend
                result = new_result
                engine = QueryEngine(
                    result.store,
                    embedder,
                    llm,
                    dep_graph=result.graph,
                    call_graph=getattr(result, "call_graph", None),
                    lexical_index=getattr(result, "lexical_index", None),
                    hybrid_search=getattr(engine, "hybrid_search", True),
                )
                render_ingestion_panel(result, current_path, elapsed_sw)
                print(f"[*] Backend updated to '{active_backend}'.\n")
                if watcher:
                    watcher.embedder = embedder
            except KeyboardInterrupt:
                print(f"\n[!] Backend switch interrupted by user (Ctrl+C). Active backend remains '{active_backend}'.\n")
            except Exception as e_be:
                print(f"[!] Error switching backend: {e_be}\n")
            continue

        # --- repos / list-repos: show all known repos with numbered selection ---
        if query.lower() in ("repos", "list-repos", "list repos", "show repos"):
            available = get_available_repos(current_path)
            render_repos_table(available, current_path)
            continue

        if (query.startswith("repo ") or query.startswith("repo:") or 
            query.startswith("use ") or query.startswith("ingest ") or 
            query.startswith("http://") or query.startswith("https://") or query.startswith("git@")):

            if query.startswith("repo:"):
                target = query[len("repo:"):].strip()
            elif query.startswith("repo ") or query.startswith("use ") or query.startswith("ingest "):
                target = query.split(maxsplit=1)[1].strip()
            else:
                target = query

            # Support switching by list number: 'repo 2'
            if target.isdigit():
                available = get_available_repos(current_path)
                idx = int(target) - 1
                if 0 <= idx < len(available):
                    target = available[idx][1]  # use the abs_path
                    print(f"[*] Selected: {available[idx][0]} -> {target}")
                else:
                    print(f"[!] Invalid number '{target}'. Run 'repos' to see the list.\n")
                    continue

            print(f"[*] Processing repository target: {target}")
            try:
                new_path = resolve_repo_path(target)
                print(f"[*] Parsing files and generating embeddings for '{new_path}'...")
                t_repo = time.perf_counter()
                new_result = ingest_repository(new_path, embedder)
                elapsed_repo = new_result.elapsed_seconds if getattr(new_result, "elapsed_seconds", 0) > 0 else (time.perf_counter() - t_repo)
                result = new_result
                current_path = new_path
                engine = QueryEngine(
                    result.store,
                    embedder,
                    llm,
                    dep_graph=result.graph,
                    call_graph=getattr(result, "call_graph", None),
                    lexical_index=getattr(result, "lexical_index", None),
                    hybrid_search=getattr(engine, "hybrid_search", True),
                )
                render_ingestion_panel(result, current_path, elapsed_repo)
                print(f"[*] Successfully switched active repository to '{new_path}'!\n")

                if watcher:
                    watcher.stop()
                try:
                    watcher = RepositoryWatcher(current_path, embedder, on_reindex=on_auto_reindex, debounce_delay=0.5)
                    watcher.start()
                except Exception:
                    pass
            except KeyboardInterrupt:
                print(f"\n[!] Repository ingestion interrupted by user (Ctrl+C).")
                print(f"[*] Active repository remains '{current_path}'. Any completed embeddings were saved to cache.\n")
            except Exception as e:
                print(f"[!] Error switching repository: {e}\n")
            continue

        if query.lower() in ("hooks:status", "hooks:check"):
            st = check_git_hooks_status(current_path)
            render_hooks_table(st, current_path)
            continue

        if query.lower() in ("hooks:remove", "hooks:uninstall"):
            ok, msg = uninstall_git_hooks(current_path)
            print(f"\n[*] {msg}\n")
            continue

        if query.lower() in ("hooks", "setup-hooks", "hooks:install", "hooks:setup"):
            ok, msg = install_git_hooks(current_path)
            print(f"\n[*] {msg}\n")
            continue

        if query.lower() in ("watch", "watch:status", "watcher"):
            render_watch_panel(watcher, current_path)
            continue

        if query.lower() in ("watch:stop", "watch:pause"):
            if watcher and watcher.is_alive():
                watcher.stop()
                print("\n[*] Real-Time Filesystem Watcher stopped.\n")
            else:
                print("\n[*] Real-Time Filesystem Watcher is already inactive.\n")
            continue

        if query.lower() in ("watch:start", "watch:resume"):
            if watcher and watcher.is_alive():
                print("\n[*] Real-Time Filesystem Watcher is already active.\n")
            else:
                try:
                    watcher = RepositoryWatcher(current_path, embedder, on_reindex=on_auto_reindex, debounce_delay=0.5)
                    if watcher.start():
                        print(f"\n[*] Real-Time Filesystem Watcher started on '{current_path}'.\n")
                    else:
                        print("\n[!] Watcher failed to start (watchdog package missing or unsupported).\n")
                except Exception as e_w:
                    print(f"\n[!] Error starting watcher: {e_w}\n")
            continue

        if query.lower() in ("hybrid", "hybrid:status"):
            render_hybrid_panel(engine)
            continue

        if query.lower() in ("hybrid:on", "hybrid:enable"):
            engine.toggle_hybrid(True)
            print("\n[*] Hybrid Search ENABLED (Dense + BM25 RRF).\n")
            continue

        if query.lower() in ("hybrid:off", "hybrid:disable"):
            engine.toggle_hybrid(False)
            print("\n[*] Hybrid Search DISABLED (Dense vector only).\n")
            continue

        if query.lower() in ("hybrid:toggle",):
            now_st = engine.toggle_hybrid()
            print(f"\n[*] Hybrid Search {'ENABLED' if now_st else 'DISABLED'}.\n")
            continue

        if query.lower().startswith("persona"):
            parts = query.split(maxsplit=1)
            if len(parts) == 1:
                print(f"\n[*] Active Persona: '{engine.active_persona}'")
                print("Available Personas: general, security, reviewer, refactor, fixer\n")
            else:
                p_name = parts[1].strip()
                try:
                    active_p = engine.set_persona(p_name)
                    print(f"[*] Active Persona updated to: '{active_p}'\n")
                except ValueError as e:
                    print(f"[!] {e}\n")
            continue

        if query.lower().startswith("model "):
            new_model = query.split(maxsplit=1)[1].strip()
            engine.set_model(new_model)
            print(f"[*] Ollama LLM model set to: '{new_model}'\n")
            continue

        if query.lower().startswith("file:") or query.lower().startswith("file "):
            new_filter = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            if new_filter.lower() in ("off", "none", "clear", ""):
                active_file_filter = None
                print("[*] File filter cleared. Querying across all files.\n")
            else:
                active_file_filter = new_filter
                print(f"[*] File filter set to: '{active_file_filter}'. Queries will target this file only.\n")
            continue

        if query.lower() in ("history", "chat"):
            hist = engine.memory.format_history()
            if not hist:
                print("\n[*] Conversation history is empty.\n")
            else:
                print(f"\n{hist}\n")
            continue

        if query.lower() in ("clear-chat", "clear:history", "clear-memory", "reset"):
            engine.clear_memory()
            print("\n[*] Conversation history cleared.\n")
            continue

        # Developer Review Gate: review / proposals
        if query.lower() in ("review", "proposals", "patches:pending"):
            from backend.database.mongo import db_manager
            proposals = db_manager.find("generated_patches", {"status": "pending"})
            if not proposals:
                print("\n[*] No pending patch proposals awaiting review.\n")
            else:
                print("\n=======================================================================")
                print(f"       PENDING PATCH PROPOSALS ({len(proposals)} awaiting review)")
                print("=======================================================================")
                for idx, p in enumerate(proposals, 1):
                    p_id = p.get("patch_id", "unknown")
                    tgt = p.get("target_file", "unknown")
                    conf = f"{p.get('confidence_score', 0):.0%}"
                    sb = p.get("sandbox_validation", {}).get("test_status", "skipped").upper()
                    print(f"[{idx}] ID: {p_id[:8]}... ({p_id})")
                    print(f"    Target File   : {tgt}")
                    print(f"    Confidence    : {conf} | Sandbox Tests: {sb}")
                    print(f"    Explanation   : {p.get('explanation', '')[:100]}...")
                    print(f"    Diff Preview  :\n{p.get('git_diff', '')[:300]}\n")
                print("Commands: approve <id>, reject <id>, review <id>\n")
            continue

        if query.lower().startswith("review "):
            p_arg = query.split(maxsplit=1)[1].strip()
            from backend.database.mongo import db_manager
            # Find by prefix or exact
            candidates = db_manager.find("generated_patches", {})
            matched = [p for p in candidates if p.get("patch_id", "").startswith(p_arg)]
            if not matched:
                print(f"[!] Proposal '{p_arg}' not found.\n")
            else:
                p = matched[0]
                render_patch_card(p, fix_time=0.0)
            continue

        if query.lower().startswith("approve "):
            p_arg = query.split(maxsplit=1)[1].strip()
            from backend.database.mongo import db_manager
            candidates = db_manager.find("generated_patches", {})
            matched = [p for p in candidates if p.get("patch_id", "").startswith(p_arg)]
            if not matched:
                print(f"[!] Proposal '{p_arg}' not found.\n")
            else:
                p = matched[0]
                updated = patch_engine.update_patch_status(p["patch_id"], status="applied", user="cli_developer")
                res = updated.get("apply_result", {}) if updated else {}
                if res.get("success"):
                    print(f"[+] Approved and applied patch {p['patch_id']} to '{p.get('target_file')}'.\n")
                else:
                    print(f"[!] Failed to apply patch: {res.get('message', 'unknown error')}\n")
            continue

        if query.lower().startswith("reject "):
            p_arg = query.split(maxsplit=1)[1].strip()
            from backend.database.mongo import db_manager
            candidates = db_manager.find("generated_patches", {})
            matched = [p for p in candidates if p.get("patch_id", "").startswith(p_arg)]
            if not matched:
                print(f"[!] Proposal '{p_arg}' not found.\n")
            else:
                p = matched[0]
                patch_engine.update_patch_status(p["patch_id"], status="rejected", user="cli_developer")
                print(f"[-] Rejected proposal {p['patch_id']}.\n")
            continue

        # Documentation Generator: doc:<target>
        if query.lower().startswith("doc:") or query.lower().startswith("doc "):
            doc_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            from backend.documentation import DocumentationGenerator
            doc_gen = DocumentationGenerator()
            chunks = getattr(store, "chunks", [])
            doc_md = doc_gen.generate_symbol_doc(doc_target, chunks, call_graph=ingested.call_graph, llm=engine.llm)
            if HAS_RICH and console:
                console.print(Panel(doc_md, title=f"[bold cyan]Documentation: {doc_target}[/bold cyan]", border_style="cyan"))
            else:
                print(f"\n{doc_md}\n")
            continue

        # Security Scanner: security:<file>
        if query.lower().startswith("security:") or query.lower().startswith("security "):
            sec_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            from core.security_scanner import run_bandit_scan, format_security_report
            abs_sec = os.path.join(current_path, sec_target) if not os.path.isabs(sec_target) else sec_target
            if not os.path.exists(abs_sec):
                print(f"[!] Path not found: {sec_target}\n")
                continue
            print(f"[*] Running Bandit AST security scan on '{sec_target}'...")
            sec_result = run_bandit_scan(abs_sec)
            sec_report = format_security_report(sec_result, llm=engine.llm)
            if HAS_RICH and console:
                console.print(Panel(sec_report, title=f"[bold red]Security Scan: {sec_target}[/bold red]", border_style="red"))
            else:
                print(f"\n{sec_report}\n")
            continue

        # Chunks View: chunks: <file>
        if query.lower().startswith("chunks:") or query.lower().startswith("chunks "):
            target_f = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            render_chunks_view(result, target_f, current_path)
            continue

        # Retrieval View: explain: <question> [--no-answer] [--json] [--full] [--compare] [--width N] [--top-k N]
        if query.lower().startswith("explain:") or query.lower().startswith("explain "):
            execute_explain_command(engine, result, query, active_file_filter=active_file_filter)
            continue


        patch_triggers = ("fix", "patch", "update", "change", "modify", "refactor", "apply")
        is_patch_cmd = any(query.lower().startswith(f"{t}:") or query.lower().startswith(f"{t} ") for t in patch_triggers)
        if is_patch_cmd:
            if ":" in query:
                err_input = query.split(":", 1)[1].strip()
            else:
                err_input = query.split(maxsplit=1)[1].strip()
            
            # Handle @file syntax in fix/update commands
            clean_err, mention_f = parse_mention(err_input)
            if mention_f:
                if clean_err and clean_err.strip():
                    err_input = f"File modification instruction for {mention_f}: {clean_err.strip()}"
                else:
                    err_input = f"Fix all bugs, incorrect operators, and logic errors in {mention_f}"
            elif err_input.startswith("@"):
                err_input = err_input.lstrip("@").strip()
            
            # If err_input points directly to a file path
            abs_check = os.path.join(current_path, err_input) if not os.path.isabs(err_input) else err_input
            if os.path.isfile(abs_check):
                try:
                    with open(abs_check, "r", encoding="utf-8", errors="ignore") as f:
                        file_body = f.read()
                    err_input = f"Find and fix all bugs in file '{err_input}':\n{file_body[:2000]}"
                    if not mention_f:
                        mention_f = err_input
                except Exception:
                    pass

            print("\n[*] Analyzing error report & localizing bug root cause...")
            t_fix = time.perf_counter()
            # CLI mode: admin=True, allow_local_sandbox=True
            patch_engine = PatchEngine(
                result.store, 
                embedder, 
                llm, 
                graph=result.graph, 
                repo_path=current_path,
                is_admin=True,
                allow_local_sandbox=True
            )

            def _on_fix_progress(turn: int, max_turns: int, msg: str):
                print(f"[*] [{turn}/{max_turns}] {msg}")

            patch_rec = patch_engine.generate_patch(
                repo_id=get_repo_id(current_path),
                error_report=err_input,
                target_file=mention_f,
                verify_in_sandbox=True,
                max_iterations=3,
                progress_callback=_on_fix_progress,
            )
            fix_time = time.perf_counter() - t_fix

            render_patch_card(patch_rec, fix_time)

            if patch_rec["status"] != "failed" and patch_rec.get("git_diff"):
                target_rel = patch_rec.get("target_file", "")
                abs_target = os.path.join(current_path, target_rel) if not os.path.isabs(target_rel) else target_rel
                initial_hash = compute_file_sha256(abs_target)

                orig_code = patch_rec.get("original_code", "")
                patched_code = patch_rec.get("suggested_patch", "")
                explanation = patch_rec.get("explanation", "")

                current_mode = "auto"
                while True:
                    display_review_screen(
                        filename=target_rel,
                        original_code=orig_code,
                        patched_code=patched_code,
                        explanation=explanation,
                        mode=current_mode,
                    )
                    prompt_label = "Choose action ([a]pprove & commit, [c]ancel, [u] toggle view): "
                    try:
                        if session is not None and use_tui:
                            action = session.prompt(prompt_label).strip().lower()
                        else:
                            action = input(prompt_label).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        action = "c"

                    if action in ("u", "toggle"):
                        current_mode = "unified" if current_mode == "side_by_side" else "side_by_side"
                        continue
                    elif action in ("a", "approve", "y", "yes"):
                        # Staleness conflict detection
                        post_hash = compute_file_sha256(abs_target)
                        if initial_hash and post_hash and initial_hash != post_hash:
                            msg_stale = f"[!] CONFLICT: '{target_rel}' was modified externally during review! Aborting to prevent overwriting newer code."
                            if HAS_RICH and console:
                                console.print(f"[bold red]{msg_stale}[/bold red]\n")
                            else:
                                print(f"{msg_stale}\n")
                            break

                        ok_app, msg_app = patch_engine.apply_patch(patch_rec)
                        if ok_app:
                            if HAS_RICH and console:
                                console.print(f"[bold green][✓][/bold green] {msg_app}")
                            else:
                                print(f"[✓] {msg_app}")

                            # Create isolated Git commit for approved file only (never pushes)
                            c_msg = f"fix({os.path.splitext(os.path.basename(target_rel))[0]}): {explanation[:70]}"
                            ok_c, msg_c = commit_approved_changes(current_path, [target_rel], c_msg)
                            if ok_c:
                                if HAS_RICH and console:
                                    console.print(f"[bold green][✓ Git][/bold green] {msg_c}\n")
                                else:
                                    print(f"[✓ Git] {msg_c}\n")
                            else:
                                if HAS_RICH and console:
                                    console.print(f"[dim yellow][* Git][/dim yellow] {msg_c}\n")
                                else:
                                    print(f"[*] {msg_c}\n")
                        else:
                            if HAS_RICH and console:
                                console.print(f"[bold red][!][/bold red] {msg_app}\n")
                            else:
                                print(f"[!] {msg_app}\n")
                        break
                    else:
                        print("[*] Proposed changes discarded. Original files remain untouched.\n")
                        break
            continue



        if query.startswith("deps:") or query.startswith("deps "):
            target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            t_deps = time.perf_counter()
            affected = files_likely_affected_by(result.graph, target)
            render_deps_panel(target, affected, time.perf_counter() - t_deps)
            continue

        if query.startswith("callers:") or query.startswith("callers "):
            symbol_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            call_g = getattr(result, "call_graph", None)
            if not call_g:
                if HAS_RICH and console:
                    console.print("[bold red][!][/bold red] Call graph is unavailable.")
                else:
                    print("[!] Call graph is unavailable.")
                continue
            t_callers = time.perf_counter()
            callers = find_callers_of_symbol(call_g, symbol_target)
            render_callers_panel(symbol_target, callers, time.perf_counter() - t_callers)
            continue

        # --- search:<query> : fast retrieval-only (no LLM wait) ---
        if query.startswith("search:") or query.startswith("search "):
            sq = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            if not sq:
                print("[!] Usage: search:<query>\n")
                continue
            t_s = time.perf_counter()
            try:
                s_results = engine.retrieve_expanded(sq, top_k=8)
                render_search_results(sq, s_results, time.perf_counter() - t_s)
            except Exception as e_s:
                print(f"[!] Search error: {e_s}\n")
            continue

        # --- info:<file> : show file stats ---
        if query.startswith("info:") or query.startswith("info "):
            info_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            if HAS_RICH and console:
                # Gather stats
                file_chunks = [
                    c for c in result.store.chunks
                    if info_target.lower() in c.file_path.lower()
                ] if getattr(result, "store", None) else []
                abs_path = None
                for c in file_chunks:
                    abs_path = c.file_path
                    break
                file_size = 0
                line_count = 0
                if abs_path and os.path.isfile(abs_path):
                    file_size = os.path.getsize(abs_path)
                    try:
                        with open(abs_path, "r", encoding="utf-8", errors="ignore") as _f:
                            line_count = sum(1 for _ in _f)
                    except Exception:
                        pass
                # Centrality score
                top_files = get_top_central_files(result.graph, top_n=999)
                centrality = next(
                    (score for fp, score in top_files if info_target.lower() in fp.lower()), None
                )
                grid = Table.grid(padding=(0, 2))
                grid.add_column(style="bold cyan", justify="right")
                grid.add_column(style="white")
                grid.add_row("File:",       abs_path or info_target)
                grid.add_row("Chunks:",     str(len(file_chunks)))
                grid.add_row("Lines:",      str(line_count) if line_count else "—")
                grid.add_row("Size:",       f"{file_size:,} bytes" if file_size else "—")
                grid.add_row("Centrality:", f"{centrality:.4f}" if centrality is not None else "—")
                console.print(Panel(
                    grid, title=f"[bold cyan]File Info — {os.path.basename(info_target)}[/bold cyan]",
                    border_style="cyan", padding=(1, 2),
                ))
            else:
                print(f"\n[*] Info: {info_target}")
                file_chunks = [
                    c for c in result.store.chunks
                    if info_target.lower() in c.file_path.lower()
                ] if getattr(result, "store", None) else []
                print(f"    Chunks: {len(file_chunks)}")
            continue

        # --- export:<filename> : save last AI answer to file ---
        if query.startswith("export:") or query.startswith("export "):
            export_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            if not export_target:
                export_target = "intellicodex_answer.md"
            if not _last_answer:
                if HAS_RICH and console:
                    console.print("[bold yellow][!][/bold yellow] No AI answer to export yet. Ask a question first.\n")
                else:
                    print("[!] No AI answer to export yet. Ask a question first.\n")
            else:
                try:
                    with open(export_target, "w", encoding="utf-8") as _ef:
                        _ef.write(f"# IntelliCodeX Answer Export\n\n{_last_answer}\n")
                    if HAS_RICH and console:
                        console.print(f"[bold green][*][/bold green] Answer saved to '[cyan]{export_target}[/cyan]'\n")
                    else:
                        print(f"[*] Answer saved to '{export_target}'\n")
                except Exception as e_exp:
                    print(f"[!] Export failed: {e_exp}\n")
            continue

        t_ask = time.perf_counter()
        try:
            # Parse @mention from query for one-shot file scoping
            cleaned_query, mention_file = parse_mention(query)
            
            # Priority logic: @mention > active_file_filter > none
            effective_file_filter = mention_file if mention_file else active_file_filter
            
            # Phase 1: Retrieve and display chunks immediately
            expanded_results = engine.retrieve_expanded(cleaned_query, top_k=5, file_filter=effective_file_filter)
            t_retrieval = time.perf_counter() - t_ask

            # Visual feedback: show which file was scoped to
            if mention_file:
                print(f"\n--- Scoping to file: '{mention_file}' ---")
            elif active_file_filter:
                print(f"\n--- Using active file filter: '{active_file_filter}' ---")
            
            if len(expanded_results) == 0 and effective_file_filter:
                print(f"[!] No chunks found matching file filter '{effective_file_filter}'. Try checking the exact filename with 'files' command.")
            
            print(f"--- Retrieved {len(expanded_results)} chunks ({format_time_consumed(t_retrieval)}) ---")
            for item in expanded_results:
                chunk = item["chunk"]
                score = item["score"]
                reason = item.get("reason", "")
                reason_str = f", context={reason}" if reason else ""
                lines_str = f"{chunk.start_line}-{chunk.end_line}"
                print(f"  {chunk.file_path} :: {chunk.name} (lines {lines_str}, score={score:.3f}{reason_str})")

            # Phase 2: Stream LLM answer tokens in real-time (or fall back to ask() for tfidf mode)
            print(f"\n--- Answer ---")
            if engine.llm is not None and hasattr(engine.llm, "stream_generate"):
                # Streaming path: tokens appear immediately as they are generated
                from rag.query_engine import format_context
                context = format_context(expanded_results, max_token_budget=3000)
                
                is_analysis = engine.memory.is_code_analysis_question(cleaned_query)
                history_str = engine.memory.format_history(is_analysis=is_analysis) if len(engine.memory) > 0 else ""
                file_scope_note = ""
                if effective_file_filter:
                    file_scope_note = (
                        f"SCOPE: Focus your answer on '{effective_file_filter}'. "
                        f"The context below is scoped to this file. Answer the user's question using this context.\n\n"
                    )
                # Check if user is asking about bugs/issues/errors
                bug_keywords = [
                    "bug", "error", "issue", "problem", "wrong", "incorrect", "fix", "mistake",
                    "check", "find", "analyze", "analyse", "inspect", "review",
                    "update", "modify", "correct", "patch", "refactor", "proper", "improve",
                ]
                is_bug_query = any(keyword in cleaned_query.lower() for keyword in bug_keywords) or bool(effective_file_filter and not cleaned_query.strip())
                
                if is_bug_query:
                    anti_hallucination = (
                        "You are analyzing code for bugs, syntax errors, and logic flaws.\n"
                        "IMPORTANT: You MUST analyze and output a separate section for EVERY function, method, and block in the context (including main!). Do NOT stop after the first function.\n\n"
                        "For EVERY function/method found in the context:\n"
                        "1. Name: [function/method name]\n"
                        "2. Docstring/intent: [what the code should do based on name/docstring]\n"
                        "3. Code: [the implementation]\n"
                        "4. Analysis: Look closely for:\n"
                        "   - Syntax & compile errors (e.g., missing semicolons ';' in Java/C/C++, missing colons ':' in Python, unbalanced braces)\n"
                        "   - Type mismatch errors (e.g., assigning a String to an int like 'int total = \"sum\";')\n"
                        "   - Logic mistakes & operand order (e.g., 'return b - a' instead of 'a - b')\n"
                        "   - Operator bugs & precision loss (e.g., using integer division '//' instead of float division '/' in a general calculator)\n"
                        "   - Quantifier / Boolean logic mistakes (e.g., using 'any()' instead of 'all()' when all conditions/subjects must be satisfied to pass)\n"
                        "   - Off-by-one errors or wrong formulas\n"
                        "5. Answer MATCH or MISMATCH\n"
                        "6. If MISMATCH, quote the exact line with the bug\n"
                        "7. Explain in one sentence why it is a bug and provide the fix\n\n"
                        "CRITICAL: Only report bugs that exist in the code. Quote the exact line from the code.\n\n"
                    )
                else:
                    anti_hallucination = (
                        "IMPORTANT: When reporting bugs or issues, only report those that exist in the files shown in context below. "
                        "Do NOT attribute a bug from one file to another file. For general questions, use the provided context accurately.\n\n"
                    )
                prompt_parts = []
                if history_str:
                    prompt_parts.append(history_str)
                prompt_parts.append(anti_hallucination + file_scope_note + f"Repository context:\n\n{context}")
                prompt_parts.append(f"Question: {cleaned_query}\n\nAnswer:")
                prompt = "\n\n".join(prompt_parts)

                accumulated = []
                t_gen_start = time.perf_counter()
                temp = 0.0 if is_bug_query else 0.2
                for token in engine.llm.stream_generate(prompt, system=engine.system_prompt, temperature=temp):
                    print(token, end="", flush=True)
                    accumulated.append(token)
                print()

                full_answer = "".join(accumulated)
                
                # Anti-hallucination filter for bug queries
                if is_bug_query:
                    full_answer = engine._filter_hallucinated_claims(full_answer, expanded_results)
                    print(f"\n[Anti-hallucination filter applied]")
                
                _last_answer = full_answer
                engine.memory.add_turn(cleaned_query, full_answer)
                t_llm = time.perf_counter() - t_gen_start
                total_time = time.perf_counter() - t_ask
            else:
                # Offline / tfidf fallback: use standard ask() without streaming
                response = engine.ask(cleaned_query)
                _last_answer = response.get("answer", "")
                render_markdown_panel(response["answer"], title="Answer")
                total_time = response.get("elapsed_seconds", time.perf_counter() - t_ask)
                t_retrieval = response.get("retrieval_seconds", t_retrieval)
                t_llm = response.get("llm_seconds", 0.0)

            print(f"\n[*] [Time Consumed]: {format_time_consumed(total_time)} (Retrieval: {format_time_consumed(t_retrieval)}, Generation: {format_time_consumed(t_llm)})\n")
        except KeyboardInterrupt:
            print("\n[!] Query cancelled by user (Ctrl+C).\n")
            continue
        except Exception as e:
            print(f"\n[!] Error processing query: {e}\n")
            continue

    if watcher:
        watcher.stop()
    return 0



if __name__ == "__main__":
    sys.exit(main())
