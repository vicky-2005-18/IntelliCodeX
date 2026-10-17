"""
Live Docker Sandbox & PatchEngine Integration Tests for Rust.

Milestone: Rust patch verification inside real Docker containers using:
  - Rust/Cargo 1.85.1 toolchain (pinned in intellicodex-sandbox:latest)
  - Strict security controls: --network none, --user 1000:1000, --read-only, --tmpfs /tmp, --memory 512m
  - Rejection invariants: zero-test, compilation failure, crashing/panic test, timeout cleanup.
  - Multi-target aggregation (unit tests in src/ and integration tests in tests/).
  - Proper interpretation of #[should_panic] and #[ignore].
  - Zero host leakage: disposable container mounts with unmodified host repositories.

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
# Helper Fixtures: Rust Project Scaffolding
# =========================================================================

def _create_rust_repo(repo_dir: str, buggy: bool = True) -> str:
    """Scaffolds a clean single-package Cargo project with a buggy or fixed math function."""
    src_dir = os.path.join(repo_dir, "src")
    os.makedirs(src_dir, exist_ok=True)

    cargo_toml = (
        "[package]\n"
        'name = "calc"\n'
        'version = "0.1.0"\n'
        'edition = "2021"\n\n'
        "[dependencies]\n"
    )
    with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
        f.write(cargo_toml)

    math_code = (
        "pub fn add(a: i32, b: i32) -> i32 {\n"
        "    a - b // BUG: subtraction instead of addition\n"
        "}\n\n"
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    use super::*;\n\n"
        "    #[test]\n"
        "    fn test_happy_path() {\n"
        "        assert_eq!(add(0, 0), 0);\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn test_reproduce_bug() {\n"
        "        assert_eq!(add(2, 3), 5);\n"
        "    }\n"
        "}\n"
    ) if buggy else (
        "pub fn add(a: i32, b: i32) -> i32 {\n"
        "    a + b\n"
        "}\n\n"
        "#[cfg(test)]\n"
        "mod tests {\n"
        "    use super::*;\n\n"
        "    #[test]\n"
        "    fn test_happy_path() {\n"
        "        assert_eq!(add(0, 0), 0);\n"
        "    }\n\n"
        "    #[test]\n"
        "    fn test_reproduce_bug() {\n"
        "        assert_eq!(add(2, 3), 5);\n"
        "    }\n"
        "}\n"
    )

    math_file = os.path.join(src_dir, "lib.rs")
    with open(math_file, "w", encoding="utf-8") as f:
        f.write(math_code)

    return math_file


def _tree_sha256(directory: str) -> str:
    """Computes a combined SHA-256 hash of all files and relative paths in directory."""
    hasher = hashlib.sha256()
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for f in sorted(files):
            rel_path = os.path.relpath(os.path.join(root, f), directory)
            hasher.update(rel_path.encode("utf-8"))
            try:
                with open(os.path.join(root, f), "rb") as fh:
                    hasher.update(fh.read())
            except Exception:
                pass
    return hasher.hexdigest()


# =========================================================================
# Live Container Tests (12 Tests)
# =========================================================================

def test_rust_docker_buggy_code_fails_reproducing_test_while_happy_path_passes(docker_available):
    """Verifies that buggy Rust code fails reproducing test while passing happy-path in Docker."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_repro_") as repo_dir:
        math_file = _create_rust_repo(repo_dir, buggy=True)

        with open(math_file, "r", encoding="utf-8") as f:
            unmodified_code = f.read()

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code=unmodified_code,
            timeout=45,
            runtime="rust",
        )

        assert not res.success, "Buggy code must not pass verification"
        assert res.exit_code != 0, f"Expected non-zero exit code, got {res.exit_code}"
        assert res.framework == "cargo"
        assert not res.skipped
        assert res.passed_count == 1, f"Expected 1 passed test (test_happy_path), got {res.passed_count}"
        assert res.failed_count == 1, f"Expected 1 failed test (test_reproduce_bug), got {res.failed_count}"
        assert any("test_happy_path" in t for t in res.passed_tests)
        assert any("test_reproduce_bug" in t for t in res.failed_tests)


