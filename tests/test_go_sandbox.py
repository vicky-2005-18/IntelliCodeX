"""
Live Docker Sandbox & PatchEngine Integration Tests for Go.

Milestone: Go patch verification inside real Docker containers using:
  - Go 1.24.4 toolchain (pinned in intellicodex-sandbox:latest)
  - Strict security controls: --network none, --user 1000:1000, --read-only, --memory 512m
  - Rejection invariants: zero-test, compilation failure, crashing/panic test, timeout cleanup.
  - Multi-package verification under single module (./...).
  - Leaf test counting convention (subtests counted, parents not double-counted).

NOTE ON REPAIR BENCHMARKS:
All candidate patches in this test file are deterministic, hand-authored fixtures
used strictly to verify container pipeline execution and rejection invariants.
They are NOT LLM repair accuracy benchmark measurements.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import pytest

from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.patch_generator import PatchEngine
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.self_improving import RepairExperienceBank

IMAGE_NAME = "intellicodex-sandbox:latest"


@pytest.fixture(scope="module")
def docker_available():
    """Confirms Docker daemon is active and responsive before running live container tests."""
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI is not installed on host")
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode != 0:
            pytest.skip("Docker daemon is not running")
    except Exception as exc:
        pytest.skip(f"Docker daemon probe failed: {exc}")
    return True


# =========================================================================
# Helper Fixtures: Go Project Scaffolding
# =========================================================================

def _create_go_repo(repo_dir: str, buggy: bool = True) -> str:
    """Scaffolds a clean single-module Go project with a buggy or fixed math function."""
    with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
        f.write("module example.com/calc\n\ngo 1.24\n")

    math_code = (
        "package calc\n\n"
        "// Add returns the sum of a and b\n"
        "func Add(a, b int) int {\n"
        "    return a - b // BUG: subtraction instead of addition\n"
        "}\n"
    ) if buggy else (
        "package calc\n\n"
        "// Add returns the sum of a and b\n"
        "func Add(a, b int) int {\n"
        "    return a + b\n"
        "}\n"
    )

    math_file = os.path.join(repo_dir, "calc.go")
    with open(math_file, "w", encoding="utf-8") as f:
        f.write(math_code)

    test_code = (
        "package calc\n\n"
        "import \"testing\"\n\n"
        "func TestHappyPath(t *testing.T) {\n"
        "    if Add(0, 0) != 0 {\n"
        "        t.Errorf(\"Add(0, 0) failed\")\n"
        "    }\n"
        "}\n\n"
        "func TestReproduceBug(t *testing.T) {\n"
        "    if Add(2, 3) != 5 {\n"
        "        t.Errorf(\"Add(2, 3) = %d; want 5\", Add(2, 3))\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(repo_dir, "calc_test.go"), "w", encoding="utf-8") as f:
        f.write(test_code)

    return math_file


# =========================================================================
# Live Container Tests (11 Tests)
# =========================================================================

def test_go_docker_buggy_code_fails_reproducing_test_while_happy_path_passes(docker_available):
    """Verifies that buggy Go code fails reproducing test while passing happy-path in Docker."""
    with tempfile.TemporaryDirectory(prefix="icx_go_repro_") as repo_dir:
        math_file = _create_go_repo(repo_dir, buggy=True)

        with open(math_file, "r", encoding="utf-8") as f:
            unmodified_code = f.read()

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.go",
            patched_code=unmodified_code,
            timeout=30,
            runtime="go",
        )

        assert not res.success, "Buggy code must not pass verification"
        assert res.exit_code != 0, f"Expected non-zero exit code, got {res.exit_code}"
        assert res.framework == "go_test"
        assert not res.skipped
        assert res.passed_count == 1, f"Expected 1 passed test (TestHappyPath), got {res.passed_count}"
        assert res.failed_count == 1, f"Expected 1 failed test (TestReproduceBug), got {res.failed_count}"
        assert any("TestHappyPath" in t for t in res.passed_tests)
        assert any("TestReproduceBug" in t for t in res.failed_tests)


def test_go_docker_correct_patch_passes_both_tests(docker_available):
    """Verifies that hand-authored correct Go patch passes both happy and reproducing tests."""
    with tempfile.TemporaryDirectory(prefix="icx_go_correct_") as repo_dir:
        _create_go_repo(repo_dir, buggy=True)

        correct_patch = (
            "package calc\n\n"
            "// Add returns the sum of a and b\n"
            "func Add(a, b int) int {\n"
            "    return a + b\n"
            "}\n"
        )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.go",
            patched_code=correct_patch,
            timeout=30,
            runtime="go",
        )

        assert res.success, f"Correct patch must succeed: {res.stderr}\n{res.error_message}"
        assert res.exit_code == 0
        assert res.framework == "go_test"
        assert not res.skipped
        assert res.passed_count == 2, f"Expected 2 passing tests, got {res.passed_count}"
        assert res.failed_count == 0
        assert any("TestHappyPath" in t for t in res.passed_tests)
        assert any("TestReproduceBug" in t for t in res.passed_tests)


def test_go_docker_incorrect_patch_fails_behavioral_tests(docker_available):
    """Verifies that an incorrect Go patch (e.g. multiplication) is rejected."""
    with tempfile.TemporaryDirectory(prefix="icx_go_incorrect_") as repo_dir:
        _create_go_repo(repo_dir, buggy=True)

        incorrect_patch = (
            "package calc\n\n"
            "func Add(a, b int) int {\n"
            "    return a * b // INSUFFICIENT FIX: passes 0,0 but fails 2,3\n"
            "}\n"
        )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.go",
            patched_code=incorrect_patch,
            timeout=30,
            runtime="go",
        )

        assert not res.success, "Incorrect patch must fail verification"
        assert res.exit_code != 0
        assert res.passed_count == 1
        assert res.failed_count == 1
        assert any("TestReproduceBug" in t for t in res.failed_tests)


def test_go_docker_compilation_failure_remains_unverified(docker_available):
    """Verifies that a Go patch introducing a compile error stops execution and reports unverified."""
    with tempfile.TemporaryDirectory(prefix="icx_go_compile_") as repo_dir:
        _create_go_repo(repo_dir, buggy=True)

        syntax_error_patch = (
            "package calc\n\n"
            "func Add(a, b int) int {\n"
            "    return a + \"type mismatch\"\n"
            "}\n"
        )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.go",
            patched_code=syntax_error_patch,
            timeout=30,
            runtime="go",
        )

        assert not res.success, "Compilation failure must not be verified"
        assert res.exit_code != 0
        assert res.failed_count >= 1
        assert "compilation" in res.failed_tests or any("calc" in t for t in res.failed_tests)
        assert len(res.assertion_errors) > 0, "Compiler diagnostics must be captured"
        assert any("cannot convert" in err.lower() or "mismatched types" in err.lower() or "build" in err.lower() for err in res.assertion_errors)


def test_go_docker_zero_tests_and_skipped_only_remain_unverified(docker_available):
    """Verifies that projects with zero tests or all skipped tests are rejected as unverified."""
    # Case A: go.mod without test files
    with tempfile.TemporaryDirectory(prefix="icx_go_notests_") as repo_dir:
        with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/notests\n\ngo 1.24\n")
        with open(os.path.join(repo_dir, "lib.go"), "w", encoding="utf-8") as f:
            f.write("package lib\nfunc Foo() int { return 42 }\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="lib.go",
            patched_code="package lib\nfunc Foo() int { return 42 }\n",
            timeout=30,
            runtime="go",
        )

        assert not res.success, "Zero tests must not count as verified repair"
        assert res.skipped, "Zero tests must be marked skipped"

    # Case B: All tests call t.Skip()
    with tempfile.TemporaryDirectory(prefix="icx_go_skipped_") as repo_dir:
        with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/skipped\n\ngo 1.24\n")
        with open(os.path.join(repo_dir, "lib.go"), "w", encoding="utf-8") as f:
            f.write("package lib\nfunc Foo() int { return 42 }\n")
        with open(os.path.join(repo_dir, "lib_test.go"), "w", encoding="utf-8") as f:
            f.write(
                "package lib\nimport \"testing\"\n"
                "func TestSkipped(t *testing.T) {\n"
                "    t.Skip(\"skipping test intentional\")\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="lib.go",
            patched_code="package lib\nfunc Foo() int { return 42 }\n",
            timeout=30,
            runtime="go",
        )

        assert not res.success, "Skipped-only test suite must not count as verified repair"
        assert res.skipped, "Skipped-only suite must have skipped=True"
        assert res.passed_count == 0


def test_go_docker_multi_package_failure_prevents_overall_verification(docker_available):
    """Verifies that a failure in one package blocks verification even when another package passes."""
    with tempfile.TemporaryDirectory(prefix="icx_go_multipkg_") as repo_dir:
        with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/multipkg\n\ngo 1.24\n")

        # Package 1: Passing
        p1 = os.path.join(repo_dir, "pkg1")
        os.makedirs(p1, exist_ok=True)
        with open(os.path.join(p1, "p1.go"), "w", encoding="utf-8") as f:
            f.write("package pkg1\nfunc V1() int { return 1 }\n")
        with open(os.path.join(p1, "p1_test.go"), "w", encoding="utf-8") as f:
            f.write("package pkg1\nimport \"testing\"\nfunc TestP1(t *testing.T) { if V1() != 1 { t.Fail() } }\n")

        # Package 2: Failing
        p2 = os.path.join(repo_dir, "pkg2")
        os.makedirs(p2, exist_ok=True)
        with open(os.path.join(p2, "p2.go"), "w", encoding="utf-8") as f:
            f.write("package pkg2\nfunc V2() int { return 2 }\n")
        with open(os.path.join(p2, "p2_test.go"), "w", encoding="utf-8") as f:
            f.write("package pkg2\nimport \"testing\"\nfunc TestP2(t *testing.T) { t.Errorf(\"p2 failed\") }\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="pkg1/p1.go",
            patched_code="package pkg1\nfunc V1() int { return 1 }\n",
            timeout=30,
            runtime="go",
        )

        assert not res.success, "Multi-package suite must fail if any package fails"
        assert res.exit_code != 0
        assert res.failed_count >= 1
        assert any("pkg2" in t for t in res.failed_tests)
        assert any("pkg1" in t for t in res.passed_tests)


def test_go_docker_missing_offline_dependencies_produces_clear_diagnostic(docker_available):
    """Verifies that an unbundled external dependency fails with clear diagnostic under --network none."""
    with tempfile.TemporaryDirectory(prefix="icx_go_dep_") as repo_dir:
        with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/missingdep\n\ngo 1.24\n")

        with open(os.path.join(repo_dir, "dep.go"), "w", encoding="utf-8") as f:
            f.write(
                "package dep\n\n"
                "import \"github.com/nonexistent/externalpkg\"\n\n"
                "func Use() {\n"
                "    externalpkg.DoSomething()\n"
                "}\n"
            )

        with open(os.path.join(repo_dir, "dep_test.go"), "w", encoding="utf-8") as f:
            f.write(
                "package dep\nimport \"testing\"\n"
                "func TestDep(t *testing.T) {\n"
                "    Use()\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="dep.go",
            patched_code=open(os.path.join(repo_dir, "dep.go")).read(),
            timeout=30,
            runtime="go",
        )

        assert not res.success
        assert res.exit_code != 0
        assert any("cannot find module" in err.lower() or "no required module" in err.lower() or "missingdep" in err.lower() for err in res.assertion_errors)


def test_go_docker_panic_reported_as_failure(docker_available):
    """Verifies that a panic in Go test code is captured as test failure with panic stack trace."""
    with tempfile.TemporaryDirectory(prefix="icx_go_panic_") as repo_dir:
        with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/panic\n\ngo 1.24\n")

        with open(os.path.join(repo_dir, "panic_test.go"), "w", encoding="utf-8") as f:
            f.write(
                "package panic\n\n"
                "import \"testing\"\n\n"
                "func TestPanicCrash(t *testing.T) {\n"
                "    var p *int\n"
                "    *p = 42 // triggers runtime SIGSEGV / nil pointer dereference\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="panic_test.go",
            patched_code=open(os.path.join(repo_dir, "panic_test.go")).read(),
            timeout=30,
            runtime="go",
        )

        assert not res.success
        assert res.exit_code != 0
        assert res.failed_count >= 1
        assert any("TestPanicCrash" in t for t in res.failed_tests)
        combined_err = f"{res.stdout}\n{res.stderr}\n{res.traceback_summary}"
        assert "panic:" in combined_err or "nil pointer" in combined_err or "SIGSEGV" in combined_err


def test_go_docker_timeout_terminates_container_cleanly(docker_available):
    """Verifies that an infinite loop in Go tests is cleanly aborted without orphaned containers."""
    with tempfile.TemporaryDirectory(prefix="icx_go_timeout_") as repo_dir:
        with open(os.path.join(repo_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write("module example.com/timeout\n\ngo 1.24\n")

        with open(os.path.join(repo_dir, "loop_test.go"), "w", encoding="utf-8") as f:
            f.write(
                "package timeout\n\n"
                "import \"testing\"\n\n"
                "func TestInfiniteLoop(t *testing.T) {\n"
                "    for {\n"
                "        // burn cpu forever\n"
                "    }\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        t_start = time.perf_counter()
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="loop_test.go",
            patched_code=open(os.path.join(repo_dir, "loop_test.go")).read(),
            timeout=3,
            runtime="go",
        )
        elapsed = time.perf_counter() - t_start

        assert not res.success
        assert res.exit_code == -1, f"Expected timeout exit code -1, got {res.exit_code}"
        assert elapsed < 15, f"Timeout abort took too long ({elapsed:.1f}s)"

        # Verify no orphan containers left running
        ps = subprocess.run(
            ["docker", "ps", "-q", "--filter", "name=icx-sandbox-"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert ps.stdout.strip() == "", "Orphaned test container leaked after timeout"


def test_go_docker_original_repo_files_remain_unchanged(docker_available):
    """Verifies that sandbox execution never mutates or writes artifacts to the host repository."""
    with tempfile.TemporaryDirectory(prefix="icx_go_isolation_") as repo_dir:
        math_file = _create_go_repo(repo_dir, buggy=True)

        def _dir_hash(path: str) -> str:
            h = hashlib.sha256()
            for root, _, files in sorted(os.walk(path)):
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    with open(fp, "rb") as fh:
                        h.update(f.encode())
                        h.update(fh.read())
            return h.hexdigest()

        hash_before = _dir_hash(repo_dir)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.go",
            patched_code="package calc\nfunc Add(a, b int) int { return a + b }\n",
            timeout=30,
            runtime="go",
        )

        hash_after = _dir_hash(repo_dir)
        assert hash_before == hash_after, "Host repository files were modified by sandbox execution"


def test_go_patchengine_integration_records_verified_experience_only_on_pass(docker_available):
    """Verifies that PatchEngine records verified experience with language='go' only upon passing test."""
    with tempfile.TemporaryDirectory(prefix="icx_go_engine_") as repo_dir:
        math_file = _create_go_repo(repo_dir, buggy=True)

        exp_bank = RepairExperienceBank(storage_path=os.path.join(repo_dir, "exp_bank.json"))
        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        engine = PatchEngine(
            store=FaissVectorStore(dim=64),
            embedder=TfidfEmbedder(),
            repo_path=repo_dir,
            sandbox_runner=runner,
            experience_bank=exp_bank,
            is_admin=True,
        )

        # 1. Invalid patch: must NOT be stored in experience bank
        invalid_patch = (
            "package calc\n\n"
            "func Add(a, b int) int {\n"
            "    return a - b // still broken\n"
            "}\n"
        )
        engine._generate_fix = lambda **kwargs: (
            invalid_patch,
            "Hand-authored invalid fix",
            False,
        )
        record_fail = engine.generate_and_verify_patch(
            target_file="calc.go",
            error_report="TestReproduceBug failed: Add(2, 3) returned -1 want 5",
            repo_id="test-go-repo",
            max_iterations=1,
            language="go",
        )

        assert record_fail["status"] in ("pending", "failed"), f"Failed patch must not be marked verified: {record_fail['status']}"
        assert not record_fail.get("sandbox_validation", {}).get("verified", False)
        assert len([e for e in exp_bank.experiences.values() if e.language == "go"]) == 0, "Failed repair was incorrectly recorded in experience bank"

        # 2. Valid patch: MUST be stored with language='go' and test_verified=True
        valid_patch = (
            "package calc\n\n"
            "func Add(a, b int) int {\n"
            "    return a + b\n"
            "}\n"
        )
        engine._generate_fix = lambda **kwargs: (
            valid_patch,
            "Hand-authored valid fix",
            False,
        )
        record_pass = engine.generate_and_verify_patch(
            target_file="calc.go",
            error_report="TestReproduceBug failed: Add(2, 3) returned -1 want 5",
            repo_id="test-go-repo",
            max_iterations=1,
            language="go",
        )

        assert record_pass["status"] == "verified", f"Valid patch must be marked verified: {record_pass.get('sandbox_validation')}"
        assert record_pass["sandbox_validation"]["verified"]
        go_exps = [e for e in exp_bank.experiences.values() if e.language == "go"]
        assert len(go_exps) == 1, "Verified repair was not recorded in experience bank"

        stored_exp = go_exps[0]
        assert stored_exp.language == "go", f"Expected language 'go', got {stored_exp.language}"
        assert stored_exp.test_verified is True
        assert stored_exp.repo_id == "test-go-repo"
        assert "return a + b" in stored_exp.fixed_code


# =========================================================================
# Parser & Subtest Unit Test (1 Test, No Docker Container Invocation)
# =========================================================================

def test_go_test_parser_leaf_counting_and_subtests():
    """
    Unit test verifying the leaf-counting convention of _parse_go_test_output.
    Confirms that parent tests with subtests are tracked as parent suites and
    are NOT double-counted in total, passed, failed, or skipped metrics.
    """
    runner = SandboxRunner(sandbox_mode="local")

    sample_subtest_stream = """
{"Time":"2026-10-15T04:01:55.859530902Z","Action":"start","Package":"example.com/math"}
{"Time":"2026-10-15T04:01:55.890284261Z","Action":"run","Package":"example.com/math","Test":"TestAdd"}
{"Time":"2026-10-15T04:01:55.890379053Z","Action":"run","Package":"example.com/math","Test":"TestAdd/sub1_positive"}
{"Time":"2026-10-15T04:01:55.890392709Z","Action":"pass","Package":"example.com/math","Test":"TestAdd/sub1_positive","Elapsed":0}
{"Time":"2026-10-15T04:01:55.890401736Z","Action":"run","Package":"example.com/math","Test":"TestAdd/sub2_skipped"}
{"Time":"2026-10-15T04:01:55.89049932Z","Action":"skip","Package":"example.com/math","Test":"TestAdd/sub2_skipped","Elapsed":0}
{"Time":"2026-10-15T04:01:55.890544958Z","Action":"pass","Package":"example.com/math","Test":"TestAdd","Elapsed":0}
{"Time":"2026-10-15T04:01:55.890549236Z","Action":"run","Package":"example.com/math","Test":"TestStandaloneFail"}
{"Time":"2026-10-15T04:01:55.890618358Z","Action":"fail","Package":"example.com/math","Test":"TestStandaloneFail","Elapsed":0}
{"Time":"2026-10-15T04:01:55.892453558Z","Action":"fail","Package":"example.com/math","Elapsed":0.033}
"""

    parsed = runner._parse_go_test_output(sample_subtest_stream, "", exit_code=1)

    # TestAdd has sub1_positive and sub2_skipped -> TestAdd is parent
    # Leaf tests: TestAdd/sub1_positive (pass), TestAdd/sub2_skipped (skip), TestStandaloneFail (fail)
    assert parsed["passed_count"] == 1
    assert parsed["skipped_count"] == 1
    assert parsed["failed_count"] == 1
    assert parsed["total_count"] == 3
    assert "example.com/math.TestAdd" in parsed["parent_tests"]
    assert "example.com/math.TestAdd/sub1_positive" in parsed["passed_tests"]
    assert "example.com/math.TestAdd/sub2_skipped" in parsed["skipped_tests"]
    assert "example.com/math.TestStandaloneFail" in parsed["failed_tests"]


def test_go_test_parser_incomplete_stream_and_parent_failure():
    """
    Unit test verifying that an abruptly terminated Go test stream and parent-test
    failures cannot appear successful, even if some leaf tests passed.
    """
    runner = SandboxRunner(sandbox_mode="local")

    # Scenario 1: Stream truncated while TestIncomplete was running
    truncated_stream = """
{"Time":"2026-10-15T04:01:55.859530902Z","Action":"start","Package":"example.com/math"}
{"Time":"2026-10-15T04:01:55.890284261Z","Action":"run","Package":"example.com/math","Test":"TestHappy"}
{"Time":"2026-10-15T04:01:55.890392709Z","Action":"pass","Package":"example.com/math","Test":"TestHappy","Elapsed":0}
{"Time":"2026-10-15T04:01:55.890401736Z","Action":"run","Package":"example.com/math","Test":"TestIncomplete"}
"""
    parsed = runner._parse_go_test_output(truncated_stream, "", exit_code=1)
    assert parsed["incomplete_stream"] is True
    assert any("TestIncomplete" in f for f in parsed["failed_tests"])
    assert parsed["failed_count"] >= 1

    # Scenario 2: Parent test fails after subtests pass
    parent_fail_stream = """
{"Time":"2026-10-15T04:01:55.859530902Z","Action":"start","Package":"example.com/math"}
{"Time":"2026-10-15T04:01:55.890284261Z","Action":"run","Package":"example.com/math","Test":"TestParent"}
{"Time":"2026-10-15T04:01:55.890379053Z","Action":"run","Package":"example.com/math","Test":"TestParent/sub1"}
{"Time":"2026-10-15T04:01:55.890392709Z","Action":"pass","Package":"example.com/math","Test":"TestParent/sub1","Elapsed":0}
{"Time":"2026-10-15T04:01:55.890544958Z","Action":"fail","Package":"example.com/math","Test":"TestParent","Elapsed":0.01}
{"Time":"2026-10-15T04:01:55.892453558Z","Action":"fail","Package":"example.com/math","Elapsed":0.033}
"""
    parsed_parent = runner._parse_go_test_output(parent_fail_stream, "", exit_code=1)
    assert any("TestParent" in f for f in parsed_parent["failed_tests"])
    assert parsed_parent["passed_count"] == 1  # sub1 passed
    assert len(parsed_parent["failed_tests"]) >= 1  # parent failure preserved
