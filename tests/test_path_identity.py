"""
Focused regression test for path identity policy in core/pipeline.py.
Ensures distinct case-sensitive paths (e.g., Utils.py and utils.py) are preserved
on Linux/POSIX environments while retaining case-insensitive matching on Windows.
"""
import pytest
from core.pipeline import normalize_path_identity


def test_normalize_path_identity_windows_behavior():
    # On Windows (case-insensitive), backslashes are converted to forward slashes
    # and paths are lowercased so case differences match.
    p1 = normalize_path_identity("src\\Utils.py", is_case_insensitive=True)
    p2 = normalize_path_identity("src/utils.py", is_case_insensitive=True)
    assert p1 == p2 == "src/utils.py"


def test_normalize_path_identity_linux_behavior():
    # On Linux/POSIX (case-sensitive), forward slashes are standardized,
    # but exact casing is preserved so Utils.py and utils.py remain distinct.
    p1 = normalize_path_identity("src/Utils.py", is_case_insensitive=False)
    p2 = normalize_path_identity("src/utils.py", is_case_insensitive=False)
    assert p1 == "src/Utils.py"
    assert p2 == "src/utils.py"
    assert p1 != p2


def test_normalize_path_identity_nested_and_dots():
    p_win = normalize_path_identity("a\\b\\C\\SubDir\\File.TS", is_case_insensitive=True)
    p_nix = normalize_path_identity("a/b/C/SubDir/File.TS", is_case_insensitive=False)
    assert p_win == "a/b/c/subdir/file.ts"
    assert p_nix == "a/b/C/SubDir/File.TS"