def test_rust_docker_correct_patch_passes_both_tests(docker_available):
    """Verifies that hand-authored correct Rust patch passes both happy and reproducing tests."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_correct_") as repo_dir:
        _create_rust_repo(repo_dir, buggy=True)

        correct_patch = (
            "pub fn add(a: i32, b: i32) -> i32 {\n"
            "    a + b\n"
            "}\n\n"
            "#[cfg(test)]\n"
            "mod tests {\n"
            "    use super::*;\n\n"
            "    #[test]\n"
            "    fn test_happy_path() {\n"
            "        assert_eq!(add(0, 0), 0);\n"
            "    }\n\n"
            "    #[test]\n"
            "    fn test_reproduce_bug() {\n"
            "        assert_eq!(add(2, 3), 5);\n"
            "    }\n"
            "}\n"
        )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code=correct_patch,
            timeout=45,
            runtime="rust",
        )

        assert res.success, f"Correct patch must succeed: {res.stderr}\n{res.error_message}"
        assert res.exit_code == 0
        assert res.framework == "cargo"
        assert not res.skipped
        assert res.passed_count == 2, f"Expected 2 passing tests, got {res.passed_count}"
        assert res.failed_count == 0
        assert any("test_happy_path" in t for t in res.passed_tests)
        assert any("test_reproduce_bug" in t for t in res.passed_tests)


def test_rust_docker_incorrect_patch_fails_behavioral_tests(docker_available):
    """Verifies that an incorrect Rust patch (e.g. multiplication) is rejected."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_incorrect_") as repo_dir:
        _create_rust_repo(repo_dir, buggy=True)

        incorrect_patch = (
            "pub fn add(a: i32, b: i32) -> i32 {\n"
            "    a * b // INSUFFICIENT FIX: passes 0,0 but fails 2,3\n"
            "}\n\n"
            "#[cfg(test)]\n"
            "mod tests {\n"
            "    use super::*;\n\n"
            "    #[test]\n"
            "    fn test_happy_path() {\n"
            "        assert_eq!(add(0, 0), 0);\n"
            "    }\n\n"
            "    #[test]\n"
            "    fn test_reproduce_bug() {\n"
            "        assert_eq!(add(2, 3), 5);\n"
            "    }\n"
            "}\n"
        )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code=incorrect_patch,
            timeout=45,
            runtime="rust",
        )

        assert not res.success, "Incorrect patch must fail verification"
        assert res.exit_code != 0
        assert res.passed_count == 1
        assert res.failed_count == 1
        assert any("test_reproduce_bug" in t for t in res.failed_tests)


def test_rust_docker_compilation_failure_remains_unverified(docker_available):
    """Verifies that a Rust patch introducing a compile error stops execution and reports unverified."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_compile_") as repo_dir:
        _create_rust_repo(repo_dir, buggy=True)

        syntax_error_patch = (
            "pub fn add(a: i32, b: i32) -> i32 {\n"
            "    a + \"type mismatch\"\n"
            "}\n"
        )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code=syntax_error_patch,
            timeout=45,
            runtime="rust",
        )

        assert not res.success, "Compilation failure must not be verified"
        assert res.exit_code != 0
        assert res.failed_count >= 1
        assert "compilation" in res.failed_tests
        assert len(res.assertion_errors) > 0, "Compiler diagnostics must be captured"
        assert any("mismatched types" in err.lower() or "cannot add" in err.lower() or "error" in err.lower() for err in res.assertion_errors)


def test_rust_docker_missing_offline_dependencies_rejected(docker_available):
    """Verifies that missing external crate dependencies in offline sandbox produce clean rejection."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_offline_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        os.makedirs(src_dir, exist_ok=True)

        # Cargo.toml requesting an unavailable crate
        cargo_toml = (
            "[package]\n"
            'name = "offline_fail"\n'
            'version = "0.1.0"\n'
            'edition = "2021"\n\n'
            "[dependencies]\n"
            'serde_json = "1.0"\n'
        )
        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write(cargo_toml)

        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write("pub fn dummy() {}\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code="pub fn dummy() {}\n",
            timeout=30,
            runtime="rust",
        )

        assert not res.success, "Missing offline dependency must fail verification"
        assert res.exit_code != 0
        assert "compilation" in res.failed_tests or "cargo_exit_failure" in res.failed_tests
        assert any(
            "offline mode is enabled" in err.lower()
            or "cannot find crate" in err.lower()
            or "no matching package" in err.lower()
            or "could not compile" in err.lower()
            for err in res.assertion_errors
        )


