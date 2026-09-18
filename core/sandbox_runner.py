"""
Isolated Sandbox Test Execution Runner for IntelliCodeX (Milestone 1)
Executes repository test suites (pytest, unittest, npm) inside an isolated
temporary sandbox directory applying proposed candidate patches without
mutating the host codebase.
"""
import dataclasses
import os
import re
import shutil
import subprocess
import sys
import time
from typing import List, Optional, Dict, Any, Tuple


@dataclasses.dataclass
class SandboxTestResult:
    """Encapsulates the execution results of a sandboxed test run."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    framework: str
    passed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    failed_tests: List[str] = dataclasses.field(default_factory=list)
    passed_tests: List[str] = dataclasses.field(default_factory=list)
    assertion_errors: List[str] = dataclasses.field(default_factory=list)
    traceback_summary: str = ""
    error_message: Optional[str] = None
    skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


class SandboxRunner:
    """
    Manages isolated temporary directory sandboxes to safely apply patches
    and execute test suites.
    """

    # Directory/file patterns to skip when copying repository into sandbox
    IGNORE_PATTERNS = {
        ".git", ".repos", ".venv", "venv", "env", "node_modules",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "dist", "build", "coverage", ".coverage", "*.pyc", "*.pyo"
    }

    def __init__(self, default_timeout: int = 30):
        self.default_timeout = default_timeout

    def detect_test_framework(self, repo_path: str) -> Optional[str]:
        """Detects test framework available in the target repository."""
        if not os.path.isdir(repo_path):
            return None

        # Check for pytest configuration or tests directory
        has_tests_dir = any(
            os.path.isdir(os.path.join(repo_path, d))
            for d in ("tests", "test", "testing", "src/tests")
        )
        has_pytest_config = any(
            os.path.isfile(os.path.join(repo_path, f))
            for f in ("pytest.ini", "setup.cfg", "pyproject.toml", "conftest.py")
        )

        # Check for test files in root or subdirectories
        has_test_files = False
        try:
            for root, _, files in os.walk(repo_path):
                if any(ignored in root for ignored in (".git", ".venv", "venv", ".repos")):
                    continue
                if any(f.startswith("test_") or f.endswith("_test.py") for f in files):
                    has_test_files = True
                    break
        except Exception:
            pass

        if has_tests_dir or has_pytest_config or has_test_files:
            return "pytest"

        # Check for npm / package.json test scripts
        pkg_json = os.path.join(repo_path, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                    if '"test"' in f.read():
                        return "npm"
            except Exception:
                pass

        return None

    def run_tests_with_patch(
        self,
        repo_path: str,
        target_file: str,
        patched_code: str,
        test_command: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> SandboxTestResult:
        """
        Copies repo to an isolated temporary sandbox, applies patched_code to target_file,
        runs test suite, and parses outcome.
        """
        import tempfile

        t_start = time.perf_counter()
        effective_timeout = timeout or self.default_timeout
        framework = self.detect_test_framework(repo_path)

        if not framework and not test_command:
            return SandboxTestResult(
                success=True,
                exit_code=0,
                stdout="",
                stderr="",
                duration_seconds=0.0,
                framework="none",
                skipped=True,
                error_message="No automated test suite discovered in repository."
            )

        with tempfile.TemporaryDirectory(prefix="icx_sandbox_") as sandbox_dir:
            try:
                # 1. Copy repo files into sandbox
                self._populate_sandbox(repo_path, sandbox_dir)

                # 2. Apply patched code to the target file inside sandbox
                dest_file = os.path.join(sandbox_dir, target_file)
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                with open(dest_file, "w", encoding="utf-8", errors="replace") as f:
                    f.write(patched_code)

                # 3. Determine command
                cmd = self._resolve_command(sandbox_dir, framework, test_command, target_file)

                # 4. Execute test command in sandbox subprocess
                env = os.environ.copy()
                env["PYTHONPATH"] = f"{sandbox_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"

                res = subprocess.run(
                    cmd,
                    cwd=sandbox_dir,
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                    env=env,
                    shell=(sys.platform == "win32" and isinstance(cmd, str))
                )

                elapsed = time.perf_counter() - t_start
                stdout = res.stdout or ""
                stderr = res.stderr or ""
                exit_code = res.returncode

                # 5. Parse test results
                if framework == "pytest" or "pytest" in (test_command or ""):
                    parsed = self._parse_pytest_output(stdout, stderr)
                else:
                    parsed = self._parse_generic_output(stdout, stderr, exit_code)

                return SandboxTestResult(
                    success=(exit_code == 0),
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=elapsed,
                    framework=framework or "custom",
                    passed_count=parsed["passed_count"],
                    failed_count=parsed["failed_count"],
                    total_count=parsed["total_count"],
                    failed_tests=parsed["failed_tests"],
                    passed_tests=parsed["passed_tests"],
                    assertion_errors=parsed["assertion_errors"],
                    traceback_summary=parsed["traceback_summary"],
                )

            except subprocess.TimeoutExpired as exc:
                elapsed = time.perf_counter() - t_start
                stdout = exc.stdout.decode("utf-8", errors="ignore") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = exc.stderr.decode("utf-8", errors="ignore") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                return SandboxTestResult(
                    success=False,
                    exit_code=-1,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=elapsed,
                    framework=framework or "unknown",
                    error_message=f"Sandbox test run timed out after {effective_timeout}s.",
                    traceback_summary=f"TimeoutExpired: Test execution exceeded {effective_timeout} seconds limit.",
                )
            except Exception as e:
                elapsed = time.perf_counter() - t_start
                return SandboxTestResult(
                    success=False,
                    exit_code=-2,
                    stdout="",
                    stderr=str(e),
                    duration_seconds=elapsed,
                    framework=framework or "unknown",
                    error_message=f"Sandbox execution error: {str(e)}",
                    traceback_summary=str(e),
                )

    def _populate_sandbox(self, src_dir: str, dest_dir: str):
        """Copies source files into sandbox directory ignoring heavy/cache artifacts."""
        def ignore_filter(dir_path, filenames):
            ignored = set()
            rel = os.path.relpath(dir_path, src_dir)
            for name in filenames:
                full_rel = os.path.join(rel, name)
                if name in self.IGNORE_PATTERNS or any(name.startswith(p) for p in (".venv", "venv", ".repos")):
                    ignored.add(name)
                elif name.endswith((".pyc", ".pyo", ".pyd")):
                    ignored.add(name)
            return ignored

        shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True, ignore=ignore_filter)

    def _resolve_command(
        self,
        sandbox_dir: str,
        framework: Optional[str],
        test_command: Optional[str],
        target_file: str,
    ) -> Any:
        if test_command:
            return test_command

        # Default for Python: run pytest or unittest
        if framework == "pytest":
            # Attempt to target tests matching the target file if obvious, or full suite
            target_base = os.path.splitext(os.path.basename(target_file))[0]
            specific_test = os.path.join(sandbox_dir, "tests", f"test_{target_base}.py")
            if os.path.isfile(specific_test):
                return [sys.executable, "-m", "pytest", f"tests/test_{target_base}.py", "-v", "--tb=short"]
            return [sys.executable, "-m", "pytest", "-v", "--tb=short"]

        if framework == "npm":
            return ["npm", "test"]

        # Default fallback: python unittest discover
        return [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test*.py"]

    def _parse_pytest_output(self, stdout: str, stderr: str) -> Dict[str, Any]:
        """Extracts passed/failed counts, assertion messages, and traceback highlights from pytest output."""
        passed_tests = []
        failed_tests = []
        assertion_errors = []
        traceback_lines = []

        # Parse test execution lines: e.g. tests/test_math.py::test_add PASSED
        for line in stdout.splitlines():
            line_str = line.strip()
            if " PASSED" in line_str:
                test_name = line_str.split(" PASSED")[0].strip()
                passed_tests.append(test_name)
            elif " FAILED" in line_str:
                test_name = line_str.split(" FAILED")[0].strip()
                failed_tests.append(test_name)
            elif " ERROR" in line_str:
                test_name = line_str.split(" ERROR")[0].strip()
                failed_tests.append(test_name)

        # Parse assertion failures & traceback section
        in_failures_section = False

        for line in stdout.splitlines():
            if "=== FAILURES ===" in line or "=== ERRORS ===" in line:
                in_failures_section = True
                continue
            if "=== short test summary info ===" in line or "=== warnings summary ===" in line:
                in_failures_section = False
                continue

            if in_failures_section:
                traceback_lines.append(line)
                if line.startswith("E   ") or line.startswith("AssertionError:") or "Error:" in line:
                    assertion_errors.append(line.strip())

        # Extract summary numbers e.g. "1 failed, 4 passed in 0.12s"
        passed_count = len(passed_tests)
        failed_count = len(failed_tests)

        summary_match = re.search(r"(=+)\s+(.*?)\s+in\s+[\d\.]+s\s+(=+)", stdout)
        if summary_match:
            summary_text = summary_match.group(2)
            pass_m = re.search(r"(\d+)\s+passed", summary_text)
            fail_m = re.search(r"(\d+)\s+failed", summary_text)
            err_m = re.search(r"(\d+)\s+error", summary_text)
            if pass_m:
                passed_count = int(pass_m.group(1))
            if fail_m:
                failed_count = int(fail_m.group(1))
            if err_m:
                failed_count += int(err_m.group(1))

        total_count = passed_count + failed_count
        traceback_summary = "\n".join(traceback_lines[:40]) if traceback_lines else (stderr[:1000] if stderr else "")

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "assertion_errors": assertion_errors[:10],
            "traceback_summary": traceback_summary,
        }

    def _parse_generic_output(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """Fallback parser for generic test runners."""
        combined = f"{stdout}\n{stderr}".strip()
        failed_count = 1 if exit_code != 0 else 0
        passed_count = 1 if exit_code == 0 else 0
        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_count": 1,
            "passed_tests": ["all"] if exit_code == 0 else [],
            "failed_tests": ["test_suite"] if exit_code != 0 else [],
            "assertion_errors": [line.strip() for line in combined.splitlines() if "Error" in line or "Assertion" in line][:5],
            "traceback_summary": combined[-1500:] if combined else "",
        }
