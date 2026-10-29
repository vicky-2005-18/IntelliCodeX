"""
Canonical Target Path Resolution & Ambiguity Disambiguation Engine for IntelliCodeX.

Ensures that user-, CLI-, and LLM-supplied target files:
1. Preserve canonical repository-relative paths (e.g. 'pkg/sub/file.py', not 'file.py').
2. Detect ambiguous duplicate basenames across the repository and require explicit disambiguation.
3. Reject non-existent paths or path-traversal escapes.
"""
import os
import re
from typing import List, Optional, Tuple, Set


def normalize_repo_relative_path(path_str: str) -> str:
    """Normalizes path separators to forward slashes and strips leading/trailing slashes."""
    clean = path_str.replace("\\", "/").strip()
    # Remove leading ./ if present
    if clean.startswith("./"):
        clean = clean[2:]
    return os.path.normpath(clean).replace("\\", "/")


def get_all_repo_files(repo_path: str, candidate_files: Optional[List[str]] = None) -> List[str]:
    """
    Returns list of all normalized repository-relative file paths.
    Uses candidate_files if provided, otherwise walks repo_path skipping VCS/cache dirs.
    """
    if candidate_files:
        normalized = []
        for f in candidate_files:
            if f:
                norm = normalize_repo_relative_path(f)
                if norm and norm not in normalized:
                    normalized.append(norm)
        if normalized:
            return normalized

    if not repo_path or not os.path.isdir(repo_path):
        return []

    ignore_dirs = {
        ".git", ".repos", ".venv", "venv", "env", "node_modules",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "dist", "build", "coverage", ".coverage"
    }

    repo_abs = os.path.abspath(repo_path)
    all_files: List[str] = []
    for root, dirs, files in os.walk(repo_abs):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, repo_abs).replace("\\", "/")
            all_files.append(rel_path)
    return all_files


def find_matching_repository_files(
    repo_path: str,
    target: str,
    candidate_files: Optional[List[str]] = None
) -> List[str]:
    """
    Finds all repository-relative paths matching target.
    A path matches if:
      - Exact match (target == path)
      - Suffix match (path.endswith('/' + target))
      - Basename match (if target has no directory components: os.path.basename(path) == target)
    """
    if not target or not target.strip():
        return []

    target_norm = normalize_repo_relative_path(target)
    all_files = get_all_repo_files(repo_path, candidate_files)

    # 1. Exact match check
    exact_matches = [f for f in all_files if f.lower() == target_norm.lower()]
    if exact_matches:
        # If case-exact exists, prefer it
        case_exact = [f for f in exact_matches if f == target_norm]
        return case_exact or exact_matches

    # 2. Check suffix / path match
    has_dir_sep = "/" in target_norm
    matches: List[str] = []

    for f in all_files:
        f_norm = f.replace("\\", "/")
        if f_norm.lower().endswith("/" + target_norm.lower()):
            matches.append(f)
        elif not has_dir_sep and os.path.basename(f_norm).lower() == target_norm.lower():
            matches.append(f)

    # Sort for deterministic output
    return sorted(list(set(matches)))