def test_rust_docker_zero_tests_and_ignored_only_remain_unverified(docker_available):
    """Verifies that projects with zero tests or all ignored tests are rejected as unverified."""
    # Case A: Cargo.toml without any test functions
    with tempfile.TemporaryDirectory(prefix="icx_rust_notests_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "notests"\nversion = "0.1.0"\nedition = "2021"\n')
        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write("pub fn foo() -> i32 { 42 }\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code="pub fn foo() -> i32 { 42 }\n",
            timeout=30,
            runtime="rust",
        )

        assert not res.success, "Zero tests must not count as verified repair"
        assert res.skipped, "Zero tests must be marked skipped"

    # Case B: All tests annotated with #[ignore]
    with tempfile.TemporaryDirectory(prefix="icx_rust_ignored_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "ignored_pkg"\nversion = "0.1.0"\nedition = "2021"\n')
        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write(
                "pub fn foo() -> i32 { 42 }\n\n"
                "#[cfg(test)]\n"
                "mod tests {\n"
                "    #[test]\n"
                "    #[ignore]\n"
                "    fn test_ignored() {\n"
                "        assert_eq!(2 + 2, 4);\n"
                "    }\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code="pub fn foo() -> i32 { 42 }\n",
            timeout=30,
            runtime="rust",
        )

        assert not res.success, "Ignored-only tests must not count as verified repair"
        assert res.skipped, "Ignored-only tests must be marked skipped"
        assert res.passed_count == 0


def test_rust_docker_failing_integration_target_defeats_passing_unit_test(docker_available):
    """Verifies that multi-target Cargo projects fail overall if an integration test fails."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_multitarget_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "multitarget"\nversion = "0.1.0"\nedition = "2021"\n')

        unit_code = (
            "pub fn unit_fn() -> i32 { 10 }\n\n"
            "#[cfg(test)]\n"
            "mod tests {\n"
            "    use super::*;\n"
            "    #[test]\n"
            "    fn test_unit_passes() {\n"
            "        assert_eq!(unit_fn(), 10);\n"
            "    }\n"
            "}\n"
        )
        # Unit tests pass in src/lib.rs
        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write(unit_code)

        # Integration test in tests/ fails
        with open(os.path.join(tests_dir, "integ_test.rs"), "w", encoding="utf-8") as f:
            f.write(
                "use multitarget::unit_fn;\n\n"
                "#[test]\n"
                "fn test_integration_fails() {\n"
                "    assert_eq!(unit_fn(), 999); // Intentionally fails\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code=unit_code,
            timeout=45,
            runtime="rust",
        )

        assert not res.success, "Failing integration target must defeat overall verification"
        assert res.exit_code != 0
        assert res.passed_count >= 1, "Unit test pass should be counted"
        assert res.failed_count >= 1, "Integration test failure must be counted"
        assert any("test_unit_passes" in t for t in res.passed_tests)
        assert any("test_integration_fails" in t for t in res.failed_tests)


def test_rust_docker_unexpected_panic_handled_correctly(docker_available):
    """Verifies that an unexpected runtime panic is caught and diagnosed."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_panic_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "panic_pkg"\nversion = "0.1.0"\nedition = "2021"\n')

        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write("pub fn dangerous_div(a: i32, b: i32) -> i32 { a + b }\n")

        with open(os.path.join(tests_dir, "panic_test.rs"), "w", encoding="utf-8") as f:
            f.write(
                "use panic_pkg::dangerous_div;\n\n"
                "#[test]\n"
                "fn test_div_panic() {\n"
                "    dangerous_div(10, 0);\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        panicking_patch = (
            "pub fn dangerous_div(a: i32, b: i32) -> i32 {\n"
            "    if b == 0 { panic!(\"fatal zero denominator\"); }\n"
            "    a / b\n"
            "}\n"
        )
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code=panicking_patch,
            timeout=30,
            runtime="rust",
        )

        assert not res.success, "Panicking test must fail verification"
        assert res.exit_code != 0
        assert res.failed_count >= 1
        assert any("test_div_panic" in t for t in res.failed_tests)
        assert any("fatal zero denominator" in err or "panicked at" in err for err in res.assertion_errors)


def test_rust_docker_should_panic_evaluated_correctly(docker_available):
    """Verifies #[should_panic] tests: pass when they panic, fail when they do not."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_should_panic_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "sp_pkg"\nversion = "0.1.0"\nedition = "2021"\n')

        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write("pub fn crash() { panic!(\"crash\"); }\npub fn no_crash() {}\n")

        with open(os.path.join(tests_dir, "sp_test.rs"), "w", encoding="utf-8") as f:
            f.write(
                "use sp_pkg::{crash, no_crash};\n\n"
                "#[test]\n"
                "#[should_panic(expected = \"crash\")]\n"
                "fn test_panics_as_expected() {\n"
                "    crash();\n"
                "}\n\n"
                "#[test]\n"
                "#[should_panic]\n"
                "fn test_fails_because_no_panic() {\n"
                "    no_crash();\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code="pub fn crash() { panic!(\"crash\"); }\npub fn no_crash() {}\n",
            timeout=30,
            runtime="rust",
        )

        assert not res.success, "Unmet should_panic expectation must fail verification"
        assert res.exit_code != 0
        assert res.passed_count == 1, f"Expected 1 passed test (test_panics_as_expected), got {res.passed_count}"
        assert res.failed_count == 1, f"Expected 1 failed test (test_fails_because_no_panic), got {res.failed_count}"
        assert any("test_panics_as_expected" in t for t in res.passed_tests)
        assert any("test_fails_because_no_panic" in t for t in res.failed_tests)
        assert any("test did not panic as expected" in err for err in res.assertion_errors)


def test_rust_docker_timeout_cleans_up_container(docker_available):
    """Verifies that an infinite loop test is killed at timeout with no container leakage."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_timeout_") as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        with open(os.path.join(repo_dir, "Cargo.toml"), "w", encoding="utf-8") as f:
            f.write('[package]\nname = "loop_pkg"\nversion = "0.1.0"\nedition = "2021"\n')

        with open(os.path.join(src_dir, "lib.rs"), "w", encoding="utf-8") as f:
            f.write("pub fn infinite() { loop {} }\n")

        with open(os.path.join(tests_dir, "loop_test.rs"), "w", encoding="utf-8") as f:
            f.write(
                "use loop_pkg::infinite;\n\n"
                "#[test]\n"
                "fn test_infinite_loop() {\n"
                "    infinite();\n"
                "}\n"
            )

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        t0 = time.time()
        res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code="pub fn infinite() { loop {} }\n",
            timeout=3,
            runtime="rust",
        )
        elapsed = time.time() - t0

        assert not res.success, "Timed-out test must fail verification"
        assert res.exit_code == -1, f"Expected -1 timeout exit code, got {res.exit_code}"
        assert elapsed < 12, f"Execution hung beyond expected timeout: {elapsed}s"
        assert "timed out" in (res.error_message or "").lower()

        # Check docker ps: the specific container created for this test should not remain
        target_container = getattr(res, "container_name", None) or getattr(runner, "last_container_name", None)
        assert target_container, "Container name should be tracked for docker execution"
        ps = subprocess.run(["docker", "ps", "--filter", f"name={target_container}", "--format", "{{.Names}}"], capture_output=True, text=True)
        assert ps.stdout.strip() == "", f"Orphaned sandbox container detected: {target_container}"


