"""
Tests for Multi-File Context-Aware Atomic Patching and Regression Prevention.
Verifies two-phase commit, transactional rollback, multi-file diff generation,
and sandbox regression detection.
"""

import os
import sys
import tempfile
import pytest

# Ensure repository root is on sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from backend.patch_generator.patch_applier import apply_multi_file_patch
from core.patch_generator import (
    MultiFilePatchResult,
    detect_test_regressions,
    PatchEngine,
)
from core.sandbox_runner import SandboxTestResult, SandboxRunner
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder


def test_detect_test_regressions_no_regressions():
    """Verifies that when all previously passing tests continue to pass, no regression is flagged."""
    baseline = SandboxTestResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        framework="pytest",
        passed_count=3,
        failed_count=1,
        passed_tests=["test_a", "test_b", "test_c"],
        failed_tests=["test_failing_target"],
    )
    patched = SandboxTestResult(
        success=True,
        exit_code=0,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        framework="pytest",
        passed_count=4,
        failed_count=0,
        passed_tests=["test_a", "test_b", "test_c", "test_failing_target"],
        failed_tests=[],
    )

    reg_info = detect_test_regressions(baseline, patched)
    assert reg_info["has_regression"] is False
    assert len(reg_info["regressed_tests"]) == 0


def test_detect_test_regressions_flags_regressed_test():
    """Verifies that if a previously passing test now fails after the patch, a regression is detected."""
    baseline = SandboxTestResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        framework="pytest",
        passed_count=2,
        failed_count=1,
        passed_tests=["test_login", "test_logout"],
        failed_tests=["test_session_expiry"],
    )
    # Patch fixed test_session_expiry, but broke test_logout
    patched = SandboxTestResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="",
        duration_seconds=1.0,
        framework="pytest",
        passed_count=2,
        failed_count=1,
        passed_tests=["test_login", "test_session_expiry"],
        failed_tests=["test_logout"],
    )

    reg_info = detect_test_regressions(baseline, patched)
    assert reg_info["has_regression"] is True
    assert "test_logout" in reg_info["regressed_tests"]
    assert "Regression detected" in reg_info["details"]


def test_apply_multi_file_patch_success_with_backups():
    """Verifies atomic multi-file patch applies across multiple files and creates timestamped .bak backups."""
    with tempfile.TemporaryDirectory(prefix="icx_mf_test_") as tmp_dir:
        file1 = os.path.join(tmp_dir, "pkg", "auth.py")
        file2 = os.path.join(tmp_dir, "pkg", "session.py")
        os.makedirs(os.path.dirname(file1), exist_ok=True)

        with open(file1, "w", encoding="utf-8") as f:
            f.write("def login():\n    return False\n")
        with open(file2, "w", encoding="utf-8") as f:
            f.write("def check_session():\n    return 'none'\n")

        patches = {
            "pkg/auth.py": "def login():\n    return True\n",
            "pkg/session.py": "def check_session():\n    return 'active'\n",
        }

        res = apply_multi_file_patch(
            repo_path=tmp_dir,
            files_content=patches,
            create_backup=True,
        )

        assert res["success"] is True
        assert len(res["files_updated"]) == 2
        assert len(res["backups"]) == 2

        # Verify disk content updated
        with open(file1, "r", encoding="utf-8") as f:
            assert "return True" in f.read()
        with open(file2, "r", encoding="utf-8") as f:
            assert "return 'active'" in f.read()

        # Verify backup files exist with original content
        for abs_p, bak_p in res["backups"].items():
            assert os.path.isfile(bak_p)
            with open(bak_p, "r", encoding="utf-8") as bf:
                content = bf.read()
                assert ("return False" in content) or ("return 'none'" in content)


def test_apply_multi_file_patch_preflight_conflict_blocks_all():
    """Verifies that if any file in the batch has a content/hash conflict, zero files are touched."""
    with tempfile.TemporaryDirectory(prefix="icx_mf_conflict_") as tmp_dir:
        file1 = os.path.join(tmp_dir, "auth.py")
        file2 = os.path.join(tmp_dir, "token.py")

        with open(file1, "w", encoding="utf-8") as f:
            f.write("ORIGINAL_AUTH_CODE")
        with open(file2, "w", encoding="utf-8") as f:
            f.write("MODIFIED_TOKEN_CODE_ON_DISK")

        patches = {
            "auth.py": "NEW_AUTH_CODE",
            "token.py": "NEW_TOKEN_CODE",
        }

        # Expected originals: token.py expects "EXPECTED_OLD_CODE", but disk has "MODIFIED_TOKEN_CODE_ON_DISK"
        expected_originals = {
            "auth.py": "ORIGINAL_AUTH_CODE",
            "token.py": "EXPECTED_OLD_CODE",
        }

        res = apply_multi_file_patch(
            repo_path=tmp_dir,
            files_content=patches,
            expected_originals=expected_originals,
        )

        assert res["success"] is False
        assert res.get("conflict") is True
        assert "token.py" in res["conflicted_file"]

        # Crucial check: file1 was NOT touched because conflict was caught up-front
        with open(file1, "r", encoding="utf-8") as f:
            assert f.read() == "ORIGINAL_AUTH_CODE"


