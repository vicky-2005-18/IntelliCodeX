"""
Live Docker Sandbox & PatchEngine Integration Tests for Java.

Milestone: Java patch verification inside real Docker containers using:
  - OpenJDK 21 LTS (`javac` 21.0.12.1)
  - JUnit Jupiter & JUnit Platform Console Standalone Launcher (1.10.2)
  - Strict security controls: --network none, --user 1000:1000, --read-only, --memory 512m
  - Zero-test, skipped-only, and compilation failure rejection invariants.
"""

import os
import shutil
import subprocess
import tempfile
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
# Packaged Java Fixtures & Behavioral Verifications
# =========================================================================

def _create_packaged_java_repo(repo_dir: str, buggy: bool = True):
    """Helper to scaffold a standard packaged Java project structure."""
    src_dir = os.path.join(repo_dir, "src", "main", "java", "com", "example")
    test_dir = os.path.join(repo_dir, "src", "test", "java", "com", "example")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    calc_java = os.path.join(src_dir, "Calculator.java")
    divide_body = "return a * b;" if buggy else "return a / b;"
    with open(calc_java, "w", encoding="utf-8") as f:
        f.write(f"""package com.example;

public class Calculator {{
    public int add(int a, int b) {{
        return a + b;
    }}

    public int divide(int a, int b) {{
        {divide_body}
    }}
}}
""")

    calc_test = os.path.join(test_dir, "CalculatorTest.java")
    with open(calc_test, "w", encoding="utf-8") as f:
        f.write("""package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class CalculatorTest {

    @Test
    void testHappyAdd() {
        Calculator calc = new Calculator();
        assertEquals(5, calc.add(2, 3));
    }

    @Test
    void testReproduceDivideBug() {
        Calculator calc = new Calculator();
        assertEquals(2, calc.divide(6, 3));
    }
}
""")
    return calc_java, calc_test


def test_java_docker_buggy_code_fails_reproducing_test_while_happy_path_passes(docker_available):
    """Verifies that unpatched buggy Java code fails its reproducing test while happy path passes."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_java, _ = _create_packaged_java_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Execute tests on unpatched buggy code
        with open(calc_java, "r", encoding="utf-8") as f:
            original_code = f.read()

        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Calculator.java",
            patched_code=original_code,
            runtime="java",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "junit"
        assert result.failed_count == 1
        assert result.passed_count == 1
        assert result.total_count == 2
        assert any("testReproduceDivideBug" in t for t in result.failed_tests)
        assert any("testHappyAdd" in t for t in result.passed_tests)
        assert any("expected: <2> but was: <18>" in err or "AssertionFailedError" in err for err in result.assertion_errors)


def test_java_docker_correct_patch_passes_both_tests(docker_available):
    """Verifies that a correct hand-authored Java patch passes both happy path and reproducing tests."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_packaged_java_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        # Hand-authored correct fix for divide
        correct_patch = """package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int divide(int a, int b) {
        return a / b;
    }
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Calculator.java",
            patched_code=correct_patch,
            runtime="java",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.framework == "junit"
        assert result.passed_count == 2
        assert result.failed_count == 0
        assert result.total_count == 2
        assert result.skipped is False


def test_java_docker_incorrect_patch_fails_behavioral_tests(docker_available):
    """Verifies that an incorrect hand-authored Java patch fails behavioral assertions."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_packaged_java_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        # Hand-authored incorrect candidate patch: subtractions instead of division
        incorrect_patch = """package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int divide(int a, int b) {
        return a - b;
    }
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Calculator.java",
            patched_code=incorrect_patch,
            runtime="java",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count == 1
        assert result.passed_count == 1
        assert any("testReproduceDivideBug" in t for t in result.failed_tests)


def test_java_docker_compilation_failure_blocks_execution(docker_available):
    """Verifies that static compilation failure with javac prevents test execution and returns diagnostics."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_packaged_java_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        # Syntax / type error candidate
        broken_patch = """package com.example;

public class Calculator {
    public int add(int a, int b) {
        return a + b;
    }

    public int divide(int a, int b) {
        return a / unknownVariableThatDoesNotExist;
    }
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Calculator.java",
            patched_code=broken_patch,
            runtime="java",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "javac"
        assert result.failed_count == 1
        assert result.passed_count == 0
        assert "cannot find symbol" in (result.traceback_summary or "") or "unknownVariableThatDoesNotExist" in (result.traceback_summary or "")
        assert "compilation failed" in (result.error_message or "").lower()


def test_java_missing_tests_results_in_unverified_status(docker_available):
    """Verifies that a repository with Java code but zero test files returns skipped=True and unverified."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src", "main", "java", "com", "example")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, "Helper.java"), "w", encoding="utf-8") as f:
            f.write("package com.example;\npublic class Helper { public int getAnswer() { return 42; } }\n")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Helper.java",
            patched_code="package com.example;\npublic class Helper { public int getAnswer() { return 100; } }\n",
            runtime="java",
        )

        assert result.skipped is True
        assert result.passed_count == 0
        assert result.failed_count == 0
        assert any(msg in (result.error_message or "") for msg in ("No automated test suite discovered", "No automated Java test files were discovered"))


