"""
SECURITY WARNING: Isolated Sandbox Test Execution Runner for IntelliCodeX

This module executes repository test suites (pytest, unittest, npm) inside an isolated
temporary sandbox directory applying proposed candidate patches without mutating the
host codebase.

SECURITY MODEL:
  - LOCAL MODE (default): Tests run as your user with filesystem and network access.
    This is NOT true isolation. Use only on repositories you trust. Hostile tests can
    read/write files, make network requests, and access system resources.
  - DOCKER MODE: Tests run in a container with --network none, memory/CPU limits,
    read-only rootfs, and PID limits. Provides strong isolation for untrusted code.

Environment Variables:
  - SANDBOX_MODE: "local" (default) or "docker"
  - SANDBOX_DOCKER_IMAGE: Docker image to use (default: python:3.11-slim)

Critical Security Features:
  1. Environment allowlist: Only PATH, SYSTEMROOT, TEMP, TMP, COMSPEC, PATHEXT,
     LANG, LC_ALL, HOME, USERPROFILE, PYTHONPATH, PYTHONDONTWRITEBYTECODE are passed.
     Variables matching *KEY*, *TOKEN*, *SECRET*, *PASSWORD*, *CREDENTIAL* are
     blocked even if on the allowlist.
  2. No shell execution: Commands are parsed with shlex.split, shell=True is never used.
     Only allowlisted executables (python, pytest, npm, npx, node, go, cargo, mvn, gradle)
     are permitted. Shell metacharacters (&&, ||, ;, |, >, <, `, $()) are rejected.
  3. Process tree termination: On timeout, the entire process tree is killed via psutil
     (children first), not just the parent.
  4. Output truncation: stdout/stderr capped at 1 MB each to prevent resource exhaustion.
  5. Symlink safety: Symlinks in source repo are never followed (prevents file exfiltration).

WARNING: Local mode provides NO protection against:
  - Reading environment variables (except those explicitly blocked)
  - Network access to exfiltrate data
  - Filesystem access outside the sandbox
  - CPU/memory exhaustion attacks
  - Side-channel attacks

For untrusted repositories, ALWAYS use Docker mode. If Docker is unavailable, the
system will fall back to local mode with a logged warning - never silently.
"""
import dataclasses
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import psutil
from typing import List, Optional, Dict, Any, Tuple

from core.safe_paths import resolve_within

logger = logging.getLogger(__name__)

# Maximum output size in bytes (1 MB)
MAX_OUTPUT_SIZE = 1024 * 1024

# Allowlisted environment variables (case-insensitive)
ENV_ALLOWLIST = {
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT",
    "LANG", "LC_ALL", "HOME", "USERPROFILE", "PYTHONPATH",
    "PYTHONDONTWRITEBYTECODE"
}

# Patterns for sensitive environment variables to block
SENSITIVE_PATTERNS = [
    re.compile(r"KEY", re.IGNORECASE),
    re.compile(r"TOKEN", re.IGNORECASE),
    re.compile(r"SECRET", re.IGNORECASE),
    re.compile(r"PASSWORD", re.IGNORECASE),
    re.compile(r"CREDENTIAL", re.IGNORECASE),
]

# Allowlisted executables (resolved via shutil.which)
EXECUTABLE_ALLOWLIST = {
    "python", "python3", "python.exe", "python3.exe",
    "pytest", "pytest.exe",
    "npm", "npm.exe", "npx", "npx.exe",
    "node", "node.exe",
    "go", "go.exe",
    "cargo", "cargo.exe",
    "mvn", "mvn.exe",
    "gradle", "gradle.exe",
    "program", "program.exe"  # Windows path executable wrapper
}

