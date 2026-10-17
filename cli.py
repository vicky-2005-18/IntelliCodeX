"""
IntelliCodeX CLI — Ingest and query software repositories interactively.

Usage:
    python cli.py [repo_path_or_url] [--backend ollama|tfidf]

Examples:
    python cli.py sample_repo
    python cli.py https://github.com/vicky-2005-18/TB --backend ollama
"""
import argparse
import atexit
import os
import re
import subprocess
import sys
import time
import tempfile
import shutil
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
import requests

logger = logging.getLogger(__name__)

# Ensure console output handles unicode without crashing on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Automatically load .env configuration if present
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
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
from core.persistence import get_repo_id, GRAPH_FORMAT_VERSION
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
    # Match @filename pattern (supports @filename.ext, @path/to/file.py, @path\to\file.py)
    # Match word characters, dots, underscores, hyphens, forward slashes, and backslashes after @
    # Stop at whitespace or punctuation that's not part of a path
    match = re.search(r'@([\w\-.\/\\]+)', query)
    if match:
        filename = match.group(1).replace("\\", "/")
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
    print(f"[*] Format version: v{GRAPH_FORMAT_VERSION} (Graph/Index v{GRAPH_FORMAT_VERSION})")
    print(f"[*] [Time Consumed]: {time_str}{speed_str} [{mode_badge}]")


def check_ollama_available(host: str = "http://localhost:11434") -> bool:
    """Checks if local Ollama server is running and accessible."""
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


import urllib.parse


def sanitize_git_url(url: str) -> str:
    """Redacts credentials in URL for safe logging/printing."""
    return re.sub(r"://([^@/]+)@", r"://***@", url)


def validate_git_url(url: str) -> str:
    """Validates that a Git clone URL uses https:// only, rejecting leading '-', whitespace, and embedded credentials."""
    if not url:
        raise ValueError("Git clone URL cannot be empty.")
    if url.startswith("-"):
        raise ValueError(f"Invalid git clone URL: '{url}' cannot start with '-'")
    if any(c.isspace() for c in url):
        raise ValueError(f"Git clone URL cannot contain whitespace: '{url}'")
    if not url.startswith("https://"):
        raise ValueError("Git clone URL must use https:// protocol only.")

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        raise ValueError(f"Malformed git clone URL: {e}")

    # Reject URLs with embedded credentials (userinfo)
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise ValueError("Git clone URL must not contain embedded credentials.")

    return url


def resolve_repo_path(repo_target: str, full_history: bool = False) -> str:
    """Resolves local directory path or clones remote Git repository URL into .repos folder (shallow clone --depth 1 by default)."""
    # Check if target is a remote repository URL or malicious clone argument
    is_remote = (
        repo_target.startswith("-") or
        repo_target.startswith("http://") or
        repo_target.startswith("https://") or
        repo_target.startswith("git@") or
        (repo_target.endswith(".git") and not os.path.exists(repo_target))
    )
    if is_remote:
        validate_git_url(repo_target)
        repo_name = repo_target.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        target_dir = os.path.abspath(os.path.join(".repos", repo_name))

        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        git_env["GIT_ALLOW_PROTOCOL"] = "https"

        if os.path.exists(target_dir) and os.path.exists(os.path.join(target_dir, ".git")):
            print(f"[*] Local clone found at '{target_dir}'. Syncing latest changes...")
            t_pull = time.perf_counter()
            try:
                subprocess.run(["git", "pull"], cwd=target_dir, capture_output=True, text=True, timeout=15, env=git_env)
                print(f"[*] Git sync finished in {format_time_consumed(time.perf_counter() - t_pull)}.")
            except subprocess.TimeoutExpired:
                print(f"[!] Warning: 'git pull' timed out after 15s. Using existing local files.")
            except Exception as e:
                print(f"[!] Warning: 'git pull' encountered an issue: {e}. Using existing local files.")
        else:
            os.makedirs(".repos", exist_ok=True)
            mode_desc = "full history" if full_history else "shallow --depth 1"
            safe_target = sanitize_git_url(repo_target)
            print(f"[*] Cloning remote Git repository '{safe_target}' into '{target_dir}' ({mode_desc})...")
            t_clone = time.perf_counter()
            clone_cmd = ["git", "clone"]
            if not full_history:
                clone_cmd.extend(["--depth", "1"])
            clone_cmd.extend(["--", repo_target, target_dir])
            try:
                res = subprocess.run(clone_cmd, capture_output=True, text=True, timeout=45, env=git_env)
                if res.returncode != 0:
                    raise RuntimeError(f"Git clone failed: {res.stderr.strip() or 'Unknown error or empty repository'}")
                print(f"[*] Git clone finished in {format_time_consumed(time.perf_counter() - t_clone)}.")
            except subprocess.TimeoutExpired:
                raise RuntimeError("Git clone operation timed out (45s). Please check repository URL or network connection.")
        return target_dir

    if not os.path.exists(repo_target):
        # Also check if target matches a known local repo folder in .repos or sample_repo
        repos_cand = os.path.abspath(os.path.join(".repos", repo_target))
        if os.path.isdir(repos_cand):
            return repos_cand
        sample_cand = os.path.abspath("sample_repo")
        if repo_target == "sample_repo" and os.path.isdir(sample_cand):
            return sample_cand
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
  arch / cycles          - Analyze circular dependencies & high-coupling bottleneck modules
  why:<query>            - Query historical design decisions and commit rationale (e.g. 'why:FAISS')
  adrs                   - List all Architectural Decision Records (ADRs) found in repo
  repos / list-repos     - List all already-added repositories and switch by number
  repo <path_or_url>     - Switch/clone active repository (e.g. 'repo https://github.com/user/repo')
  repo <number>          - Switch to a previously added repo by its list number (e.g. 'repo 2')
  repo remove <num|name> - Unregister repository registration (preserves source files & cache)
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


def get_available_repos(current_path: str, db_path: Optional[str] = None) -> list:
    """Returns a list of (label, abs_path) tuples for all known local repositories.

    Scans:
    - Built-in sample_repo
    - All previously indexed repositories recorded in SQLite (.storage/metadata.db)
    - The .repos/ folder
    - The currently active repository
    """
    known: list = []  # list of (label, abs_path)
    seen_paths: set = set()

    unregistered_paths: set = set()
    try:
        from core.persistence import get_unregistered_repos
        unregistered_paths = get_unregistered_repos(db_path=db_path) if db_path else get_unregistered_repos()
    except Exception:
        pass

    def _add_repo(label: str, raw_path: str):
        if not raw_path or not os.path.isdir(raw_path):
            return
        abs_p = os.path.abspath(raw_path)
        norm_key = os.path.normcase(abs_p)
        if norm_key in seen_paths or norm_key in unregistered_paths:
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
        conn = get_db_connection(db_path) if db_path else get_db_connection()
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
        console.print("[dim]Tip: type 'repo <number>' or 'repo <name>' to switch | 'repo remove <number|name>' to unregister[/dim]\n")
    else:
        print(f"\n--- Available Repositories ({len(available)}) ---")
        for idx, (label, abs_p) in enumerate(available, start=1):
            active_marker = " (active ✓)" if abs_p == active_abs else ""
            print(f"  [{idx}] {label:<25} {abs_p}{active_marker}")
        print("\n  Tip: type 'repo <number>' to switch, 'repo remove <number|name>' to unregister\n")