def test_apply_multi_file_patch_rejects_path_traversal():
    """Verifies path traversal in any filename rejects the entire multi-file batch."""
    with tempfile.TemporaryDirectory(prefix="icx_mf_traversal_") as tmp_dir:
        file1 = os.path.join(tmp_dir, "valid.py")
        with open(file1, "w", encoding="utf-8") as f:
            f.write("valid")

        patches = {
            "valid.py": "new_valid",
            "../outside.py": "malicious_payload",
        }

        res = apply_multi_file_patch(repo_path=tmp_dir, files_content=patches)
        assert res["success"] is False
        assert "Path traversal rejected" in res["error"]

        # Ensure valid.py was not modified
        with open(file1, "r", encoding="utf-8") as f:
            assert f.read() == "valid"


def test_patch_engine_generate_multi_file_patch():
    """Verifies PatchEngine.generate_multi_file_patch coordinates multi-file unified diff and syntax checks."""
    with tempfile.TemporaryDirectory(prefix="icx_mf_engine_") as tmp_dir:
        f1 = os.path.join(tmp_dir, "calc.py")
        f2 = os.path.join(tmp_dir, "util.py")

        with open(f1, "w", encoding="utf-8") as f:
            f1_orig = "def add(a, b):\n    return a - b\n"
            f.write(f1_orig)
        with open(f2, "w", encoding="utf-8") as f:
            f2_orig = "def log_op(op):\n    print('op')\n"
            f.write(f2_orig)

        store = FaissVectorStore(dim=64)
        embedder = TfidfEmbedder()
        engine = PatchEngine(
            store=store,
            embedder=embedder,
            repo_path=tmp_dir,
            sandbox_runner=SandboxRunner(is_admin=True, allow_local_sandbox=True),
        )

        modifications = {
            "calc.py": "def add(a, b):\n    return a + b\n",
            "util.py": "def log_op(op):\n    print(f'Operation: {op}')\n",
        }

        mf_res = engine.generate_multi_file_patch(
            repo_id="test_repo",
            error_report="Fix operator in add and format in log_op",
            target_files=["calc.py", "util.py"],
            file_modifications=modifications,
            verify_in_sandbox=False,  # Unit test check without live runner
        )

        assert isinstance(mf_res, MultiFilePatchResult)
        assert "calc.py" in mf_res.files
        assert "util.py" in mf_res.files
        assert "diff --git a/calc.py" in mf_res.git_diff
        assert "diff --git a/util.py" in mf_res.git_diff
        assert mf_res.validation["calc.py"]["is_valid"] is True
        assert mf_res.validation["util.py"]["is_valid"] is True

        # Now apply the multi-file patch atomically
        apply_res = engine.apply_multi_file_patch(mf_res)
        assert apply_res["success"] is True

        # Verify on disk
        with open(f1, "r", encoding="utf-8") as f:
            assert "return a + b" in f.read()
        with open(f2, "r", encoding="utf-8") as f:
            assert "Operation: {op}" in f.read()


def test_patch_engine_multi_file_sandbox_regression_detection():
    """Verifies that live sandbox execution flags regressions when a patch fixes one test but breaks another."""
    with tempfile.TemporaryDirectory(prefix="icx_mf_reg_") as tmp_dir:
        calc_py = os.path.join(tmp_dir, "calc.py")
        util_py = os.path.join(tmp_dir, "util.py")
        test_py = os.path.join(tmp_dir, "test_calc.py")

        with open(calc_py, "w", encoding="utf-8") as f:
            f.write(
                "def add(a, b):\n    return a - b  # Bug: minus instead of plus\n\n"
                "def subtract(a, b):\n    return a - b  # Correct\n"
            )
        with open(util_py, "w", encoding="utf-8") as f:
            f.write("def helper():\n    return 42\n")

        with open(test_py, "w", encoding="utf-8") as f:
            f.write(
                "from calc import add, subtract\n"
                "def test_add():\n    assert add(2, 3) == 5\n"
                "def test_subtract():\n    assert subtract(10, 4) == 6\n"
            )

        store = FaissVectorStore(dim=64)
        embedder = TfidfEmbedder()
        engine = PatchEngine(
            store=store,
            embedder=embedder,
            repo_path=tmp_dir,
            sandbox_runner=SandboxRunner(is_admin=True, allow_local_sandbox=True),
        )

        # Regressive fix: fixes add, but accidentally breaks subtract
        regressive_mods = {
            "calc.py": (
                "def add(a, b):\n    return a + b  # Fixed!\n\n"
                "def subtract(a, b):\n    return a + b  # Regression: accidentally changed to plus!\n"
            ),
            "util.py": "def helper():\n    return 42\n",
        }

        mf_res = engine.generate_multi_file_patch(
            repo_id="test_repo",
            error_report="Fix add() in calc.py",
            target_files=["calc.py", "util.py"],
            file_modifications=regressive_mods,
            verify_in_sandbox=True,
        )

        assert mf_res.status == "regressed"
        assert mf_res.regression_analysis is not None
        assert mf_res.regression_analysis["has_regression"] is True
        assert any("test_subtract" in t for t in mf_res.regression_analysis["regressed_tests"])