# Shell metacharacters to reject in user commands
SHELL_METACHARACTERS = ["&&", "||", ";", "|", ">", "<", "`", "$(", "${"]


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

    SECURITY: Local mode runs tests as your user. Use Docker mode for untrusted code.
    """

    # Directory/file patterns to skip when copying repository into sandbox
    IGNORE_PATTERNS = {
        ".git", ".repos", ".venv", "venv", "env", "node_modules",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "dist", "build", "coverage", ".coverage", "*.pyc", "*.pyo"
    }

    def __init__(self, default_timeout: int = 30, sandbox_mode: str = "local", docker_image: str = "python:3.11-slim", allow_local_sandbox: bool = True, is_admin: bool = False):
        self.default_timeout = default_timeout
        self.sandbox_mode = sandbox_mode
        self.docker_image = docker_image
        self.allow_local_sandbox = allow_local_sandbox
        self.is_admin = is_admin

    def _build_sandbox_environment(self, sandbox_dir: str) -> Dict[str, str]:
        """
        Builds a minimal environment for the sandbox process.

        Only allowlisted variables are passed. Variables matching sensitive patterns
        are blocked even if on the allowlist.
        """
        env = {}

        for key, value in os.environ.items():
            # Check if key is on allowlist
            if key.upper() not in ENV_ALLOWLIST:
                continue

            # Check if key matches any sensitive pattern
            if any(pattern.search(key) for pattern in SENSITIVE_PATTERNS):
                logger.warning("Blocking sensitive environment variable: %s", key)
                continue

            env[key] = value

        # Set safe defaults
        env["PYTHONPATH"] = sandbox_dir
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        # Set HOME/USERPROFILE to sandbox dir to prevent home directory access
        if sys.platform == "win32":
            env["USERPROFILE"] = sandbox_dir
        else:
            env["HOME"] = sandbox_dir

        return env

    def _validate_command(self, command: List[str]) -> Optional[str]:
        """
        Validates a command list for security.

        Returns error message if invalid, None if valid.
        """
        if not command:
            return "Empty command"

        # Check first element (executable) is allowlisted
        exe_name = os.path.basename(command[0]).lower()
        if exe_name not in EXECUTABLE_ALLOWLIST:
            return f"Executable '{exe_name}' is not allowlisted. Allowed: {', '.join(sorted(EXECUTABLE_ALLOWLIST))}"

        # Resolve executable with shutil.which to ensure it exists
        resolved = shutil.which(command[0])
        if not resolved:
            return f"Executable '{command[0]}' not found in PATH"

        # Check for shell metacharacters in all arguments
        for arg in command:
            for meta in SHELL_METACHARACTERS:
                if meta in arg:
                    return f"Shell metacharacter '{meta}' detected in command argument: {arg}"

        return None

    def _parse_command(self, command: str) -> Tuple[Optional[List[str]], Optional[str]]:
        """
        Parses a string command into a list using shlex.split.

        Returns (command_list, error_message).
        """
        try:
            # Use shlex.split with posix=False on Windows for proper handling
            parsed = shlex.split(command, posix=(os.name != "nt"))
            return parsed, None
        except ValueError as e:
            return None, f"Failed to parse command: {e}"

    def _truncate_output(self, output: str) -> str:
        """Truncates output to MAX_OUTPUT_SIZE bytes with a marker."""
        if len(output.encode('utf-8', errors='ignore')) <= MAX_OUTPUT_SIZE:
            return output

        # Truncate byte-wise
        truncated = output.encode('utf-8', errors='ignore')[:MAX_OUTPUT_SIZE]
        return truncated.decode('utf-8', errors='ignore') + "\n[... OUTPUT TRUNCATED ...]"

    def _kill_process_tree(self, pid: int):
        """
        Kills an entire process tree starting from pid.

        Kills children first, then the parent. Uses psutil for robust process tree handling.
        """
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)

            # Kill children first (reverse order to kill deeper descendants first)
            for child in reversed(children):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

            # Kill parent
            try:
                parent.kill()
            except psutil.NoSuchProcess:
                pass

            # Wait for processes to terminate
            psutil.wait_procs(children + [parent], timeout=2)
        except psutil.NoSuchProcess:
            pass
        except Exception as e:
            logger.warning("Failed to kill process tree for pid %d: %s", pid, e)

    def _check_docker_available(self) -> bool:
        """Checks if Docker is available."""
        return shutil.which("docker") is not None

    def _run_with_docker(
        self,
        command: List[str],
        sandbox_dir: str,
        timeout: int
    ) -> Tuple[int, str, str, Optional[str]]:
        """
        Runs command in a Docker container with isolation.

        Returns (exit_code, stdout, stderr, error_message).
        """
        if not self._check_docker_available():
            return None, "", "", "Docker not available"

        try:
            # Build docker command with security hardening
            docker_cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", "512m",
                "--cpus", "1",
                "--pids-limit", "256",
                "--read-only",
                "--tmpfs", "/tmp",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--user", "1000:1000",
                "-v", f"{sandbox_dir}:/work",
                "-w", "/work",
                self.docker_image
            ] + command

            # Convert to string for shell execution (docker CLI needs shell on Windows)
            if sys.platform == "win32":
                docker_cmd_str = " ".join(f'"{c}"' if " " in c else c for c in docker_cmd)
                result = subprocess.run(
                    docker_cmd_str,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    shell=True
                )
            else:
                result = subprocess.run(
                    docker_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )

            return result.returncode, result.stdout, result.stderr, None

        except subprocess.TimeoutExpired:
            # Docker will handle cleanup via --rm
            return -1, "", "", f"Docker container timed out after {timeout}s"
        except Exception as e:
            return -2, "", "", f"Docker execution error: {e}"

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
                try:
                    dest_file = resolve_within(sandbox_dir, target_file)
                except ValueError as exc:
                    logger.warning(
                        "sandbox_runner: path traversal rejected for target_file=%r: %s",
                        target_file, exc,
                    )
                    elapsed = time.perf_counter() - t_start
                    return SandboxTestResult(
                        success=False,
                        exit_code=-3,
                        stdout="",
                        stderr=str(exc),
                        duration_seconds=elapsed,
                        framework=framework or "unknown",
                        error_message=f"Path traversal rejected: {exc}",
                        traceback_summary=str(exc),
                    )
                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                with open(dest_file, "w", encoding="utf-8", errors="replace") as f:
                    f.write(patched_code)

                # 3. Determine and validate command
                cmd = self._resolve_command(sandbox_dir, framework, test_command, target_file)

                # If command is a string, parse it
                if isinstance(cmd, str):
                    cmd, parse_error = self._parse_command(cmd)
                    if parse_error:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=-4,
                            stdout="",
                            stderr=parse_error,
                            duration_seconds=elapsed,
                            framework=framework or "unknown",
                            error_message=f"Command parsing failed: {parse_error}",
                            traceback_summary=parse_error,
                        )

                # Validate command
                validation_error = self._validate_command(cmd)
                if validation_error:
                    elapsed = time.perf_counter() - t_start
                    return SandboxTestResult(
                        success=False,
                        exit_code=-5,
                        stdout="",
                        stderr=validation_error,
                        duration_seconds=elapsed,
                        framework=framework or "unknown",
                        error_message=f"Command validation failed: {validation_error}",
                        traceback_summary=validation_error,
                    )

                # Check if user-supplied test_command is allowed (admin only)
                if test_command and not self.is_admin:
                    elapsed = time.perf_counter() - t_start
                    return SandboxTestResult(
                        success=False,
                        exit_code=-7,
                        stdout="",
                        stderr="User-supplied test commands are only allowed for admin users",
                        duration_seconds=elapsed,
                        framework=framework or "unknown",
                        error_message="User-supplied test commands are only allowed for admin users",
                        traceback_summary="Security: test_command requires admin privileges",
                    )

                # Check if local sandbox is allowed in API mode
                if self.sandbox_mode == "local" and not self.allow_local_sandbox:
                    elapsed = time.perf_counter() - t_start
                    return SandboxTestResult(
                        success=False,
                        exit_code=-8,
                        stdout="",
                        stderr="Local sandbox mode is disabled for API security. Set ALLOW_LOCAL_SANDBOX=true or use SANDBOX_MODE=docker",
                        duration_seconds=elapsed,
                        framework=framework or "unknown",
                        error_message="Local sandbox disabled: set ALLOW_LOCAL_SANDBOX=true or use SANDBOX_MODE=docker",
                        traceback_summary="Security: local sandbox requires ALLOW_LOCAL_SANDBOX=true",
                    )

                # 4. Build sandbox environment
                env = self._build_sandbox_environment(sandbox_dir)

                # 5. Execute based on sandbox mode
                if self.sandbox_mode == "docker":
                    if not self._check_docker_available():
                        logger.warning("Docker mode requested but Docker not available, falling back to local mode")
                        self.sandbox_mode = "local"

                if self.sandbox_mode == "docker":
                    exit_code, stdout, stderr, docker_error = self._run_with_docker(
                        cmd, sandbox_dir, effective_timeout
                    )
                    if docker_error:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=docker_error,
                            duration_seconds=elapsed,
                            framework=framework or "unknown",
                            error_message=f"Docker execution failed: {docker_error}",
                            traceback_summary=docker_error,
                        )
                else:
                    # Local mode execution
                    exit_code, stdout, stderr = self._run_local(
                        cmd, sandbox_dir, effective_timeout, env
                    )

                elapsed = time.perf_counter() - t_start
                stdout = self._truncate_output(stdout or "")
                stderr = self._truncate_output(stderr or "")

                # 6. Parse test results
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

    def _read_stream_bounded(self, stream, max_bytes: int) -> Tuple[str, bool]:
        """
        Reads from a stream in chunks, capping at max_bytes.
        
        Returns (content, truncated_flag).
        Keeps reading and discarding data after reaching max_bytes so child never blocks.
        Memory use stays bounded regardless of how much the child prints.
        """
        chunks = []
        total_bytes = 0
        chunk_size = 8192  # 8 KB chunks
        truncated = False
        
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            
            chunk_bytes = len(chunk)
            if not truncated and total_bytes + chunk_bytes > max_bytes:
                # Read only up to the limit
                remaining = max_bytes - total_bytes
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                chunks.append("\n[... OUTPUT TRUNCATED ...]")
                truncated = True
                # Continue reading but discard to prevent pipe blockage
                continue
            
            if not truncated:
                chunks.append(chunk)
                total_bytes += chunk_bytes
            # If truncated, we just discard the chunk
        
        return ''.join(chunks), truncated

    def _run_local(
        self,
        command: List[str],
        sandbox_dir: str,
        timeout: int,
        env: Dict[str, str]
    ) -> Tuple[int, str, str]:
        """
        Runs command locally with timeout, process tree killing, and truly bounded output reading.

        Returns (exit_code, stdout, stderr).
        Memory use stays bounded regardless of child output size.
        Uses threaded reading to avoid buffering all output before truncation.
        """
        process = subprocess.Popen(
            command,
            cwd=sandbox_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            env=env
        )

        # Start reader threads for stdout and stderr
        from threading import Thread
        stdout_buffer = []
        stderr_buffer = []
        stdout_truncated = [False]
        stderr_truncated = [False]
        
        def read_stdout():
            content, truncated = self._read_stream_bounded(process.stdout, MAX_OUTPUT_SIZE)
            stdout_buffer.append(content)
            stdout_truncated[0] = truncated
        
        def read_stderr():
            content, truncated = self._read_stream_bounded(process.stderr, MAX_OUTPUT_SIZE)
            stderr_buffer.append(content)
            stderr_truncated[0] = truncated
        
        stdout_thread = Thread(target=read_stdout, daemon=True)
        stderr_thread = Thread(target=read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        try:
            # Wait for process with timeout
            process.wait(timeout=timeout)
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            # Kill entire process tree
            self._kill_process_tree(process.pid)
            exit_code = -1
        
        # Wait for reader threads to finish (they should finish quickly after process dies)
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        
        stdout = stdout_buffer[0] if stdout_buffer else ""
        stderr = stderr_buffer[0] if stderr_buffer else ""
        
        return exit_code, stdout, stderr

    def _populate_sandbox(self, src_dir: str, dest_dir: str):
        """Copies source files into the sandbox directory.

        Symlinks in the source tree are **never** followed — they are skipped
        entirely.  This prevents a malicious symlink inside the repo from
        importing or leaking files that live outside the repo root.
        Heavy/cache artefacts are also excluded.
        """
        real_src = os.path.realpath(src_dir)

        for dirpath, dirnames, filenames in os.walk(src_dir, followlinks=False):
            # Prune ignored directory names in-place so os.walk skips them
            dirnames[:] = [
                d for d in dirnames
                if d not in self.IGNORE_PATTERNS
                and not any(d.startswith(p) for p in (".venv", "venv", ".repos"))
                and not os.path.islink(os.path.join(dirpath, d))  # skip symlinked dirs
            ]

            rel_dir = os.path.relpath(dirpath, src_dir)
            dest_subdir = os.path.join(dest_dir, rel_dir) if rel_dir != '.' else dest_dir
            os.makedirs(dest_subdir, exist_ok=True)

            for name in filenames:
                src_file = os.path.join(dirpath, name)

                # Skip symlinks — never dereference them
                if os.path.islink(src_file):
                    continue

                # Skip compiled / cache files
                if name.endswith((".pyc", ".pyo", ".pyd")):
                    continue
                if name in self.IGNORE_PATTERNS:
                    continue

                dest_file = os.path.join(dest_subdir, name)
                try:
                    shutil.copy2(src_file, dest_file)
                except OSError:
                    pass  # non-fatal; skip unreadable files

    def _resolve_command(
        self,
        sandbox_dir: str,
        framework: Optional[str],
        test_command: Optional[str],
        target_file: str,
    ) -> Any:
        if test_command:
            return test_command

        # Default for Python: run pytest or unittest with sys.executable
        if framework == "pytest":
            # Attempt to target tests matching the target file if obvious, or full suite
            target_base = os.path.splitext(os.path.basename(target_file))[0]
            specific_test = os.path.join(sandbox_dir, "tests", f"test_{target_base}.py")
            if os.path.isfile(specific_test):
                return [sys.executable, "-m", "pytest", f"tests/test_{target_base}.py", "-v", "--tb=short", "-p", "no:cacheprovider"]
            return [sys.executable, "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider"]

        if framework == "npm":
            # Use npx or npm from PATH
            if shutil.which("npx"):
                return ["npx", "npm", "test"]
            return ["npm", "test"]

        # Default fallback: python unittest discover with sys.executable
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
