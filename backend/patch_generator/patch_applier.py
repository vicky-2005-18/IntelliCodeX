"""
Patch Application Module
Safely applies approved patches to the repository filesystem with backup support.
"""
import os
import shutil
import time
from typing import Dict, Any, Optional


def apply_patch_to_file(
    repo_path: str,
    target_file: str,
    patched_content: str,
    create_backup: bool = True,
) -> Dict[str, Any]:
    """
    Write patched content to the target file within the repository.

    Creates a .bak backup alongside the original when create_backup=True.
    """
    abs_path = os.path.join(repo_path, target_file)
    if not os.path.isfile(abs_path):
        return {
            "success": False,
            "error": f"Target file not found: {abs_path}",
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


def apply_unified_diff(
    repo_path: str,
    git_diff: str,
) -> Dict[str, Any]:
    """
    Apply a unified diff using git apply when available.

    Falls back to manual application is not supported here — caller should
    use apply_patch_to_file with the full patched content instead.
    """
    import subprocess
    import tempfile

    if not git_diff or not git_diff.strip():
        return {"success": False, "error": "Empty diff"}

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
    """
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
