"""
Rich fuzzy autocompleter and symbol completion subsystem for IntelliCodeX CLI.
"""
import os
from typing import List, Tuple, Dict, Any, Optional, Callable, Union

try:
    from prompt_toolkit.completion import Completer, Completion
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    Completer = object  # type: ignore
    Completion = None   # type: ignore
    HAS_PROMPT_TOOLKIT = False


COMMAND_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "Search & AI": {
        "color": "cyan",
        "commands": [
            ("search:<query>", "Instant lexical & semantic search without LLM wait", ["search:"]),
            ("chunks:<file>", "Inspect chunk-level index, line ranges & vector preview", ["chunks:"]),
            ("index-stats", "Display overall index statistics across the repository", ["index-stats"]),
            ("explain:<query>", "Inspect RAG pipeline, prompt & retrieval (--compare, --width)", ["explain:"]),
            ("create: <task> Target: \"<file>\"", "Explicit new-file creation workflow with sandbox validation (e.g. 'create: ... Target: \"TodoApp.java\"')", ["create:"]),
            ("run: @<file>", "Interactively run a Java, Python, or JS file in isolated Docker container (e.g. 'run: @TodoApp.java')", ["run:"]),
            ("fix: @<file>", "Diagnose bug & generate automated sandbox code patch (e.g. 'fix: @utils.py')", ["fix:"]),
            ("doc:<target>", "Generate documentation for symbol or file using call graph", ["doc:"]),
            ("security:<file>", "Run security vulnerability & secret scan on target file", ["security:"]),
            ("<question>", "Ask AI a question about the repository (supports @file scoping)", []),
            ("@<filename>", "Scope query to a specific file (one-shot, e.g. 'any issue in @auth.py?')", ["@"]),
        ],
    },
    "Code Analysis": {
        "color": "magenta",
        "commands": [
            ("graph:<entity>", "Query knowledge graph for entity attributes, callers & lines", ["graph:"]),
            ("deps:<file>", "View direct & reverse dependencies for a file", ["deps:"]),
            ("callers:<func>", "Find all call sites calling <func> across repo AST", ["callers:"]),
            ("top / centrality", "Show PageRank centrality rankings for files & symbols", ["top", "centrality"]),
            ("arch / cycles", "Analyze circular dependencies & high-coupling bottleneck modules", ["arch", "cycles"]),
            ("info:<file>", "Show file stats: size, chunk count, lines, centrality score", ["info:"]),
        ],
    },
    "Repository": {
        "color": "green",
        "commands": [
            ("repos / list-repos", "List all known repositories and switch by number", ["repos", "list-repos"]),
            ("repo <path_or_url>", "Switch or clone active repository (e.g. 'repo https://github.com/user/repo')", ["repo "]),
            ("repo <number>", "Switch to a previously added repo by its list number (e.g. 'repo 2')", []),
            ("repo remove <name|num>", "Unregister repository from list (preserves source files & cache)", ["repo remove "]),
            ("clone <url>", "Clone repository (shallow default, use --full-history for all commits)", ["clone "]),
            ("files / ls", "List all indexed repository source files", ["files", "ls"]),
        ],
    },
    "Review & Safe Repair": {
        "color": "yellow",
        "commands": [
            ("review", "List pending patch proposals awaiting developer review", ["review"]),
            ("review <id>", "Inspect detailed patch proposal card and diff", ["review "]),
            ("approve <id>", "Approve and apply a pending patch proposal", ["approve "]),
            ("reject <id>", "Reject and discard a pending patch proposal", ["reject "]),
        ],
    },
    "Settings & Configuration": {
        "color": "yellow",
        "commands": [
            ("backend <ollama|tfidf>", "Switch active backend engine dynamically", ["backend "]),
            ("persona <name>", "Switch AI persona (general, security, reviewer, refactor, fixer)", ["persona "]),
            ("model <model_name>", "Switch active Ollama LLM model (e.g. 'model qwen2.5-coder:7b')", ["model "]),
            ("file:<filename>", "Set persistent file filter for all queries (e.g. 'file:auth.py')", ["file:"]),
            ("file:off", "Clear persistent file filter", ["file:off"]),
            ("hybrid / hybrid:status", "Check hybrid search status (BM25 + Dense RRF)", ["hybrid", "hybrid:status"]),
            ("hybrid:on / hybrid:off", "Enable or disable BM25 lexical hybrid ranking", ["hybrid:on", "hybrid:off"]),
            ("hybrid:toggle", "Toggle hybrid BM25 search on/off", ["hybrid:toggle"]),
        ],
    },
    "Git & Watcher": {
        "color": "blue",
        "commands": [
            ("hooks", "Install Git background re-indexing hooks for current repository", ["hooks"]),
            ("hooks:status", "Check status of installed Git hooks", ["hooks:status"]),
            ("hooks:remove", "Uninstall Git background re-indexing hooks", ["hooks:remove"]),
            ("watch", "Check real-time filesystem watcher status", ["watch", "watch:status"]),
            ("watch:start / watch:stop", "Start or stop real-time file watcher", ["watch:start", "watch:stop"]),
        ],
    },
    "Architecture & Memory": {
        "color": "magenta",
        "commands": [
            ("why:<query>", "Query historical design decisions and commit rationale (e.g. 'why:FAISS')", ["why:"]),
            ("adrs", "List all Architectural Decision Records (ADRs) found in repo", ["adrs"]),
            ("decision: <title> | <desc>", "Record developer architectural decision into memory", ["decision:"]),
            ("learned", "Show self-improving agent memory bank and repair statistics", ["learned"]),
        ],
    },
    "Session": {
        "color": "white",
        "commands": [
            ("wave / hi", "Greet mascot (primary command; IDEs may intercept Ctrl+G/F1)", ["wave", "hi", "hello", "hey", "greet", "mascot"]),
            ("status", "Show full system status, active backend, model & watcher", ["status"]),
            ("history", "View multi-turn conversation history", ["history", "chat"]),
            ("clear-chat / reset", "Clear conversation history", ["clear-chat", "reset"]),
            ("export:<file>", "Save last AI answer to a Markdown file", ["export:"]),
            ("version", "Show IntelliCodeX CLI version", ["version"]),
            ("clear / cls", "Clear terminal screen", ["clear", "cls"]),
            ("help / ?", "Show this command reference", ["help", "?"]),
            ("exit / quit", "Exit IntelliCodeX CLI", ["exit", "quit"]),
        ],
    },
}


