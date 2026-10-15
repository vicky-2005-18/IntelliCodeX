"""
Canonical Target Path Resolution & Ambiguity Disambiguation Engine for IntelliCodeX.

Ensures that user-, CLI-, and LLM-supplied target files:
1. Preserve canonical repository-relative paths (e.g. 'pkg/sub/file.py', not 'file.py').
2. Detect ambiguous duplicate basenames across the repository and require explicit disambiguation.
3. Reject non-existent paths or path-traversal escapes.
"""
import os
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
    }
    if target_ext:
        candidate_test_names.add(f"test_{target_base}{target_ext}")
        candidate_test_names.add(f"{target_base}_test{target_ext}")

    for f in all_files:
        f_norm = normalize_repo_relative_path(f)
        f_base = os.path.basename(f_norm)
        f_dir = os.path.dirname(f_norm)

        # 1. Exact candidate test name in the same directory, in tests/, or anywhere in repo
        if f_base in candidate_test_names:
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

    return sorted(list(discovered))

