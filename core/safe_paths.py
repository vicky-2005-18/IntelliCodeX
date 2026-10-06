"""
Shared path-safety utilities for IntelliCodeX.

All code that joins a user- or LLM-supplied relative path with a trusted root
(repo_path, sandbox_dir, …) MUST go through ``resolve_within`` before any
filesystem access so that path-traversal attacks cannot escape the root.
"""
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns that are always dangerous regardless of platform
# ---------------------------------------------------------------------------

# Windows alternate data streams: "file.txt:stream"
_ADS_RE = re.compile(r'[^/\\]:(?![/\\]|$)')

# Trailing dots or spaces (Windows treats "file. " as "file")
_TRAILING_DOT_SPACE_RE = re.compile(r'[\. ]+$')

# Drive-relative paths: "C:escape.txt"  (drive letter + colon, no following slash)
_DRIVE_RELATIVE_RE = re.compile(r'^[A-Za-z]:(?![/\\])')

# UNC paths: "\\server\share\..." or "//server/share/..."
_UNC_RE = re.compile(r'^(?:\\\\|//)')


def resolve_within(root: str, relative_path: str) -> str:
    """Resolve *relative_path* inside *root* with strict containment checks.

    Rules enforced (in order):
    1.  *relative_path* must not be empty or consist only of whitespace.
    2.  *relative_path* must not contain null bytes.
    3.  *relative_path* must not be an absolute path (POSIX or Windows).
    4.  Windows-specific rejections (run on every platform so diffs coming
        from Windows clients are safe on Linux servers too):
        a. Drive-relative paths  ``C:escape.txt``
        b. UNC paths             ``\\\\server\\share\\x``  /  ``//server/share/x``
        c. Alternate data streams ``file.txt:stream``
        d. Trailing dots or spaces in any path component
    5.  After ``os.path.realpath`` resolution (which follows symlinks), the
        resulting path must still be inside ``realpath(root)``.

    Parameters
    ----------
    root:
        The trusted directory that the resolved path must stay inside.
    relative_path:
        The user- / LLM-supplied path component to validate.

    Returns
    -------
    str
        The fully resolved absolute path, guaranteed to be inside *root*.

    Raises
    ------
    ValueError
        On any containment violation.
    """
    # --- 1. Reject empty / whitespace-only paths ---
    if not relative_path or not relative_path.strip():
        raise ValueError(
            f"Path traversal rejected: relative_path is empty or blank "
            f"(got {relative_path!r})"
        )

    # --- 2. Reject null bytes ---
    if "\x00" in relative_path:
        raise ValueError(
            f"Path traversal rejected: relative_path contains a null byte "
            f"(got {relative_path!r})"
        )

    # --- 3. Reject absolute paths (POSIX /… or Windows C:\… or \…) ---
    if os.path.isabs(relative_path):
        raise ValueError(
            f"Path traversal rejected: relative_path must be relative, "
            f"got absolute path {relative_path!r}"
        )

    # --- 4a. Reject Windows drive-relative paths (e.g. "C:escape.txt") ---
    if _DRIVE_RELATIVE_RE.match(relative_path):
        raise ValueError(
            f"Path traversal rejected: Windows drive-relative path "
            f"{relative_path!r}"
        )

    # --- 4b. Reject UNC paths (\\server\share or //server/share) ---
    if _UNC_RE.match(relative_path):
        raise ValueError(
            f"Path traversal rejected: UNC path {relative_path!r}"
        )

    # --- 4c. Reject Windows alternate data streams (file.txt:stream) ---
    if _ADS_RE.search(relative_path):
        raise ValueError(
            f"Path traversal rejected: alternate data stream in path "
            f"{relative_path!r}"
        )

    # --- 4d. Reject trailing dots or spaces in any path component ---
    # Split on both forward and back slashes for cross-platform coverage.
    components = re.split(r'[/\\]', relative_path)
    for component in components:
        if component and _TRAILING_DOT_SPACE_RE.search(component):
            raise ValueError(
                f"Path traversal rejected: path component {component!r} has "
                f"trailing dots or spaces in {relative_path!r}"
            )

    # --- 5. Resolve and verify containment ---
    real_root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(real_root, relative_path))

    # os.path.commonpath raises ValueError for mixed absolute/relative inputs,
    # but both paths are absolute here so it is safe.
    try:
        common = os.path.commonpath([real_root, candidate])
    except ValueError:
        common = ""

    if common != real_root:
        raise ValueError(
            f"Path traversal rejected: '{relative_path}' resolves to "
            f"'{candidate}' which is outside root '{real_root}'"
        )

    return candidate