def build_completer_commands(categories: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Tuple[str, str]]:
    """Derives autocomplete commands and descriptions directly from shared COMMAND_CATEGORIES."""
    cats = categories if categories is not None else COMMAND_CATEGORIES
    cmds: List[Tuple[str, str]] = []
    seen: set = set()
    for cat_data in cats.values():
        for item in cat_data.get("commands", []):
            desc = item[1]
            tokens = item[2] if len(item) > 2 else []
            for tok in tokens:
                if tok and tok not in seen:
                    cmds.append((tok, desc))
                    seen.add(tok)
    return cmds


def is_subsequence(query: str, target: str) -> bool:
    """Return True if all characters of query appear in target in order (case-insensitive)."""
    if not query:
        return True
    q = query.lower()
    t = target.lower()
    it = iter(t)
    return all(char in it for char in q)


class IntelliCodeXCompleter(Completer if HAS_PROMPT_TOOLKIT else object):  # type: ignore
    """Context-aware fuzzy autocompleter for commands, files, symbols, and settings."""

    COMMANDS: List[Tuple[str, str]] = build_completer_commands()

    PERSONAS: List[str] = ["general", "security", "reviewer", "refactor", "fixer"]
    BACKENDS: List[str] = ["ollama", "tfidf"]
    COMMON_ERRORS: List[str] = [
        "KeyError", "IndexError", "TypeError", "ValueError",
        "ZeroDivisionError", "AttributeError", "FileNotFoundError"
    ]

    def __init__(
        self,
        get_files_fn: Optional[Callable[[], List[str]]] = None,
        get_symbols_fn: Optional[Callable[[], Union[List[str], List[Dict[str, Any]]]]] = None,
        get_repos_fn: Optional[Callable[[], List[Tuple[str, str]]]] = None,
    ):
        self.get_files_fn = get_files_fn
        self.get_symbols_fn = get_symbols_fn
        self.get_repos_fn = get_repos_fn

    @staticmethod
    def build_completer_commands(categories: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Tuple[str, str]]:
        return build_completer_commands(categories)

    def get_completions(self, document, complete_event=None):
        if not HAS_PROMPT_TOOLKIT or Completion is None:
            return
        if document is None:
            return

        text = getattr(document, "text_before_cursor", None)
        if not text:
            return

        stripped = text.lstrip(">").lstrip("$").lstrip()
        if not stripped:
            return

        # 0. Parameter completion: run:<file> or run <file>
        for prefix in ("run: ", "run ", "run:"):
            if stripped.startswith(prefix):
                raw_arg = stripped[len(prefix):]
                clean_arg = raw_arg.strip().lstrip("@").strip()
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in (".java", ".py", ".js", ".mjs", ".cjs"):
                            basename = os.path.basename(f)
                            if (
                                not clean_arg
                                or clean_arg.lower() in f.lower()
                                or clean_arg.lower() in basename.lower()
                                or is_subsequence(clean_arg, basename)
                            ):
                                yield Completion(f"@{basename}", start_position=-len(raw_arg), display=f"@{basename}", display_meta="Run Target")
                return

        # 0b. @mention completion: @filename
        if "@" in stripped:
            at_pos = stripped.rfind("@")
            arg = stripped[at_pos + 1:]
            if self.get_files_fn:
                files = self.get_files_fn() or []
                for f in files:
                    basename = os.path.basename(f)
                    if (
                        not arg
                        or arg.lower() in f.lower()
                        or arg.lower() in basename.lower()
                        or is_subsequence(arg, basename)
                    ):
                        if "/" in arg or "\\" in arg:
                            display_text = f.replace("\\", "/")
                            yield Completion(display_text, start_position=-len(arg), display=display_text, display_meta="File")
                        else:
                            yield Completion(basename, start_position=-len(arg), display=basename, display_meta="File")
            return

        # 0c. Parameter completion: chunks:<file> or chunks <file>
        for prefix in ("chunks: ", "chunks ", "chunks:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        if not arg or arg.lower() in f.lower() or is_subsequence(arg, os.path.basename(f)):
                            yield Completion(f, start_position=-len(arg), display=f, display_meta="File")
                return

        # 1. Parameter completion: deps:<file> or deps <file>
        for prefix in ("deps: ", "deps ", "deps:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        if not arg or arg.lower() in f.lower() or is_subsequence(arg, os.path.basename(f)):
                            yield Completion(f, start_position=-len(arg), display=f, display_meta="File")
                return

        # 2. Parameter completion: fix:<file_or_err> or fix <file_or_err>
        for prefix in ("fix: ", "fix ", "fix:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                for err in self.COMMON_ERRORS:
                    if not arg or arg.lower() in err.lower() or is_subsequence(arg, err):
                        yield Completion(err, start_position=-len(arg), display=err, display_meta="Error")
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        if not arg or arg.lower() in f.lower() or is_subsequence(arg, os.path.basename(f)):
                            yield Completion(f, start_position=-len(arg), display=f, display_meta="File")
                return

        # 3. Parameter completion: callers:<symbol> or callers <symbol>
        for prefix in ("callers: ", "callers ", "callers:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_symbols_fn:
                    symbols = self.get_symbols_fn() or []
                    for sym in symbols:
                        sym_name = sym if isinstance(sym, str) else sym.get("name", str(sym))
                        sym_meta = "Symbol" if isinstance(sym, str) else sym.get("signature", "Symbol")
                        if not arg or arg.lower() in sym_name.lower() or is_subsequence(arg, sym_name):
                            yield Completion(sym_name, start_position=-len(arg), display=sym_name, display_meta=sym_meta)
                return

        # 3b. Parameter completion: doc:<target> or doc <target>
        for prefix in ("doc: ", "doc ", "doc:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                if self.get_symbols_fn:
                    symbols = self.get_symbols_fn() or []
                    for sym in symbols:
                        sym_name = sym if isinstance(sym, str) else sym.get("name", str(sym))
                        sym_meta = "Symbol" if isinstance(sym, str) else sym.get("signature", "Symbol")
                        if not arg or arg.lower() in sym_name.lower() or is_subsequence(arg, sym_name):
                            yield Completion(sym_name, start_position=-len(arg), display=sym_name, display_meta=sym_meta)
                if self.get_files_fn:
                    files = self.get_files_fn() or []
                    for f in files:
                        basename = os.path.basename(f)
                        if not arg or arg.lower() in f.lower() or arg.lower() in basename.lower():
                            yield Completion(basename, start_position=-len(arg), display=basename, display_meta="File")
                return

        # 3c. Symbol #mention completion: #symbol
        if "#" in stripped:
            hash_pos = stripped.rfind("#")
            arg = stripped[hash_pos + 1:]
            if self.get_symbols_fn:
                symbols = self.get_symbols_fn() or []
                for sym in symbols:
                    sym_name = sym if isinstance(sym, str) else sym.get("name", str(sym))
                    sym_meta = "Symbol" if isinstance(sym, str) else sym.get("signature", "Symbol")
                    if not arg or arg.lower() in sym_name.lower() or is_subsequence(arg, sym_name):
                        yield Completion(sym_name, start_position=-len(arg), display=sym_name, display_meta=sym_meta)
            return

        # 4. Parameter completion: persona <name>
        for prefix in ("persona ", "persona:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
                for p in self.PERSONAS:
                    if p.lower().startswith(arg.lower()):
                        yield Completion(p, start_position=-len(arg), display=p, display_meta="Persona")
                return

        # 5. Parameter completion: backend <name>
        for prefix in ("backend ", "backend:"):
            if stripped.startswith(prefix):
                arg = stripped[len(prefix):]
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

        # 8. Top-level commands with Fuzzy Matching (prefix > substring > subsequence)
        q = stripped.lower()
        prefix_matches: List[Tuple[str, str]] = []
        substring_matches: List[Tuple[str, str]] = []
        fuzzy_matches: List[Tuple[str, str]] = []
        seen: set = set()

        for cmd, desc in self.COMMANDS:
            cmd_lower = cmd.lower()
            if cmd in seen:
                continue
            if cmd_lower.startswith(q):
                prefix_matches.append((cmd, desc))
                seen.add(cmd)
            elif q in cmd_lower:
                substring_matches.append((cmd, desc))
                seen.add(cmd)
            elif is_subsequence(q, cmd_lower):
                fuzzy_matches.append((cmd, desc))
                seen.add(cmd)

        for cmd, desc in prefix_matches + substring_matches + fuzzy_matches:
            yield Completion(cmd, start_position=-len(stripped), display=cmd, display_meta=desc)