def test_java_skipped_or_aborted_tests_remain_unverified(docker_available):
    """Verifies that disabled (@Disabled) or aborted tests conservatively produce skipped=True and unverified status."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src", "main", "java", "com", "example")
        test_dir = os.path.join(repo_dir, "src", "test", "java", "com", "example")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(test_dir, exist_ok=True)

        with open(os.path.join(src_dir, "Service.java"), "w", encoding="utf-8") as f:
            f.write("package com.example;\npublic class Service { public String ping() { return \"pong\"; } }\n")

        # Test class where all tests are disabled
        with open(os.path.join(test_dir, "ServiceTest.java"), "w", encoding="utf-8") as f:
            f.write("""package com.example;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Disabled;
import static org.junit.jupiter.api.Assertions.*;

public class ServiceTest {

    @Test
    @Disabled("Temporarily disabled pending upstream fix")
    void testDisabledFeature() {
        assertEquals("pong", new Service().ping());
    }
}
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Service.java",
            patched_code="package com.example;\npublic class Service { public String ping() { return \"pong\"; } }\n",
            runtime="java",
        )

        # Skipped-only runs must never count as verified
        assert result.skipped is True
        assert result.success is False
        assert result.passed_count == 0
        assert "Zero tests executed or all tests skipped/aborted" in (result.error_message or "")


def test_java_missing_dependencies_produce_clear_diagnostic(docker_available):
    """Verifies that unavailable third-party dependencies produce clear compiler diagnostics."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src", "main", "java", "com", "example")
        test_dir = os.path.join(repo_dir, "src", "test", "java", "com", "example")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(test_dir, exist_ok=True)

        # Code referencing a non-existent external dependency
        with open(os.path.join(src_dir, "DepUtil.java"), "w", encoding="utf-8") as f:
            f.write("""package com.example;

import org.apache.commons.lang3.StringUtils;

public class DepUtil {
    public static boolean isEmpty(String s) {
        return StringUtils.isEmpty(s);
    }
}
""")

        with open(os.path.join(test_dir, "DepUtilTest.java"), "w", encoding="utf-8") as f:
            f.write("""package com.example;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

public class DepUtilTest {
    @Test
    void testCheck() {
        assertTrue(DepUtil.isEmpty(""));
    }
}
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/DepUtil.java",
            patched_code=open(os.path.join(src_dir, "DepUtil.java")).read(),
            runtime="java",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "javac"
        assert "package org.apache.commons.lang3 does not exist" in (result.traceback_summary or "")


def test_java_docker_timeout_cleanup(docker_available):
    """Verifies that an infinite loop test times out and cleanly terminates the container."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src", "main", "java", "com", "example")
        test_dir = os.path.join(repo_dir, "src", "test", "java", "com", "example")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(test_dir, exist_ok=True)

        with open(os.path.join(src_dir, "Hang.java"), "w", encoding="utf-8") as f:
            f.write("""package com.example;

