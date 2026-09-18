"""
Unit and Integration Tests for Sandbox Test Execution Runner (Milestone 1)
"""
import os
import sys
import tempfile
import pytest

from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.chunker import CodeChunk
from core.patch_generator import PatchEngine


def test_detect_test_framework_pytest():
    runner = SandboxRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "tests"))
        with open(os.path.join(tmpdir, "tests", "test_sample.py"), "w") as f:
            f.write("def test_ok(): pass\n")
        assert runner.detect_test_framework(tmpdir) == "pytest"


def test_detect_test_framework_npm():
    runner = SandboxRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "package.json"), "w") as f:
            f.write('{"scripts": {"test": "jest"}}\n')
        assert runner.detect_test_framework(tmpdir) == "npm"


def test_detect_test_framework_none():
    runner = SandboxRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "app.py"), "w") as f:
            f.write("print('hello')\n")
        assert runner.detect_test_framework(tmpdir) is None


def test_sandbox_run_passing_test():
    runner = SandboxRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        # Buggy initial file
        with open(os.path.join(tmpdir, "math_ops.py"), "w") as f:
            f.write("def add(a, b):\n    return a - b  # BUG\n")

        with open(os.path.join(tmpdir, "tests", "test_math_ops.py"), "w") as f:
            f.write("from math_ops import add\ndef test_add():\n    assert add(2, 3) == 5\n")

        # Patched code fixing the bug
        fixed_code = "def add(a, b):\n    return a + b\n"
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="math_ops.py",
            patched_code=fixed_code,
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.passed_count >= 1
        assert result.failed_count == 0


def test_sandbox_run_failing_test():
    runner = SandboxRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        with open(os.path.join(tmpdir, "math_ops.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")

        with open(os.path.join(tmpdir, "tests", "test_math_ops.py"), "w") as f:
            f.write("from math_ops import add\ndef test_add():\n    assert add(2, 3) == 999\n")

        bad_patch = "def add(a, b):\n    return a + b\n"
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="math_ops.py",
            patched_code=bad_patch,
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count >= 1
        assert len(result.assertion_errors) > 0 or "AssertionError" in result.traceback_summary


def test_parse_pytest_output():
    runner = SandboxRunner()
    sample_stdout = """
============================= test session starts =============================
rootdir: /tmp/test
collected 3 items

tests/test_calc.py::test_pass PASSED                                    [ 33%]
tests/test_calc.py::test_fail FAILED                                    [ 66%]
tests/test_calc.py::test_pass2 PASSED                                   [100%]

================================== FAILURES ===================================
__________________________________ test_fail __________________________________

    def test_fail():
>       assert 2 + 2 == 5
E       AssertionError: assert 4 == 5

tests/test_calc.py:6: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_calc.py::test_fail - AssertionError: assert 4 == 5
========================= 1 failed, 2 passed in 0.15s =========================
"""
    parsed = runner._parse_pytest_output(sample_stdout, "")
    assert parsed["passed_count"] == 2
    assert parsed["failed_count"] == 1
    assert "tests/test_calc.py::test_fail" in parsed["failed_tests"]
    assert any("AssertionError" in err for err in parsed["assertion_errors"])


def test_sandbox_timeout_handling():
    runner = SandboxRunner(default_timeout=2)
    with tempfile.TemporaryDirectory() as tmpdir:
        # Run a command that exceeds timeout
        sleep_cmd = [sys.executable, "-c", "import time; time.sleep(10)"]
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="dummy.py",
            patched_code="# dummy",
            test_command=sleep_cmd,
            timeout=1,
        )
        assert result.success is False
        assert result.exit_code == -1
        assert "timed out" in (result.error_message or "").lower()


def test_patch_engine_closed_loop_repair_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "tests"), exist_ok=True)
        file_path = "auth.py"
        full_path = os.path.join(tmpdir, file_path)
        with open(full_path, "w") as f:
            f.write("def authenticate(user_dict):\n    return user_dict['token']\n")

        with open(os.path.join(tmpdir, "tests", "test_auth.py"), "w") as f:
            f.write(
                "from auth import authenticate\n"
                "def test_auth_valid():\n"
                "    assert authenticate({'token': 'secret'}) == 'secret'\n"
                "def test_auth_missing():\n"
                "    assert authenticate({}) is None\n"
            )

        embedder = TfidfEmbedder(dim=16)
        chunk = CodeChunk(
            chunk_id="auth.py::authenticate",
            file_path=file_path,
            language="python",
            kind="function",
            name="authenticate",
            start_line=1,
            end_line=2,
            code="def authenticate(user_dict):\n    return user_dict['token']\n",
        )
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        engine = PatchEngine(store, embedder, llm=None, repo_path=tmpdir)
        patch_record = engine.generate_and_verify_patch(
            repo_id="test_repo",
            error_report="KeyError: 'token' in authenticate",
            target_file=file_path,
        )

        assert patch_record["patch_id"] is not None
        assert patch_record["sandbox_validation"]["verified"] is True
        assert patch_record["sandbox_validation"]["test_status"] == "passed"
        assert patch_record["status"] == "verified"
        assert patch_record["confidence_score"] > 0.6
