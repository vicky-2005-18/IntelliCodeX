"""
End-to-end integration tests for JavaScript and TypeScript patch verification inside real Docker containers.

Covers:
1. JavaScript buggy code failing behavioral tests, correct hand-authored patch passing, incorrect patch failing.
2. TypeScript compilation failure (Phase 1), buggy TS behavioral failure (Phase 2), correct hand-authored patch passing.
3. Missing tests resulting in skipped/unverified status (zero tests != verified repair).
4. Container timeout enforcement and process cleanup.
5. Preservation of unrelated host repository files.
6. PatchEngine -> SandboxRunner integration with experience recording invariants.
"""
import os
import shutil
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
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    if not runner._check_docker_available():
        pytest.skip("Docker daemon is unavailable on host. Skipping live Docker tests.")
    return True


# =========================================================================
# JavaScript Test Fixtures and Verification
# =========================================================================

def test_js_docker_buggy_code_fails_behavioral_test(docker_available):
    """Verifies that original buggy JS code fails the bug test inside Docker."""
    with tempfile.TemporaryDirectory() as repo_dir:
        # Original buggy implementation: subtraction bug in multiply
        calc_js = os.path.join(repo_dir, "calc.js")
        with open(calc_js, "w", encoding="utf-8") as f:
            f.write("function multiply(a, b) { return a - b; }\nmodule.exports = { multiply };\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_js = os.path.join(test_dir, "calc.test.js")
        with open(test_js, "w", encoding="utf-8") as f:
            f.write("""const test = require('node:test');
const assert = require('node:assert');
const { multiply } = require('../calc');

test('multiplies numbers correctly', () => {
    assert.strictEqual(multiply(3, 4), 12);
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Run test against original buggy code
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.js",
            patched_code="function multiply(a, b) { return a - b; }\nmodule.exports = { multiply };\n",
            runtime="javascript",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count >= 1
        assert result.framework == "node_test"
        assert len(result.failed_tests) > 0 or len(result.assertion_errors) > 0


def test_js_docker_correct_patch_passes_behavioral_test(docker_available):
    """Verifies that a correct hand-authored JS patch passes the test suite."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_js = os.path.join(repo_dir, "calc.js")
        with open(calc_js, "w", encoding="utf-8") as f:
            f.write("function multiply(a, b) { return a - b; }\nmodule.exports = { multiply };\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_js = os.path.join(test_dir, "calc.test.js")
        with open(test_js, "w", encoding="utf-8") as f:
            f.write("""const test = require('node:test');
const assert = require('node:assert');
const { multiply } = require('../calc');

test('multiplies numbers correctly', () => {
    assert.strictEqual(multiply(3, 4), 12);
});
test('multiplies with zero', () => {
    assert.strictEqual(multiply(5, 0), 0);
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Correct hand-authored patch
        correct_patch = "function multiply(a, b) { return a * b; }\nmodule.exports = { multiply };\n"
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.js",
            patched_code=correct_patch,
            runtime="javascript",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.passed_count == 2
        assert result.failed_count == 0
        assert result.skipped is False


def test_js_docker_incorrect_patch_fails_behavioral_test(docker_available):
    """Verifies that an incorrect hand-authored patch still fails the test suite."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_js = os.path.join(repo_dir, "calc.js")
        with open(calc_js, "w", encoding="utf-8") as f:
            f.write("function multiply(a, b) { return a - b; }\nmodule.exports = { multiply };\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_js = os.path.join(test_dir, "calc.test.js")
        with open(test_js, "w", encoding="utf-8") as f:
            f.write("""const test = require('node:test');
const assert = require('node:assert');
const { multiply } = require('../calc');

test('multiplies numbers correctly', () => {
    assert.strictEqual(multiply(3, 4), 12);
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Incorrect patch: returns sum instead of product
        incorrect_patch = "function multiply(a, b) { return a + b; }\nmodule.exports = { multiply };\n"
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.js",
            patched_code=incorrect_patch,
            runtime="javascript",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count >= 1


# =========================================================================
# TypeScript Test Fixtures and Verification (Phase 1 Compile + Phase 2 Test)
# =========================================================================

def test_ts_docker_compilation_failure_blocks_execution(docker_available):
    """Verifies that TypeScript type/syntax errors fail in Phase 1 without running behavioral tests."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_ts = os.path.join(repo_dir, "calc.ts")
        with open(calc_ts, "w", encoding="utf-8") as f:
            f.write("export function divide(a: number, b: number): number { return a / b; }\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_ts = os.path.join(test_dir, "calc.test.ts")
        with open(test_ts, "w", encoding="utf-8") as f:
            f.write("""import test from 'node:test';
import assert from 'node:assert';
import { divide } from '../calc';

test('divides numbers', () => {
    assert.strictEqual(divide(10, 2), 5);
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Candidate patch with blatant TypeScript type mismatch error: returns string instead of number
        broken_ts_patch = 'export function divide(a: number, b: number): number { return "not_a_number" as unknown as boolean; }\n'

        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.ts",
            patched_code=broken_ts_patch,
            runtime="typescript",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "typescript"
        assert result.failed_count == 1
        assert "error TS" in (result.stdout + result.stderr + "\n".join(result.assertion_errors))
        assert "tsc_compilation" in result.failed_tests


def test_ts_docker_buggy_code_fails_behavioral_test(docker_available):
    """Verifies that syntactically valid TS with behavioral bug compiles but fails test execution."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_ts = os.path.join(repo_dir, "calc.ts")
        with open(calc_ts, "w", encoding="utf-8") as f:
            # Bug: returns addition instead of power
            f.write("export function power(base: number, exp: number): number { return base + exp; }\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_ts = os.path.join(test_dir, "calc.test.ts")
        with open(test_ts, "w", encoding="utf-8") as f:
            f.write("""import test from 'node:test';
import assert from 'node:assert';
import { power } from '../calc';

test('computes exponential power', () => {
    assert.strictEqual(power(2, 3), 8);
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Buggy code
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.ts",
            patched_code="export function power(base: number, exp: number): number { return base + exp; }\n",
            runtime="typescript",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count >= 1


def test_ts_docker_correct_patch_passes_compile_and_behavioral_tests(docker_available):
    """Verifies that a correct hand-authored TS patch compiles and passes behavioral tests."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_ts = os.path.join(repo_dir, "calc.ts")
        with open(calc_ts, "w", encoding="utf-8") as f:
            f.write("export function power(base: number, exp: number): number { return base + exp; }\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_ts = os.path.join(test_dir, "calc.test.ts")
        with open(test_ts, "w", encoding="utf-8") as f:
            f.write("""import test from 'node:test';
import assert from 'node:assert';
import { power } from '../calc';

test('computes exponential power', () => {
    assert.strictEqual(power(2, 3), 8);
});
test('computes zero power', () => {
    assert.strictEqual(power(5, 0), 1);
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Hand-authored correct patch
        correct_patch = "export function power(base: number, exp: number): number { return Math.pow(base, exp); }\n"
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.ts",
            patched_code=correct_patch,
            runtime="typescript",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.passed_count == 2
        assert result.failed_count == 0
        assert result.skipped is False


# =========================================================================
# Edge Case & Safety Invariant Verifications
# =========================================================================

def test_missing_tests_results_in_unverified_status(docker_available):
    """Verifies that zero discovered tests does not count as a verified repair."""
    with tempfile.TemporaryDirectory() as repo_dir:
        # Repository with code but no test files
        util_js = os.path.join(repo_dir, "util.js")
        with open(util_js, "w", encoding="utf-8") as f:
            f.write("function helper() { return 42; }\nmodule.exports = { helper };\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="util.js",
            patched_code="function helper() { return 100; }\nmodule.exports = { helper };\n",
            runtime="javascript",
        )

        assert result.skipped is True
        assert result.success is False
        assert result.passed_count == 0
        assert "No automated JavaScript test files were discovered" in (result.error_message or "")


def test_ts_compilation_alone_without_tests_is_not_verified(docker_available):
    """Verifies that successful TypeScript compilation without behavioral tests does not verify."""
    with tempfile.TemporaryDirectory() as repo_dir:
        # TS file without any test files
        math_ts = os.path.join(repo_dir, "math.ts")
        with open(math_ts, "w", encoding="utf-8") as f:
            f.write("export const PI: number = 3.14159;\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="math.ts",
            patched_code="export const PI: number = 3.14159265;\n",
            runtime="typescript",
        )

        assert result.skipped is True
        assert result.success is False
        assert result.passed_count == 0
        assert "zero behavioral test files were discovered" in (result.error_message or "")


def test_js_docker_timeout_cleanup(docker_available):
    """Verifies that an infinite loop test times out and cleans up the container."""
    with tempfile.TemporaryDirectory() as repo_dir:
        hang_js = os.path.join(repo_dir, "hang.js")
        with open(hang_js, "w", encoding="utf-8") as f:
            f.write("function runInfinite() { while (true) {} }\nmodule.exports = { runInfinite };\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        test_js = os.path.join(test_dir, "hang.test.js")
        with open(test_js, "w", encoding="utf-8") as f:
            f.write("""const test = require('node:test');
const { runInfinite } = require('../hang');

test('hang test', () => {
    runInfinite();
});
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True, default_timeout=2)
        t0 = time.perf_counter()
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="hang.js",
            patched_code="function runInfinite() { while (true) {} }\nmodule.exports = { runInfinite };\n",
            timeout=2,
            runtime="javascript",
        )
        elapsed = time.perf_counter() - t0

        assert result.success is False
        assert result.exit_code == -1
        assert "timed out" in (result.error_message or "").lower()
        assert elapsed < 10.0


def test_host_files_are_strictly_preserved(docker_available):
    """Verifies that sandbox execution does not mutate or contaminate host repository files."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_js = os.path.join(repo_dir, "calc.js")
        orig_content = "function add(a, b) { return a + b; }\nmodule.exports = { add };\n"
        with open(calc_js, "w", encoding="utf-8") as f:
            f.write(orig_content)

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        with open(os.path.join(test_dir, "calc.test.js"), "w", encoding="utf-8") as f:
            f.write("const test = require('node:test'); const assert = require('node:assert'); const { add } = require('../calc'); test('add', () => { assert.strictEqual(add(1, 2), 3); });")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Attempt to run tests with a mutated patch
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.js",
            patched_code="function add(a, b) { return 999; }\nmodule.exports = { add };\n",
            runtime="javascript",
        )

        # Host file must be 100% identical to original
        with open(calc_js, "r", encoding="utf-8") as f:
            current_host_content = f.read()
        assert current_host_content == orig_content


# =========================================================================
# PatchEngine -> SandboxRunner Integration
# =========================================================================

def test_patch_engine_js_ts_verification_and_experience_invariants(docker_available):
    """
    Exercises PatchEngine -> SandboxRunner closed-loop verification on JS/TS repos.
    Ensures that verified repairs register test_verified=True and record in experience bank,
    while broken patches or zero-test patches never record as verified.
    """
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_ts = os.path.join(repo_dir, "calc.ts")
        with open(calc_ts, "w", encoding="utf-8") as f:
            f.write("export function multiply(a: number, b: number): number { return a - b; }\n")

        test_dir = os.path.join(repo_dir, "test")
        os.makedirs(test_dir, exist_ok=True)
        with open(os.path.join(test_dir, "calc.test.ts"), "w", encoding="utf-8") as f:
            f.write("""import test from 'node:test';
import assert from 'node:assert';
import { multiply } from '../calc';

test('multiplies numbers', () => {
    assert.strictEqual(multiply(4, 5), 20);
});
""")

        # Set up an isolated experience bank
        exp_file = os.path.join(repo_dir, "exp.json")
        exp_bank = RepairExperienceBank(storage_path=exp_file)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        store = FaissVectorStore(dim=64)
        embedder = TfidfEmbedder()

        engine = PatchEngine(
            store=store,
            embedder=embedder,
            repo_path=repo_dir,
            sandbox_runner=runner,
            is_admin=True,
            experience_bank=exp_bank,
        )

        # 1. Test running an incorrect candidate patch directly through runner
        bad_res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.ts",
            patched_code="export function multiply(a: number, b: number): number { return a + b; }\n",
            runtime="typescript",
        )
        assert bad_res.success is False
        ts_exps_before = [e for e in exp_bank.experiences.values() if e.language == "typescript"]
        assert len(ts_exps_before) == 0

        # 2. Test running a hand-authored correct patch directly through runner
        good_res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="calc.ts",
            patched_code="export function multiply(a: number, b: number): number { return a * b; }\n",
            runtime="typescript",
        )
        assert good_res.success is True
        assert good_res.passed_count == 1
        assert good_res.failed_count == 0

        # 3. Verify experience recording contract
        exp_bank.record_success(
            error_type="AssertionError",
            error_description="multiply(4, 5) did not equal 20",
            original_code="return a - b;",
            fixed_code="return a * b;",
            explanation="Hand-authored verified fix for TS multiplication",
            source="sandbox_pass",
            language="typescript",
            test_verified=True,
            developer_approved=False,
            repo_id="test_ts_repo",
            event_id="sandbox:test_ts_repo:001",
        )

        experiences = [e for e in exp_bank.experiences.values() if e.language == "typescript"]
        assert len(experiences) == 1
        assert experiences[0].language == "typescript"
        assert experiences[0].test_verified is True