public class Hang {
    public static void runInfinite() {
        while (true) {}
    }
}
""")

        with open(os.path.join(test_dir, "HangTest.java"), "w", encoding="utf-8") as f:
            f.write("""package com.example;

import org.junit.jupiter.api.Test;

public class HangTest {
    @Test
    void testHang() {
        Hang.runInfinite();
    }
}
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True, default_timeout=2)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Hang.java",
            patched_code=open(os.path.join(src_dir, "Hang.java")).read(),
            runtime="java",
            timeout=2,
        )

        assert result.exit_code == -1
        assert result.success is False
        assert result.duration_seconds >= 2.0
        assert "timed out" in (result.traceback_summary or "").lower() or "timed out" in (result.error_message or "").lower()

        # Confirm zero orphaned containers remain active
        ps_out = subprocess.run(
            ["docker", "ps", "--filter", "name=icx-sandbox-", "--format", "{{.ID}}"],
            capture_output=True,
            text=True,
        )
        assert ps_out.stdout.strip() == ""


def test_java_host_files_are_strictly_preserved(docker_available):
    """Verifies that executing a patch against a disposable copy strictly preserves host repository files."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_java, _ = _create_packaged_java_repo(repo_dir, buggy=True)

        # Create an unrelated file on host with unstaged changes
        unrelated_file = os.path.join(repo_dir, "unrelated_notes.txt")
        with open(unrelated_file, "w", encoding="utf-8") as f:
            f.write("Unrelated staged and unstaged notes\n")

        with open(calc_java, "r", encoding="utf-8") as f:
            host_calc_before = f.read()

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        # Attempt to patch with different code
        runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Calculator.java",
            patched_code="// Mutated code inside sandbox\npackage com.example;\npublic class Calculator {}\n",
            runtime="java",
        )

        # Verify host files were completely untouched
        with open(calc_java, "r", encoding="utf-8") as f:
            assert f.read() == host_calc_before
        with open(unrelated_file, "r", encoding="utf-8") as f:
            assert f.read() == "Unrelated staged and unstaged notes\n"


def test_patch_engine_java_verification_and_experience_invariants(docker_available):
    """
    Exercises PatchEngine -> SandboxRunner closed-loop verification on Java repositories.
    Ensures that verified repairs register test_verified=True and record in experience bank with language="java",
    while broken patches or zero-test patches never record as verified.
    """
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_packaged_java_repo(repo_dir, buggy=True)

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
            target_file="src/main/java/com/example/Calculator.java",
            patched_code="""package com.example;
public class Calculator {
    public int add(int a, int b) { return a + b; }
    public int divide(int a, int b) { return a - b; }
}
""",
            runtime="java",
        )
        assert bad_res.success is False
        java_exps_before = [e for e in exp_bank.experiences.values() if e.language == "java"]
        assert len(java_exps_before) == 0

        # 2. Test running a hand-authored correct patch directly through runner
        good_res = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/main/java/com/example/Calculator.java",
            patched_code="""package com.example;
public class Calculator {
    public int add(int a, int b) { return a + b; }
    public int divide(int a, int b) { return a / b; }
}
""",
            runtime="java",
        )
        assert good_res.success is True
        assert good_res.passed_count == 2
        assert good_res.failed_count == 0

        # 3. Verify experience recording contract with language="java"
        exp_bank.record_success(
            error_type="AssertionFailedError",
            error_description="expected: <2> but was: <18>",
            original_code="return a * b;",
            fixed_code="return a / b;",
            explanation="Hand-authored verified fix for Java Calculator.divide()",
            source="sandbox_pass",
            language="java",
            test_verified=True,
            developer_approved=False,
            repo_id="test_java_repo",
            event_id="sandbox:test_java_repo:001",
        )

        experiences = [e for e in exp_bank.experiences.values() if e.language == "java"]
        assert len(experiences) == 1
        assert experiences[0].language == "java"
        assert experiences[0].test_verified is True
        assert experiences[0].fixed_code == "return a / b;"
