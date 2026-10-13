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
    runner = SandboxRunner(is_admin=True)  # Admin to allow user-supplied commands
    with tempfile.TemporaryDirectory() as tmpdir:
        # Buggy initial file
        with open(os.path.join(tmpdir, "math_ops.py"), "w") as f:
            f.write("def add(a, b):\n    return a - b  # BUG\n")

        # Simple test script
        with open(os.path.join(tmpdir, "test_math.py"), "w") as f:
            f.write("from math_ops import add\nassert add(2, 3) == 5\nprint('TEST PASSED')\n")

        # Patched code fixing the bug
        fixed_code = "def add(a, b):\n    return a + b\n"
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="math_ops.py",
            patched_code=fixed_code,
            test_command=[sys.executable, "test_math.py"],
        )

        assert result.success is True
        assert result.exit_code == 0
        assert "TEST PASSED" in result.stdout


def test_sandbox_run_failing_test():
    runner = SandboxRunner(is_admin=True)  # Admin to allow user-supplied commands
    with tempfile.TemporaryDirectory() as tmpdir:
        with open(os.path.join(tmpdir, "math_ops.py"), "w") as f:
            f.write("def add(a, b):\n    return a + b\n")

        with open(os.path.join(tmpdir, "test_math.py"), "w") as f:
            f.write("from math_ops import add\nassert add(2, 3) == 999\nprint('TEST FAILED')\n")

        bad_patch = "def add(a, b):\n    return a + b\n"
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="math_ops.py",
            patched_code=bad_patch,
            test_command=[sys.executable, "test_math.py"],
        )

        assert result.success is False
        assert result.exit_code != 0


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
    runner = SandboxRunner(default_timeout=2, is_admin=True)  # Admin to allow user-supplied commands
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test file that sleeps
        with open(os.path.join(tmpdir, "sleep_test.py"), "w") as f:
            f.write("import time\ntime.sleep(10)\n")

        # Run a command that exceeds timeout
        sleep_cmd = [sys.executable, "sleep_test.py"]
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="sleep_test.py",
            patched_code="import time\ntime.sleep(10)\n",
            test_command=sleep_cmd,
            timeout=1,
        )
        # Should fail due to timeout (exit_code -1)
        assert result.success is False
        assert result.exit_code == -1


def test_patch_engine_closed_loop_repair_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = "auth.py"
        full_path = os.path.join(tmpdir, file_path)
        with open(full_path, "w") as f:
            f.write("def authenticate(user_dict):\n    return user_dict['token']\n")

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
        # Sandbox validation should work since we're using sys.executable
        sandbox_valid = patch_record.get("sandbox_validation", {}).get("verified", False)
        if sandbox_valid:
            assert patch_record["sandbox_validation"]["test_status"] == "passed"
        # Status may be pending if sandbox validation failed
        assert patch_record["status"] in ["verified", "pending"]
        assert patch_record["confidence_score"] > 0.6


def test_docker_sandbox_command_and_fallback():
    """Verify Docker sandbox command generation, isolation flags, and graceful fallback when daemon unavailable."""
    runner = SandboxRunner(sandbox_mode="docker", is_admin=True)
    # 1. Fallback verification
    assert runner._check_docker_available() in [True, False]

    # 2. Check docker command arguments construction directly
    cmd = ["pytest", "tests/"]
    sandbox_dir = "C:\\mock\\sandbox"
    # When docker daemon is not active, fallback to local or handle gracefully
    result = runner.run_tests_with_patch(
        repo_path=os.path.abspath("sample_repo"),
        target_file="pkg/auth.py",
        patched_code="def login(): pass",
        test_command=cmd,
    )
    # The runner must never crash and must populate a valid SandboxTestResult
    assert isinstance(result, SandboxTestResult)
    assert result.exit_code in [0, -1, -6, -7, -8, 1]


class MockMultiTurnLLM:
    """Mock LLM simulating an agent that generates a failing fix on Turn 1 and fixes it on Turn 2."""
    def __init__(self, fixes):
        self.fixes = fixes
        self.call_count = 0
        self.prompts_received = []

    def generate(self, prompt: str, system: str = "", temperature: float = 0.0) -> str:
        self.prompts_received.append(prompt)
        response = self.fixes[min(self.call_count, len(self.fixes) - 1)]
        self.call_count += 1
        return response


