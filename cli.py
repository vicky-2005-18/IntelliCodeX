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
from backend.services.incremental_indexer import RepositoryWatcher

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.table import Table
    from rich.syntax import Syntax
    from rich.text import Text
    console = Console()
    HAS_RICH = True
except ImportError:
    console = None
    HAS_RICH = False

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import HTML
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False
    Completer = object
    Completion = None


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
  hooks / setup-hooks   - Install Git background re-indexing hooks for current repository
  hooks:status          - Check status of installed Git hooks
  hooks:remove          - Uninstall Git background re-indexing hooks
  watch / watch:status   - Check real-time file watcher status
  watch:stop / watch:start - Stop or restart real-time file watching
  hybrid / hybrid:status - Check hybrid search status (BM25 + Dense RRF)
  hybrid:on / hybrid:off - Enable or disable BM25 hybrid ranking
  files / ls             - List all indexed source files in the active repository
  clear / cls            - Clear terminal screen
  help / ?               - Show this help message
  exit / quit            - Exit IntelliCodeX CLI
"""
    print(help_text)


def get_available_repos(current_path: str) -> list:
    """Returns a list of (label, abs_path) tuples for all known local repositories.

    Scans:
    - The .repos/ folder (cloned remote repos)
    - sample_repo (built-in demo)
    - The currently active repository (if not already listed)
    """
    known: list = []  # list of (label, abs_path)
    seen_paths: set = set()

    # 1. Built-in sample_repo
    sample_abs = os.path.abspath("sample_repo")
    if os.path.isdir(sample_abs):
        known.append(("sample_repo", sample_abs))
        seen_paths.add(sample_abs)

    # 2. Everything cloned into .repos/
    repos_dir = os.path.abspath(".repos")
    if os.path.isdir(repos_dir):
        for entry in sorted(os.scandir(repos_dir), key=lambda e: e.name.lower()):
            if entry.is_dir() and os.path.isdir(os.path.join(entry.path, ".git")):
                abs_p = os.path.abspath(entry.path)
                if abs_p not in seen_paths:
                    known.append((entry.name, abs_p))
                    seen_paths.add(abs_p)

    # 3. Currently active repo if not already listed
    active_abs = os.path.abspath(current_path)
    if active_abs not in seen_paths and os.path.isdir(active_abs):
        label = os.path.basename(active_abs)
        known.append((label, active_abs))
        seen_paths.add(active_abs)

    return known


def should_use_tui() -> bool:
    """Returns True if rich prompt_toolkit interactive session should be enabled."""
    if not HAS_PROMPT_TOOLKIT:
        return False
    if os.environ.get("INTELLICODEX_NO_TUI", "").strip() == "1":
        return False
    try:
        if not sys.stdin.isatty():
            return False
    except Exception:
        return False
    return True


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
    time_str = format_time_consumed(fix_time)
    conf = f"{patch_rec.get('confidence_score', 0):.0%}"

    if HAS_RICH and console:
        status_color = "green" if sb_status == "PASSED" else ("red" if sb_status == "FAILED" else "yellow")
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="bold cyan", justify="right")
        info_table.add_column(style="white")
        info_table.add_row("Target File:", patch_rec.get("target_file", "Unknown"))
        info_table.add_row("Error Type:", str(patch_rec.get("error_type", "Unknown")))
        info_table.add_row("Confidence:", conf)
        info_table.add_row("Sandbox Tests:", f"[{status_color}]{sb_status} (Iterations: {sb_turns})[/{status_color}]")
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
        print(f"Sandbox Tests   : {sb_status} (Iterations: {sb_turns})")
        print(f"Time Consumed   : {time_str}")
        print(f"Explanation     : {patch_rec['explanation']}")
        print("\n--- Unified Git Diff ---")
        print(patch_rec.get("git_diff", ""))
        print("=======================================================================\n")


class IntelliCodeXCompleter(Completer if HAS_PROMPT_TOOLKIT else object):
    """Context-aware autocompleter for commands, files, symbols, and settings."""

    COMMANDS = [
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

VERSION = "1.0.0"


def main():
    parser = argparse.ArgumentParser(description="IntelliCodeX CLI — AI Repository Intelligence")
    parser.add_argument("repo_path", nargs="?", default="sample_repo",
                        help="Local directory path or Git URL (default: sample_repo)")
    parser.add_argument("--backend", choices=["ollama", "tfidf"], default="tfidf",
                        help="LLM & Embedding backend (default: tfidf)")
    parser.add_argument("-q", "--query", type=str,
                        help="Execute a non-interactive query in batch mode and exit")
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

    print_ingestion_summary(result, current_path, elapsed)

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
        print(f"\n[*] Executing Batch Query: '{args.query}'\n")
        t_batch = time.perf_counter()
        response = engine.ask(args.query)
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
        sys.stdout.write(f"\n[*] [Watchdog] Detected changes in {diff_desc}. Auto-reindexed ({result.num_chunks} chunks in {t_str}).\n>> ")
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
        syms = set()
        if result:
            call_g = getattr(result, "call_graph", None)
            if call_g:
                syms.update(call_g.nodes())
            if getattr(result, "store", None) and result.store.chunks:
                for c in result.store.chunks:
                    if c.name and "::" in c.name:
                        syms.add(c.name.split("::")[-1])
                    elif c.name:
                        syms.add(c.name)
        return sorted(list(syms))

    completer = IntelliCodeXCompleter(
        get_files_fn=get_indexed_files,
        get_symbols_fn=get_indexed_symbols,
        get_repos_fn=lambda: get_available_repos(current_path),
    )

    use_tui = should_use_tui()
    session = None
    if use_tui:
        try:
            session = PromptSession(completer=completer, history=InMemoryHistory())
        except Exception:
            session = None
            use_tui = False

    print("\nIntelliCodeX ready. Type a question or 'help' for options, 'exit' to quit.\n")

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
                query = session.prompt(">> ", bottom_toolbar=get_toolbar).strip()
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
            print_help()
            continue

        if query.lower() in ("clear", "cls"):
            os.system("cls" if os.name == "nt" else "clear")
            render_banner()
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
                print_ingestion_summary(result, current_path, elapsed_sw)
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
                print_ingestion_summary(result, current_path, elapsed_repo)
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
            if watcher and watcher.is_alive():
                print(f"\n[*] Real-Time Filesystem Watcher: ACTIVE")
                print(f"    Target Directory: '{current_path}'")
                print("    Debounce Window : 500ms")
                print("    Auto-reindex    : Enabled (updates in-memory vector store on save)\n")
            else:
                print("\n[*] Real-Time Filesystem Watcher: INACTIVE / STOPPED\n")
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
            st = "ACTIVE (Dense Vectors + BM25 Lexical with RRF)" if engine.hybrid_search else "INACTIVE (Dense Vectors only)"
            print(f"\n[*] Hybrid Search: {st}")
            print("    Algorithm  : Reciprocal Rank Fusion (k=60)")
            print("    Lexical    : Inverted BM25Okapi (sub-token identifier splitting)")
            print("    Commands   : 'hybrid:on', 'hybrid:off', 'hybrid:toggle'\n")
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

        if query.lower() in ("history", "chat"):
            hist = engine.memory.format_history()
            if not hist:
                print("\n[*] Conversation history is empty.\n")
            else:
                print(f"\n{hist}\n")
            continue

        if query.lower() in ("clear-chat", "clear:history", "clear-memory"):
            engine.clear_memory()
            print("\n[*] Conversation history cleared.\n")
            continue


        if query.startswith("fix:") or query.startswith("fix "):
            err_input = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            
            # If err_input points to a file, read its error log content
            if os.path.isfile(err_input):
                try:
                    with open(err_input, "r", encoding="utf-8", errors="ignore") as f:
                        err_input = f.read()
                except Exception:
                    pass

            print("\n[*] Analyzing error report & localizing bug root cause...")
            t_fix = time.perf_counter()
            patch_engine = PatchEngine(result.store, embedder, llm, graph=result.graph, repo_path=current_path)

            def _on_fix_progress(turn: int, max_turns: int, msg: str):
                print(f"[*] [{turn}/{max_turns}] {msg}")

            patch_rec = patch_engine.generate_patch(
                repo_id=get_repo_id(current_path),
                error_report=err_input,
                verify_in_sandbox=True,
                max_iterations=3,
                progress_callback=_on_fix_progress,
            )
            fix_time = time.perf_counter() - t_fix

            render_patch_card(patch_rec, fix_time)

            if patch_rec["status"] != "failed" and patch_rec["git_diff"]:
                try:
                    ans = input(f"Apply this patch to '{patch_rec['target_file']}'? [y/N]: ").strip().lower()
                    if ans in ("y", "yes"):
                        ok_app, msg_app = patch_engine.apply_patch(patch_rec)
                        print(f"[*] {msg_app}\n")
                except (EOFError, KeyboardInterrupt):
                    pass
            continue



        if query.startswith("deps:") or query.startswith("deps "):
            target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            t_deps = time.perf_counter()
            affected = files_likely_affected_by(result.graph, target)
            print(f"\n--- Dependency Analysis for '{target}' ---")
            print("  Reverse Dependencies (Files affected if modified):")
            if not affected:
                print("    (none found)")
            else:
                for aff in affected:
                    print(f"    ├── {aff}")
            print(f"\n[*] [Time Consumed]: Dependencies analyzed in {format_time_consumed(time.perf_counter() - t_deps)}\n")
            continue

        if query.startswith("callers:") or query.startswith("callers "):
            symbol_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            call_g = getattr(result, "call_graph", None)
            if not call_g:
                print("[!] Call graph is unavailable.")
                continue

            t_callers = time.perf_counter()
            callers = find_callers_of_symbol(call_g, symbol_target)
            print(f"\n--- Symbol Callers for '{symbol_target}' ---")
            if not callers:
                print("  (no calling function sites found)")
            else:
                for c_id in callers:
                    print(f"  ├── {c_id}")
            print(f"\n[*] [Time Consumed]: Callers resolved in {format_time_consumed(time.perf_counter() - t_callers)}\n")
            continue

        t_ask = time.perf_counter()
        try:
            # Fix 4: Two-phase streaming — retrieve+display chunks first, then stream LLM tokens.
            # This lets the user see retrieved context in ~3s instead of waiting for the full 54s response.

            # Phase 1: Retrieve and display chunks immediately
            expanded_results = engine.retrieve_expanded(query, top_k=5)
            t_retrieval = time.perf_counter() - t_ask

            print(f"\n--- Retrieved {len(expanded_results)} chunks ({format_time_consumed(t_retrieval)}) ---")
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
                history_str = engine.memory.format_history() if len(engine.memory) > 0 else ""
                prompt_parts = []
                if history_str:
                    prompt_parts.append(history_str)
                prompt_parts.append(f"Repository context:\n\n{context}")
                prompt_parts.append(f"Question: {query}\n\nAnswer:")
                prompt = "\n\n".join(prompt_parts)

                accumulated = []
                t_gen_start = time.perf_counter()
                for token in engine.llm.stream_generate(prompt, system=engine.system_prompt):
                    print(token, end="", flush=True)
                    accumulated.append(token)
                print()

                full_answer = "".join(accumulated)
                engine.memory.add_turn(query, full_answer)
                t_llm = time.perf_counter() - t_gen_start
                total_time = time.perf_counter() - t_ask
            else:
                # Offline / tfidf fallback: use standard ask() without streaming
                response = engine.ask(query)
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
