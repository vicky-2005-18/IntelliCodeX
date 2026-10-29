"""
Patch Application Module
Safely applies approved patches to the repository filesystem with backup support.
"""
import os
import shutil
import time
import logging
from typing import Dict, Any, Optional, List

from core.safe_paths import resolve_within, validate_diff_paths

logger = logging.getLogger(__name__)


def apply_patch_to_file(
    repo_path: str,
    target_file: str,
    patched_content: str,
    create_backup: bool = True,
    expected_original: Optional[str] = None,
    expected_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write patched content to the target file within the repository.

    Creates a .bak backup alongside the original when create_backup=True.
    Rejects any target_file that escapes repo_path via path traversal.
    Verifies that the target file has not been concurrently modified since
    patch proposal generation if expected_original or expected_hash is provided.
    """
    import hashlib

    # -- Path-safety check: must resolve inside repo_path --
    try:
        abs_path = resolve_within(repo_path, target_file)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    if not os.path.isfile(abs_path):
        return {
            "success": False,
            "error": f"Target file not found: {abs_path}",
        }

    # -- Concurrent modification conflict detection (REQ-CORE-17) --
    if expected_hash is not None or expected_original is not None:
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                current_disk_content = f.read()
        except Exception as exc:
            return {"success": False, "error": f"Failed to read target file: {exc}"}

        if expected_hash is not None:
            current_hash = hashlib.sha256(current_disk_content.encode("utf-8")).hexdigest()
            if current_hash != expected_hash:
                return {
                    "success": False,
                    "error": "Conflict detected: Target file content has changed on disk since patch proposal was generated.",
                    "conflict": True,
                }
        elif expected_original is not None:
            if current_disk_content != expected_original:
                return {
                    "success": False,
                    "error": "Conflict detected: Target file content has changed on disk since patch proposal was generated.",
                    "conflict": True,
                }

    backup_path = None
    try:
        if create_backup:
            backup_path = f"{abs_path}.bak.{int(time.time())}"
            shutil.copy2(abs_path, backup_path)

        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(patched_content)

        return {
            "success": True,
            "file_path": abs_path,
            "backup_path": backup_path,
        }
    except OSError as exc:
        return {"success": False, "error": str(exc)}


def apply_multi_file_patch(
    repo_path: str,
    files_content: Dict[str, str],
    expected_hashes: Optional[Dict[str, str]] = None,
    expected_originals: Optional[Dict[str, str]] = None,
    create_backup: bool = True,
) -> Dict[str, Any]:
    """
    Atomically writes patched content to multiple files within repo_path.

    Guarantees strict two-phase commit:
    1. Pre-flight phase:
       - Every target path is validated against directory traversal with resolve_within.
       - Every existing file is checked against expected_hashes and expected_originals.
       - If ANY file fails path safety or has a modification conflict, the entire batch
         is rejected with conflict=True without modifying any file on disk.
    2. Execution phase:
       - If create_backup=True, timestamped backups (.bak.<ts>) are created for each file.
       - Content is written to all target files.
       - If ANY write operation raises an error, an automatic rollback restores all
         files that were modified from their backups, ensuring zero partial-state contamination.
    """
    import hashlib

    if not files_content:
        return {"success": False, "error": "No files provided in multi-file patch batch"}

    # Phase 1: Pre-flight validation (All or nothing)
    resolved_paths: Dict[str, str] = {}
    for rel_path in files_content:
        try:
            abs_p = resolve_within(repo_path, rel_path)
            resolved_paths[rel_path] = abs_p
        except ValueError as exc:
            return {"success": False, "error": f"Path traversal rejected for '{rel_path}': {exc}"}

    # Verify conflict hashes across all files before modifying any file
    expected_hashes = expected_hashes or {}
    expected_originals = expected_originals or {}

    for rel_path, abs_p in resolved_paths.items():
        if os.path.isfile(abs_p):
            exp_h = expected_hashes.get(rel_path)
            exp_orig = expected_originals.get(rel_path)
            if exp_h is not None or exp_orig is not None:
                try:
                    with open(abs_p, "r", encoding="utf-8") as f:
                        current_content = f.read()
                except Exception as exc:
                    return {"success": False, "error": f"Failed reading '{rel_path}' for conflict check: {exc}"}

                if exp_h is not None:
                    curr_h = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
                    if curr_h != exp_h:
                        return {
                            "success": False,
                            "error": f"Conflict detected on '{rel_path}': content on disk modified since patch generation.",
                            "conflict": True,
                            "conflicted_file": rel_path,
                        }
                elif exp_orig is not None:
                    if current_content != exp_orig:
                        return {
                            "success": False,
                            "error": f"Conflict detected on '{rel_path}': content on disk modified since patch generation.",
                            "conflict": True,
                            "conflicted_file": rel_path,
                        }

    # Phase 2: Transactional Execution with Rollback
    ts = int(time.time())
    backups_created: Dict[str, str] = {}
    files_written: List[str] = []

    try:
        # Step A: Create backups
        if create_backup:
            for rel_path, abs_p in resolved_paths.items():
                if os.path.isfile(abs_p):
                    bak_path = f"{abs_p}.bak.{ts}"
                    shutil.copy2(abs_p, bak_path)
                    backups_created[abs_p] = bak_path

        # Step B: Write new content
        for rel_path, new_content in files_content.items():
            abs_p = resolved_paths[rel_path]
            os.makedirs(os.path.dirname(abs_p), exist_ok=True)
            with open(abs_p, "w", encoding="utf-8") as f:
                f.write(new_content)
            files_written.append(abs_p)

        return {
            "success": True,
            "files_updated": list(resolved_paths.keys()),
            "files_written": files_written,
            "backups": backups_created,
            "timestamp": ts,
        }

    except Exception as exc:
        # Rollback all modified files to restore atomic state
        logger.error(f"Error during multi-file patch application: {exc}. Rolling back changes.")
        rollback_errors = []
        for abs_p, bak_p in backups_created.items():
            try:
                shutil.copy2(bak_p, abs_p)
            except Exception as r_err:
                rollback_errors.append(f"Failed to restore '{abs_p}' from '{bak_p}': {r_err}")

        # Delete any newly created files that didn't have a backup
        for abs_p in files_written:
            if abs_p not in backups_created and os.path.isfile(abs_p):
                try:
                    os.unlink(abs_p)
                except Exception:
                    pass

        return {
            "success": False,
            "error": f"Write failed: {exc}. Rollback executed.",
            "rolled_back": True,
            "rollback_errors": rollback_errors,
        }



def apply_unified_diff(
    repo_path: str,
    git_diff: str,
) -> Dict[str, Any]:
    """
    Apply a unified diff using git apply when available.

    Validates all file headers in the diff to ensure none escape repo_path
    before handing the diff to git apply.
    Falls back to manual application is not supported here — caller should
    use apply_patch_to_file with the full patched content instead.
    """
    import subprocess
    import tempfile

    if not git_diff or not git_diff.strip():
        return {"success": False, "error": "Empty diff"}

    # -- Path-safety check: reject diffs whose headers escape the repo --
    path_error = validate_diff_paths(repo_path, git_diff)
    if path_error:
        return {"success": False, "error": path_error}

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(git_diff)
            patch_path = tmp.name

        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        os.unlink(patch_path)

        if result.returncode == 0:
            return {"success": True, "method": "git_apply"}
        return {
            "success": False,
            "error": result.stderr.strip() or "git apply failed",
            "method": "git_apply",
        }
    except FileNotFoundError:
        return {"success": False, "error": "git not available", "method": "git_apply"}
    except Exception as exc:
        return {"success": False, "error": str(exc), "method": "git_apply"}


def merge_snippet_into_file(
    full_file_content: str,
    original_snippet: str,
    patched_snippet: str,
    start_line: int = 1,
) -> Optional[str]:
    """
    Replace a snippet region inside a full file with the patched version.

    First attempts exact string replacement; falls back to line-range replacement
    when the snippet spans known start/end lines.
    Guards against duplicating symbols that exist outside the targeted snippet.
    """
    if not full_file_content or not original_snippet:
        return None

    # Guard: if patched_snippet defines top-level Python symbols that exist outside original_snippet
    try:
        import ast
        cand_tree = ast.parse(patched_snippet)
        full_tree = ast.parse(full_file_content)
        snip_tree = ast.parse(original_snippet)

        cand_symbols = {n.name for n in cand_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        snip_symbols = {n.name for n in snip_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        full_symbols = {n.name for n in full_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

        external_symbols = full_symbols - snip_symbols
        if cand_symbols & external_symbols:
            # patched_snippet defines symbols existing outside original_snippet;
            # blind string replacement would create duplicates!
            return None
    except Exception:
        pass

    if original_snippet in full_file_content:
        return full_file_content.replace(original_snippet, patched_snippet, 1)

    lines = full_file_content.splitlines(keepends=True)
    snippet_lines = original_snippet.splitlines()
    snippet_len = len(snippet_lines)

    # Line-range fallback using start_line (1-indexed)
    idx = max(0, start_line - 1)
    if idx + snippet_len <= len(lines):
        candidate = "".join(lines[idx : idx + snippet_len])
        if candidate.strip() == original_snippet.strip():
            new_lines = lines[:idx] + [patched_snippet + "\n"] + lines[idx + snippet_len:]
            return "".join(new_lines)

    return None