# ---------------------------------------------------------------------------
# Helpers for validate_diff_paths
# ---------------------------------------------------------------------------

def _unquote_git_path(raw: str) -> str:
    """Strip git's C-style octal quoting from a path.

    git quotes paths with embedded spaces or special bytes as
    ``"path with spaces"`` using C-style escapes.  This function strips the
    surrounding quotes and decodes ``\\NNN`` octal sequences so that the plain
    path can be validated.
    """
    s = raw.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
        # Decode only the simple octal sequences git emits (\NNN)
        s = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), s)
        s = s.replace('\\"', '"').replace('\\\\', '\\')
    return s


def _strip_ab_prefix(path: str) -> str:
    """Remove the ``a/`` or ``b/`` prefix git adds to diff paths."""
    if path.startswith(('a/', 'b/')):
        return path[2:]
    return path


_NULL_PATHS = frozenset({"/dev/null", "dev/null", "nul", "NUL"})


def _check_diff_path(root: str, raw_path: str) -> Optional[str]:
    """Validate a single raw path token extracted from a diff header."""
    path = _unquote_git_path(raw_path)
    # Strip trailing tab+timestamp git sometimes appends
    path = path.split("\t")[0].rstrip()
    path = _strip_ab_prefix(path)
    if path in _NULL_PATHS:
        return None  # always safe
    try:
        resolve_within(root, path)
    except ValueError as exc:
        return str(exc)
    return None


def validate_diff_paths(root: str, git_diff: str) -> Optional[str]:
    """Scan a unified / extended diff for file paths that escape *root*.

    Header types checked:
    * ``--- a/<path>``  /  ``+++ b/<path>``  (standard unified diff)
    * ``diff --git a/<path> b/<path>``        (git extended header)
    * ``rename from <path>`` / ``rename to <path>``
    * ``copy from <path>``   / ``copy to <path>``

    Handles:
    * ``/dev/null`` — allowed (new/deleted files)
    * Quoted paths containing spaces (git C-style quoting)
    * ``a/`` / ``b/`` prefix stripping

    Parameters
    ----------
    root:
        Trusted repository root.
    git_diff:
        Raw unified diff text (may include extended git headers).

    Returns
    -------
    str or None
        Human-readable error message on the first violation, ``None`` if clean.
    """
    # --- Standard unified diff headers: "--- a/…" and "+++ b/…" ---
    unified_re = re.compile(r'^(?:---|\+\+\+)\s+(.+)$', re.MULTILINE)
    for m in unified_re.finditer(git_diff):
        err = _check_diff_path(root, m.group(1).strip())
        if err:
            return err

    # --- "diff --git a/<X> b/<Y>" — extract both X and Y ---
    git_header_re = re.compile(
        r'^diff --git\s+(\S+|\".+?\")\s+(\S+|\".+?\")$', re.MULTILINE
    )
    for m in git_header_re.finditer(git_diff):
        for token in (m.group(1), m.group(2)):
            err = _check_diff_path(root, token.strip())
            if err:
                return err

    # --- "rename from/to" and "copy from/to" ---
    from_to_re = re.compile(
        r'^(?:rename|copy)\s+(?:from|to)\s+(.+)$', re.MULTILINE
    )
    for m in from_to_re.finditer(git_diff):
        err = _check_diff_path(root, m.group(1).strip())
        if err:
            return err

    return None
