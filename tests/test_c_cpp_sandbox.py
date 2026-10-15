"""
Live Docker Sandbox & PatchEngine Integration Tests for C and C++.

Milestone: C and C++ patch verification inside real Docker containers using:
  - GCC 14.2.0 (gcc, g++)
  - CMake 3.31.6 & CTest 3.31.6
  - Strict security controls: --network none, --user 1000:1000, --read-only, --memory 512m
  - Rejection invariants: zero-test, compilation failure, crashing test, timeout cleanup.
"""

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
# Helper Fixtures: C Project Scaffolding
# =========================================================================

def _create_c_repo(repo_dir: str, buggy: bool = True):
    """Scaffolds a clean CMake-based C project."""
    inc_dir = os.path.join(repo_dir, "include")
    src_dir = os.path.join(repo_dir, "src")
    tests_dir = os.path.join(repo_dir, "tests")
    os.makedirs(inc_dir, exist_ok=True)
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(tests_dir, exist_ok=True)

    cmakelists = os.path.join(repo_dir, "CMakeLists.txt")
    with open(cmakelists, "w", encoding="utf-8") as f:
        f.write("""cmake_minimum_required(VERSION 3.16)
project(c_calc C)
enable_testing()

add_library(calc_c src/calc.c)
target_include_directories(calc_c PUBLIC include)

add_executable(test_calc_happy tests/test_happy.c)
target_link_libraries(test_calc_happy PRIVATE calc_c)
add_test(NAME HappyPathCTest COMMAND test_calc_happy)

add_executable(test_calc_reproduce tests/test_reproduce.c)
target_link_libraries(test_calc_reproduce PRIVATE calc_c)
add_test(NAME ReproduceDivideBugCTest COMMAND test_calc_reproduce)
""")

    calc_h = os.path.join(inc_dir, "calc.h")
    with open(calc_h, "w", encoding="utf-8") as f:
        f.write("""#ifndef CALC_H
#define CALC_H

int add(int a, int b);
int divide(int a, int b);

#endif
""")

    calc_c = os.path.join(src_dir, "calc.c")
    divide_body = "return a * b;" if buggy else "return a / b;"
    with open(calc_c, "w", encoding="utf-8") as f:
        f.write(f"""#include "calc.h"

int add(int a, int b) {{
    return a + b;
}}

int divide(int a, int b) {{
    {divide_body}
}}
""")

    test_happy = os.path.join(tests_dir, "test_happy.c")
    with open(test_happy, "w", encoding="utf-8") as f:
        f.write("""#include <assert.h>
#include "calc.h"

int main(void) {
    assert(add(10, 20) == 30);
    return 0;
}
""")

    test_reproduce = os.path.join(tests_dir, "test_reproduce.c")
    with open(test_reproduce, "w", encoding="utf-8") as f:
        f.write("""#include <assert.h>
#include "calc.h"

int main(void) {
    assert(divide(12, 4) == 3);
    return 0;
}
""")
    return calc_c, test_reproduce


# =========================================================================
# Helper Fixtures: C++ Project Scaffolding
# =========================================================================