def resolve_canonical_target_path(
    repo_path: str,
    target: str,
    candidate_files: Optional[List[str]] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolves target to a canonical repository-relative path.

    Returns:
      (canonical_path, None) on unique success.
      (None, error_message) on ambiguity or missing file.
    """
    if not target or not target.strip():
        return None, "Target file cannot be empty."

    # If target is an absolute path within repo_path
    if os.path.isabs(target):
        try:
            rel = os.path.relpath(target, os.path.abspath(repo_path)).replace("\\", "/")
            if not rel.startswith(".."):
                abs_check = os.path.join(repo_path, rel)
                if os.path.isfile(abs_check):
                    return normalize_repo_relative_path(rel), None
        except Exception:
            pass

    target_norm = normalize_repo_relative_path(target)
    # Check if target_norm directly exists inside repo
    direct_abs = os.path.join(repo_path, target_norm)
    if os.path.isfile(direct_abs):
        return target_norm, None

    # Search for matching repository files
    matches = find_matching_repository_files(repo_path, target, candidate_files)

    if not matches:
        return None, f"Target file '{target}' does not match any file in repository '{repo_path}'."

    if len(matches) == 1:
        return matches[0], None

    # Multiple matches found -> Ambiguity must require disambiguation
    cand_list = "\n".join(f"  [{idx + 1}] {m}" for idx, m in enumerate(matches))
    error_msg = (
        f"Ambiguous target filename '{target}' matches {len(matches)} files in repository:\n"
        f"{cand_list}\n"
        f"Disambiguation required: please specify the canonical repository-relative path."
    )
    return None, error_msg


def discover_relevant_tests(repo_path: str, target_file: str) -> List[str]:
    """
    Discovers existing relevant test files for a canonically resolved target file.
    Returns a sorted list of repository-relative paths (e.g. ['pkg/test_schedule.py']).
    If no relevant tests exist in the repository, returns [].
    """
    if not repo_path or not os.path.isdir(repo_path) or not target_file:
        return []

    target_norm = normalize_repo_relative_path(target_file)
    target_base = os.path.splitext(os.path.basename(target_norm))[0]
    target_dir = os.path.dirname(target_norm)
    target_ext = os.path.splitext(target_norm)[1].lower()

    all_files = get_all_repo_files(repo_path)
    discovered: Set[str] = set()

    candidate_test_names = {
        f"test_{target_base}.py",
        f"{target_base}_test.py",
        f"{target_base}.test.ts",
        f"{target_base}.test.js",
        f"{target_base}.spec.ts",
        f"{target_base}.spec.js",
        f"test_{target_base}.js",
        f"{target_base}_test.go",
        f"test_{target_base}.cpp",
        f"test_{target_base}.c",
        f"{target_base}_test.rs",
        f"{target_base}test.java",
        f"{target_base}Test.java",
        f"{target_base}Tests.java",
        f"Test{target_base}.java",
    }
    if target_ext:
        candidate_test_names.add(f"test_{target_base}{target_ext}")
        candidate_test_names.add(f"{target_base}_test{target_ext}")

    cand_lower = {c.lower() for c in candidate_test_names}

    for f in all_files:
        f_norm = normalize_repo_relative_path(f)
        f_base = os.path.basename(f_norm)
        f_dir = os.path.dirname(f_norm)

        # 1. Exact candidate test name in the same directory, in tests/, or anywhere in repo
        if f_base in candidate_test_names or f_base.lower() in cand_lower:
            discovered.add(f_norm)
            continue

        # 2. Peer test in target directory (e.g. target_dir/test_*.py)
        if target_dir and f_dir == target_dir and (f_base.startswith("test_") or f_base.endswith("_test.py")):
            discovered.add(f_norm)
            continue

        # 3. Subdirectory test: target_dir/tests/test_*.py or target_dir/test/test_*.py
        if target_dir and f_dir in (f"{target_dir}/tests", f"{target_dir}/test") and (f_base.startswith("test_") or f_base.endswith("_test.py")):
            if target_base in f_base:
                discovered.add(f_norm)
                continue

        # 4. Cross-file integration tests: tests importing target_base
        is_test_file = (
            f_dir.startswith("tests") or f_dir.startswith("test")
            or f_base.startswith("test_") or f_base.endswith("_test.py")
            or f_base.endswith(".test.js") or f_base.endswith(".test.ts")
            or f_base.endswith("_test.go") or "test" in f_base.lower()
        )
        if is_test_file and target_base and f_norm != target_norm:
            abs_test = os.path.join(repo_path, f_norm)
            try:
                with open(abs_test, "r", encoding="utf-8", errors="ignore") as tf:
                    t_content = tf.read()
                matched = bool(re.search(
                    r'\b(?:import\s+(?:[\w.]+\.)?' + re.escape(target_base) +
                    r'|from\s+(?:[\w.]+\.)?' + re.escape(target_base) +
                    r'\s+import|require\([\'"]\.\.?/.*' + re.escape(target_base) + r'[\'"]\))\b',
                    t_content
                ))
                if not matched and target_dir:
                    # Check if test file directly imports target package/directory
                    matched = bool(re.search(r'[\'"](?:.*[\\/])?' + re.escape(target_dir) + r'[\'"]', t_content))

                if not matched and target_dir and f_dir:
                    # Check if peer source files in the same directory/package import target_dir or target_base
                    abs_test_dir = os.path.dirname(abs_test)
                    if os.path.isdir(abs_test_dir):
                        for peer in os.listdir(abs_test_dir):
                            peer_path = os.path.join(abs_test_dir, peer)
                            if os.path.isfile(peer_path) and not ("test" in peer.lower()):
                                try:
                                    with open(peer_path, "r", encoding="utf-8", errors="ignore") as pf:
                                        p_content = pf.read()
                                    if (target_base in p_content) or (target_dir and target_dir in p_content):
                                        matched = True
                                        break
                                except OSError:
                                    pass

                if matched:
                    discovered.add(f_norm)
            except OSError:
                pass

    return sorted(list(discovered))


def parse_mention(query: str) -> Tuple[str, Optional[str]]:
    """Extracts @filename mention from query and returns (cleaned_query, filename).
    Supports quoted filenames containing spaces (e.g. @"to do.java" or @'to do.java')
    as well as standard unquoted filenames (e.g. @TodoApp.java).
    """
    import re
    if not query:
        return "", None

    # 1. Match quoted @mention: @"file with spaces.py" or @'file with spaces.py'
    m_quoted = re.search(r'@["\']([^"\']+)["\']', query)
    if m_quoted:
        filename = m_quoted.group(1).replace("\\", "/")
        cleaned_query = query.replace(m_quoted.group(0), "").strip()
        cleaned_query = re.sub(r'\s+', ' ', cleaned_query)
        return cleaned_query, filename

    # 2. Match standard unquoted @filename pattern
    match = re.search(r'@([\w\-.\/\\]+)', query)
    if match:
        raw_token = match.group(1)
        filename = raw_token.rstrip(".,:;!?").replace("\\", "/")
        cleaned_query = query.replace(f"@{raw_token}", "").strip()
        cleaned_query = re.sub(r'\s+', ' ', cleaned_query)
        return cleaned_query, filename
    return query, None


def parse_file_modification_request(
    query: str,
    repo_path: Optional[str] = None,
    candidate_files: Optional[List[str]] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Detects whether a query is an explicit file-scoped modification request.

    Handles:
    - Queries starting with @<file>, e.g.:
        '@TodoApp.java create a to do list with all button show'
        '@TodoApp.java add buttons for Add, Edit, Complete, Delete, and Clear Completed'
    - Queries mentioning @<file> with modification intent, e.g.:
        'create a to do list with all button show @TodoApp.java'
        'add buttons to @TodoApp.java'
    - Queries with Target: <file> or target: <file>, e.g.:
        'add buttons Target: TodoApp.java'

    Distinguishes informational/retrieval questions (e.g. '@TodoApp.java what does this do?',
    '@TodoApp.java explain addTask') from actual modification directives.

    Returns:
        (is_modification, target_file_candidate, clean_instruction)
    """
    import re
    if not query or not query.strip():
        return False, None, ""

    q_strip = query.strip()

    # 1. Extract @file mention
    cleaned_query, mention_target = parse_mention(q_strip)
    clean_inst = cleaned_query

    # 2. Check for explicit Target: <file> or target: <file> if no @mention
    if not mention_target:
        m_target = re.search(r'(?i)\btarget\s*[:=]\s*["\']([^"\']+)["\']', clean_inst)
        if m_target:
            mention_target = m_target.group(1).strip().replace("\\", "/")
            clean_inst = (clean_inst[:m_target.start()] + ' ' + clean_inst[m_target.end():]).strip()
        else:
            m_target_unq = re.search(r'(?i)\btarget\s*[:=]\s*([\w\-.\/\\]+)', clean_inst)
            if m_target_unq:
                mention_target = m_target_unq.group(1).strip().replace("\\", "/")
                clean_inst = (clean_inst[:m_target_unq.start()] + ' ' + clean_inst[m_target_unq.end():]).strip()

    clean_inst = re.sub(r'\s+', ' ', clean_inst).strip()

    if not mention_target:
        return False, None, q_strip

    # Check file extension
    ext = os.path.splitext(mention_target)[1].lower()
    known_exts = {".java", ".py", ".js", ".ts", ".cpp", ".c", ".go", ".rs", ".jsx", ".tsx"}
    if ext and ext not in known_exts:
        return False, mention_target, clean_inst

    # 3. Informational question detection (Q&A/explain mode)
    is_info_question = bool(re.search(
        r"^(?:how\s+(?:does|do|can|is|are|to)\b|what\s+(?:is|are|does|do|did|can)\b|"
        r"where\s+(?:is|are|does|do)\b|why\s+(?:is|are|does|do|did)\b|"
        r"who\s+|which\s+|explain\b|describe\b|summarize\b|"
        r"show\s+me\s+(?:where|how|the\s+code)|tell\s+me\s+about\b)",
        clean_inst.lower()
    ))
    if is_info_question:
        return False, mention_target, clean_inst

    if clean_inst.endswith("?") and not re.search(
        r"^(?:create|add|modify|update|change|refactor|fix|patch|implement|build|make|delete|remove|replace|rewrite)\b",
        clean_inst.lower()
    ):
        return False, mention_target, clean_inst

    # 4. Modification intent detection
    actionable = re.sub(
        r"^(?:please\s+|can\s+you\s+|could\s+you\s+|i\s+want\s+to\s+|we\s+need\s+to\s+)",
        "",
        clean_inst,
        flags=re.IGNORECASE
    ).strip()

    starts_with_mod_verb = bool(re.search(
        r"^(?:create|add|modify|update|change|refactor|fix|patch|implement|build|make|"
        r"delete|remove|replace|rewrite|convert|insert|wire|integrate|support|enhance|"
        r"render|set\s*up|put|include)\b",
        actionable.lower()
    ))

    has_action_intent = bool(re.search(
        r"\b(?:create|add|modify|update|change|refactor|fix|patch|implement|build|make|"
        r"delete|remove|replace|rewrite|buttons?|to\s*do\s*list|gui|ui|interface)\b",
        actionable.lower()
    ))

    if starts_with_mod_verb or (has_action_intent and len(actionable.split()) >= 2):
        return True, mention_target, clean_inst

    return False, mention_target, clean_inst


is_file_modification_request = parse_file_modification_request


def parse_source_display_request(
    query: str,
    repo_path: Optional[str] = None,
    candidate_files: Optional[List[str]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Detects explicit source-display requests (e.g. 'show me code of @TodoApp.java',
    'view @TodoApp.java', 'code: @TodoApp.java', 'cat @TodoApp.java', 'display @TodoApp.java').

    Returns:
        (is_display_request, target_file)
    """
    if not query or not query.strip():
        return False, None

    raw_q = query.strip()
    while raw_q.startswith(">") or raw_q.startswith("$"):
        raw_q = raw_q.lstrip(">").lstrip("$").strip()

    # If it is a file modification request, it is NOT a source display request
    is_mod, _, _ = parse_file_modification_request(raw_q, repo_path=repo_path, candidate_files=candidate_files)
    if is_mod:
        return False, None

    # Check explicit command prefixes: code:, source:, cat:, view:, read:, display:
    prefix_match = re.match(r"^(?:code|source|cat|view|read|display)\s*:\s*(.+)$", raw_q, re.IGNORECASE)
    if prefix_match:
        target_candidate = prefix_match.group(1).strip()
        _, mention = parse_mention(target_candidate)
        target = mention if mention else target_candidate.strip("'\"`")
        return True, target

    # Extract @mention if present
    cleaned, mention = parse_mention(raw_q)
    if mention:
        cleaned_lower = cleaned.lower().strip()
        display_patterns = [
            r"^(?:show(?:\s+me)?(?:\s+the)?\s+(?:source|code|content|contents|file)(?:\s+(?:of|for|in))?)$",
            r"^(?:show(?:\s+me)?)$",
            r"^(?:view(?:\s+the)?(?:\s+(?:source|code|content|contents|file))?(?:\s+(?:of|for|in))?)$",
            r"^(?:cat(?:\s+the)?(?:\s+(?:source|code|content|contents|file))?(?:\s+(?:of|for|in))?)$",
            r"^(?:display(?:\s+the)?(?:\s+(?:source|code|content|contents|file))?(?:\s+(?:of|for|in))?)$",
            r"^(?:print(?:\s+the)?(?:\s+(?:source|code|content|contents|file))?(?:\s+(?:of|for|in))?)$",
            r"^(?:read(?:\s+the)?(?:\s+(?:source|code|content|contents|file))?(?:\s+(?:of|for|in))?)$",
            r"^(?:(?:source|code|contents?)(?:\s+(?:of|for|in))?)$",
            r"^(?:see(?:\s+the)?(?:\s+(?:source|code))?)$",
            r"^$"
        ]
        for pat in display_patterns:
            if re.match(pat, cleaned_lower):
                return True, mention

    # Also handle queries without @mention, e.g. "show me code of TodoApp.java" or "view TodoApp.java"
    no_at_match = re.match(
        r"^(?:show(?:\s+me)?(?:\s+the)?\s+(?:source|code|content|contents|file)?(?:\s+(?:of|for|in))?|"
        r"view|cat|display|read|print(?:\s+code(?:\s+of)?)?)\s+([a-zA-Z0-9_\-./\\]+\.[a-zA-Z0-9]+)$",
        raw_q,
        re.IGNORECASE
    )
    if no_at_match:
        target = no_at_match.group(1).strip()
        ext = os.path.splitext(target)[1].lower()
        if ext in ('.java', '.py', '.js', '.ts', '.jsx', '.tsx', '.c', '.cpp', '.h', '.hpp', '.go', '.rs', '.rb', '.php', '.html', '.css', '.json', '.xml', '.yaml', '.yml', '.md', '.txt', '.sh'):
            return True, target

    return False, None


def render_source_display(
    repo_path: str,
    target: str,
    candidate_files: Optional[List[str]] = None,
    HAS_RICH: bool = True,
    console=None
) -> bool:
    """
    Directly reads and displays source code from disk for the resolved canonical file.
    Does NOT invoke LLM, does NOT reconstruct or summarize.
    """
    canon_path, disambig_err = resolve_canonical_target_path(repo_path, target, candidate_files=candidate_files)
    if disambig_err:
        if HAS_RICH and console:
            console.print(f"\n[bold red][!] Target File Error:[/bold red]\n{disambig_err}\n")
        else:
            print(f"\n[!] Target File Error:\n{disambig_err}\n")
        return False

    abs_path = os.path.join(repo_path, canon_path) if not os.path.isabs(canon_path) else canon_path
    if not os.path.isfile(abs_path):
        err = f"Target file '{canon_path}' does not exist on disk at '{abs_path}'."
        if HAS_RICH and console:
            console.print(f"\n[bold red][!] File Error:[/bold red] {err}\n")
        else:
            print(f"\n[!] File Error: {err}\n")
        return False

    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as e:
        err = f"Failed to read file '{abs_path}': {e}"
        if HAS_RICH and console:
            console.print(f"\n[bold red][!] Read Error:[/bold red] {err}\n")
        else:
            print(f"\n[!] Read Error: {err}\n")
        return False

    file_size = os.path.getsize(abs_path)
    line_count = len(lines)

    if HAS_RICH and console:
        from rich.panel import Panel
        from rich.syntax import Syntax
        ext = os.path.splitext(canon_path)[1].lstrip(".").lower()
        lexer_map = {
            "java": "java", "py": "python", "js": "javascript", "ts": "typescript",
            "c": "c", "cpp": "cpp", "h": "c", "hpp": "cpp", "go": "go", "rs": "rust",
            "html": "html", "css": "css", "json": "json", "xml": "xml", "md": "markdown",
            "sh": "bash", "bat": "bat"
        }
        lexer = lexer_map.get(ext, ext or "text")
        full_code = "".join(lines)

        header_text = (
            f"[bold cyan]SOURCE FILE:[/bold cyan] [bold green]{canon_path}[/bold green] "
            f"({line_count} lines, {file_size:,} bytes)\n"
            f"[dim]Canonical Path : {canon_path}[/dim]\n"
            f"[dim]Resolved Disk  : {abs_path}[/dim]"
        )
        console.print()
        console.print(Panel(header_text, border_style="cyan", padding=(0, 1)))
        try:
            syntax = Syntax(full_code, lexer, line_numbers=True, theme="monokai", word_wrap=True)
            console.print(syntax)
        except Exception:
            for idx, line in enumerate(lines, 1):
                console.print(f"[dim]{idx:4d} |[/dim] {line.rstrip()}")
        console.print(Panel(
            "[dim][Direct Source Display — Read directly from active filesystem without LLM reconstruction][/dim]",
            border_style="cyan", padding=(0, 1)
        ))
        console.print()
    else:
        print("\n" + "=" * 75)
        print(f"SOURCE FILE: {canon_path} ({line_count} lines, {file_size:,} bytes)")
        print(f"Canonical Path : {canon_path}")
        print(f"Resolved Disk  : {abs_path}")
        print("=" * 75)
        for idx, line in enumerate(lines, 1):
            print(f"{idx:4d} | {line}", end="" if line.endswith("\n") else "\n")
        print("=" * 75)
        print("[Direct Source Display — Read directly from active filesystem without LLM reconstruction]")
        print("=" * 75 + "\n")

    return True