def test_rust_docker_preserves_original_repository_state(docker_available):
    """Verifies that sandbox execution leaves the original host repository bytes pristine."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_host_") as repo_dir:
        _create_rust_repo(repo_dir, buggy=True)

        tree_hash_before = _tree_sha256(repo_dir)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME)
        runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/lib.rs",
            patched_code="pub fn add(a: i32, b: i32) -> i32 { a + b }\n",
            timeout=45,
            runtime="rust",
        )

        tree_hash_after = _tree_sha256(repo_dir)
        assert tree_hash_before == tree_hash_after, "Host repository was mutated by sandbox runner"


def test_rust_patchengine_integration_records_verified_experience(docker_available):
    """Verifies that PatchEngine records verified experience with language='rust' only upon passing test."""
    with tempfile.TemporaryDirectory(prefix="icx_rust_engine_") as repo_dir:
        math_file = _create_rust_repo(repo_dir, buggy=True)

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
            "pub fn add(a: i32, b: i32) -> i32 {\n"
            "    a - b // still broken\n"
            "}\n"
        )
        engine._generate_fix = lambda **kwargs: (
            invalid_patch,
            "Hand-authored invalid fix",
            False,
        )
        record_fail = engine.generate_and_verify_patch(
            target_file="src/lib.rs",
            error_report="test_reproduce_bug failed: assert_eq!(add(2, 3), 5)",
            repo_id="test-rust-repo",
            max_iterations=1,
            language="rust",
        )

        assert record_fail["status"] in ("pending", "failed"), f"Failed patch must not be marked verified: {record_fail['status']}"
        assert not record_fail.get("sandbox_validation", {}).get("verified", False)
        assert len([e for e in exp_bank.experiences.values() if e.language == "rust"]) == 0, "Failed repair was incorrectly recorded in experience bank"

        # 2. Valid patch: MUST be stored with language='rust' and test_verified=True
        valid_patch = (
            "pub fn add(a: i32, b: i32) -> i32 {\n"
            "    a + b\n"
            "}\n\n"
            "#[cfg(test)]\n"
            "mod tests {\n"
            "    use super::*;\n\n"
            "    #[test]\n"
            "    fn test_happy_path() {\n"
            "        assert_eq!(add(0, 0), 0);\n"
            "    }\n\n"
            "    #[test]\n"
            "    fn test_reproduce_bug() {\n"
            "        assert_eq!(add(2, 3), 5);\n"
            "    }\n"
            "}\n"
        )
        engine._generate_fix = lambda **kwargs: (
            valid_patch,
            "Hand-authored valid fix",
            False,
        )
        record_pass = engine.generate_and_verify_patch(
            target_file="src/lib.rs",
            error_report="test_reproduce_bug failed: assert_eq!(add(2, 3), 5)",
            repo_id="test-rust-repo",
            max_iterations=1,
            language="rust",
        )

        assert record_pass["status"] == "verified", f"Valid patch must be marked verified: {record_pass.get('sandbox_validation')}"
        assert record_pass["sandbox_validation"]["verified"]
        rust_exps = [e for e in exp_bank.experiences.values() if e.language == "rust"]
        assert len(rust_exps) == 1, "Verified repair was not recorded in experience bank"

        stored_exp = rust_exps[0]
        assert stored_exp.language == "rust", f"Expected language 'rust', got {stored_exp.language}"
        assert stored_exp.test_verified is True
        assert stored_exp.repo_id == "test-rust-repo"
        assert "a + b" in stored_exp.fixed_code


# =========================================================================
# Unit Test: Parser Multi-Target and Edge Cases (1 Test)
# =========================================================================

def test_rust_parser_unit_multi_target_and_edge_cases():
    """Unit test for _parse_cargo_test_output verifying multi-target aggregation, panics, and edge cases."""
    runner = SandboxRunner(sandbox_mode="local")

    # Multi-target output: 1 target ok, 1 target FAILED
    stdout = (
        "     Running unittests src/lib.rs (target/debug/deps/mypkg-1234)\n\n"
        "running 2 tests\n"
        "test tests::test_one ... ok\n"
        "test tests::test_two ... ok\n\n"
        "test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n\n"
        "     Running tests/integ.rs (target/debug/deps/integ-5678)\n\n"
        "running 1 test\n"
        "test test_integration_case ... FAILED\n\n"
        "failures:\n\n"
        "---- test_integration_case stdout ----\n"
        "thread 'test_integration_case' panicked at tests/integ.rs:5:5:\n"
        "assertion `left == right` failed\n"
        "  left: 10\n"
        " right: 20\n\n"
        "failures:\n"
        "    test_integration_case\n\n"
        "test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s\n"
    )
    stderr = (
        "   Compiling mypkg v0.1.0 (/work)\n"
        "    Finished `test` profile [unoptimized + debuginfo] target(s) in 1.20s\n"
        "error: test failed, to rerun pass `--test integ`\n"
    )

    parsed = runner._parse_cargo_test_output(stdout, stderr, exit_code=101)

    assert parsed["passed_count"] == 2
    assert parsed["failed_count"] == 1
    assert parsed["total_count"] == 3
    assert len(parsed["target_summaries"]) == 2
    assert any("test_integration_case" in t for t in parsed["failed_tests"])
    assert any("assertion `left == right` failed" in err for err in parsed["assertion_errors"])
    assert not parsed["incomplete_stream"]

    # Incomplete stream: target started but crashed before summary
    stdout_incomplete = (
        "     Running unittests src/lib.rs (target/debug/deps/mypkg-1234)\n\n"
        "running 2 tests\n"
        "test tests::test_one ... ok\n"
    )
    parsed_inc = runner._parse_cargo_test_output(stdout_incomplete, "fatal crash", exit_code=139)
    assert parsed_inc["incomplete_stream"] is True
    assert parsed_inc["failed_count"] >= 1