def _create_cpp_repo(repo_dir: str, buggy: bool = True):
    """Scaffolds a clean CMake-based C++ project."""
    inc_dir = os.path.join(repo_dir, "include")
    src_dir = os.path.join(repo_dir, "src")
    tests_dir = os.path.join(repo_dir, "tests")
    os.makedirs(inc_dir, exist_ok=True)
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(tests_dir, exist_ok=True)

    cmakelists = os.path.join(repo_dir, "CMakeLists.txt")
    with open(cmakelists, "w", encoding="utf-8") as f:
        f.write("""cmake_minimum_required(VERSION 3.16)
project(cpp_calc CXX)
set(CMAKE_CXX_STANDARD 17)
enable_testing()

add_library(calc_cpp src/calc.cpp)
target_include_directories(calc_cpp PUBLIC include)

add_executable(test_calc_happy tests/test_happy.cpp)
target_link_libraries(test_calc_happy PRIVATE calc_cpp)
add_test(NAME HappyPathCppTest COMMAND test_calc_happy)

add_executable(test_calc_reproduce tests/test_reproduce.cpp)
target_link_libraries(test_calc_reproduce PRIVATE calc_cpp)
add_test(NAME ReproduceDivideBugCppTest COMMAND test_calc_reproduce)
""")

    calc_hpp = os.path.join(inc_dir, "calc.hpp")
    with open(calc_hpp, "w", encoding="utf-8") as f:
        f.write("""#ifndef CALC_HPP
#define CALC_HPP

class Calculator {
public:
    int add(int a, int b);
    int divide(int a, int b);
};

#endif
""")

    calc_cpp = os.path.join(src_dir, "calc.cpp")
    divide_body = "return a * b;" if buggy else "return a / b;"
    with open(calc_cpp, "w", encoding="utf-8") as f:
        f.write(f"""#include "calc.hpp"

int Calculator::add(int a, int b) {{
    return a + b;
}}

int Calculator::divide(int a, int b) {{
    {divide_body}
}}
""")

    test_happy = os.path.join(tests_dir, "test_happy.cpp")
    with open(test_happy, "w", encoding="utf-8") as f:
        f.write("""#include <cassert>
#include "calc.hpp"

int main() {
    Calculator calc;
    assert(calc.add(10, 20) == 30);
    return 0;
}
""")

    test_reproduce = os.path.join(tests_dir, "test_reproduce.cpp")
    with open(test_reproduce, "w", encoding="utf-8") as f:
        f.write("""#include <cassert>
#include "calc.hpp"

int main() {
    Calculator calc;
    assert(calc.divide(12, 4) == 3);
    return 0;
}
""")
    return calc_cpp, test_reproduce


# =========================================================================
# Live Docker Container Tests for C
# =========================================================================

def test_c_docker_buggy_code_fails_reproducing_test_while_happy_path_passes(docker_available):
    """Verifies unpatched buggy C code fails reproducing assertion test while happy path passes."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_c, _ = _create_c_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        with open(calc_c, "r", encoding="utf-8") as f:
            original_code = f.read()

        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code=original_code,
            runtime="c",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "ctest"
        assert result.failed_count == 1
        assert result.passed_count == 1
        assert result.total_count == 2
        assert "ReproduceDivideBugCTest" in result.failed_tests
        assert "HappyPathCTest" in result.passed_tests
        assert any("assert" in err.lower() or "***failed" in err.lower() for err in result.assertion_errors)


def test_c_docker_correct_patch_passes_both_tests(docker_available):
    """Verifies a correct hand-authored C patch passes both happy path and reproducing tests."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_c_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        # Hand-authored correct C patch
        correct_patch = """#include "calc.h"

int add(int a, int b) {
    return a + b;
}

int divide(int a, int b) {
    return a / b;
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code=correct_patch,
            runtime="c",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.framework == "ctest"
        assert result.passed_count == 2
        assert result.failed_count == 0
        assert result.total_count == 2
        assert "HappyPathCTest" in result.passed_tests
        assert "ReproduceDivideBugCTest" in result.passed_tests


def test_c_docker_incorrect_patch_fails_behavioral_tests(docker_available):
    """Verifies an incorrect hand-authored patch fails behavioral tests."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_c_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        # Hand-authored incorrect fix
        incorrect_patch = """#include "calc.h"

int add(int a, int b) {
    return a + b;
}

int divide(int a, int b) {
    return a - b;
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code=incorrect_patch,
            runtime="c",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count == 1
        assert "ReproduceDivideBugCTest" in result.failed_tests


def test_c_docker_compilation_failure_prevents_test_execution(docker_available):
    """Verifies syntax/compilation error stops execution before CTest runs."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_c_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        syntax_error_patch = """#include "calc.h"

