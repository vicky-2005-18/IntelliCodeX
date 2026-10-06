import os
import tempfile
import pytest
from core.code_review import (
    align_side_by_side_diff,
    render_side_by_side_diff,
    render_unified_diff_view,
    compute_file_sha256,
    commit_approved_changes,
)


def test_align_side_by_side_diff_changes():
    orig = "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return b - a"
    patched = "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b"

    pairs = align_side_by_side_diff(orig, patched)
    assert len(pairs) >= 5

    # Check that modification line is captured
    tags = [p[4] for p in pairs]
    assert "replace" in tags or ("delete" in tags and "insert" in tags)
    assert "equal" in tags


def test_render_side_by_side_diff_table():
    orig = "x = 10\ny = 20\n"
    patched = "x = 15\ny = 20\nz = 30\n"
    table = render_side_by_side_diff(orig, patched, "test.py", table_width=130)
    assert table is not None
    assert "test.py" in str(table.title)


def test_render_unified_diff_view_panel():
    orig = "def divide(a, b):\n    return a // b\n"
    patched = "def divide(a, b):\n    return a / b\n"
    panel = render_unified_diff_view(orig, patched, "calc.py")
    assert panel is not None
    assert "calc.py" in str(panel.title)


def test_compute_file_sha256():
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".py") as tmp:
        tmp.write("print('hello')\n")
        tmp_path = tmp.name

    try:
        h1 = compute_file_sha256(tmp_path)
        assert h1 is not None

        # Modify file -> hash must change (staleness detection)
        with open(tmp_path, "w") as f:
            f.write("print('modified externally')\n")

        h2 = compute_file_sha256(tmp_path)
        assert h2 is not None
        assert h1 != h2
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_commit_approved_changes_not_git():
    with tempfile.TemporaryDirectory() as tmp_dir:
        success, msg = commit_approved_changes(tmp_dir, ["foo.py"], "test commit")
        assert not success
        assert "Not a Git repository" in msg
