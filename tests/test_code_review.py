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


def test_commit_approved_changes_empty_list():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.makedirs(os.path.join(tmp_dir, ".git"))
        success, msg = commit_approved_changes(tmp_dir, [], "test commit")
        assert not success
        assert "No files specified" in msg


def test_commit_approved_changes_preserves_unrelated_staged_files():
    import subprocess
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Initialize Git repo
        subprocess.run(["git", "init"], cwd=tmp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmp_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_dir, check=True, capture_output=True)

        # Baseline commit
        init_file = os.path.join(tmp_dir, "init.py")
        with open(init_file, "w") as f:
            f.write("# initial code\n")
        subprocess.run(["git", "add", "init.py"], cwd=tmp_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_dir, check=True, capture_output=True)

        # User has an unrelated file already staged
        unrelated_file = os.path.join(tmp_dir, "unrelated.txt")
        with open(unrelated_file, "w") as f:
            f.write("user work in progress\n")
        subprocess.run(["git", "add", "unrelated.txt"], cwd=tmp_dir, check=True, capture_output=True)

        # IntelliCodeX creates an approved patched file
        approved_file = os.path.join(tmp_dir, "approved_fix.py")
        with open(approved_file, "w") as f:
            f.write("def fix():\n    return True\n")

        # Run commit_approved_changes for ONLY approved_fix.py
        ok, msg = commit_approved_changes(tmp_dir, ["approved_fix.py"], "applied patch for approved_fix")
        assert ok is True
        assert "Created local Git commit for 1 file(s)" in msg

        # Verify ONLY approved_fix.py was committed
        show_res = subprocess.run(["git", "show", "--name-only", "--format="], cwd=tmp_dir, capture_output=True, text=True, check=True)
        files_in_commit = [line.strip() for line in show_res.stdout.splitlines() if line.strip()]
        assert files_in_commit == ["approved_fix.py"]
        assert "unrelated.txt" not in files_in_commit

        # Verify unrelated.txt is STILL staged in working directory
        status_res = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_dir, capture_output=True, text=True, check=True)
        assert "A  unrelated.txt" in status_res.stdout