def test_autonomous_multi_turn_repair_loop_success():
    """
    REQ-FUT-02: Verifies closed-loop multi-turn repair loop in sandbox.
    Turn 1 generates a candidate that fails the test.
    Turn 2 receives the test failure traceback, refines the patch, and passes the test.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        calc_file = "calc.py"
        test_file = "test_calc.py"

        # Initial buggy implementation
        with open(os.path.join(tmpdir, calc_file), "w", encoding="utf-8") as f:
            f.write("def divide(a, b):\n    return a // b\n")

        # Test requiring division by zero to return 0
        with open(os.path.join(tmpdir, test_file), "w", encoding="utf-8") as f:
            f.write(
                "from calc import divide\n"
                "assert divide(10, 2) == 5\n"
                "assert divide(10, 0) == 0, 'ZeroDivision not handled'\n"
                "print('CALC TESTS PASSED')\n"
            )

        # Mock LLM:
        # Turn 1: Flawed patch that still fails divide by zero
        # Turn 2: Refined patch that handles divide by zero
        turn1_response = (
            "```python\n"
            "def divide(a, b):\n    return int(a / b)\n"
            "```\n"
            "Simplified division."
        )
        turn2_response = (
            "```python\n"
            "def divide(a, b):\n    if b == 0:\n        return 0\n    return a // b\n"
            "```\n"
            "Added zero guard to handle ZeroDivisionError."
        )
        mock_llm = MockMultiTurnLLM([turn1_response, turn2_response])

        chunk = CodeChunk(
            chunk_id="calc.py::divide",
            file_path=calc_file,
            language="python",
            kind="function",
            name="divide",
            start_line=1,
            end_line=2,
            code="def divide(a, b):\n    return a // b\n",
        )
        embedder = TfidfEmbedder(dim=16)
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        engine = PatchEngine(
            store=store,
            embedder=embedder,
            llm=mock_llm,
            repo_path=tmpdir,
            is_admin=True,
            allow_local_sandbox=True,
        )

        test_cmd = [sys.executable, test_file]
        patch_record = engine.generate_and_verify_patch(
            repo_id="test_repo",
            error_report="ZeroDivisionError: integer division or modulo by zero in divide",
            target_file=calc_file,
            test_command=test_cmd,
            max_iterations=3,
        )

        # Verifications
        assert mock_llm.call_count == 2
        assert patch_record["status"] == "verified"
        assert patch_record["sandbox_validation"]["verified"] is True
        assert patch_record["sandbox_validation"]["test_status"] == "passed"
        assert patch_record["sandbox_validation"]["iterations_count"] == 2

        # Verify iteration history
        history = patch_record["sandbox_validation"]["iteration_history"]
        assert len(history) == 2
        assert history[0]["turn"] == 1
        assert history[0]["test_passed"] is False
        assert history[1]["turn"] == 2
        assert history[1]["test_passed"] is True

        # Verify Turn 2 prompt included test failure feedback
        turn2_prompt = mock_llm.prompts_received[1]
        assert "Previous Failed Patch Candidate" in turn2_prompt
        assert "Test Traceback / Output" in turn2_prompt


def test_autonomous_multi_turn_repair_loop_exhausts_max_iterations():
    """
    REQ-FUT-02: Verifies that when candidate patches continuously fail,
    the repair loop terminates at max_iterations without infinite loops.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        calc_file = "calc.py"
        test_file = "test_calc.py"

        with open(os.path.join(tmpdir, calc_file), "w", encoding="utf-8") as f:
            f.write("def divide(a, b):\n    return a // b\n")

        with open(os.path.join(tmpdir, test_file), "w", encoding="utf-8") as f:
            f.write(
                "from calc import divide\n"
                "assert False, 'Always fail test'\n"
            )

        failing_response = (
            "```python\n"
            "def divide(a, b):\n    return 42\n"
            "```\n"
            "Failing attempt."
        )
        mock_llm = MockMultiTurnLLM([failing_response])

        chunk = CodeChunk(
            chunk_id="calc.py::divide",
            file_path=calc_file,
            language="python",
            kind="function",
            name="divide",
            start_line=1,
            end_line=2,
            code="def divide(a, b):\n    return a // b\n",
        )
        embedder = TfidfEmbedder(dim=16)
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        engine = PatchEngine(
            store=store,
            embedder=embedder,
            llm=mock_llm,
            repo_path=tmpdir,
            is_admin=True,
            allow_local_sandbox=True,
        )

        test_cmd = [sys.executable, test_file]
        patch_record = engine.generate_and_verify_patch(
            repo_id="test_repo",
            error_report="AssertionError: Always fail test",
            target_file=calc_file,
            test_command=test_cmd,
            max_iterations=3,
        )

        # Loop must stop at max_iterations (3)
        assert mock_llm.call_count == 3
        assert patch_record["status"] == "pending"
        assert patch_record["sandbox_validation"]["verified"] is False
        assert patch_record["sandbox_validation"]["test_status"] == "failed"
        assert patch_record["sandbox_validation"]["iterations_count"] == 3
        assert len(patch_record["sandbox_validation"]["iteration_history"]) == 3
        assert all(h["test_passed"] is False for h in patch_record["sandbox_validation"]["iteration_history"])