def handle_repo_remove(
    target_arg: str,
    current_path: str,
    available_repos: Optional[list] = None,
    confirm_fn: Optional[Callable[[str], str]] = None,
    output_fn: Optional[Callable[[str], None]] = None,
    db_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Handles 'repo remove <number|name>' command.

    - Resolves numbers using the exact ordering shown by 'repos'.
    - Matches names case-insensitively.
    - Requires disambiguation if duplicate names exist.
    - Rejects removal if target is the active repository.
    - Shows exact repository name and full path before confirmation.
    - Removes registration from persistent repository list (SQLite).
    - Preserves all source folders, Git history, and index/cache files.
    """
    out = output_fn or print
    target = (target_arg or "").strip().strip("\"'")
    if not target:
        msg = "Usage: repo remove <number|name>\nRun 'repos' to view registered repositories."
        out(f"\n[!] {msg}\n")
        return False, msg

    available = available_repos if available_repos is not None else get_available_repos(current_path, db_path=db_path)
    if not available:
        msg = "No registered repositories found."
        out(f"\n[!] {msg}\n")
        return False, msg

    target_entry = None
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(available):
            target_entry = available[idx]
        else:
            msg = f"Invalid repository number '{target}'. Valid range is 1 to {len(available)}.\nRun 'repos' to view the list."
            out(f"\n[!] {msg}\n")
            return False, msg
    else:
        # Match by repository name (case-insensitive)
        name_matches = [e for e in available if e[0].lower() == target.lower()]
        if not name_matches:
            # Fallback: check matching directory basename or matching full path
            norm_target = os.path.normcase(os.path.abspath(target))
            name_matches = [
                e for e in available
                if os.path.basename(e[1]).lower() == target.lower()
                or os.path.normcase(os.path.abspath(e[1])) == norm_target
            ]

        if len(name_matches) == 0:
            msg = f"Repository '{target}' not found. Run 'repos' to view available repositories."
            out(f"\n[!] {msg}\n")
            return False, msg
        elif len(name_matches) > 1:
            out(f"\n[!] Multiple repositories named '{target}' found:")
            for idx, (lbl, p) in enumerate(available, start=1):
                if (lbl, p) in name_matches:
                    out(f"    [{idx}] {lbl:<20} {p}")
            msg = f"Multiple repositories named '{target}' found. Please disambiguate by number using 'repo remove <number>'."
            out("    Please disambiguate by number using 'repo remove <number>'.\n")
            return False, msg
        else:
            target_entry = name_matches[0]

    selected_name, selected_path = target_entry
    selected_abs = os.path.abspath(selected_path)
    active_abs = os.path.abspath(current_path) if current_path else ""

    # Check if target is the active repository
    if active_abs and os.path.normcase(selected_abs) == os.path.normcase(active_abs):
        out(f"\n[!] Cannot remove the active repository '{selected_name}'.")
        out(f"[*] Path: {selected_abs}")
        msg = f"Cannot remove active repository '{selected_name}'. Please switch to another repository first using 'repo <number|name>' before removing."
        out("[*] Please switch to another repository first using 'repo <number|name>' before removing.\n")
        return False, msg

    # Show exact repository name and full path before confirmation
    out("\nRepository unregister:")
    out(f"  Name: {selected_name}")
    out(f"  Path: {selected_abs}")

    prompt_str = f"Are you sure you want to unregister '{selected_name}' ({selected_abs})? [y/N]: "
    if confirm_fn is None:
        confirm_fn = input

    try:
        confirm_ans = confirm_fn(prompt_str)
    except (KeyboardInterrupt, EOFError):
        msg = "Repository unregister cancelled."
        out(f"\n[*] {msg}\n")
        return False, msg

    if not confirm_ans or confirm_ans.strip().lower() not in ("y", "yes"):
        msg = "Repository unregister cancelled."
        out(f"[*] {msg}\n")
        return False, msg

    # Unregister repository
    from core.persistence import unregister_repo
    if db_path:
        unregister_repo(selected_abs, db_path=db_path)
    else:
        unregister_repo(selected_abs)

    msg = f"Successfully unregistered repository '{selected_name}'."
    out(f"\n[✓] {msg}")
    out(f"[*] Source files, Git history, and index cache at '{selected_abs}' remain untouched.\n")
    return True, msg



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
    """Renders automated patch diagnosis and git diff, separating execution results from model claims."""
    sb_val = patch_rec.get("sandbox_validation", {})
    sb_status = sb_val.get("test_status", "skipped").upper()
    sb_turns = sb_val.get("iterations_count", 1)
    sb_skipped = sb_val.get("skipped", False)
    time_str = format_time_consumed(fix_time)
    conf = f"{patch_rec.get('confidence_score', 0):.0%}"

    test_res = sb_val.get("test_result") or {}
    exit_code = test_res.get("exit_code")
    p_cnt = test_res.get("passed_count", 0)
    f_cnt = test_res.get("failed_count", 0)
    
    contract_type = sb_val.get("contract_type", "existing_tests")
    contract_disclaimer = sb_val.get("contract_disclaimer")

    # Show "not verified" message when tests were skipped
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
    cited_chunks = [f"{c.get('file', '')}:{c.get('lines', '')} ({c.get('name', '')})" for c in rag_chunks if c.get("file")]
    sec_val = patch_rec.get("security_validation") or {}

    if HAS_RICH and console:
        status_color = "green" if sb_status == "PASSED" else ("red" if sb_status == "FAILED" else "yellow")
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="bold cyan", justify="right")
        info_table.add_column(style="white")
        info_table.add_row("Canonical Target:", patch_rec.get("target_file", "Unknown"))
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
        info_table.add_row("Model Advisory:", patch_rec.get("explanation", ""))
        if sb_status == "FAILED":
            info_table.add_row("Warning:", "[bold red][!] Model advisory claims cannot override failed test execution results.[/bold red]")

        console.print(Panel(info_table, title="[bold cyan]INTELLICODEX AUTOMATED CODE PATCH[/bold cyan]", border_style="cyan"))
        render_diff(patch_rec.get("git_diff", ""))
    else:
        print("\n=======================================================================")
        print("                 INTELLICODEX AUTOMATED CODE PATCH")
        print("=======================================================================")
        print(f"Canonical Target: {patch_rec.get('target_file')}")
        print(f"Error Type      : {patch_rec.get('error_type', 'Unknown')}")
        print(f"Confidence      : {conf}")
        print(f"Sandbox Tests   : {sb_display}")
        print(f"Iterations      : {sb_turns} attempt(s)")
        if passed_tests:
            print(f"Tests Passed    : {', '.join(passed_tests[:3])}")
        if failed_tests:
            print(f"Tests Failed    : {', '.join(failed_tests[:3])}")
        if cited_chunks:
            print(f"Grounded Chunks : {', '.join(cited_chunks[:3])}")
        if sec_val:
            print(f"Security Scan   : {sec_val.get('security_status', 'unscanned').upper()} ({sec_val.get('findings_count', 0)} finding(s))")
        if contract_type == "ai_generated_proposal":
            print("Contract Grounding: AI-Generated Test Proposal (disposable contract)")
            if contract_disclaimer:
                print(f"Disclaimer      : {contract_disclaimer}")
        if sb_status == "FAILED":
            print("[!] REPAIR FAILED: Automated tests did not pass in Docker sandbox.")
            print("[!] Model advisory claims cannot override failed test execution results.")
        print(f"Time Consumed   : {time_str}")
        print(f"Model Advisory  : {patch_rec.get('explanation')}")
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
                ("graph:<entity>",  "Query knowledge graph for entity attributes, callers & lines"),
                ("deps:<file>",     "View reverse dependency impact for a file"),
                ("callers:<func>",  "Find all call sites of a function across the repo"),
                ("top / centrality","Show PageRank centrality rankings for files & symbols"),
                ("info:<file>",     "Show file stats: size, chunk count, centrality score"),
            ]),
            ("Repository", "green", [
                ("repo <path|url>", "Switch or clone a repository (shallow --depth 1 default)"),
                ("clone <url>",     "Clone repository (shallow default, use --full-history for all commits)"),
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
        grid.add_row("[green]✓[/green] Format version:", f"[dim]v{GRAPH_FORMAT_VERSION} (Graph/Index v{GRAPH_FORMAT_VERSION})[/dim]")
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



def execute_graph_command(result, query: str):
    """
    REQ-FUT-07: Queries the repository knowledge graph from CLI.
    Supports:
      graph:<entity>
      graph:query <entity>
      graph:path <source> <target> [--directed]
      graph:entities [type]
      graph:metadata
    """
    from backend.dependency_graph import EnhancedDependencyGraph

    source_files = getattr(result, "source_files", None)
    if not source_files and hasattr(result, "store") and hasattr(result.store, "chunks"):
        file_map = {}
        for c in result.store.chunks:
            if c.file_path not in file_map:
                from core.parser import SourceFile
                file_map[c.file_path] = SourceFile(c.file_path, c.file_path, "", c.language)
        source_files = list(file_map.values())

    engine = getattr(result, "enhanced_graph_engine", None)
    if engine is None:
        engine = EnhancedDependencyGraph()
        engine.build(source_files or [], call_graph=getattr(result, "call_graph", None))
        result.enhanced_graph_engine = engine

    args_str = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()

    if args_str.startswith("path ") or args_str.startswith("path:"):
        path_args = args_str[5:].strip().split()
        if len(path_args) < 2:
            print("[!] Usage: graph:path <source_entity> <target_entity> [--directed]\n")
            return
        src, tgt = path_args[0], path_args[1]
        directed = "--directed" in path_args
        res = engine.find_path(src, tgt, directed=directed)
        if not res.get("found"):
            print(f"[!] {res.get('error', 'Path resolution failed')}\n")
            return
        if not res.get("path_exists"):
            print(f"[*] {res.get('message', 'No path found.')}\n")
            return

        print(f"\n[*] Shortest Knowledge Graph Path ({'directed' if directed else 'undirected'}): {src} -> {tgt} (length={res['length']})")
        for idx, node in enumerate(res["path"]):
            print(f"  [{idx}] {node['id']} ({node['type']}, file={node.get('file_path') or '—'})")
        if res.get("edges"):
            print("\n  Connecting Edges:")
            for e in res["edges"]:
                line_info = f":{e['line']}" if e.get("line") else ""
                print(f"    - {e['source']} --[{e['relationship']}]--> {e['target']} ({e.get('source_file') or ''}{line_info})")
        print()
        return

    if args_str.lower() in ("metadata", "stats"):
        meta = engine.get_metadata()
        print("\n=== Repository Knowledge Graph Metadata ===")
        print(f"  Total Nodes : {meta['total_nodes']}")
        print(f"  Total Edges : {meta['total_edges']}")
        print("  Node Types  :", ", ".join(f"{k}: {v}" for k, v in meta["node_types"].items()))
        print("  Relationships:", ", ".join(f"{k}: {v}" for k, v in meta["relationship_types"].items()))
        print("\n  Supported Relationships:")
        for s in meta["supported_relationships"]:
            print(f"    - {s['type']}: {s['description']}")
        print("\n  Unsupported Relationships (Not Statically Inferred):")
        for u in meta["unsupported_relationships"]:
            print(f"    - {u['type']}: {u['reason']}")
        print()
        return

    if args_str.startswith("entities") or args_str.startswith("list"):
        parts = args_str.split()
        ent_type = parts[1] if len(parts) > 1 else None
        ents = engine.list_entities(entity_type=ent_type, limit=50)
        print(f"\n[*] Indexed Entities (showing {len(ents)}):")
        for e in ents:
            line_str = f" lines {e['start_line']}–{e['end_line']}" if e.get("start_line") else ""
            print(f"  - [{e['type']}] {e['id']} ({e.get('file_path') or '—'}{line_str})")
        print()
        return

    entity_name = args_str
    if entity_name.startswith("query "):
        entity_name = entity_name[6:].strip()

    t0 = time.perf_counter()
    res = engine.query_entity(entity_name, direction="both", depth=1)
    elapsed = time.perf_counter() - t0

    if not res.get("found"):
        print(f"\n[!] Entity '{entity_name}' not found in repository knowledge graph.")
        similar = engine.list_entities(search=entity_name, limit=5)
        if similar:
            print("    Did you mean one of these?")
            for s in similar:
                print(f"      - {s['id']} ({s['type']})")
        print()
        return

    ent = res["entity"]
    rels = res["relationships"]

    if HAS_RICH and console:
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan", justify="right")
        grid.add_column(style="white")
        grid.add_row("Entity ID:", ent["id"])
        grid.add_row("Symbol Name:", ent["name"])
        grid.add_row("Entity Type:", f"[bold yellow]{ent['type'].upper()}[/bold yellow]")
        grid.add_row("Source File:", f"{ent.get('file_path') or '—'}")
        if ent.get("start_line"):
            grid.add_row("Line Range:", f"Lines {ent['start_line']} – {ent.get('end_line') or ent['start_line']}")
        if ent.get("docstring"):
            grid.add_row("Docstring:", ent["docstring"].strip().splitlines()[0])
        grid.add_row("Query Time:", format_time_consumed(elapsed))

        console.print(Panel(
            grid,
            title=f"[bold bright_blue]Knowledge Graph — {ent['name']}[/bold bright_blue]",
            border_style="bright_blue",
        ))

        if rels:
            t = Table(title=f"Incident Relationships ({len(rels)})", border_style="cyan")
            t.add_column("Dir", style="bold yellow", width=8)
            t.add_column("Relationship", style="bold green", width=18)
            t.add_column("Related Symbol", style="cyan")
            t.add_column("Type", style="dim", width=10)
            t.add_column("Source File & Line", style="magenta")

            for r in rels:
                direction_arrow = "OUT ->" if r["direction"] == "outgoing" else "IN  <-"
                related_sym = r["target_name"] if r["direction"] == "outgoing" else r["source_name"]
                related_type = r["target_type"] if r["direction"] == "outgoing" else r["source_type"]
                line_str = f"{r.get('source_file') or ''}:{r.get('line') or ''}" if r.get("line") else (r.get("source_file") or "—")
                t.add_row(direction_arrow, r["relationship"], related_sym, related_type, line_str)
            console.print(t)
        else:
            console.print("[dim yellow]No incident relationships found for this entity.[/dim yellow]")
        print()
    else:
        print(f"\n=== Knowledge Graph: {ent['name']} ({ent['type']}) ===")
        print(f"  ID         : {ent['id']}")
        print(f"  File       : {ent.get('file_path') or '—'}")
        if ent.get("start_line"):
            print(f"  Lines      : {ent['start_line']} - {ent.get('end_line')}")
        print(f"  Relationships ({len(rels)}):")
        for r in rels:
            arrow = "->" if r["direction"] == "outgoing" else "<-"
            rel_sym = r["target_name"] if r["direction"] == "outgoing" else r["source_name"]
            line_str = f" (line {r['line']})" if r.get("line") else ""
            print(f"    {arrow} [{r['relationship']}] {rel_sym}{line_str}")
        print()


class IntelliCodeXCompleter(Completer if HAS_PROMPT_TOOLKIT else object):
    """Context-aware autocompleter for commands, files, symbols, and settings."""

    COMMANDS = [
        ("graph:", "Query repository knowledge graph entity, relationships, or paths (e.g. 'graph:Calculator')"),
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
        ("repo remove ", "Unregister repository from persistent list by number or name"),
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
        ("why:", "Query historical design decisions and commit rationale (e.g. 'why:FAISS')"),
        ("adrs", "List all Architectural Decision Records (ADRs) found in repo"),
        ("learned", "Show self-improving agent few-shot repair memory and statistics"),
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

        # 6a. Parameter completion: repo remove <name_or_number>
        if stripped.startswith("repo remove "):
            arg = stripped[len("repo remove "):]
            if self.get_repos_fn:
                repos = self.get_repos_fn() or []
                for idx, (lbl, p) in enumerate(repos, start=1):
                    s_idx = str(idx)
                    if s_idx.startswith(arg):
                        yield Completion(s_idx, start_position=-len(arg), display=f"[{s_idx}] {lbl}", display_meta="Repo Number")
                    if lbl.lower().startswith(arg.lower()):
                        yield Completion(lbl, start_position=-len(arg), display=lbl, display_meta="Repo Name")
            return

        # 6. Parameter completion: repo <name_or_number>
        if stripped.startswith("repo "):
            arg = stripped[len("repo "):]
            if "remove".startswith(arg.lower()):
                yield Completion("remove ", start_position=-len(arg), display="remove <number|name>", display_meta="Unregister repository")
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
def create_components(
    backend_choice: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    num_predict: Optional[int] = None,
    repeat_penalty: Optional[float] = None,
):
    """Factory helper to instantiate embedder and LLM with automatic fallback."""
    if backend_choice == "ollama":
        if check_ollama_available():
            chosen_model = model or os.getenv("OLLAMA_LLM_MODEL", "qwen2.5-coder:7b")
            temp = 0.0 if temperature is None else temperature
            predict = 800 if num_predict is None else num_predict
            penalty = 1.1 if repeat_penalty is None else repeat_penalty
            print(f"[*] Backend: Ollama AI ({chosen_model} + nomic-embed-text)")
            print(f"[*] Generation Config: temperature={temp}, num_predict={predict}, repeat_penalty={penalty}")
            llm = OllamaLLM(
                model=chosen_model,
                temperature=temp,
                num_predict=predict,
                repeat_penalty=penalty,
            )
            return OllamaEmbedder(), llm, "ollama"
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


# Standard CI/CD Pipeline Exit Codes (REQ-FUT-04)
EXIT_SUCCESS = 0
EXIT_VERIFICATION_FAILURE = 1
EXIT_INFRA_OR_CONFIG_ERROR = 2


def apply_unified_diff(
    original_text: str,
    diff_text: str,
    expected_target_file: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Applies a single-file unified diff to original text with strict format validation.

    Guarantees (REQ-FUT-04 / REQ-FUT-05):
    1. Distinguishes input formats explicitly:
       - If diff syntax (diff --git, ---, +++, @@) is absent, treats as valid full replacement code.
       - If diff syntax is present, strictly parses as unified diff.
    2. Rejects malformed diffs (missing hunks, invalid hunk headers, truncated lines).
    3. Rejects mismatched context and deletion lines explicitly (does NOT silently skip or corrupt).
    4. Rejects unexpected target paths if expected_target_file is supplied and headers do not match.
    5. NEVER silently reinterprets a failed unified diff as full replacement code.

    Returns:
        (patched_text, None) on success.
        (None, error_reason) on failure.
    """
    if diff_text is None:
        return None, "Diff content is None"

    # 1. Distinguish input formats
    has_diff_markers = bool(re.search(r"^(?:diff --git|--- |\+\+\+ |@@\s+-\d+)", diff_text, re.MULTILINE))
    if not has_diff_markers:
        # Documented valid usage: plain replacement content
        return diff_text, None

    # 2. Check header target path if expected_target_file is given
    if expected_target_file:
        m_plus = re.search(r"^\+\+\+\s+(?:[b/]|/)*(.*?)(?:\t|\n|$)", diff_text, re.MULTILINE)
        m_minus = re.search(r"^---\s+(?:[a/]|/)*(.*?)(?:\t|\n|$)", diff_text, re.MULTILINE)
        header_target = None
        if m_plus and m_plus.group(1).strip() not in ("/dev/null", "null", ""):
            header_target = m_plus.group(1).strip()
        elif m_minus and m_minus.group(1).strip() not in ("/dev/null", "null", ""):
            header_target = m_minus.group(1).strip()

        if header_target:
            norm_header = os.path.normpath(header_target).replace("\\", "/")
            norm_expected = os.path.normpath(expected_target_file).replace("\\", "/")
            if (
                norm_header != norm_expected
                and not norm_expected.endswith("/" + norm_header)
                and not norm_header.endswith("/" + norm_expected)
                and os.path.basename(norm_header) != os.path.basename(norm_expected)
            ):
                return None, f"Diff target path '{header_target}' does not match expected target file '{expected_target_file}'"

    # 3. Parse hunks
    diff_lines = diff_text.splitlines(keepends=True)
    lines = original_text.splitlines(keepends=True) if original_text is not None else []

    # Find first hunk
    i = 0
    while i < len(diff_lines) and not diff_lines[i].startswith("@@"):
        i += 1

    if i >= len(diff_lines):
        return None, "Malformed unified diff: no hunk headers (@@ -start,count +start,count @@) found"

    out: List[str] = []
    orig_idx = 0

    while i < len(diff_lines):
        hunk_header = diff_lines[i]
        if not hunk_header.startswith("@@"):
            if not hunk_header.strip():
                i += 1
                continue
            return None, f"Malformed diff: unexpected content outside hunk: '{hunk_header.strip()}'"

        m = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", hunk_header)
        if not m:
            return None, f"Malformed hunk header syntax: '{hunk_header.strip()}'"

        hunk_start = int(m.group(1))
        orig_start = max(0, hunk_start - 1)

        if orig_idx > orig_start:
            return None, f"Malformed diff: overlapping or out-of-order hunk at line {hunk_start}"

        while orig_idx < orig_start and orig_idx < len(lines):
            out.append(lines[orig_idx])
            orig_idx += 1

        if orig_idx < orig_start:
            return None, f"Hunk start line {hunk_start} exceeds original file length ({len(lines)} lines)"

        i += 1
        while i < len(diff_lines) and not diff_lines[i].startswith("@@"):
            dline = diff_lines[i]
            prefix = dline[:1]
            content = dline[1:]

            if prefix == "+":
                out.append(content)
                i += 1
            elif prefix == "-":
                if orig_idx >= len(lines):
                    return None, f"Mismatched context on deletion at line {orig_idx + 1}: expected '{content.rstrip()}', reached EOF"
                orig_line_clean = lines[orig_idx].rstrip("\r\n")
                dline_clean = content.rstrip("\r\n")
                if orig_line_clean != dline_clean:
                    return None, f"Mismatched context on deletion at line {orig_idx + 1}: expected '{dline_clean}', found '{orig_line_clean}'"
                orig_idx += 1
                i += 1
            elif prefix == " ":
                if orig_idx >= len(lines):
                    return None, f"Mismatched context line at line {orig_idx + 1}: expected '{content.rstrip()}', reached EOF"
                orig_line_clean = lines[orig_idx].rstrip("\r\n")
                dline_clean = content.rstrip("\r\n")
                if orig_line_clean != dline_clean:
                    return None, f"Mismatched context line at line {orig_idx + 1}: expected '{dline_clean}', found '{orig_line_clean}'"
                out.append(lines[orig_idx])
                orig_idx += 1
                i += 1
            elif dline.startswith("\\"):
                # e.g. \ No newline at end of file
                i += 1
            elif dline in ("\n", "\r\n"):
                if orig_idx >= len(lines):
                    return None, f"Mismatched context empty line at line {orig_idx + 1}: reached EOF"
                orig_line_clean = lines[orig_idx].rstrip("\r\n")
                if orig_line_clean != "":
                    return None, f"Mismatched context empty line at line {orig_idx + 1}: found '{orig_line_clean}'"
                out.append(lines[orig_idx])
                orig_idx += 1
                i += 1
            else:
                return None, f"Malformed diff line in hunk: '{dline.rstrip()}'"

    while orig_idx < len(lines):
        out.append(lines[orig_idx])
        orig_idx += 1

    return "".join(out), None


def _apply_diff_to_text(original_text: str, diff_text: str, expected_target_file: Optional[str] = None) -> Optional[str]:
    """
    Applies a single-file unified diff to original text.
    Returns the patched text on success, or None if the diff cannot be applied cleanly.
    """
    patched, err = apply_unified_diff(original_text, diff_text, expected_target_file=expected_target_file)
    if err:
        logger.warning(f"Diff application failed: {err}")
    return patched


def _sanitize_report_data(obj: Any) -> Any:
    """Recursively scrub tokens, secrets, credentials, and passwords from report data."""
    if isinstance(obj, str):
        # Scrub Bearer tokens
        s = re.sub(r'Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+(?:\.[A-Za-z0-9\-_.+/=]+)?', 'Bearer [REDACTED_TOKEN]', obj)
        # Scrub URI passwords: e.g. postgresql://user:password@host:port/db
        s = re.sub(r'(://[^:\s]+:)([^@\s]+)(@)', r'\1[REDACTED_SECRET]\3', s)
        # Scrub explicit key/secret assignments
        s = re.sub(r'(api[_-]?key|secret|password|token)\s*[:=]\s*["\']?[^"\'\s]+["\']?', r'\1: [REDACTED_SECRET]', s, flags=re.IGNORECASE)
        return s
    elif isinstance(obj, dict):
        return {k: _sanitize_report_data(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize_report_data(v) for v in obj]
    return obj


def _write_ci_report(
    output_path: Optional[str] = None,
    status: str = "success",
    exit_code: int = 0,
    repo_path: str = "",
    analysis: Optional[Dict[str, Any]] = None,
    patch_verification: Optional[Dict[str, Any]] = None,
    failures: Optional[List[str]] = None,
    error_message: Optional[str] = None,
    sandbox_mode: Optional[str] = None,
    patch_report: Optional[Dict[str, Any]] = None,
) -> None:
    """Writes a machine-readable JSON execution and verification report with sanitized diagnostics (REQ-FUT-04)."""
    if not output_path:
        return
    import json
    import datetime

    pv = patch_verification or patch_report or {"tested": False}
    canonical_status = "success" if status in ("passed", "success") else status
    report: Dict[str, Any] = {
        "status": canonical_status,
        "ci_status": canonical_status,
        "exit_code": exit_code,
        "pipeline_exit_code": exit_code,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo_path": os.path.abspath(repo_path) if repo_path else "",
        "analysis": analysis or {},
        "patch_verification": pv,
        "failures": failures or ([] if not error_message else [error_message]),
    }
    if error_message and not pv.get("tested"):
        report["error_message"] = error_message
    if sandbox_mode and pv.get("tested"):
        report["patch_verification"]["sandbox_mode"] = sandbox_mode

    # Sanitize any credentials or sensitive tokens from report
    sanitized_report = _sanitize_report_data(report)

    try:
        out_dir = os.path.dirname(os.path.abspath(output_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sanitized_report, f, indent=2, default=str)
    except Exception as exc:
        logger.warning(f"Failed to write CI report to '{output_path}': {exc}")


def _render_ci_summary(
    repo_path: str,
    analysis: Dict[str, Any],
    patch_report: Dict[str, Any],
    failures: List[str],
    status: str,
    exit_code: int,
) -> None:
    """Renders human-readable summary of CI pipeline execution to console."""
    print("=" * 65)
    print(f"CI Target Repository   : {repo_path}")
    print(f"Total Files Ingested   : {analysis.get('num_files', 0)}")
    print(f"Total Chunks Extracted : {analysis.get('num_chunks', 0)}")
    print(f"AST Chunks Count       : {analysis.get('ast_chunks_count', 0)} ({analysis.get('ast_ratio_percent', 0.0)}%)")
    sec_info = analysis.get("security_scan", {})
    sec_status = sec_info.get("status", "unknown").upper()
    sec_thresh = sec_info.get("severity_threshold", "HIGH")
    sec_pol = sec_info.get("security_policy", "strict").upper()
    sec_cnt = sec_info.get("metrics", {}).get("total_findings", 0) if "metrics" in sec_info else sec_info.get("total_findings", 0)
    print(f"Security Scan Status   : {sec_status} (Policy: {sec_pol}, Threshold: {sec_thresh}, Findings: {sec_cnt})")
    if patch_report.get("tested"):
        print("-" * 65)
        print(f"Candidate Target File  : {patch_report.get('target_file')}")
        print(f"Candidate Snapshot     : {patch_report.get('candidate_snapshot', 'patched_disposable_snapshot')}")
        print(f"Language Runtime       : {patch_report.get('runtime')}")
        print(f"Sandbox Mode           : {patch_report.get('sandbox_mode')} ({patch_report.get('docker_image')})")
        print(f"Test Framework         : {patch_report.get('framework')}")
        counts = patch_report.get("test_counts", {})
        print(f"Tests Passed / Failed  : {counts.get('passed', 0)} passed / {counts.get('failed', 0)} failed ({counts.get('skipped', 0)} skipped)")
        print(f"Behavioral Test Status : {str(patch_report.get('behavioral_status', 'N/A')).upper()} (Verified: {'YES' if patch_report.get('behavioral_verified') else 'NO'})")
        print(f"Security Policy Gate   : {str(patch_report.get('security_policy', 'strict')).upper()} (Coverage: {str(patch_report.get('security_coverage', 'unknown')).upper()})")
        print(f"Patch Security Status  : {str(patch_report.get('security_status', 'N/A')).upper()} (Approved: {'YES' if patch_report.get('security_approved') else 'NO'}, Failing Findings: {patch_report.get('failing_findings_count', 0)})")
        print(f"Overall Patch Gate     : {'PASSED (Verified Repair)' if patch_report.get('verified') else 'FAILED (Unverified / Policy Rejection)'}")
        print(f"Candidate Outcome      : {patch_report.get('outcome', 'unknown')}")
    print("=" * 65)
    if failures:
        print(f"CI Execution Status    : {status.upper()} (Exit Code: {exit_code})")
        print("CI Status              : FAILED")
        for f in failures:
            print(f"  [!] {f}")
    else:
        print(f"CI Execution Status    : PASSED (Exit Code: 0)")
        print("CI Status              : PASSED")
    print("=" * 65 + "\n")


def run_ci_pipeline(
    repo_path: str,
    result: Any,
    elapsed_seconds: float,
    patch_file: Optional[str] = None,
    target_file: Optional[str] = None,
    runtime: Optional[str] = None,
    sandbox_mode: str = "docker",
    docker_image: str = "intellicodex-sandbox:latest",
    output_json: Optional[str] = None,
    patch: Optional[str] = None,
    patch_content: Optional[str] = None,
    security_threshold: str = "HIGH",
    security_policy: str = "strict",
) -> int:
    """
    Non-interactive pipeline entry point for CI/CD environments (REQ-FUT-04 / REQ-FUT-05).

    Performs:
    1. Static repository quality verification (file count, chunk extraction ratio, multi-layer security scan).
    2. Optional candidate-patch testing inside isolated Docker sandbox on a disposable clone.
    3. Candidate-patch security gate verification on disposable snapshot.
    4. Produces machine-readable JSON report and human-readable summary.
    5. Returns standard exit codes:
       - 0: Success (all gates and patch tests passed)
       - 1: Verification / Quality Failure (tests failed, security issues, zero tests, unverified repair)
       - 2: Configuration / Infrastructure Error (missing files, Docker offline, invalid arguments, scanner crash)
    """
    print("\n" + "=" * 65)
    print("[*] [CI Mode] IntelliCodeX Non-Interactive Pipeline Gate (REQ-FUT-04 / REQ-FUT-05)")
    print("=" * 65)

    ci_failures: List[str] = []
    exit_code = EXIT_SUCCESS
    status = "passed"
    sec_policy_clean = (security_policy or "strict").lower().strip()

    # 1. Static Repository Quality Checks
    num_files = getattr(result, "num_files", 0)
    num_chunks = getattr(result, "num_chunks", 0)
    ast_chunks = getattr(result, "ast_chunks_count", 0)
    ast_ratio = getattr(result, "ast_ratio_percent", None)
    if ast_ratio is None or (ast_ratio == 0.0 and ast_chunks > 0 and num_chunks > 0):
        ast_ratio = round((ast_chunks / num_chunks * 100.0), 2)
    elif ast_ratio is None:
        ast_ratio = 0.0

    if num_files == 0:
        ci_failures.append("No ingestible source files found in target repository.")
    if num_chunks == 0:
        ci_failures.append("Zero AST/code chunks generated during ingestion.")

    try:
        from core.security_scanner import run_security_scan
        sec_res = run_security_scan(
            repo_path,
            repo_root=repo_path,
            severity_threshold=security_threshold,
            security_policy=sec_policy_clean,
        )
        if sec_res.get("status") == "error":
            ci_failures.append(f"Security Scanner Infrastructure Error: {sec_res.get('error')}")
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
        elif sec_res.get("status") == "failed":
            ci_failures.append(
                f"Repository Security Gate Failed: {sec_res.get('failing_findings_count', 0)} finding(s) met or exceeded severity threshold '{security_threshold.upper()}'."
            )
        elif sec_res.get("status") == "incomplete":
            ci_failures.append(f"Repository Security Gate Incomplete: {sec_res.get('coverage_warning')}")
    except Exception as e:
        logger.warning(f"CI security scan error: {e}")
        sec_res = {
            "status": "error",
            "passed": False,
            "error": str(e),
            "security_policy": sec_policy_clean,
            "severity_threshold": security_threshold.upper(),
            "target": repo_path,
            "metrics": {"total_findings": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0},
            "findings": [],
        }
        ci_failures.append(f"Security Scanner Infrastructure Error: {e}")
        exit_code = EXIT_INFRA_OR_CONFIG_ERROR
        status = "error"

    analysis_report = {
        "num_files": num_files,
        "num_chunks": num_chunks,
        "ast_chunks_count": ast_chunks,
        "ast_ratio_percent": ast_ratio,
        "ingestion_duration_seconds": round(elapsed_seconds, 3),
        "security_scan": sec_res,
    }

    patch_report: Dict[str, Any] = {"tested": False}

    # 2. Candidate Patch Verification (if specified)
    raw_patch = patch_content if patch_content is not None else (patch if patch is not None else patch_file)
    if raw_patch is not None:
        patch_report["tested"] = True
        patch_report["sandbox_mode"] = sandbox_mode
        patch_report["docker_image"] = docker_image

        patch_str = None
        if os.path.isfile(raw_patch):
            try:
                with open(raw_patch, "r", encoding="utf-8", errors="replace") as pf:
                    patch_str = pf.read()
            except Exception as exc:
                msg = f"Failed to read patch file '{raw_patch}': {exc}"
                ci_failures.append(msg)
                exit_code = EXIT_INFRA_OR_CONFIG_ERROR
                status = "error"
                patch_report["verified"] = False
                patch_report["outcome"] = "error"
                patch_report["error_message"] = msg
                _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
                _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
                return exit_code
        else:
            if patch_file and not os.path.isfile(patch_file) and "\n" not in patch_file:
                msg = f"Candidate patch file not found: '{patch_file}'"
                ci_failures.append(msg)
                exit_code = EXIT_INFRA_OR_CONFIG_ERROR
                status = "error"
                patch_report["verified"] = False
                patch_report["outcome"] = "error"
                patch_report["error_message"] = msg
                _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
                _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
                return exit_code
            patch_str = raw_patch

        patch_content = patch_str

        # Resolve target file
        resolved_target = target_file
        if not resolved_target:
            diff_match = re.search(r"^\+\+\+\s+[b/]*(.*?)(?:\t|\n|$)", patch_content, re.MULTILINE)
            if not diff_match:
                diff_match = re.search(r"^---\s+[a/]*(.*?)(?:\t|\n|$)", patch_content, re.MULTILINE)
            if diff_match:
                resolved_target = diff_match.group(1).strip()

        if not resolved_target:
            msg = "Missing required --target-file for candidate patch (could not infer from patch content)."
            ci_failures.append(msg)
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
            patch_report["verified"] = False
            patch_report["outcome"] = "error"
            patch_report["error_message"] = msg
            _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
            _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
            return exit_code

        from core.canonical_path import resolve_canonical_target_path
        canon_tgt, disambig_err = resolve_canonical_target_path(repo_path, resolved_target)
        if disambig_err:
            ci_failures.append(disambig_err)
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
            patch_report["verified"] = False
            patch_report["outcome"] = "error"
            patch_report["error_message"] = disambig_err
            _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
            _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
            return exit_code
        resolved_target = canon_tgt

        target_abs = os.path.join(repo_path, resolved_target)
        if not os.path.isfile(target_abs):
            msg = f"Target file '{resolved_target}' not found in repository."
            ci_failures.append(msg)
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
            patch_report["verified"] = False
            patch_report["outcome"] = "error"
            patch_report["error_message"] = msg
            _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
            _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
            return exit_code

        # Detect diff format vs replacement code explicitly
        has_diff_markers = bool(re.search(r"^(?:diff --git|--- |\+\+\+ |@@\s+-\d+)", patch_content, re.MULTILINE))
        if has_diff_markers:
            with open(target_abs, "r", encoding="utf-8", errors="replace") as tf:
                orig_code = tf.read()
            patched_code, diff_err = apply_unified_diff(orig_code, patch_content, expected_target_file=resolved_target)
            if patched_code is None:
                msg = f"Failed to cleanly apply candidate diff: {diff_err}"
                ci_failures.append(msg)
                exit_code = EXIT_VERIFICATION_FAILURE
                status = "failed"
                patch_report["verified"] = False
                patch_report["outcome"] = "failed"
                patch_report["error_message"] = msg
                _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
                _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
                return exit_code
        else:
            patched_code = patch_content

        # 2a. Candidate Security Gate: scan the patched disposable snapshot
        patch_report["candidate_snapshot"] = "patched_disposable_snapshot"
        td_kwargs = {"prefix": "cand_snapshot_"}
        if sys.version_info >= (3, 10):
            td_kwargs["ignore_cleanup_errors"] = True
        with tempfile.TemporaryDirectory(**td_kwargs) as snap_dir:
            snap_repo = os.path.join(snap_dir, "repo")
            shutil.copytree(
                repo_path,
                snap_repo,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules", "target", "build", ".pytest_cache"),
            )
            snap_target_abs = os.path.join(snap_repo, resolved_target)
            os.makedirs(os.path.dirname(snap_target_abs), exist_ok=True)
            with open(snap_target_abs, "w", encoding="utf-8") as sf:
                sf.write(patched_code)

            from core.security_scanner import run_security_scan
            try:
                cand_sec_res = run_security_scan(
                    snap_repo,
                    repo_root=snap_repo,
                    severity_threshold=security_threshold,
                    security_policy=sec_policy_clean,
                )
            except Exception as sec_exc:
                cand_sec_res = {
                    "status": "error",
                    "passed": False,
                    "error": str(sec_exc),
                    "security_policy": sec_policy_clean,
                    "severity_threshold": security_threshold.upper(),
                    "target": snap_repo,
                    "coverage_status": "error",
                    "incomplete_coverage": True,
                    "coverage_warning": f"Candidate scanner infrastructure error: {sec_exc}",
                    "metrics": {"total_findings": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0},
                    "findings": [],
                }

        patch_report["security_scan"] = cand_sec_res
        cand_sec_status = cand_sec_res.get("status", "error")
        patch_report["security_status"] = cand_sec_status
        patch_report["security_coverage"] = cand_sec_res.get("coverage_status", "unknown")
        patch_report["security_policy"] = sec_policy_clean
        cand_sec_approved = bool(cand_sec_status == "passed")
        patch_report["security_approved"] = cand_sec_approved
        patch_report["failing_findings_count"] = cand_sec_res.get("failing_findings_count", 0)

        if cand_sec_status == "error":
            msg = f"Candidate security scanner infrastructure error: {cand_sec_res.get('error', 'Scanner error')}"
            ci_failures.append(msg)
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
            patch_report["behavioral_status"] = "untested"
            patch_report["behavioral_verified"] = False
            patch_report["verified"] = False
            patch_report["overall_policy"] = "failed"
            patch_report["outcome"] = "error"
            patch_report["error_message"] = msg
            _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
            _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
            return exit_code
        elif cand_sec_status == "failed":
            ci_failures.append(
                f"Candidate patch rejected by Security Gate: {cand_sec_res.get('failing_findings_count', 0)} finding(s) met or exceeded severity threshold '{security_threshold.upper()}'."
            )
        elif cand_sec_status == "incomplete":
            ci_failures.append(
                f"Candidate patch Security Gate Incomplete: {cand_sec_res.get('coverage_warning')}"
            )

        from core.sandbox_runner import SandboxRunner
        effective_runtime = (runtime.lower() if runtime else SandboxRunner.detect_runtime(repo_path, resolved_target))
        patch_report["target_file"] = resolved_target
        patch_report["runtime"] = effective_runtime

        if sandbox_mode == "docker" and not SandboxRunner._check_docker_available():
            msg = "Infrastructure Error: Docker daemon is not running or unavailable for requested docker sandbox."
            ci_failures.append(msg)
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
            patch_report["behavioral_status"] = "error"
            patch_report["behavioral_verified"] = False
            patch_report["verified"] = False
            patch_report["overall_policy"] = "failed"
            patch_report["outcome"] = "error"
            patch_report["error_message"] = msg
            _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
            _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
            return exit_code

        runner = SandboxRunner(sandbox_mode=sandbox_mode, docker_image=docker_image, is_admin=True)
        test_res = runner.run_tests_with_patch(
            repo_path=repo_path,
            target_file=resolved_target,
            patched_code=patched_code,
            runtime=effective_runtime,
        )

        patch_report["framework"] = getattr(test_res, "framework", "unknown")
        patch_report["duration_seconds"] = round(getattr(test_res, "duration_seconds", 0.0), 3)
        patch_report["test_counts"] = {
            "passed": getattr(test_res, "passed_count", 0),
            "failed": getattr(test_res, "failed_count", 0),
            "skipped": getattr(test_res, "skipped_count", 0),
            "total": getattr(test_res, "total_count", 0),
        }
        patch_report["passed_tests"] = getattr(test_res, "passed_tests", [])
        patch_report["failed_tests"] = getattr(test_res, "failed_tests", [])
        patch_report["assertion_errors"] = [
            re.sub(r"(token|secret|password|key)=\S+", r"\1=[REDACTED]", err, flags=re.IGNORECASE)[:250]
            for err in getattr(test_res, "assertion_errors", [])
        ][:5]

        # Check infrastructure crash codes (-2: validation, -3: path traversal, -6: proc error, -8: docker offline)
        if test_res.exit_code in (-2, -3, -6, -8):
            msg = f"Sandbox execution infrastructure error ({test_res.exit_code}): {test_res.error_message}"
            ci_failures.append(msg)
            exit_code = EXIT_INFRA_OR_CONFIG_ERROR
            status = "error"
            patch_report["behavioral_status"] = "error"
            patch_report["behavioral_verified"] = False
            patch_report["verified"] = False
            patch_report["overall_policy"] = "failed"
            patch_report["outcome"] = "error"
            patch_report["error_message"] = msg
        else:
            tests_passed_count = getattr(test_res, "passed_count", 0)
            tests_failed_count = getattr(test_res, "failed_count", 0)
            tests_skipped = bool(getattr(test_res, "skipped", False) or (getattr(test_res, "skipped_count", 0) > 0 and tests_passed_count == 0))

            behavioral_verified = bool(
                test_res.success
                and not tests_skipped
                and tests_passed_count > 0
                and tests_failed_count == 0
            )
            if behavioral_verified:
                behavioral_status = "passed"
            elif tests_failed_count > 0 or (not test_res.success and not tests_skipped):
                behavioral_status = "failed"
            elif tests_skipped or tests_passed_count == 0:
                behavioral_status = "skipped"
            else:
                behavioral_status = "failed"

            patch_report["behavioral_status"] = behavioral_status
            patch_report["behavioral_verified"] = behavioral_verified

            is_verified = bool(behavioral_verified and cand_sec_approved)
            patch_report["verified"] = is_verified
            patch_report["overall_policy"] = "passed" if is_verified else "failed"

            if is_verified:
                patch_report["outcome"] = "passed"
            elif behavioral_status == "failed":
                patch_report["outcome"] = "behavioral_failed"
                ci_failures.append(
                    f"Candidate patch failed verification: {test_res.failed_count} test(s) failed."
                )
            elif behavioral_status == "skipped":
                patch_report["outcome"] = "behavioral_skipped"
                ci_failures.append(
                    f"Candidate patch unverified: zero tests executed or all tests skipped/ignored. ({test_res.error_message or 'No runnable tests'})"
                )
            elif not cand_sec_approved:
                if cand_sec_status == "incomplete":
                    patch_report["outcome"] = "incomplete_coverage"
                else:
                    patch_report["outcome"] = "security_rejected"
            else:
                patch_report["outcome"] = "failed"
                ci_failures.append(
                    "Candidate patch failed verification: test execution was unsuccessful."
                )

    if exit_code != EXIT_INFRA_OR_CONFIG_ERROR:
        if ci_failures:
            status = "failed"
            exit_code = EXIT_VERIFICATION_FAILURE
        else:
            status = "passed"
            exit_code = EXIT_SUCCESS

    _write_ci_report(output_json, status, exit_code, repo_path, analysis_report, patch_report, ci_failures)
    _render_ci_summary(repo_path, analysis_report, patch_report, ci_failures, status, exit_code)
    return exit_code


VERSION = "1.0.0"


def main():
    parser = argparse.ArgumentParser(description="IntelliCodeX CLI — AI Repository Intelligence")
    parser.add_argument("repo_path", nargs="?", default="sample_repo",
                        help="Local directory path or Git URL (default: sample_repo)")
    parser.add_argument("--server", type=str, default=None,
                        help="Remote IntelliCodeX server URL (e.g., http://localhost:8000)")
    parser.add_argument("--token", type=str, default=None,
                        help="JWT Bearer authentication token for remote server access")
    default_backend = os.getenv("DEFAULT_EMBEDDER_BACKEND", "ollama")
    parser.add_argument("--backend", choices=["ollama", "tfidf"], default=default_backend,
                        help=f"LLM & Embedding backend (default: {default_backend})")
    parser.add_argument("--model", type=str, default=None,
                        help="Ollama LLM model name (default: qwen2.5-coder:7b)")
    parser.add_argument("--temperature", type=float, default=None,
                        help="LLM sampling temperature (default: 0.0 for factual Q&A)")
    parser.add_argument("--num-predict", type=int, default=None,
                        help="LLM max output tokens cap (default: 800)")
    parser.add_argument("--repeat-penalty", type=float, default=None,
                        help="LLM repetition penalty (default: 1.1)")
    parser.add_argument("--full-history", action="store_true", default=False,
                        help="Clone remote Git repository with full history instead of shallow clone (--depth 1)")
    parser.add_argument("--legacy-call-graph", action="store_true", default=False,
                        help="Use legacy bare-name matching for call graph generation instead of scoped resolution")
    parser.add_argument("--include-overloads", action="store_true", default=False,
                        help="Include @typing.overload stub chunks (default: False, stubs are skipped)")
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
    parser.add_argument("--ci", action="store_true", default=False,
                        help="Run in headless CI/CD pipeline mode (exit codes: 0=success, 1=verification failure, 2=config/infra error)")
    parser.add_argument("--patch", dest="patch", type=str, default=None,
                        help="Candidate patch content string or path to verify in isolated sandbox (REQ-FUT-04)")
    parser.add_argument("--patch-file", dest="patch_file", type=str, default=None,
                        help="Path to candidate patch file to verify in isolated sandbox (REQ-FUT-04)")
    parser.add_argument("--target-file", type=str, default=None,
                        help="Target file within repository that the candidate patch applies to (REQ-FUT-04)")
    parser.add_argument("--runtime", type=str, default=None,
                        help="Language runtime for test verification (python, javascript, typescript, java, c, cpp, go, rust)")
    parser.add_argument("--sandbox", type=str, default="docker", choices=["docker", "local"],
                        help="Sandbox execution mode (default: docker)")
    parser.add_argument("--docker-image", type=str, default="intellicodex-sandbox:latest",
                        help="Docker sandbox image name (default: intellicodex-sandbox:latest)")
    parser.add_argument("--output-json", "--report-file", dest="output_json", type=str, default=None,
                        help="Path to write machine-readable JSON execution and verification report")
    parser.add_argument("--repos", type=str, default=None,
                        help="Comma-separated repository paths for federated multi-repo analysis (REQ-FUT-08)")
    parser.add_argument("--security", action="store_true", default=False,
                        help="Run static security vulnerability & secret scan on target repository and exit (REQ-FUT-05)")
    parser.add_argument("--security-threshold", type=str, default="HIGH", choices=["HIGH", "MEDIUM", "LOW", "high", "medium", "low"],
                        help="Severity threshold for security gate failure (default: HIGH)")
    parser.add_argument("--security-policy", type=str, default="strict", choices=["strict", "secrets_only", "STRICT", "SECRETS_ONLY"],
                        help="Security gate policy: 'strict' (default, rejects incomplete AST coverage) or 'secrets_only' (REQ-FUT-05)")
    parser.add_argument("-v", "--version", action="version", version=f"IntelliCodeX CLI v{VERSION}")
    args = parser.parse_args()

    has_patch = bool(args.patch or args.patch_file)
    if args.ci or has_patch:
        args.no_tui = True
        args.tui = False

        # Input Pre-Validation (REQ-FUT-04)
        if args.patch_file and not os.path.isfile(args.patch_file):
            msg = f"Candidate patch file not found: '{args.patch_file}'"
            print(f"[!] Configuration Error: {msg}")
            _write_ci_report(
                args.output_json,
                status="error",
                exit_code=EXIT_INFRA_OR_CONFIG_ERROR,
                repo_path=args.repo_path,
                error_message=msg,
                patch_verification={"tested": True, "verified": False, "outcome": "error", "error_message": msg},
            )
            return EXIT_INFRA_OR_CONFIG_ERROR

        if args.runtime and args.runtime.lower() not in ("python", "javascript", "typescript", "java", "c", "cpp", "go", "rust"):
            msg = f"Unsupported runtime: '{args.runtime}'. Supported: python, javascript, typescript, java, c, cpp, go, rust."
            print(f"[!] Configuration Error: {msg}")
            _write_ci_report(
                args.output_json,
                status="error",
                exit_code=EXIT_INFRA_OR_CONFIG_ERROR,
                repo_path=args.repo_path,
                error_message=msg,
                patch_verification={"tested": has_patch, "verified": False, "outcome": "error", "error_message": msg},
            )
            return EXIT_INFRA_OR_CONFIG_ERROR

        if has_patch and args.sandbox == "docker":
            from core.sandbox_runner import SandboxRunner
            if not SandboxRunner._check_docker_available():
                msg = "Infrastructure Error: Docker daemon is not running or unavailable"
                print(f"[!] {msg}")
                _write_ci_report(
                    args.output_json,
                    status="error",
                    exit_code=EXIT_INFRA_OR_CONFIG_ERROR,
                    repo_path=args.repo_path,
                    error_message=msg,
                    sandbox_mode="docker",
                    patch_verification={"tested": True, "verified": False, "outcome": "error", "error_message": msg, "sandbox_mode": "docker"},
                )
                return EXIT_INFRA_OR_CONFIG_ERROR

        is_remote_repo = (
            args.repo_path.startswith("http://")
            or args.repo_path.startswith("https://")
            or args.repo_path.startswith("git@")
        )
        if not is_remote_repo and not os.path.exists(args.repo_path):
            msg = f"Repository path invalid / not found: '{args.repo_path}'"
            print(f"[!] Configuration Error: {msg}")
            _write_ci_report(
                args.output_json,
                status="error",
                exit_code=EXIT_INFRA_OR_CONFIG_ERROR,
                repo_path=args.repo_path,
                error_message=msg,
            )
            return EXIT_INFRA_OR_CONFIG_ERROR

    if args.benchmark:
        target = resolve_repo_path(args.repo_path, full_history=args.full_history)
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

    if args.security:
        target = resolve_repo_path(args.repo_path, full_history=args.full_history)
        threshold = args.security_threshold.upper()
        policy = args.security_policy.lower().strip()
        print(f"\n[*] Running IntelliCodeX Security Vulnerability & Secret Scan on '{target}' (Policy: {policy.upper()}, Threshold: {threshold})...")
        from core.security_scanner import run_security_scan, format_security_report
        sec_res = run_security_scan(target, repo_root=target, severity_threshold=threshold, security_policy=policy)
        report_md = format_security_report(sec_res)
        print("\n" + report_md + "\n")
        if args.output_json:
            sanitized = _sanitize_report_data(sec_res)
            with open(args.output_json, "w", encoding="utf-8") as jf:
                json.dump(sanitized, jf, indent=2)
            print(f"[*] Security scan report written to: {args.output_json}")
        return 0 if sec_res.get("status") == "passed" else 1

    # Handle direct hook CLI flags if requested
    if args.setup_hooks:
        target = resolve_repo_path(args.repo_path, full_history=args.full_history)
        ok, msg = install_git_hooks(target)
        print(f"[*] {msg}")
        return 0 if ok else 1

    if args.check_hooks:
        target = resolve_repo_path(args.repo_path, full_history=args.full_history)
        st = check_git_hooks_status(target)
        print(f"[*] Git Hook Status for '{target}':")
        for hook, is_inst in st.items():
            print(f"  - {hook}: {'Installed' if is_inst else 'Not Installed'}")
        return 0

    if args.remove_hooks:
        target = resolve_repo_path(args.repo_path, full_history=args.full_history)
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

    embedder, llm, active_backend = create_components(
        args.backend,
        model=args.model,
        temperature=args.temperature,
        num_predict=args.num_predict,
        repeat_penalty=args.repeat_penalty,
    )

    # Multi-Repository Workspace Mode (REQ-FUT-08)
    if args.repos:
        from core.multi_repo import MultiRepoWorkspace
        repo_paths = [r.strip() for r in args.repos.split(",") if r.strip()]
        workspace = MultiRepoWorkspace(workspace_id="cli-multi-repo", embedder=embedder)
        print(f"[*] Initializing Multi-Repository Workspace for {len(repo_paths)} repositories...")
        for r_p in repo_paths:
            try:
                resolved_rp = resolve_repo_path(r_p, full_history=args.full_history)
                r_id = os.path.basename(resolved_rp.rstrip("/\\")) or resolved_rp
                workspace.add_repository(repo_id=r_id, repo_path=resolved_rp)
                print(f"  + Attached [{r_id}]: {resolved_rp}")
            except Exception as e_repo:
                print(f"  [!] Failed to attach repository '{r_p}': {e_repo}")

        print(f"[*] Total federated chunks: {len(workspace.namespaced_chunks)}")
        print(f"[*] Discovered microservice contracts: {len(workspace.contracts)}")
        for c in workspace.contracts:
            print(f"  - [{c.consumer_repo}] -> [{c.producer_repo}]: {c.endpoint_or_symbol} ({c.producer_file})")

        def _render_multi_repo_result(res: dict):
            render_markdown_panel(res.get("answer", ""), title="Multi-Repository Answer")
            obs = res.get("observed_facts", {})
            eps = obs.get("endpoint_definitions", [])
            calls = obs.get("client_call_sites", [])
            if eps or calls:
                print("\n[+] Observed Code Facts:")
                for ep in eps:
                    print(f"  - Endpoint: {ep['endpoint']} [{ep['repo_id']}:{ep['file']}:{ep['line']}] (symbol: {ep['symbol']})")
                for cs in calls:
                    print(f"  - Client Call: {cs['endpoint_or_pattern']} [{cs['repo_id']}:{cs['file']}:{cs['line']}]")
            
            inferred = res.get("inferred_relationships", [])
            if inferred:
                print("\n[?] Inferred Cross-Repository Relationships:")
                for rel in inferred:
                    print(f"  - {rel['consumer_repo']} -> {rel['producer_repo']}: {rel['endpoint_or_symbol']} (basis: {rel.get('basis', 'candidate')})")
            
            impact = res.get("candidate_impact_analysis", {})
            rev_files = impact.get("candidate_review_files", [])
            if rev_files:
                print("\n[*] Candidate Impact Analysis (Files requiring review):")
                for rf in rev_files:
                    print(f"  - [{rf['repo_id']}] {rf['file']} ({rf['role']})")
                if impact.get("disclaimer"):
                    print(f"  Note: {impact['disclaimer']}")

            chunks = res.get("retrieved_chunks", [])
            if chunks:
                print(f"\nSources ({len(chunks)}):")
                for c in chunks:
                    print(f"  - {c.get('citation')} (score={c.get('score', 0):.3f})")
            
            snaps = res.get("snapshot_info", {})
            if snaps:
                snap_strs = [f"{r}: {info.get('snapshot_id', 'unknown')}" for r, info in snaps.items()]
                print(f"\nFreshness: {', '.join(snap_strs)}")
            print()

        if args.query:
            res = workspace.ask(args.query, llm=llm)
            _render_multi_repo_result(res)
            return 0

        # Interactive loop for multi-repo
        print("\nMulti-Repository IntelliCodeX session ready. Type query, 'contracts', or 'exit'.\n")
        while True:
            try:
                q = input("multi-repo>> ").strip()
                if not q:
                    continue
                if q.lower() in ("exit", "quit", "q"):
                    print("[*] Exiting Multi-Repository Session.")
                    return 0
                if q.lower() in ("contracts", "contracts:list"):
                    print(f"[*] Discovered contracts ({len(workspace.contracts)}):")
                    for c in workspace.contracts:
                        print(f"  - {c.consumer_repo} -> {c.producer_repo}: {c.endpoint_or_symbol} (Producer: {c.producer_file}:{c.producer_line})")
                    continue
                res = workspace.ask(q, llm=llm)
                _render_multi_repo_result(res)
            except (KeyboardInterrupt, EOFError):
                print("\n[*] Exiting Multi-Repository Session.")
                return 0
            except Exception as e:
                print(f"[!] Error: {e}\n")

    skip_overload_stubs = not args.include_overloads
    try:
        current_path = resolve_repo_path(args.repo_path, full_history=args.full_history)
        print(f"[*] Ingesting repository: {current_path}")
        t0 = time.perf_counter()
        result = ingest_repository(current_path, embedder, legacy_call_graph=args.legacy_call_graph, skip_overload_stubs=skip_overload_stubs)
        elapsed = result.elapsed_seconds if getattr(result, "elapsed_seconds", 0) > 0 else (time.perf_counter() - t0)
    except KeyboardInterrupt:
        print("\n[!] Initial repository ingestion cancelled by user (Ctrl+C).")
        if args.repo_path != "sample_repo" and os.path.exists("sample_repo"):
            print("[*] Falling back to default 'sample_repo'...")
            try:
                current_path = "sample_repo"
                result = ingest_repository(current_path, embedder, legacy_call_graph=args.legacy_call_graph, skip_overload_stubs=skip_overload_stubs)
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
        repo_path=current_path,
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

        if bq.lower() in ("arch", "cycles", "optimize", "architecture"):
            from core.architecture_optimizer import ArchitectureOptimizer
            optimizer = ArchitectureOptimizer()
            arch_report = optimizer.analyze(
                dep_graph=result.graph,
                source_files=getattr(result, "source_files", None),
                llm=llm,
                repo_id=os.path.basename(current_path),
                snapshot_id="cli_session",
            )
            render_markdown_panel(arch_report.format_markdown(), title="Architecture Optimization Report")
            return 0

        if bq.lower().startswith("explain:") or bq.lower().startswith("explain "):
            execute_explain_command(engine, result, bq, active_file_filter=None)
            return 0

        if bq.lower().startswith("graph:") or bq.lower().startswith("graph "):
            execute_graph_command(result, bq)
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
        response = engine.ask(cleaned_query, file_filter=effective_file_filter, append_sources=True)
        total_batch = response.get("elapsed_seconds", time.perf_counter() - t_batch)

        # Requirement F: Print retrieved chunks list before the answer (as in interactive mode)
        retrieved_chunks = response.get("retrieved_chunks", [])
        retrieval_time = response.get("retrieval_seconds", 0.0)
        print(f"--- Retrieved {len(retrieved_chunks)} chunks ({format_time_consumed(retrieval_time)}) ---")
        for rc in retrieved_chunks:
            c_fp = rc.get("file") or rc.get("file_path", "")
            c_name = rc.get("name", "")
            c_score = rc.get("score", 0.0)
            c_lines = rc.get("lines") or f"{rc.get('start_line', '')}-{rc.get('end_line', '')}"
            c_reason = rc.get("reason", "")
            reason_str = f", context={c_reason}" if c_reason else ""
            print(f"  {c_fp} :: {c_name} (lines {c_lines}, score={c_score:.3f}{reason_str})")
        print()

        render_markdown_panel(response['answer'], title="Answer")
        print(f"[*] [Time Consumed]: {format_time_consumed(total_batch)} (Retrieval: {format_time_consumed(response.get('retrieval_seconds', 0.0))}, Generation: {format_time_consumed(response.get('llm_seconds', 0.0))})\n")
        return 0

    # Headless CI Pipeline Gate & Patch Verification (REQ-FUT-04)
    if args.ci or args.patch or args.patch_file:
        return run_ci_pipeline(
            repo_path=current_path,
            result=result,
            elapsed_seconds=elapsed,
            patch=args.patch,
            patch_file=args.patch_file,
            target_file=args.target_file,
            runtime=args.runtime,
            sandbox_mode=args.sandbox,
            docker_image=args.docker_image,
            output_json=args.output_json,
            security_threshold=args.security_threshold.upper(),
            security_policy=args.security_policy.lower().strip(),
        )

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
            atexit.register(watcher.stop)
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
            os.system("cls" if os.name == "nt" else "clear")  # nosec B605
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

        if query.lower() in ("arch", "cycles", "optimize", "architecture"):
            t_arch = time.perf_counter()
            from core.architecture_optimizer import ArchitectureOptimizer
            optimizer = ArchitectureOptimizer()
            arch_report = optimizer.analyze(
                dep_graph=result.graph,
                source_files=getattr(result, "source_files", None),
                llm=llm,
                repo_id=os.path.basename(current_path),
                snapshot_id="cli_session",
            )
            render_markdown_panel(arch_report.format_markdown(), title="Architecture Optimization Report")
            print(f"[*] [Time Consumed]: Architecture analysis in {format_time_consumed(time.perf_counter() - t_arch)}\n")
            continue

        if query.lower().startswith("why:") or query.lower().startswith("org:") or query.lower().startswith("history:"):
            target_q = query.split(":", 1)[1].strip()
            if not target_q:
                print("[!] Please provide a question (e.g. 'why:did we choose FAISS?').\n")
                continue
            t_org = time.perf_counter()
            from core.org_memory import OrgMemoryStore
            org_store = OrgMemoryStore(repo_id=os.path.basename(current_path), embedder=embedder)
            org_store.ingest_repository(current_path)
            res = org_store.ask(target_q, llm=llm)
            render_markdown_panel(res.get("answer", ""), title="Organizational Memory Rationale")
            if res.get("retrieved_records"):
                print("[*] Retrieved Organizational Records:")
                for rec in res["retrieved_records"]:
                    print(f"  - {rec.get('citation')} [{rec.get('type')}, status: {rec.get('verification_status')}, scope: {rec.get('scope')}]: {rec.get('title')}")
            if res.get("citations"):
                print(f"Historical Citations: {', '.join(res['citations'])}")
            print(f"[*] [Time Consumed]: Org memory query in {format_time_consumed(time.perf_counter() - t_org)}\n")
            continue

        if query.lower().startswith("decision:") or query.lower().startswith("decision "):
            raw_dec = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            if "|" in raw_dec:
                dec_title, dec_content = [p.strip() for p in raw_dec.split("|", 1)]
            else:
                dec_title = raw_dec
                dec_content = raw_dec

            if not dec_title:
                print("[!] Usage: decision: <title> | <rationale and context>\n")
                continue

            from core.org_memory import OrgMemoryStore
            r_id = os.path.basename(current_path)
            org_store = OrgMemoryStore(repo_id=r_id, embedder=embedder)
            item = org_store.record_decision(
                title=dec_title,
                content=dec_content,
                author="cli_developer",
                repo_id=r_id,
                scope="repo_private",
            )
            print(f"\n[*] Recorded Developer Decision: {item.citation}")
            print(f"  - Title: {item.title}")
            print(f"  - Verification: {item.verification_status} (developer approved)")
            print(f"  - Scope: {item.scope} (repository private)\n")
            continue

        if query.lower() in ("adrs", "adr", "decisions"):
            from core.org_memory import ADRMiner, OrgMemoryStore
            found_adrs = ADRMiner.mine_adrs(current_path)
            r_id = os.path.basename(current_path)
            org_store = OrgMemoryStore(repo_id=r_id, embedder=embedder)
            custom_decisions = [it for it in org_store.items if it.memory_type == "decision" and it.state == "active"]

            if not found_adrs and not custom_decisions:
                print("[*] No Architectural Decision Records (ADRs) or recorded decisions found in repository.\n")
            else:
                if found_adrs:
                    print(f"[*] Found {len(found_adrs)} Architectural Decision Record(s):")
                    for a in found_adrs:
                        print(f"  - [{a.metadata.get('status', 'Accepted')}] {a.title} ({a.metadata.get('file_path', '')})")
                if custom_decisions:
                    print(f"\n[*] Found {len(custom_decisions)} Recorded Decision(s):")
                    for d in custom_decisions:
                        print(f"  - {d.citation} [{d.verification_status}]: {d.title}")
                print()
            continue

        if query.lower() in ("learned", "experiences", "memory:repairs"):
            from core.self_improving import global_experience_bank
            stats = global_experience_bank.get_stats()
            print(f"[*] Self-Improving Agent Memory Bank (REQ-FUT-10):")
            print(f"  - Total Learned Experiences: {stats['total_experiences']}")
            print(f"  - Total Successful Fixes: {stats['total_successful_repairs']}")
            print("  - Learned Error Patterns:")
            for et, count in stats["error_types_breakdown"].items():
                print(f"    * {et}: {count} verified pattern(s)")
            print()
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
                new_result = ingest_repository(current_path, new_embedder, skip_overload_stubs=skip_overload_stubs)
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

        # --- repo remove <number|name>: unregister repository ---
        if (query.strip() in ("repo remove", "repo:remove") or
            query.startswith("repo remove ") or query.startswith("repo:remove ")):
            if query.startswith("repo remove "):
                target_arg = query[len("repo remove "):]
            elif query.startswith("repo:remove "):
                target_arg = query[len("repo:remove "):]
            else:
                target_arg = ""
            handle_repo_remove(target_arg, current_path, confirm_fn=input)
            continue

        if (query.startswith("repo ") or query.startswith("repo:") or 
            query.startswith("clone ") or query.startswith("repo-clone ") or
            query.startswith("use ") or query.startswith("ingest ") or 
            query.startswith("http://") or query.startswith("https://") or query.startswith("git@")):

            full_hist = False
            if "--full-history" in query:
                full_hist = True
                query = query.replace("--full-history", "").strip()

            if query.startswith("repo:"):
                target = query[len("repo:"):].strip()
            elif query.startswith("clone "):
                target = query[len("clone "):].strip()
            elif query.startswith("repo-clone "):
                target = query[len("repo-clone "):].strip()
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
                new_path = resolve_repo_path(target, full_history=full_hist)
                try:
                    from core.persistence import clear_unregistered_repo
                    clear_unregistered_repo(new_path)
                except Exception:
                    pass
                print(f"[*] Parsing files and generating embeddings for '{new_path}'...")
                t_repo = time.perf_counter()
                new_result = ingest_repository(new_path, embedder, skip_overload_stubs=skip_overload_stubs)
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

        # Security Scanner: security:<file> (REQ-FUT-05)
        if query.lower().startswith("security:") or query.lower().startswith("security "):
            sec_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            from core.security_scanner import run_security_scan, format_security_report
            if sec_target in ("", ".", "repo", "all"):
                abs_sec = current_path
            else:
                abs_sec = os.path.join(current_path, sec_target) if not os.path.isabs(sec_target) else sec_target
            if not os.path.exists(abs_sec):
                print(f"[!] Path not found: {sec_target}\n")
                continue
            print(f"[*] Running multi-layer security & secret scan on '{sec_target or '.'}'...")
            sec_result = run_security_scan(abs_sec, repo_root=current_path, severity_threshold="HIGH")
            sec_report = format_security_report(sec_result, llm=engine.llm)
            if HAS_RICH and console:
                console.print(Panel(sec_report, title=f"[bold red]Security Scan: {sec_target or '.'}[/bold red]", border_style="red"))
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
            from core.canonical_path import resolve_canonical_target_path, discover_relevant_tests
            all_indexed = [c.file_path for c in result.store.chunks] if hasattr(result, "store") and result.store and hasattr(result.store, "chunks") else None

            # If user didn't use @file but passed a filename or file path directly
            if not mention_f and err_input:
                raw_cand = err_input.lstrip("@").strip()
                c_test, _ = resolve_canonical_target_path(current_path, raw_cand, candidate_files=all_indexed)
                if c_test:
                    mention_f = c_test
                    clean_err = ""

            repair_extra_files = None
            repair_contract_type = "existing_tests"

            if mention_f:
                canon_path, disambig_err = resolve_canonical_target_path(current_path, mention_f, candidate_files=all_indexed)
                if disambig_err:
                    if HAS_RICH and console:
                        console.print(f"\n[bold red][!] Target File Error:[/bold red]\n{disambig_err}\n")
                    else:
                        print(f"\n[!] Target File Error:\n{disambig_err}\n")
                    continue
                mention_f = canon_path
                print(f"[*] Target resolved to canonical path: '{mention_f}'")

                from core.sandbox_runner import SandboxRunner
                sb_runner = SandboxRunner(
                    sandbox_mode=getattr(args, "sandbox", "docker"),
                    docker_image=getattr(args, "docker_image", "intellicodex-sandbox:latest"),
                    allow_local_sandbox=True,
                    is_admin=True,
                )

                # Discover existing relevant tests for target file
                discovered_tests = discover_relevant_tests(current_path, mention_f)
                if not discovered_tests:
                    from core.test_proposer import TestProposer, format_test_proposal_card

                    msg_no_tests = (
                        f"[*] No existing tests discovered for '{mention_f}'.\n"
                        f"[*] Retrieving repository specifications, docstrings, README, and call sites..."
                    )
                    if HAS_RICH and console:
                        console.print(f"\n[bold yellow]{msg_no_tests}[/bold yellow]\n")
                    else:
                        print(f"\n{msg_no_tests}\n")

                    proposer = TestProposer()
                    user_clarif = None
                    proposal_accepted = False
                    proposal = None

                    while True:
                        analysis = proposer.analyze_contract(current_path, mention_f, user_clarification=user_clarif)
                        if analysis.is_ambiguous:
                            msg_ambig = f"[!] SPECIFICATION AMBIGUITY DETECTED: {analysis.ambiguity_reason}"
                            q_str = f"[*] Clarification Needed: {analysis.clarification_question}"
                            if HAS_RICH and console:
                                console.print(f"\n[bold red]{msg_ambig}[/bold red]")
                                console.print(f"[bold cyan]{q_str}[/bold cyan]")
                                for idx, opt in enumerate(analysis.clarification_options, 1):
                                    console.print(f"    [yellow][{idx}][/yellow] {opt}")
                            else:
                                print(f"\n{msg_ambig}")
                                print(q_str)
                                for idx, opt in enumerate(analysis.clarification_options, 1):
                                    print(f"    [{idx}] {opt}")

                            clarif_prompt = f"Please select option (1-{len(analysis.clarification_options)}) or enter clarification: "
                            try:
                                if session is not None and use_tui:
                                    ans = session.prompt(clarif_prompt).strip()
                                else:
                                    ans = input(clarif_prompt).strip()
                            except (EOFError, KeyboardInterrupt):
                                ans = ""

                            if ans.isdigit() and 1 <= int(ans) <= len(analysis.clarification_options):
                                user_clarif = analysis.clarification_options[int(ans) - 1]
                            else:
                                user_clarif = ans.strip()

                            if not user_clarif:
                                msg_abort = "[!] Specification ambiguity unresolved. Aborting to avoid inventing ungrounded assertions."
                                if HAS_RICH and console:
                                    console.print(f"\n[bold red]{msg_abort}[/bold red]\n")
                                else:
                                    print(f"\n{msg_abort}\n")
                                break
                            print(f"[*] Specification clarified as: '{user_clarif}'")
                            continue

                        # Propose candidate tests and validate inside Docker
                        print(f"[*] Generating candidate test contract grounded in identified sources...")
                        proposal = proposer.generate_candidate_tests(current_path, mention_f, analysis, llm=llm)
                        print(f"[*] Validating candidate tests inside Docker sandbox ({getattr(args, 'docker_image', 'intellicodex-sandbox:latest')})...")
                        val = proposer.validate_proposed_tests_in_docker(sb_runner, current_path, proposal)

                        card_str = format_test_proposal_card(proposal)
                        print(card_str)
                        print("\n--- PROPOSED CANDIDATE TEST CODE (DISPOSABLE STORAGE) ---")
                        print(proposal.test_code)
                        print("---------------------------------------------------------\n")

                        if not val.is_runnable or val.harness_errors:
                            msg_harness = (
                                f"[!] Proposed tests failed Docker harness validation. "
                                f"Harness / import errors detected: {', '.join(val.harness_errors)}. "
                                f"Proposed tests cannot be used as an accepted contract."
                            )
                            if HAS_RICH and console:
                                console.print(f"[bold red]{msg_harness}[/bold red]\n")
                            else:
                                print(f"{msg_harness}\n")
                            break

                        # Review prompt for user
                        prompt_choice = "Candidate Test Action ([a]ccept & proceed to repair, [r]eject, [c]larify): "
                        try:
                            if session is not None and use_tui:
                                user_act = session.prompt(prompt_choice).strip().lower()
                            else:
                                user_act = input(prompt_choice).strip().lower()
                        except (EOFError, KeyboardInterrupt):
                            user_act = "r"

                        if user_act in ("c", "clarify"):
                            c_prompt = "Enter additional contract clarification / specification detail: "
                            try:
                                if session is not None and use_tui:
                                    user_clarif = session.prompt(c_prompt).strip()
                                else:
                                    user_clarif = input(c_prompt).strip()
                            except (EOFError, KeyboardInterrupt):
                                user_clarif = None
                            continue
                        elif user_act in ("a", "accept", "y", "yes"):
                            proposal_accepted = True
                            proposal.accepted = True
                            proposal.frozen = True
                            print(f"[✓] Candidate test contract accepted and FROZEN at '{proposal.disposable_path}'.")
                            break
                        else:
                            print(f"[*] Candidate test proposal rejected. Proposed tests retained at '{proposal.disposable_path}' without modifying repository.")
                            break

                    if not proposal_accepted or not proposal:
                        continue

                    target_dir = os.path.dirname(mention_f)
                    target_base = os.path.splitext(os.path.basename(mention_f))[0]
                    rel_test_file = os.path.join(target_dir, f"test_{target_base}.py").replace("\\", "/") if target_dir else f"test_{target_base}.py"
                    repair_extra_files = {rel_test_file: proposal.test_code}
                    repair_contract_type = "ai_generated_proposal"
                    discovered_tests = [f"{rel_test_file} (AI-Generated Proposal)"]
                else:
                    print(f"[*] Discovered {len(discovered_tests)} relevant test file(s): {', '.join(discovered_tests)}")

                # Run baseline test suite inside Docker sandbox without requiring user to paste failures
                print(f"[*] Running baseline test suite inside Docker sandbox for '{mention_f}'...")
                baseline_res = sb_runner.run_baseline_tests(current_path, mention_f, extra_files=repair_extra_files)

                if baseline_res.success and baseline_res.passed_count > 0 and baseline_res.failed_count == 0:
                    if not clean_err or not clean_err.strip():
                        msg_all_pass = (
                            f"[✓] BASELINE: All {baseline_res.passed_count} discovered tests for '{mention_f}' are currently PASSING in Docker sandbox.\n"
                            f"[*] No baseline failure detected. If you want to modify functionality, please provide a prompt or failing test specification."
                        )
                        if HAS_RICH and console:
                            console.print(f"\n[bold green]{msg_all_pass}[/bold green]\n")
                        else:
                            print(f"\n{msg_all_pass}\n")
                        continue
                    else:
                        err_input = f"File modification instruction for {mention_f}: {clean_err.strip()}"
                else:
                    print(f"[*] Baseline test failure captured: {baseline_res.failed_count} failed, {baseline_res.passed_count} passed.")
                    for ft in baseline_res.failed_tests:
                        print(f"    - [FAIL] {ft}")
                    for pt in baseline_res.passed_tests:
                        print(f"    - [PASS] {pt}")

                    pass_block = "\n".join(f"- {pt}" for pt in baseline_res.passed_tests) if baseline_res.passed_tests else "- None (all tests failing)"
                    fail_block = "\n".join(f"- {ft}" for ft in baseline_res.failed_tests) if baseline_res.failed_tests else "- Baseline test failure"
                    assert_block = "\n".join(f"- {ae}" for ae in baseline_res.assertion_errors) if baseline_res.assertion_errors else f"- {baseline_res.error_message or 'Assertion failed'}"

                    err_input = (
                        f"Baseline test failures detected in Docker sandbox for '{mention_f}':\n"
                        f"Discovered Test Files: {', '.join(discovered_tests)}\n\n"
                        f"Failed Tests:\n{fail_block}\n\n"
                        f"Passing Tests (MUST PRESERVE - DO NOT BREAK):\n{pass_block}\n\n"
                        f"Assertion Errors:\n{assert_block}\n\n"
                        f"Test Traceback / Output Details:\n{baseline_res.traceback_summary}\n"
                    )
                    if clean_err and clean_err.strip():
                        err_input += f"\nUser Instruction / Additional Notes: {clean_err.strip()}\n"
            else:
                from core.sandbox_runner import SandboxRunner
                sb_runner = SandboxRunner(
                    sandbox_mode=getattr(args, "sandbox", "docker"),
                    docker_image=getattr(args, "docker_image", "intellicodex-sandbox:latest"),
                    allow_local_sandbox=True,
                    is_admin=True,
                )

            print("\n[*] Analyzing error report & localizing bug root cause...")
            t_fix = time.perf_counter()
            patch_engine = PatchEngine(
                result.store, 
                embedder, 
                llm, 
                graph=result.graph, 
                repo_path=current_path,
                sandbox_runner=sb_runner,
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
                extra_files=repair_extra_files,
                contract_type=repair_contract_type,
            )
            fix_time = time.perf_counter() - t_fix

            render_patch_card(patch_rec, fix_time)

            is_verified = patch_rec.get("sandbox_validation", {}).get("verified", False)
            if not is_verified or patch_rec.get("status") != "verified":
                failed_tests = patch_rec.get("sandbox_validation", {}).get("test_result", {}).get("failed_tests", [])
                err_summary = patch_rec.get("sandbox_validation", {}).get("test_result", {}).get("traceback_summary", "")
                unresolved_msg = (
                    f"\n[!] REPAIR UNRESOLVED: Candidate patch exhausted all refinement attempts without passing sandbox test verification."
                )
                if HAS_RICH and console:
                    console.print(f"[bold yellow]{unresolved_msg}[/bold yellow]")
                    if failed_tests:
                        console.print(f"    [red]Remaining Failing Tests:[/red] {', '.join(failed_tests)}")
                    if err_summary:
                        console.print(f"    [dim]Failure Traceback Summary:\n{err_summary[:400]}[/dim]\n")
                else:
                    print(unresolved_msg)
                    if failed_tests:
                        print(f"    Remaining Failing Tests: {', '.join(failed_tests)}")
                    if err_summary:
                        print(f"    Failure Traceback Summary:\n{err_summary[:400]}\n")

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
                        verification_info=patch_rec.get("sandbox_validation", {}),
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
                        from core.patch_generator import evaluate_patch_approval_gate
                        ok_gate, msg_gate = evaluate_patch_approval_gate(patch_rec)
                        if not ok_gate:
                            msg_reject = f"[!] APPROVAL REJECTED: {msg_gate}"
                            if HAS_RICH and console:
                                console.print(f"\n[bold red]{msg_reject}[/bold red]\n")
                            else:
                                print(f"\n{msg_reject}\n")
                            break

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



        if query.lower().startswith("graph:") or query.lower().startswith("graph "):
            execute_graph_command(result, query)
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
            
            # Deduplicate by chunk_id
            seen_cids = set()
            deduped_results = []
            for item in expanded_results:
                c = item[0] if isinstance(item, tuple) else item.get("chunk")
                if c and getattr(c, "chunk_id", None):
                    if c.chunk_id not in seen_cids:
                        seen_cids.add(c.chunk_id)
                        deduped_results.append(item)
                else:
                    deduped_results.append(item)
            expanded_results = deduped_results

            def _format_entry_80col(file_path: str, name: str, lines: str, score: float, reason: str = "", max_width: int = 80) -> str:
                prefix = f"  {file_path} :: {name} (lines {lines}, score={score:.3f}"
                suffix = f", context={reason})" if reason else ")"
                full = prefix + suffix
                if len(full) <= max_width:
                    return full
                avail_for_reason = max_width - len(prefix) - len(", context=...)")
                if avail_for_reason > 5 and reason:
                    trunc_reason = reason[:avail_for_reason] + "..."
                    cand = f"{prefix}, context={trunc_reason})"
                    if len(cand) <= max_width:
                        return cand
                cand = f"{prefix})"
                if len(cand) <= max_width:
                    return cand
                return prefix[:max_width - 4] + "...)"

            print(f"--- Retrieved {len(expanded_results)} chunks ({format_time_consumed(t_retrieval)}) ---")
            for item in expanded_results:
                chunk = item[0] if isinstance(item, tuple) else item["chunk"]
                score = item[1] if isinstance(item, tuple) else item["score"]
                reason = item[2] if isinstance(item, tuple) and len(item) > 2 else (item.get("reason", "") if isinstance(item, dict) else "")
                lines_str = f"{chunk.start_line}-{chunk.end_line}"
                print(_format_entry_80col(chunk.file_path, chunk.name, lines_str, score, reason, max_width=80))

            # Phase 2: Stream LLM answer tokens in real-time (or fall back to ask() for tfidf mode)
            print(f"\n--- Answer ---")
            if engine.llm is not None and hasattr(engine.llm, "stream_generate"):
                # Streaming path: tokens appear immediately as they are generated
                from rag.query_engine import format_context, QA_SYSTEM_PROMPT, strip_qa_scaffolding, partition_sources
                context = format_context(expanded_results, max_token_budget=3000)

                current_files = {
                    c.file_path
                    for item in expanded_results
                    for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
                    if c and getattr(c, "file_path", None)
                }
                if len(engine.memory) > 0 and engine.memory.is_topic_shifted(current_files):
                    engine.memory.clear()

                is_analysis = engine.memory.is_code_analysis_question(cleaned_query)
                history_str = engine.memory.format_history(is_analysis=is_analysis) if len(engine.memory) > 0 else ""
                file_scope_note = ""
                if effective_file_filter:
                    file_scope_note = (
                        f"SCOPE: Focus your answer on '{effective_file_filter}'. "
                        f"The context below is scoped to this file. Answer the user's question using this context.\n\n"
                    )

                is_bug_query = engine._classify_query_intent(cleaned_query, file_filter=effective_file_filter)
                
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
                    system_prompt_to_use = engine.system_prompt
                else:
                    anti_hallucination = (
                        "Answer the question directly based on the provided repository context. "
                        "Cite file paths and line numbers accurately. Do not invent or assume behavior not shown in the context.\n\n"
                    )
                    system_prompt_to_use = QA_SYSTEM_PROMPT
                    context = strip_qa_scaffolding(context)

                prompt_parts = []
                if history_str:
                    prompt_parts.append(history_str)
                prompt_parts.append(anti_hallucination + file_scope_note + f"Repository context:\n\n{context}")
                prompt_parts.append(f"Question: {cleaned_query}\n\nAnswer:")
                prompt = "\n\n".join(prompt_parts)

                accumulated = []
                t_gen_start = time.perf_counter()
                temp = 0.0
                for token in engine.llm.stream_generate(prompt, system=system_prompt_to_use, temperature=temp):
                    if not is_bug_query:
                        curr_text = "".join(accumulated) + token
                        drift_match = re.search(r'(?:###\s*Analysis|\bMATCH\b|\bMISMATCH\b)', curr_text)
                        if drift_match:
                            break
                    print(token, end="", flush=True)
                    accumulated.append(token)
                print()

                full_answer = "".join(accumulated)
                
                # Anti-hallucination filter for bug queries
                if is_bug_query:
                    full_answer = engine._filter_hallucinated_claims(full_answer, expanded_results)
                    print(f"\n[Anti-hallucination filter applied]")

                relied_items, other_items = partition_sources(full_answer, expanded_results)
                relied_sources = [
                    f"{c.file_path}:{c.start_line}-{c.end_line}"
                    for item in relied_items
                    for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
                    if c and getattr(c, "file_path", None)
                ]
                relied_sources = list(dict.fromkeys(relied_sources))

                other_sources = [
                    f"{c.file_path}:{c.start_line}-{c.end_line}"
                    for item in other_items
                    for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
                    if c and getattr(c, "file_path", None)
                ]
                other_sources = list(dict.fromkeys(other_sources))

                full_answer, unv_f, unv_s = engine._post_process_answer(
                    full_answer,
                    sources=relied_sources,
                    append_to_answer=False,
                    retrieved_context=other_sources,
                )
                if relied_sources and "Sources:" not in "".join(accumulated):
                    print(f"\nSources: {', '.join(relied_sources)}")
                if other_sources and "Retrieved context:" not in "".join(accumulated):
                    print(f"\nRetrieved context: {', '.join(other_sources)}")
                if unv_f:
                    print(f"\n[Unverified file path(s): {', '.join(unv_f)}]")
                if unv_s:
                    print(f"\n[Unverified names: {', '.join(unv_s)}]")
                
                _last_answer = full_answer
                engine.memory.add_turn(cleaned_query, full_answer, files=current_files)
                t_llm = time.perf_counter() - t_gen_start
                total_time = time.perf_counter() - t_ask
            else:
                # Offline / tfidf fallback: use standard ask() without streaming
                response = engine.ask(cleaned_query, append_sources=True)
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
        try:
            watcher.stop()
        except Exception:
            pass
    return 0



if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nExiting IntelliCodeX CLI. Goodbye!")
        sys.exit(0)
    except SystemExit as e:
        sys.exit(e.code)
    except Exception as e:
        sys.stderr.write(f"\n[!] Unexpected fatal error: {e}\n")
        sys.exit(1)
