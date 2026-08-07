"""
Patch Validation Module
Validates generated patches via syntax checking and optional git apply --check.
"""
import ast
import os
import subprocess
import tempfile
from typing import Dict, Any, Optional


def validate_python_syntax(code: str) -> Dict[str, Any]:
    """Parse Python source with ast; return validity and any error message."""
    try:
        ast.parse(code)
        return {"valid": True, "error": None}
    except SyntaxError as exc:
        return {"valid": False, "error": f"SyntaxError at line {exc.lineno}: {exc.msg}"}


def validate_syntax(code: str, language: str = "python") -> Dict[str, Any]:
    """Language-aware syntax validation. Currently supports Python only."""
    if language == "python":
        return validate_python_syntax(code)
    # Non-Python languages: skip syntax check (no parser available)
    return {"valid": True, "error": None, "skipped": True}


def validate_git_apply(
    git_diff: str,
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate a unified diff using `git apply --check`.

    Writes the diff to a temp file and runs git apply in dry-run mode.
    Falls back gracefully when git is unavailable.
    """
    if not git_diff or not git_diff.strip():
        return {"valid": False, "error": "Empty diff", "method": "git_apply"}

    work_dir = repo_path if repo_path and os.path.isdir(repo_path) else None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(git_diff)
            patch_path = tmp.name

        cmd = ["git", "apply", "--check", "--whitespace=nowarn", patch_path]
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=15,
        )
        os.unlink(patch_path)

        if result.returncode == 0:
            return {"valid": True, "error": None, "method": "git_apply"}
        return {
            "valid": False,
            "error": result.stderr.strip() or "git apply --check failed",
            "method": "git_apply",
        }
    except FileNotFoundError:
        return {"valid": True, "error": None, "method": "skipped", "skipped": True}
    except subprocess.TimeoutExpired:
        return {"valid": False, "error": "git apply timed out", "method": "git_apply"}
    except Exception as exc:
        return {"valid": False, "error": str(exc), "method": "git_apply"}


def compute_patch_quality_score(
    localization_confidence: float,
    syntax_valid: bool,
    git_apply_valid: bool,
    has_changes: bool,
    llm_generated: bool,
) -> float:
    """
    Combine multiple signals into a final patch confidence score (0.0–1.0).

    Weights:
    - Localization confidence: 40%
    - Syntax validity:         25%
    - Git apply validity:      20%
    - Has actual changes:      10%
    - LLM-generated (vs fallback): 5%
    """
    score = localization_confidence * 0.40
    score += (0.25 if syntax_valid else 0.0)
    score += (0.20 if git_apply_valid else 0.0)
    score += (0.10 if has_changes else 0.0)
    score += (0.05 if llm_generated else 0.0)
    return round(min(0.99, max(0.05, score)), 3)


def validate_patch(
    patched_code: str,
    git_diff: str,
    language: str = "python",
    repo_path: Optional[str] = None,
    original_code: str = "",
) -> Dict[str, Any]:
    """Run all validation checks and return a combined report."""
    syntax_result = validate_syntax(patched_code, language)
    git_result = validate_git_apply(git_diff, repo_path)
    has_changes = patched_code.strip() != original_code.strip()

    return {
        "syntax_valid": syntax_result.get("valid", False),
        "syntax_error": syntax_result.get("error"),
        "git_apply_valid": git_result.get("valid", False),
        "git_apply_error": git_result.get("error"),
        "git_apply_skipped": git_result.get("skipped", False),
        "has_changes": has_changes,
    }