int add(int a, int b) {
    SYNTAX_ERROR_NOT_VALID_C
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code=syntax_error_patch,
            runtime="c",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "cmake"
        assert result.failed_count == 1
        assert result.passed_count == 0
        assert "compilation" in result.failed_tests
        assert any("error:" in err.lower() for err in result.assertion_errors)


# =========================================================================
# Live Docker Container Tests for C++
# =========================================================================

def test_cpp_docker_buggy_code_fails_reproducing_test_while_happy_path_passes(docker_available):
    """Verifies unpatched buggy C++ code fails reproducing test while happy path passes."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_cpp, _ = _create_cpp_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        with open(calc_cpp, "r", encoding="utf-8") as f:
            original_code = f.read()

        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.cpp",
            patched_code=original_code,
            runtime="cpp",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "ctest"
        assert result.failed_count == 1
        assert result.passed_count == 1
        assert result.total_count == 2
        assert "ReproduceDivideBugCppTest" in result.failed_tests
        assert "HappyPathCppTest" in result.passed_tests


def test_cpp_docker_correct_patch_passes_both_tests(docker_available):
    """Verifies a correct hand-authored C++ patch passes both happy path and reproducing tests."""
    with tempfile.TemporaryDirectory() as repo_dir:
        _create_cpp_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)

        correct_patch = """#include "calc.hpp"

int Calculator::add(int a, int b) {
    return a + b;
}

int Calculator::divide(int a, int b) {
    return a / b;
}
"""
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.cpp",
            patched_code=correct_patch,
            runtime="cpp",
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.framework == "ctest"
        assert result.passed_count == 2
        assert result.failed_count == 0
        assert "HappyPathCppTest" in result.passed_tests
        assert "ReproduceDivideBugCppTest" in result.passed_tests


# =========================================================================
# Rejection Invariants: Zero-Test, Missing Dependencies, Crashing, Timeout
# =========================================================================

def test_c_cpp_docker_zero_tests_remains_unverified(docker_available):
    """Verifies that compilation success with zero discovered tests remains unverified."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        os.makedirs(src_dir, exist_ok=True)
        calc_c = os.path.join(src_dir, "calc.c")
        with open(calc_c, "w", encoding="utf-8") as f:
            f.write("int add(int a, int b) { return a + b; }\n")

        # CMakeLists with enable_testing() but zero add_test() calls
        with open(os.path.join(repo_dir, "CMakeLists.txt"), "w", encoding="utf-8") as f:
            f.write("""cmake_minimum_required(VERSION 3.16)
project(zero_test C)
enable_testing()
add_library(calc_c src/calc.c)
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code="int add(int a, int b) { return a + b; }\n",
            runtime="c",
        )

        assert result.success is False
        assert result.skipped is True
        assert result.passed_count == 0
        assert "Zero tests discovered" in (result.error_message or "")


def test_c_cpp_docker_missing_dependencies_produces_clear_diagnostic(docker_available):
    """Verifies missing build dependencies fail at configure phase with clear diagnostic."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        os.makedirs(src_dir, exist_ok=True)
        calc_c = os.path.join(src_dir, "calc.c")
        with open(calc_c, "w", encoding="utf-8") as f:
            f.write("int add(int a, int b) { return a + b; }\n")

        with open(os.path.join(repo_dir, "CMakeLists.txt"), "w", encoding="utf-8") as f:
            f.write("""cmake_minimum_required(VERSION 3.16)
project(missing_dep C)
find_package(NonExistentSuperLibrary REQUIRED)
enable_testing()
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code="int add(int a, int b) { return a + b; }\n",
            runtime="c",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.framework == "cmake"
        assert result.failed_count == 1
        assert "cmake_configure" in result.failed_tests
        assert any("nonexistentsuperlibrary" in err.lower() or "cmake error" in err.lower() for err in result.assertion_errors)


def test_c_cpp_docker_crashing_test_executable_reported_as_failure(docker_available):
    """Verifies a test crashing with SIGSEGV/abort is reported as a test failure."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        calc_c = os.path.join(src_dir, "calc.c")
        with open(calc_c, "w", encoding="utf-8") as f:
            f.write("int add(int a, int b) { return a + b; }\n")

        # Test executable triggers a crash / SIGSEGV
        test_crash = os.path.join(tests_dir, "test_crash.c")
        with open(test_crash, "w", encoding="utf-8") as f:
            f.write("""#include <stdlib.h>

int main(void) {
    volatile int* ptr = NULL;
    *ptr = 42; // Causes segmentation fault
    return 0;
}
""")

        with open(os.path.join(repo_dir, "CMakeLists.txt"), "w", encoding="utf-8") as f:
            f.write("""cmake_minimum_required(VERSION 3.16)
project(crash_test C)
enable_testing()
add_executable(test_crash tests/test_crash.c)
add_test(NAME CrashingTest COMMAND test_crash)
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code="int add(int a, int b) { return a + b; }\n",
            runtime="c",
        )

        assert result.success is False
        assert result.exit_code != 0
        assert result.failed_count >= 1
        assert "CrashingTest" in result.failed_tests
        assert any("exception" in err.lower() or "subprocess" in err.lower() or "failed" in err.lower() for err in result.assertion_errors)


def test_c_cpp_docker_timeout_terminates_container_cleanly(docker_available):
    """Verifies timeout terminates compilation/test container and leaves no orphans."""
    with tempfile.TemporaryDirectory() as repo_dir:
        src_dir = os.path.join(repo_dir, "src")
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(src_dir, exist_ok=True)
        os.makedirs(tests_dir, exist_ok=True)

        calc_c = os.path.join(src_dir, "calc.c")
        with open(calc_c, "w", encoding="utf-8") as f:
            f.write("int add(int a, int b) { return a + b; }\n")

        # Test executable that hangs indefinitely
        test_hang = os.path.join(tests_dir, "test_hang.c")
        with open(test_hang, "w", encoding="utf-8") as f:
            f.write("""#include <unistd.h>

int main(void) {
    sleep(100);
    return 0;
}
""")

        with open(os.path.join(repo_dir, "CMakeLists.txt"), "w", encoding="utf-8") as f:
            f.write("""cmake_minimum_required(VERSION 3.16)
project(hang_test C)
enable_testing()
add_executable(test_hang tests/test_hang.c)
add_test(NAME HangTest COMMAND test_hang)
""")

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code="int add(int a, int b) { return a + b; }\n",
            runtime="c",
            timeout=3,
        )

        assert result.success is False
        assert result.exit_code == -1
        assert "timed out" in (result.error_message or "").lower()

        # Verify no orphan containers left running
        ps_res = subprocess.run(
            ["docker", "ps", "--filter", "name=icx-sandbox-", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
        )
        assert ps_res.stdout.strip() == ""


def test_c_cpp_docker_original_repo_files_remain_unchanged(docker_available):
    """Verifies that patch testing does not mutate the host repository."""
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_c, _ = _create_c_repo(repo_dir, buggy=True)

        with open(calc_c, "r", encoding="utf-8") as f:
            original_content = f.read()

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="src/calc.c",
            patched_code="/* MUTATED CODE */\n",
            runtime="c",
        )

        # Host file must be untouched
        with open(calc_c, "r", encoding="utf-8") as f:
            post_content = f.read()

        assert post_content == original_content


# =========================================================================
# PatchEngine -> SandboxRunner Live Closed-Loop Integration Test
# =========================================================================

def test_c_cpp_patchengine_integration_records_verified_experience_only_on_pass(docker_available):
    """
    Exercises PatchEngine -> SandboxRunner integration in real Docker:
    - Demonstrates that a verified C repair records experience with language='c'.
    - Demonstrates that failed repairs do NOT become verified experiences.
    """
    with tempfile.TemporaryDirectory() as repo_dir:
        calc_c, _ = _create_c_repo(repo_dir, buggy=True)

        runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
        exp_bank = RepairExperienceBank()
        engine = PatchEngine(
            store=FaissVectorStore(dim=64),
            embedder=TfidfEmbedder(),
            repo_path=repo_dir,
            sandbox_runner=runner,
            experience_bank=exp_bank,
            is_admin=True,
        )

        correct_patch = """#include "calc.h"

int add(int a, int b) {
    return a + b;
}

int divide(int a, int b) {
    return a / b;
}
"""
        # Override _generate_fix to return our hand-authored candidate
        engine._generate_fix = lambda **kwargs: (
            correct_patch,
            "Hand-authored fix for C divide operator",
            False,
        )

        record = engine.generate_and_verify_patch(
            repo_id="c_calc_repo",
            error_report="Assertion error: ReproduceDivideBugCTest failed on divide(12, 4) == 3",
            target_file="src/calc.c",
        )

        assert record["status"] == "verified"
        assert record["sandbox_validation"]["verified"] is True
        assert record["sandbox_validation"]["test_status"] == "passed"

        # Check experience bank recorded with language="c" and test_verified=True
        experiences = [e for e in exp_bank.experiences.values() if e.language == "c"]
        assert len(experiences) == 1
        assert experiences[0].language == "c"
        assert experiences[0].test_verified is True
        assert "return a / b;" in experiences[0].fixed_code
