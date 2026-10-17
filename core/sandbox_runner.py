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
import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import math
import sys
import time
import uuid
import psutil
from typing import List, Optional, Dict, Any, Tuple, Union

from core.safe_paths import resolve_within

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT: int = 30


def validate_timeout(timeout: Any, name: str = "timeout") -> int:
    """
    Validates that a timeout value is positive numeric (int or float) and returns it as int.
    Rejects booleans, non-numeric values, <= 0, NaN, and infinity with a clear ValueError.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError(
            f"Invalid {name}: must be a positive integer or float, got {type(timeout).__name__} ({timeout!r})"
        )
    if math.isnan(timeout) or math.isinf(timeout) or timeout <= 0:
        raise ValueError(
            f"Invalid {name}: must be a positive number greater than 0, got {timeout}"
        )
    return int(timeout)

# Maximum output size in bytes (1 MB)
MAX_OUTPUT_SIZE = 1024 * 1024

# Allowlisted environment variables (case-insensitive)
ENV_ALLOWLIST = {
    "PATH", "SYSTEMROOT", "TEMP", "TMP", "COMSPEC", "PATHEXT",
    "LANG", "LC_ALL", "HOME", "USERPROFILE", "PYTHONPATH",
    "PYTHONDONTWRITEBYTECODE", "APPDATA", "NODE_PATH",
    "JAVA_HOME", "CLASSPATH", "JUNIT_PLATFORM_JAR",
    "CMAKE_BUILD_TYPE", "CC", "CXX", "CFLAGS", "CXXFLAGS",
    "GOCACHE", "GOPATH", "GOPROXY", "GOTOOLCHAIN", "GONOSUMDB",
    "CGO_ENABLED", "GOTMPDIR",
    "CARGO_NET_OFFLINE", "CARGO_TERM_COLOR", "CARGO_HOME",
    "CARGO_TARGET_DIR", "RUSTFLAGS", "RUST_BACKTRACE"
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
    "tsc", "tsc.exe", "tsc.cmd",
    "javac", "javac.exe",
    "java", "java.exe",
    "jar", "jar.exe",
    "cmake", "cmake.exe",
    "ctest", "ctest.exe",
    "make", "make.exe",
    "ninja", "ninja.exe",
    "gcc", "gcc.exe",
    "g++", "g++.exe",
    "go", "go.exe",
    "cargo", "cargo.exe",
    "rustc", "rustc.exe",
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
    collection_errors: List[str] = dataclasses.field(default_factory=list)
    traceback_summary: str = ""
    error_message: Optional[str] = None
    skipped: bool = False
    test_command: Optional[List[str]] = None
    working_dir: Optional[str] = None
    patched_file_path: Optional[str] = None
    container_name: Optional[str] = None

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
        "dist", "build", "coverage", ".coverage", "*.pyc", "*.pyo",
        "target"
    }

    def __init__(
        self,
        default_timeout: Optional[Union[int, float]] = None,
        sandbox_mode: str = "local",
        docker_image: str = "python:3.11-slim",
        allow_local_sandbox: bool = True,
        is_admin: bool = False,
    ):
        if default_timeout is not None:
            self.default_timeout = validate_timeout(default_timeout, "default_timeout")
            self._explicit_default_timeout = True
        else:
            self.default_timeout = DEFAULT_TIMEOUT
            self._explicit_default_timeout = False
        self.sandbox_mode = sandbox_mode
        self.docker_image = docker_image
        self.allow_local_sandbox = allow_local_sandbox
        self.is_admin = is_admin
        self.last_container_name: Optional[str] = None

    @staticmethod
    def _collect_test_file_hashes(sandbox_dir: str) -> Dict[str, str]:
        hashes = {}
        for root, _, files in os.walk(sandbox_dir):
            for f in files:
                fl = f.lower()
                if fl.startswith("test") or fl.endswith("_test.py") or fl.endswith(".test.js") or fl.endswith(".test.ts") or fl.endswith("_test.go"):
                    fp = os.path.join(root, f)
                    try:
                        with open(fp, "rb") as fh:
                            hashes[fp] = hashlib.sha256(fh.read()).hexdigest()
                    except OSError:
                        pass
        return hashes

    @staticmethod
    def _verify_test_files_immutable(initial_hashes: Dict[str, str]) -> Tuple[bool, Optional[str]]:
        for fp, pre_hash in initial_hashes.items():
            if not os.path.isfile(fp):
                return False, f"Test file immutability violation: test file '{os.path.basename(fp)}' was deleted during test execution."
            try:
                with open(fp, "rb") as f:
                    post_hash = hashlib.sha256(f.read()).hexdigest()
                if post_hash != pre_hash:
                    return False, f"Test file immutability violation: test file '{os.path.basename(fp)}' was modified during test execution (hash mismatch)."
            except OSError as e:
                return False, f"Could not read test file '{os.path.basename(fp)}': {e}"
        return True, None


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

        # Set Go safe defaults
        env.setdefault("GOCACHE", "/tmp/go-cache")
        env.setdefault("GOPATH", "/tmp/go-path")
        env.setdefault("GOPROXY", "off")
        env.setdefault("GOTOOLCHAIN", "local")
        env.setdefault("GONOSUMDB", "*")
        env.setdefault("CGO_ENABLED", "0")
        env.setdefault("GOTMPDIR", "/tmp/gotmp")

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

        # Resolve executable with shutil.which to ensure it exists on host when running locally
        if self.sandbox_mode != "docker":
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

    @staticmethod
    def _check_docker_available() -> bool:
        """Checks if Docker CLI is installed and the Docker daemon is responsive."""
        if shutil.which("docker") is None:
            return False
        try:
            res = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return res.returncode == 0 and bool(res.stdout.strip())
        except Exception:
            return False

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
            return None, "", "", "Docker not available: daemon is not running"

        try:
            # Sanitize command for Linux container execution:
            # 1. Replace Windows host Python paths with container Python executable
            # 2. Normalize Windows backslashes in argument paths to POSIX forward slashes
            container_cmd = []
            for idx, arg in enumerate(command):
                if idx == 0:
                    base_exe = os.path.basename(arg).lower()
                    if base_exe in ("python.exe", "python3.exe", "python", "python3") or arg == sys.executable:
                        container_cmd.append("python")
                    elif base_exe in ("pytest.exe", "pytest"):
                        container_cmd.extend(["python", "-m", "pytest"])
                    elif base_exe in ("node.exe", "node"):
                        container_cmd.append("node")
                    elif base_exe in ("npm.exe", "npm"):
                        container_cmd.append("npm")
                    elif base_exe in ("npx.exe", "npx"):
                        container_cmd.append("npx")
                    elif base_exe in ("tsc.exe", "tsc", "tsc.cmd"):
                        container_cmd.append("tsc")
                    elif base_exe in ("javac.exe", "javac"):
                        container_cmd.append("javac")
                    elif base_exe in ("java.exe", "java"):
                        container_cmd.append("java")
                    elif base_exe in ("jar.exe", "jar"):
                        container_cmd.append("jar")
                    elif base_exe in ("cmake.exe", "cmake"):
                        container_cmd.append("cmake")
                    elif base_exe in ("ctest.exe", "ctest"):
                        container_cmd.append("ctest")
                    elif base_exe in ("make.exe", "make"):
                        container_cmd.append("make")
                    elif base_exe in ("ninja.exe", "ninja"):
                        container_cmd.append("ninja")
                    elif base_exe in ("gcc.exe", "gcc"):
                        container_cmd.append("gcc")
                    elif base_exe in ("g++.exe", "g++"):
                        container_cmd.append("g++")
                    elif base_exe in ("go.exe", "go"):
                        container_cmd.append("go")
                    elif base_exe in ("cargo.exe", "cargo"):
                        container_cmd.append("cargo")
                    elif base_exe in ("rustc.exe", "rustc"):
                        container_cmd.append("rustc")
                    else:
                        container_cmd.append(arg)
                else:
                    norm_arg = arg.replace("\\", "/")
                    if idx > 0 and command[idx - 1] in ("-cp", "-classpath", "--class-path"):
                        norm_arg = norm_arg.replace(";", ":")
                    container_cmd.append(norm_arg)

            container_name = f"icx-sandbox-{uuid.uuid4().hex[:12]}"
            self.last_container_name = container_name
            # Build docker command with security hardening
            docker_cmd = [
                "docker", "run", "--rm",
                "--name", container_name,
                "--network", "none",
                "--memory", "512m",
                "--cpus", "1",
                "--pids-limit", "256",
                "--read-only",
                "--tmpfs", "/tmp",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--user", "1000:1000",
                "-e", "PYTHONPATH=/work",
                "-e", "NODE_PATH=/usr/local/lib/node_modules",
                "-e", "JUNIT_PLATFORM_JAR=/usr/local/lib/junit-platform-console-standalone.jar",
                "-e", "GOCACHE=/tmp/go-cache",
                "-e", "GOPATH=/tmp/go-path",
                "-e", "GOPROXY=off",
                "-e", "GOTOOLCHAIN=local",
                "-e", "GONOSUMDB=*",
                "-e", "CGO_ENABLED=0",
                "-e", "GOTMPDIR=/tmp/gotmp",
                "-e", "CARGO_NET_OFFLINE=true",
                "-e", "CARGO_TERM_COLOR=never",
                "-e", "CARGO_HOME=/tmp/cargo-home",
                "-e", "CARGO_TARGET_DIR=/work/target",
                "-e", "RUST_BACKTRACE=1",
                "-v", f"{sandbox_dir}:/work",
                "-w", "/work",
                self.docker_image
            ] + container_cmd

            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout
            )

            # Check for infrastructure communication error from Docker CLI
            if result.returncode != 0 and (
                "error during connect" in (result.stderr or "").lower()
                or "cannot connect to the docker daemon" in (result.stderr or "").lower()
                or "daemon is not running" in (result.stderr or "").lower()
            ):
                return result.returncode, result.stdout, result.stderr, f"Docker daemon communication error: {result.stderr.strip()}"

            return result.returncode, result.stdout, result.stderr, None

        except subprocess.TimeoutExpired:
            # Explicitly force-kill and remove the container to ensure no orphaned test container remains running
            try:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=5)
            except Exception:
                pass
            return -1, "", "", f"Docker container timed out after {timeout}s"
        except Exception as e:
            return -2, "", "", f"Docker execution error: {e}"

    def detect_runtime(self, repo_path: str, target_file: Optional[str] = None) -> str:
        """Determines the programming runtime (python, javascript, typescript, java, c, cpp)."""
        if target_file:
            ext = os.path.splitext(target_file)[1].lower()
            if ext in (".ts", ".tsx"):
                return "typescript"
            if ext in (".js", ".jsx", ".mjs", ".cjs"):
                return "javascript"
            if ext in (".java",):
                return "java"
            if ext in (".cpp", ".cxx", ".cc", ".hpp"):
                return "cpp"
            if ext in (".c",):
                return "c"
            if ext in (".go",):
                return "go"
            if ext in (".rs",):
                return "rust"
            if ext in (".h",):
                has_cpp = False
                try:
                    for root, _, files in os.walk(repo_path):
                        if any(ignored in root for ignored in (".git", ".venv", "venv", ".repos", "node_modules", "target", "build")):
                            continue
                        if any(f.endswith((".cpp", ".cxx", ".cc", ".hpp")) for f in files):
                            has_cpp = True
                            break
                except Exception:
                    pass
                return "cpp" if has_cpp else "c"
            if ext in (".py", ".pyw"):
                return "python"

        has_ts = False
        has_js = False
        has_java = False
        has_cpp = False
        has_c = False
        has_go = False
        has_rust = False
        try:
            for root, _, files in os.walk(repo_path):
                if any(ignored in root for ignored in (".git", ".venv", "venv", ".repos", "node_modules", "target", "build")):
                    continue
                for f in files:
                    if f.endswith((".ts", ".tsx")) or f == "tsconfig.json":
                        has_ts = True
                        break
                    elif f.endswith((".js", ".jsx", ".mjs", ".cjs")) or f == "package.json":
                        has_js = True
                    elif f.endswith(".java") or f in ("pom.xml", "build.gradle"):
                        has_java = True
                    elif f.endswith((".cpp", ".cxx", ".cc", ".hpp")):
                        has_cpp = True
                    elif f.endswith((".c", ".h")):
                        has_c = True
                    elif f.endswith(".go") or f == "go.mod":
                        has_go = True
                    elif f.endswith(".rs") or f == "Cargo.toml":
                        has_rust = True
                if has_ts:
                    break
        except Exception:
            pass

        if has_ts:
            return "typescript"
        if has_js:
            return "javascript"
        if has_java:
            return "java"
        if has_cpp:
            return "cpp"
        if has_c:
            return "c"
        if has_go:
            return "go"
        if has_rust:
            return "rust"
        return "python"

    def detect_test_framework(
        self,
        repo_path: str,
        target_file: Optional[str] = None,
        runtime: Optional[str] = None,
    ) -> Optional[str]:
        """Detects test framework available in the target repository for the given runtime."""
        if not os.path.isdir(repo_path):
            return None

        rt = runtime or self.detect_runtime(repo_path, target_file)

        if rt in ("c", "cpp"):
            if os.path.isfile(os.path.join(repo_path, "CMakeLists.txt")):
                return "ctest"
            return None

        if rt == "go":
            if os.path.isfile(os.path.join(repo_path, "go.mod")):
                return "go_test"
            has_go_tests = False
            try:
                for root, _, files in os.walk(repo_path):
                    if any(ignored in root for ignored in (".git", "vendor", ".gotmp")):
                        continue
                    if any(f.endswith("_test.go") for f in files):
                        has_go_tests = True
                        break
            except Exception:
                pass
            if has_go_tests:
                return "go_test"
            return None

        if rt == "rust":
            if os.path.isfile(os.path.join(repo_path, "Cargo.toml")):
                return "cargo"
            has_rust_tests = False
            try:
                for root, _, files in os.walk(repo_path):
                    if any(ignored in root for ignored in (".git", "target")):
                        continue
                    if any(f.endswith(".rs") for f in files):
                        has_rust_tests = True
                        break
            except Exception:
                pass
            if has_rust_tests:
                return "cargo"
            return None

        if rt == "typescript":
            return "typescript"

        if rt in ("javascript", "node"):
            # Check for node test files
            has_node_tests = False
            try:
                for root, _, files in os.walk(repo_path):
                    if any(ignored in root for ignored in (".git", ".venv", "venv", ".repos", "node_modules")):
                        continue
                    if any(
                        f.endswith((".test.js", ".spec.js", "_test.js"))
                        or (os.path.basename(root) in ("test", "tests") and f.endswith(".js"))
                        for f in files
                    ):
                        has_node_tests = True
                        break
            except Exception:
                pass
            if has_node_tests:
                return "node_test"

            pkg_json = os.path.join(repo_path, "package.json")
            if os.path.isfile(pkg_json):
                try:
                    with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                        if '"test"' in f.read():
                            return "npm"
                except Exception:
                    pass
            return "node_test"

        if rt == "java":
            has_java_tests = False
            try:
                for root, _, files in os.walk(repo_path):
                    if any(ignored in root for ignored in (".git", "target", "build", ".gradle", ".repos")):
                        continue
                    root_base = os.path.basename(root).lower()
                    if any(
                        f.endswith(("Test.java", "Tests.java", "TestCase.java"))
                        or f.startswith("Test")
                        or "src/test/java" in root.replace("\\", "/")
                        or (root_base in ("test", "tests") and f.endswith(".java"))
                        for f in files
                    ):
                        has_java_tests = True
                        break
            except Exception:
                pass
            if has_java_tests:
                return "junit"
            return None

        # Python test framework detection (default)
        has_tests_dir = any(
            os.path.isdir(os.path.join(repo_path, d))
            for d in ("tests", "test", "testing", "src/tests")
        )
        has_pytest_config = any(
            os.path.isfile(os.path.join(repo_path, f))
            for f in ("pytest.ini", "setup.cfg", "pyproject.toml", "conftest.py")
        )
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

        pkg_json = os.path.join(repo_path, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, "r", encoding="utf-8", errors="ignore") as f:
                    if '"test"' in f.read():
                        return "npm"
            except Exception:
                pass

        return None

    def _execute_in_sandbox(
        self,
        cmd: List[str],
        sandbox_dir: str,
        timeout: int,
        env: Dict[str, str],
    ) -> Tuple[int, str, str, Optional[str]]:
        """Executes a command inside sandbox (docker or local) returning (exit_code, stdout, stderr, error_msg)."""
        if self.sandbox_mode == "docker":
            if not self._check_docker_available():
                return -8, "", "", "Docker mode requested but Docker daemon is unavailable: Docker Desktop / Linux daemon is not running."
            return self._run_with_docker(cmd, sandbox_dir, timeout)
        else:
            if not self.allow_local_sandbox:
                return -8, "", "", "Local sandbox mode is disabled for API security. Set ALLOW_LOCAL_SANDBOX=true or use SANDBOX_MODE=docker"
            exit_code, stdout, stderr = self._run_local(cmd, sandbox_dir, timeout, env)
            return exit_code, stdout, stderr, None

    def _parse_node_test_output(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """Parses Node.js built-in test runner output (TAP / spec reporter)."""
        combined = f"{stdout}\n{stderr}".strip()
        passed_tests = []
        failed_tests = []
        assertion_errors = []
        traceback_lines = []

        for line in stdout.splitlines():
            line_str = line.strip()
            # TAP format: 'ok 1 - test name', 'not ok 1 - test name'
            if re.match(r"^ok\s+\d+\s+-\s+(.+)$", line_str):
                name = re.sub(r"^ok\s+\d+\s+-\s+", "", line_str).split("#")[0].strip()
                passed_tests.append(name)
            elif re.match(r"^not ok\s+\d+\s+-\s+(.+)$", line_str):
                name = re.sub(r"^not ok\s+\d+\s+-\s+", "", line_str).split("#")[0].strip()
                failed_tests.append(name)
            # Spec / symbol format: '✔ test name', '✖ test name'
            elif line_str.startswith("✔ "):
                name = line_str[2:].split("(")[0].strip()
                passed_tests.append(name)
            elif line_str.startswith("✖ "):
                name = line_str[2:].split("(")[0].strip()
                failed_tests.append(name)

        pass_m = re.search(r"(?:#|ℹ)\s*pass(?:ed)?\s*(\d+)", stdout, re.IGNORECASE)
        fail_m = re.search(r"(?:#|ℹ)\s*fail(?:ed)?\s*(\d+)", stdout, re.IGNORECASE)
        tests_m = re.search(r"(?:#|ℹ)\s*tests\s*(\d+)", stdout, re.IGNORECASE)

        passed_count = int(pass_m.group(1)) if pass_m else len(passed_tests)
        failed_count = int(fail_m.group(1)) if fail_m else len(failed_tests)
        total_count = int(tests_m.group(1)) if tests_m else (passed_count + failed_count)

        in_failure_block = False
        for line in combined.splitlines():
            s = line.strip()
            if any(k in s for k in ("AssertionError", "ERR_ASSERTION", "error TS", "failureType:")):
                assertion_errors.append(s)
            if "not ok" in s or "✖" in s:
                in_failure_block = True
            if in_failure_block and s.startswith("stack:"):
                traceback_lines.append(s)

        if exit_code != 0 and failed_count == 0:
            failed_count = 1
            total_count = max(total_count, passed_count + failed_count)
            if not failed_tests:
                failed_tests.append("node_test_failure")

        traceback_summary = "\n".join(traceback_lines[:30]) if traceback_lines else combined[-1500:]

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "assertion_errors": assertion_errors[:10],
            "traceback_summary": traceback_summary,
        }

    def _parse_junit_output(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """Parses JUnit Platform Console Launcher output."""
        combined = f"{stdout}\n{stderr}".strip()
        passed_tests = []
        failed_tests = []
        assertion_errors = []
        traceback_lines = []

        # Parse summary counts from JUnit banner table
        found_m = re.search(r"\[\s*(\d+)\s+tests found\s*\]", combined, re.IGNORECASE)
        skipped_m = re.search(r"\[\s*(\d+)\s+tests skipped\s*\]", combined, re.IGNORECASE)
        aborted_m = re.search(r"\[\s*(\d+)\s+tests aborted\s*\]", combined, re.IGNORECASE)
        success_m = re.search(r"\[\s*(\d+)\s+tests successful\s*\]", combined, re.IGNORECASE)
        failed_m = re.search(r"\[\s*(\d+)\s+tests failed\s*\]", combined, re.IGNORECASE)

        passed_count = int(success_m.group(1)) if success_m else 0
        failed_count = int(failed_m.group(1)) if failed_m else 0
        skipped_count = int(skipped_m.group(1)) if skipped_m else 0
        aborted_count = int(aborted_m.group(1)) if aborted_m else 0
        total_count = int(found_m.group(1)) if found_m else (passed_count + failed_count + skipped_count + aborted_count)

        current_test = None
        current_class = None
        in_failure_trace = False

        for line in combined.splitlines():
            s = line.strip()
            if "[class:" in line:
                class_m = re.search(r"\[class:([^\]]+)\]", line)
                if class_m:
                    current_class = class_m.group(1)

            if "uniqueId:" in line and "/[method:" in line:
                method_m = re.search(r"/\[method:([^\]]+)\]", line)
                if method_m:
                    current_test = method_m.group(1)
            elif "├─ " in line or "│  ├─ " in line:
                node_name = re.sub(r"^[│\s├─\xa0\x82\x94\x1c]+", "", line).split()[0]
                if "(" in node_name:
                    current_test = node_name

            if "status:" in line:
                test_label = f"{current_class}#{current_test}" if current_class and current_test else (current_test or "test")
                if "SUCCESSFUL" in line:
                    if test_label not in passed_tests:
                        passed_tests.append(test_label)
                    in_failure_trace = False
                elif "FAILED" in line:
                    if test_label not in failed_tests:
                        failed_tests.append(test_label)
                    in_failure_trace = False
                elif "ABORTED" in line or "SKIPPED" in line:
                    in_failure_trace = False

            if "caught:" in line:
                in_failure_trace = True
                caught_err = line.split("caught:", 1)[1].strip()
                assertion_errors.append(caught_err)
                traceback_lines.append(line)
            elif in_failure_trace:
                if line.strip().startswith("at ") or "..." in line:
                    traceback_lines.append(line.strip())
                elif any(k in line for k in ("duration:", "status:", "Test plan", "Test run")):
                    in_failure_trace = False

            if any(k in s for k in ("AssertionFailedError", "AssertionError", "org.opentest4j", "ComparisonFailure")):
                if s not in assertion_errors:
                    assertion_errors.append(s)

        if exit_code != 0 and failed_count == 0 and passed_count == 0:
            failed_count = 1
            total_count = max(total_count, 1)
            if not failed_tests:
                failed_tests.append("junit_execution_failure")

        traceback_summary = "\n".join(traceback_lines[:40]) if traceback_lines else combined[-1500:]

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "aborted_count": aborted_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "assertion_errors": assertion_errors[:10],
            "traceback_summary": traceback_summary,
        }

    def _parse_ctest_output(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """Parses CTest console output."""
        combined = f"{stdout}\n{stderr}".strip()
        passed_tests = []
        failed_tests = []
        assertion_errors = []
        traceback_lines = []
        skipped_count = 0

        # Match summary line: e.g. "100% tests passed, 0 tests failed out of 2"
        # or "50% tests passed, 1 tests failed out of 2"
        summary_m = re.search(
            r"(\d+)%\s+tests\s+passed,\s+(\d+)\s+tests\s+failed\s+out\s+of\s+(\d+)",
            combined,
            re.IGNORECASE,
        )
        if summary_m:
            failed_count = int(summary_m.group(2))
            total_count = int(summary_m.group(3))
            passed_count = total_count - failed_count
        else:
            passed_count = 0
            failed_count = 0
            total_count = 0

        # Parse individual test results:
        # "1/2 Test #1: test_happy ....................   Passed    0.01 sec"
        # "2/2 Test #2: test_reproduce ................***Failed    0.02 sec"
        # "2/2 Test #2: test_crash ....................***Exception: Other Failure  0.01 sec"
        # "1/1 Test #1: test_skip .....................***Skipped   0.00 sec"
        for line in combined.splitlines():
            line_str = line.strip()
            test_m = re.search(
                r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(\S+)\s+\.+\s*(\S[^\n]*)",
                line_str
            )
            if test_m:
                tname = test_m.group(1)
                tstatus = test_m.group(2).strip()
                if "Passed" in tstatus:
                    if tname not in passed_tests:
                        passed_tests.append(tname)
                elif "Failed" in tstatus or "Exception" in tstatus or "Timeout" in tstatus:
                    if tname not in failed_tests:
                        failed_tests.append(tname)
                elif "Skipped" in tstatus:
                    skipped_count += 1

            # Look for assertion failures, crashes, signals
            if any(k in line_str for k in (
                "Assertion failed:", "assert failed", "Assertion `", "assert:",
                "SIGSEGV", "Segmentation fault", "SIGABRT", "Aborted", "core dumped",
                "***Exception:", "***Failed", "***Timeout", "Child aborted", "Subprocess aborted", "Subprocess killed"
            )):
                if line_str not in assertion_errors:
                    assertion_errors.append(line_str)
                traceback_lines.append(line_str)

        # In "The following tests FAILED:" block:
        # 	  2 - test_reproduce (Failed)
        in_failed_block = False
        for line in combined.splitlines():
            if "The following tests FAILED:" in line:
                in_failed_block = True
                continue
            if in_failed_block:
                m = re.match(r"^\s*\d+\s+-\s+(\S+)\s+\(([^)]+)\)", line)
                if m:
                    f_name = m.group(1)
                    if f_name not in failed_tests:
                        failed_tests.append(f_name)
                elif line.strip() and not line.startswith("\t") and not line.startswith(" "):
                    in_failed_block = False

        # Check for "No tests were found!!!"
        if "no tests were found" in combined.lower():
            total_count = 0
            passed_count = 0
            failed_count = 0

        if not summary_m and (passed_tests or failed_tests or skipped_count):
            passed_count = len(passed_tests)
            failed_count = len(failed_tests)
            total_count = passed_count + failed_count + skipped_count

        if exit_code != 0 and failed_count == 0 and passed_count == 0:
            failed_count = 1
            total_count = max(total_count, 1)
            if not failed_tests:
                failed_tests.append("ctest_execution_failure")

        traceback_summary = "\n".join(traceback_lines[:40]) if traceback_lines else combined[-1500:]

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "assertion_errors": assertion_errors[:10],
            "traceback_summary": traceback_summary,
        }

    def _parse_go_test_output(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """
        Parses structured JSON stream output from `go test -count=1 -json ./...`.

        Counting convention:
        - Parent tests with subtests (e.g. TestAdd when TestAdd/sub1 and TestAdd/sub2 exist)
          are tracked as parent suites and are NOT double-counted.
        - Only leaf test executions (individual leaf subtests and top-level tests without subtests)
          contribute to passed_count, failed_count, and skipped_count.
        - Captures panics, individual test assertion errors, build-failures, and package-level failures.
        """
        import json

        events = []
        malformed_lines = []
        for line in stdout.splitlines():
            line_s = line.strip()
            if not line_s:
                continue
            try:
                events.append(json.loads(line_s))
            except Exception:
                malformed_lines.append(line_s)

        build_errors = []
        test_outputs = {}   # (pkg, test) -> list of output strings
        pkg_outputs = {}    # pkg -> list of output strings
        test_actions = {}   # (pkg, test) -> terminal action ("pass", "fail", "skip")
        pkg_actions = {}    # pkg -> terminal action
        panics = []

        started_tests = set()
        completed_tests = set()

        for ev in events:
            action = ev.get("Action", "")
            pkg = ev.get("Package", "")
            test = ev.get("Test", "")
            output = ev.get("Output", "")

            if action in ("build-output", "build-fail"):
                if output:
                    build_errors.append(output.strip())
            elif "FailedBuild" in ev:
                build_errors.append(f"Failed build: {ev['FailedBuild']}")

            if test:
                key = (pkg, test)
                if action == "run":
                    started_tests.add(key)
                if output:
                    test_outputs.setdefault(key, []).append(output)
                    if "--- FAIL:" in output or "panic:" in output or "[signal SIG" in output:
                        test_actions[key] = "fail"
                    if "panic:" in output or "[signal SIG" in output:
                        panics.append(output.strip())
                if action in ("pass", "fail", "skip"):
                    test_actions[key] = action
                    completed_tests.add(key)
            elif pkg:
                if output:
                    pkg_outputs.setdefault(pkg, []).append(output)
                if action in ("pass", "fail", "skip"):
                    pkg_actions[pkg] = action

        # Flag any test that started but never completed (abrupt crash/truncation)
        incomplete_tests = started_tests - completed_tests
        for key in incomplete_tests:
            test_actions[key] = "fail"
            test_outputs.setdefault(key, []).append("Test started but terminated abruptly without completing\n")

        # Determine leaf tests to avoid double-counting parent tests and subtests
        all_tests = set(test_actions.keys())
        parent_tests = set()
        for (pkg, t) in all_tests:
            prefix = t + "/"
            if any(other_pkg == pkg and other_t != t and other_t.startswith(prefix) for (other_pkg, other_t) in all_tests):
                parent_tests.add((pkg, t))

        leaf_tests = all_tests - parent_tests

        passed_tests = []
        failed_tests = []
        skipped_tests = []
        assertion_errors = []

        # Tally leaf tests for pass/fail/skip counts
        for (pkg, t) in sorted(leaf_tests):
            act = test_actions.get((pkg, t), "")
            test_display = f"{pkg}.{t}" if pkg else t
            if act == "pass":
                passed_tests.append(test_display)
            elif act == "fail":
                failed_tests.append(test_display)
                outs = test_outputs.get((pkg, t), [])
                for out in outs:
                    for o_line in out.splitlines():
                        o_s = o_line.strip()
                        if o_s and not o_s.startswith("=== RUN") and not o_s.startswith("--- FAIL"):
                            assertion_errors.append(o_s)
            elif act == "skip":
                skipped_tests.append(test_display)

        # Preserve parent-test failures even though only leaf tests contribute to displayed counts
        for (pkg, t) in sorted(parent_tests):
            if test_actions.get((pkg, t)) == "fail":
                parent_display = f"{pkg}.{t}" if pkg else t
                if parent_display not in failed_tests:
                    failed_tests.append(parent_display)
                for out in test_outputs.get((pkg, t), []):
                    for o_line in out.splitlines():
                        o_s = o_line.strip()
                        if o_s and not o_s.startswith("=== RUN") and not o_s.startswith("--- FAIL"):
                            assertion_errors.append(o_s)

        if panics:
            assertion_errors.extend(panics[:5])

        # Preserve package-level failures (e.g. init failure or aborted run)
        for pkg, act in pkg_actions.items():
            if act == "fail":
                has_failed_test = any(ft.startswith(f"{pkg}.") for ft in failed_tests)
                if not has_failed_test:
                    failed_tests.append(f"{pkg}.package")
                    for out in pkg_outputs.get(pkg, []):
                        for o_line in out.splitlines():
                            o_s = o_line.strip()
                            if o_s and not o_s.startswith("FAIL\t"):
                                assertion_errors.append(o_s)

        # Abrupt process termination with non-zero exit code must not pass
        if exit_code != 0 and not failed_tests:
            failed_tests.append("process_exit_failure")

        # Malformed lines indicate truncated stream
        if malformed_lines and not failed_tests:
            failed_tests.append("malformed_output")

        # Check for build/compile errors from compiler or stderr
        if build_errors or (exit_code != 0 and not passed_tests):
            for line in (stderr or "").splitlines():
                line_s = line.strip()
                if any(k in line_s.lower() for k in ("cannot find", "undefined:", "syntax error", "no required module", "error:")):
                    build_errors.append(line_s)
            if not failed_tests:
                failed_tests.append("compilation")
            assertion_errors = build_errors[:10] + assertion_errors

        passed_count = len(passed_tests)
        failed_count = len(failed_tests)
        skipped_count = len(skipped_tests)
        total_count = passed_count + failed_count + skipped_count

        traceback_summary = (
            "\n".join(assertion_errors[:20])
            if assertion_errors
            else (stderr.strip()[:1000] if stderr else "")
        )

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "skipped_tests": skipped_tests,
            "assertion_errors": assertion_errors[:10],
            "traceback_summary": traceback_summary,
            "parent_tests": [f"{p}.{t}" for (p, t) in parent_tests],
            "malformed_lines": malformed_lines,
            "malformed_json": bool(malformed_lines),
            "incomplete_stream": bool(incomplete_tests),
        }

    def _parse_cargo_test_output(self, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
        """
        Parses test results from Cargo test runs (`cargo test --tests`).

        - Aggregates multi-target test executions (e.g. unit tests in src/ and integration tests in tests/).
        - Parses individual test outcomes: 'test <name> ... ok|FAILED|ignored'.
        - Captures panic backtraces ('thread ... panicked at ...') and assertion messages.
        - Captures compiler errors (error[E...], rustc build errors, missing offline dependencies).
        - Detects incomplete target execution streams and unhandled failures.
        - Supports #[should_panic] which libtest reports as 'ok' on panic and 'FAILED' on non-panic.
        """
        combined = f"{stdout}\n{stderr}".strip()
        passed_tests = []
        failed_tests = []
        ignored_tests = []
        assertion_errors = []
        build_errors = []
        panics = []

        target_summaries = []
        targets_started = []
        current_target = "unit"

        target_header_re = re.compile(r"^\s*Running\s+(?:unittests\s+)?([^\s(]+)")
        running_tests_re = re.compile(r"^\s*running\s+(\d+)\s+tests?")
        test_line_re = re.compile(r"^test\s+([^\s]+)(?:\s+-\s+should\s+panic)?\s+\.\.\.\s+(ok|FAILED|ignored)")
        test_result_re = re.compile(
            r"^test result:\s*(ok|FAILED)\.\s*(\d+)\s+passed;\s*(\d+)\s+failed;\s*(\d+)\s+ignored;"
        )

        captured_traceback = []

        for line in stdout.splitlines():
            line_s = line.strip()
            if not line_s:
                continue

            m_target = target_header_re.search(line_s)
            if m_target:
                current_target = m_target.group(1).replace("\\", "/")

            m_running = running_tests_re.search(line_s)
            if m_running:
                targets_started.append({"target": current_target, "declared": int(m_running.group(1))})

            m_test = test_line_re.match(line_s)
            if m_test:
                test_name = m_test.group(1)
                status = m_test.group(2)
                full_test_name = f"{current_target}::{test_name}" if current_target != "unit" else test_name
                if status == "ok":
                    passed_tests.append(full_test_name)
                elif status == "FAILED":
                    failed_tests.append(full_test_name)
                elif status == "ignored":
                    ignored_tests.append(full_test_name)
                continue

            m_res = test_result_re.search(line_s)
            if m_res:
                status = m_res.group(1)
                p_cnt = int(m_res.group(2))
                f_cnt = int(m_res.group(3))
                i_cnt = int(m_res.group(4))
                target_summaries.append({
                    "target": current_target,
                    "status": status,
                    "passed": p_cnt,
                    "failed": f_cnt,
                    "ignored": i_cnt,
                })
                continue

            if "note: test did not panic as expected" in line_s:
                assertion_errors.append(line_s)
                captured_traceback.append(line_s)

        for line in combined.splitlines():
            line_s = line.strip()
            if not line_s:
                continue

            if (
                re.match(r"^error(?:\[E\d+\])?:", line_s)
                or line_s.startswith("could not compile")
                or "offline mode is enabled" in line_s
                or "no matching package named" in line_s
                or "cannot find crate" in line_s
            ):
                build_errors.append(line_s)
                captured_traceback.append(line_s)

            if line_s.startswith("thread '") and "panicked at" in line_s:
                panics.append(line_s)
                captured_traceback.append(line_s)

            if line_s.startswith("assertion `") or line_s.startswith("assertion failed:"):
                assertion_errors.append(line_s)
                captured_traceback.append(line_s)

        if target_summaries:
            passed_count = sum(t["passed"] for t in target_summaries)
            failed_count = sum(t["failed"] for t in target_summaries)
            skipped_count = sum(t["ignored"] for t in target_summaries)
            any_target_failed = any(t["status"] == "FAILED" or t["failed"] > 0 for t in target_summaries)
        else:
            passed_count = len(passed_tests)
            failed_count = len(failed_tests)
            skipped_count = len(ignored_tests)
            any_target_failed = failed_count > 0

        incomplete_stream = len(targets_started) > len(target_summaries)

        if exit_code != 0:
            if build_errors:
                if not failed_tests:
                    failed_tests.append("compilation")
                assertion_errors = build_errors[:10] + assertion_errors
                if failed_count == 0:
                    failed_count = 1
            elif any_target_failed or failed_tests:
                if failed_count == 0:
                    failed_count = len(failed_tests) or 1
            else:
                if not failed_tests:
                    failed_tests.append("cargo_exit_failure")
                if failed_count == 0:
                    failed_count = 1

        if panics:
            assertion_errors = panics[:10] + assertion_errors

        def _dedup(items):
            seen = set()
            res = []
            for item in items:
                if item not in seen:
                    seen.add(item)
                    res.append(item)
            return res

        failed_tests = _dedup(failed_tests)
        passed_tests = _dedup(passed_tests)
        ignored_tests = _dedup(ignored_tests)
        assertion_errors = _dedup(assertion_errors)

        total_count = passed_count + failed_count + skipped_count

        traceback_summary = (
            "\n".join(captured_traceback[:30])
            if captured_traceback
            else (combined[-1500:] if combined else "")
        )

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "skipped_tests": ignored_tests,
            "assertion_errors": assertion_errors[:10],
            "traceback_summary": traceback_summary,
            "target_summaries": target_summaries,
            "incomplete_stream": incomplete_stream,
            "build_errors": build_errors,
        }

    def run_tests_with_patch(
        self,
        repo_path: str,
        target_file: str,
        patched_code: str,
        test_command: Optional[Union[str, List[str]]] = None,
        timeout: Optional[Union[int, float]] = None,
        runtime: Optional[str] = None,
        extra_files: Optional[Dict[str, str]] = None,
    ) -> SandboxTestResult:
        """
        Copies repo to an isolated temporary sandbox, applies patched_code to target_file,
        runs test suite, and parses outcome.
        """
        if timeout is not None:
            effective_timeout = validate_timeout(timeout, "timeout")
        else:
            effective_timeout = self.default_timeout

        self.last_container_name = None
        res = self._run_tests_with_patch_impl(
            repo_path=repo_path,
            target_file=target_file,
            patched_code=patched_code,
            test_command=test_command,
            timeout=effective_timeout,
            runtime=runtime,
            extra_files=extra_files,
        )
        if res is not None and getattr(res, "container_name", None) is None:
            res.container_name = getattr(self, "last_container_name", None)
        return res

    def _run_tests_with_patch_impl(
        self,
        repo_path: str,
        target_file: str,
        patched_code: str,
        test_command: Optional[Union[str, List[str]]] = None,
        timeout: Optional[int] = None,
        runtime: Optional[str] = None,
        extra_files: Optional[Dict[str, str]] = None,
    ) -> SandboxTestResult:
        """Internal implementation for sandboxed test execution."""
        import tempfile

        t_start = time.perf_counter()
        effective_timeout = timeout or self.default_timeout

        effective_runtime = runtime or self.detect_runtime(repo_path, target_file)
        if effective_runtime not in ("python", "javascript", "typescript", "node", "java", "c", "cpp", "go", "rust"):
            elapsed = time.perf_counter() - t_start
            return SandboxTestResult(
                success=False,
                exit_code=-9,
                stdout="",
                stderr=f"Runtime '{effective_runtime}' is not supported for sandbox test execution. Supported: python, javascript, typescript, java, c, cpp, go, rust.",
                duration_seconds=elapsed,
                framework=effective_runtime,
                error_message=f"Unsupported sandbox runtime: {effective_runtime}",
            )

        framework = self.detect_test_framework(repo_path, target_file, effective_runtime)
        if not framework and (extra_files or (target_file and "test" in os.path.basename(target_file).lower())) and effective_runtime == "python":
            framework = "pytest"

        if not framework and not test_command and not extra_files:
            return SandboxTestResult(
                success=False,
                exit_code=0,
                stdout="",
                stderr="",
                duration_seconds=0.0,
                framework="none",
                skipped=True,
                passed_count=0,
                failed_count=0,
                total_count=0,
                error_message="No automated test suite discovered in repository."
            )

        with tempfile.TemporaryDirectory(prefix="icx_sandbox_") as sandbox_dir:
            try:
                # 1. Copy repo files into sandbox
                self._populate_sandbox(repo_path, sandbox_dir)
                initial_test_hashes = self._collect_test_file_hashes(sandbox_dir)

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

                norm_dest = os.path.normpath(dest_file)
                # Guard all test files in repo against modification (excluding target_file itself if explicitly tested)
                guarded_test_hashes = {
                    fp: h for fp, h in initial_test_hashes.items()
                    if os.path.normpath(fp) != norm_dest
                }

                os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                with open(dest_file, "w", encoding="utf-8", errors="replace") as f:
                    f.write(patched_code)

                # Apply any isolated extra files (e.g., frozen proposed test contracts)
                if extra_files:
                    for ef_rel, ef_content in extra_files.items():
                        try:
                            ef_dest = resolve_within(sandbox_dir, ef_rel)
                            os.makedirs(os.path.dirname(ef_dest), exist_ok=True)
                            with open(ef_dest, "w", encoding="utf-8", errors="replace") as ef:
                                ef.write(ef_content)
                        except Exception as ef_err:
                            logger.warning("Could not populate extra file '%s' into sandbox: %s", ef_rel, ef_err)

                # 3. Check permissions for test_command or local execution
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

                if self.sandbox_mode == "docker" and not self._check_docker_available():
                    elapsed = time.perf_counter() - t_start
                    return SandboxTestResult(
                        success=False,
                        exit_code=-8,
                        stdout="",
                        stderr="Docker unavailable and local sandbox disabled: Docker Desktop is not running or Linux daemon is disconnected. Live container validation is blocked.",
                        duration_seconds=elapsed,
                        framework=framework or "unknown",
                        error_message="Docker unavailable and local sandbox disabled: Docker Desktop / Linux daemon is not running. Live container validation is blocked.",
                        traceback_summary="Infrastructure: Docker daemon unavailable",
                    )

                # 4. Build sandbox environment
                env = self._build_sandbox_environment(sandbox_dir)

                # 5. Execute based on runtime / custom test_command
                if test_command:
                    cmd_to_run = test_command
                    if isinstance(cmd_to_run, str):
                        cmd_to_run, parse_error = self._parse_command(cmd_to_run)
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
                    val_err = self._validate_command(cmd_to_run)
                    if val_err:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=-5,
                            stdout="",
                            stderr=val_err,
                            duration_seconds=elapsed,
                            framework=framework or "unknown",
                            error_message=f"Command validation failed: {val_err}",
                            traceback_summary=val_err,
                        )
                    exit_code, stdout, stderr, exec_err = self._execute_in_sandbox(
                        cmd_to_run, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if exec_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=exec_err,
                            duration_seconds=elapsed,
                            framework=framework or "unknown",
                            error_message=f"Execution failed: {exec_err}",
                            traceback_summary=exec_err,
                        )
                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")
                    if framework in ("node_test", "typescript"):
                        parsed = self._parse_node_test_output(stdout, stderr, exit_code)
                    elif framework == "pytest":
                        parsed = self._parse_pytest_output(stdout, stderr, exit_code)
                    elif framework == "junit":
                        parsed = self._parse_junit_output(stdout, stderr, exit_code)
                    elif framework in ("ctest", "cmake"):
                        parsed = self._parse_ctest_output(stdout, stderr, exit_code)
                    elif framework in ("go_test", "gotest"):
                        parsed = self._parse_go_test_output(stdout, stderr, exit_code)
                    else:
                        parsed = self._parse_generic_output(stdout, stderr, exit_code)

                    immut_ok, immut_err = self._verify_test_files_immutable(guarded_test_hashes)
                    if not immut_ok:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-9,
                            stdout=stdout,
                            stderr=immut_err or "Test file immutability violation",
                            duration_seconds=elapsed,
                            framework=framework or "custom",
                            error_message=immut_err,
                            traceback_summary=immut_err or "Test file immutability violation",
                        )

                    has_coll_errors = bool(parsed.get("collection_errors"))
                    is_skipped = (not has_coll_errors) and ((parsed["total_count"] == 0) or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0))
                    is_success = (exit_code == 0 and parsed["passed_count"] > 0 and parsed["failed_count"] == 0 and not has_coll_errors)
                    if is_success:
                        err_msg = None
                    elif has_coll_errors:
                        err_msg = f"Collection error: {'; '.join(parsed['collection_errors'])}"
                    elif is_skipped:
                        err_msg = "Zero tests executed"
                    else:
                        err_msg = "Tests failed"

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework=framework or "custom",
                        skipped=is_skipped,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        collection_errors=parsed.get("collection_errors", []),
                        traceback_summary=parsed["traceback_summary"],
                        error_message=err_msg,
                        test_command=cmd_to_run if isinstance(cmd_to_run, list) else [cmd_to_run],
                        working_dir="/work" if self.sandbox_mode == "docker" else sandbox_dir,
                        patched_file_path=target_file,
                    )

                # TypeScript two-phase verification: Phase 1 (tsc) -> Phase 2 (node --test)
                if effective_runtime == "typescript":
                    ts_files = []
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "node_modules", "dist", "build", "coverage", ".repos")):
                            continue
                        for f in files:
                            if f.endswith((".ts", ".tsx")) and not f.endswith(".d.ts"):
                                rel_p = os.path.relpath(os.path.join(root, f), sandbox_dir).replace("\\", "/")
                                ts_files.append(rel_p)

                    if not ts_files:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="typescript",
                            skipped=True,
                            error_message="No TypeScript source files discovered to compile."
                        )

                    if os.path.isfile(os.path.join(sandbox_dir, "tsconfig.json")):
                        compile_cmd = ["tsc", "--project", "."]
                    else:
                        type_roots = ["--typeRoots", "/usr/local/lib/node_modules/@types", "--types", "node"] if (self.sandbox_mode == "docker" or os.path.isdir("/usr/local/lib/node_modules/@types")) else ["--skipLibCheck"]
                        compile_cmd = ["tsc", "--target", "ES2022", "--module", "commonjs"] + type_roots + ts_files

                    exit_code, stdout, stderr, compile_err = self._execute_in_sandbox(
                        compile_cmd, sandbox_dir, effective_timeout, env
                    )
                    if compile_err and exit_code != -1:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=compile_err,
                            duration_seconds=elapsed,
                            framework="typescript",
                            error_message=f"TypeScript compiler execution error: {compile_err}",
                            traceback_summary=compile_err,
                        )

                    if exit_code != 0:
                        elapsed = time.perf_counter() - t_start
                        combined_err = f"{stdout}\n{stderr}".strip()
                        compile_errs = [line.strip() for line in combined_err.splitlines() if "error TS" in line or "Error:" in line][:10]
                        return SandboxTestResult(
                            success=False,
                            exit_code=exit_code,
                            stdout=self._truncate_output(stdout or ""),
                            stderr=self._truncate_output(stderr or ""),
                            duration_seconds=elapsed,
                            framework="typescript",
                            failed_count=1,
                            passed_count=0,
                            total_count=1,
                            failed_tests=["tsc_compilation"],
                            assertion_errors=compile_errs,
                            traceback_summary=combined_err[-1500:],
                            error_message=f"TypeScript compilation failed with exit code {exit_code}",
                        )

                    # Phase 2: Behavioral test execution on compiled JavaScript tests
                    test_files = []
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "node_modules", ".repos")):
                            continue
                        for f in files:
                            if (f.endswith((".test.js", ".spec.js", "_test.js")) or (os.path.basename(root) in ("test", "tests") and f.endswith(".js"))):
                                rel_p = os.path.relpath(os.path.join(root, f), sandbox_dir).replace("\\", "/")
                                test_files.append(rel_p)

                    if not test_files:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=0,
                            stdout=self._truncate_output(stdout or ""),
                            stderr=self._truncate_output(stderr or ""),
                            duration_seconds=elapsed,
                            framework="typescript",
                            skipped=True,
                            passed_count=0,
                            failed_count=0,
                            total_count=0,
                            error_message="TypeScript compiled successfully, but zero behavioral test files were discovered."
                        )

                    target_base = os.path.splitext(os.path.basename(target_file))[0]
                    matching_tests = [tf for tf in test_files if target_base in os.path.basename(tf)]
                    selected_tests = matching_tests if matching_tests else test_files
                    test_cmd = ["node", "--test"] + selected_tests

                    exit_code, stdout, stderr, test_err = self._execute_in_sandbox(
                        test_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if test_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=test_err,
                            duration_seconds=elapsed,
                            framework="typescript",
                            error_message=f"Node test runner execution error: {test_err}",
                            traceback_summary=test_err,
                        )

                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")
                    parsed = self._parse_node_test_output(stdout, stderr, exit_code)
                    is_skipped = (parsed["total_count"] == 0) or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0)
                    is_success = (exit_code == 0 and parsed["passed_count"] > 0 and parsed["failed_count"] == 0)

                    if is_success:
                        err_msg = None
                    elif exit_code == -1:
                        err_msg = test_err or f"Execution timed out after {effective_timeout}s"
                    elif is_skipped:
                        err_msg = "Zero tests executed"
                    else:
                        err_msg = "Behavioral tests failed"

                    tb_sum = (test_err or f"TimeoutExpired: Execution timed out after {effective_timeout}s") if exit_code == -1 else parsed["traceback_summary"]

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework="typescript",
                        skipped=is_skipped,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        traceback_summary=tb_sum,
                        error_message=err_msg,
                    )

                # JavaScript Node test runner verification
                if effective_runtime in ("javascript", "node"):
                    test_files = []
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "node_modules", ".repos")):
                            continue
                        for f in files:
                            if (f.endswith((".test.js", ".spec.js", "_test.js")) or (os.path.basename(root) in ("test", "tests") and f.endswith(".js"))):
                                rel_p = os.path.relpath(os.path.join(root, f), sandbox_dir).replace("\\", "/")
                                test_files.append(rel_p)

                    if not test_files:
                        pkg_json = os.path.join(sandbox_dir, "package.json")
                        if os.path.isfile(pkg_json) and framework == "npm":
                            test_cmd = ["npm", "test"]
                        else:
                            elapsed = time.perf_counter() - t_start
                            return SandboxTestResult(
                                success=False,
                                exit_code=0,
                                stdout="",
                                stderr="",
                                duration_seconds=elapsed,
                                framework="node_test",
                                skipped=True,
                                passed_count=0,
                                failed_count=0,
                                total_count=0,
                                error_message="No automated JavaScript test files were discovered."
                            )
                    else:
                        target_base = os.path.splitext(os.path.basename(target_file))[0]
                        matching_tests = [tf for tf in test_files if target_base in os.path.basename(tf)]
                        selected_tests = matching_tests if matching_tests else test_files
                        test_cmd = ["node", "--test"] + selected_tests

                    exit_code, stdout, stderr, test_err = self._execute_in_sandbox(
                        test_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if test_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=test_err,
                            duration_seconds=elapsed,
                            framework="node_test",
                            error_message=f"Node test runner execution error: {test_err}",
                            traceback_summary=test_err,
                        )

                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")
                    parsed = self._parse_node_test_output(stdout, stderr, exit_code)
                    is_skipped = (parsed["total_count"] == 0) or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0)
                    is_success = (exit_code == 0 and parsed["passed_count"] > 0 and parsed["failed_count"] == 0)

                    if is_success:
                        err_msg = None
                    elif exit_code == -1:
                        err_msg = test_err or f"Execution timed out after {effective_timeout}s"
                    elif is_skipped:
                        err_msg = "Zero tests executed"
                    else:
                        err_msg = "Behavioral tests failed"

                    tb_sum = (test_err or f"TimeoutExpired: Execution timed out after {effective_timeout}s") if exit_code == -1 else parsed["traceback_summary"]

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework="node_test",
                        skipped=is_skipped,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        traceback_summary=tb_sum,
                        error_message=err_msg,
                    )

                # Java two-phase verification: Phase 1 (javac) -> Phase 2 (JUnit Platform Console Launcher)
                if effective_runtime == "java":
                    java_files = []
                    test_files = []
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "target", "build", ".gradle", ".repos", "bin", "build_classes")):
                            continue
                        for f in files:
                            if f.endswith(".java"):
                                rel_p = os.path.relpath(os.path.join(root, f), sandbox_dir).replace("\\", "/")
                                java_files.append(rel_p)
                                root_base = os.path.basename(root).lower()
                                is_test = (
                                    f.endswith(("Test.java", "Tests.java", "TestCase.java"))
                                    or f.startswith("Test")
                                    or "src/test/java" in rel_p
                                    or root_base in ("test", "tests")
                                )
                                if is_test:
                                    test_files.append(rel_p)

                    if not java_files:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=True,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="junit",
                            skipped=True,
                            passed_count=0,
                            failed_count=0,
                            total_count=0,
                            error_message="No Java source files were discovered in repository."
                        )

                    if not test_files:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=True,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="junit",
                            skipped=True,
                            passed_count=0,
                            failed_count=0,
                            total_count=0,
                            error_message="No automated Java test files were discovered."
                        )

                    classes_dir = os.path.join(sandbox_dir, "build_classes")
                    os.makedirs(classes_dir, exist_ok=True)

                    repo_jars = []
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "target", "build", ".gradle", ".repos", "build_classes")):
                            continue
                        for f in files:
                            if f.endswith(".jar"):
                                rel_jar = os.path.relpath(os.path.join(root, f), sandbox_dir).replace("\\", "/")
                                repo_jars.append(rel_jar)

                    junit_jar = os.environ.get("JUNIT_PLATFORM_JAR", "/usr/local/lib/junit-platform-console-standalone.jar")
                    cp_elements = [junit_jar] + repo_jars
                    compile_cp = ":".join(cp_elements)

                    # Phase 1: Compile all Java files with javac
                    compile_cmd = ["javac", "-d", "build_classes", "-cp", compile_cp] + java_files
                    exit_code, stdout, stderr, compile_err = self._execute_in_sandbox(
                        compile_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if exit_code != 0:
                        combined_err = f"{stdout}\n{stderr}".strip()
                        assertion_errors = [l.strip() for l in combined_err.splitlines() if "error:" in l.lower()][:10]
                        return SandboxTestResult(
                            success=False,
                            exit_code=exit_code if exit_code != 0 else -1,
                            stdout=self._truncate_output(stdout or ""),
                            stderr=self._truncate_output(stderr or ""),
                            duration_seconds=elapsed,
                            framework="javac",
                            skipped=False,
                            passed_count=0,
                            failed_count=1,
                            total_count=1,
                            failed_tests=["compilation"],
                            assertion_errors=assertion_errors,
                            traceback_summary=self._truncate_output(combined_err),
                            error_message=compile_err or f"Java compilation failed with exit code {exit_code}",
                        )

                    # Phase 2: Behavioral test execution using JUnit Platform Console Launcher
                    test_cmd = [
                        "java", "-jar", junit_jar,
                        "execute",
                        "--disable-banner",
                        "--disable-ansi-colors",
                        "--details=verbose",
                        "--class-path", "build_classes",
                        "--scan-class-path"
                    ]

                    exit_code, stdout, stderr, test_err = self._execute_in_sandbox(
                        test_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if test_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=test_err,
                            duration_seconds=elapsed,
                            framework="junit",
                            error_message=f"JUnit test runner execution error: {test_err}",
                            traceback_summary=test_err,
                        )

                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")
                    parsed = self._parse_junit_output(stdout, stderr, exit_code)

                    is_skipped = (
                        (parsed["total_count"] == 0)
                        or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0)
                        or (parsed.get("aborted_count", 0) > 0 and parsed["passed_count"] == 0)
                    )
                    is_success = (
                        exit_code == 0
                        and parsed["passed_count"] > 0
                        and parsed["failed_count"] == 0
                        and parsed.get("aborted_count", 0) == 0
                    )

                    if is_success:
                        err_msg = None
                    elif exit_code == -1:
                        err_msg = test_err or f"Execution timed out after {effective_timeout}s"
                    elif is_skipped:
                        err_msg = "Zero tests executed or all tests skipped/aborted"
                    else:
                        err_msg = "Behavioral tests failed"

                    tb_sum = (
                        (test_err or f"TimeoutExpired: Execution timed out after {effective_timeout}s")
                        if exit_code == -1
                        else parsed["traceback_summary"]
                    )

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework="junit",
                        skipped=is_skipped,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        traceback_summary=tb_sum,
                        error_message=err_msg,
                    )

                # C and C++ verification: CMake configure -> build -> CTest
                if effective_runtime in ("c", "cpp"):
                    cmake_file = os.path.join(sandbox_dir, "CMakeLists.txt")
                    if not os.path.isfile(cmake_file):
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="ctest",
                            skipped=True,
                            passed_count=0,
                            failed_count=0,
                            total_count=0,
                            error_message="No CMakeLists.txt build specification discovered in repository.",
                        )

                    # Clean disposable build directory
                    build_dir = os.path.join(sandbox_dir, "build")
                    if os.path.exists(build_dir):
                        shutil.rmtree(build_dir, ignore_errors=True)
                    os.makedirs(build_dir, exist_ok=True)

                    # Phase 1: Configure with CMake
                    # Ensure Debug mode and -UNDEBUG so assertions are never silenced
                    config_cmd = [
                        "cmake", "-S", ".", "-B", "build",
                        "-DCMAKE_BUILD_TYPE=Debug",
                        "-DCMAKE_C_FLAGS=-UNDEBUG",
                        "-DCMAKE_CXX_FLAGS=-UNDEBUG",
                    ]
                    exit_code, stdout, stderr, config_err = self._execute_in_sandbox(
                        config_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if config_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=config_err,
                            duration_seconds=elapsed,
                            framework="cmake",
                            error_message=f"CMake configure execution error: {config_err}",
                            traceback_summary=config_err,
                        )

                    if exit_code != 0:
                        combined_err = f"{stdout}\n{stderr}".strip()
                        diag_lines = [
                            line.strip() for line in combined_err.splitlines()
                            if any(k in line.lower() for k in ("cmake error", "error:", "fatal:"))
                        ][:10]
                        return SandboxTestResult(
                            success=False,
                            exit_code=exit_code if exit_code != 0 else -1,
                            stdout=self._truncate_output(stdout or ""),
                            stderr=self._truncate_output(stderr or ""),
                            duration_seconds=elapsed,
                            framework="cmake",
                            failed_count=1,
                            passed_count=0,
                            total_count=1,
                            failed_tests=["cmake_configure"],
                            assertion_errors=diag_lines,
                            traceback_summary=self._truncate_output(combined_err[-1500:]),
                            error_message=f"CMake configuration failed with exit code {exit_code}",
                        )

                    # Phase 2: Build project with cmake --build
                    build_cmd = ["cmake", "--build", "build", "--config", "Debug"]
                    exit_code, stdout, stderr, build_err = self._execute_in_sandbox(
                        build_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if build_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=build_err,
                            duration_seconds=elapsed,
                            framework="cmake",
                            error_message=f"CMake build execution error: {build_err}",
                            traceback_summary=build_err,
                        )

                    if exit_code != 0:
                        combined_err = f"{stdout}\n{stderr}".strip()
                        compiler_errs = [
                            line.strip() for line in combined_err.splitlines()
                            if any(k in line for k in ("error:", "fatal error:"))
                        ][:10]
                        return SandboxTestResult(
                            success=False,
                            exit_code=exit_code if exit_code != 0 else -1,
                            stdout=self._truncate_output(stdout or ""),
                            stderr=self._truncate_output(stderr or ""),
                            duration_seconds=elapsed,
                            framework="cmake",
                            failed_count=1,
                            passed_count=0,
                            total_count=1,
                            failed_tests=["compilation"],
                            assertion_errors=compiler_errs,
                            traceback_summary=self._truncate_output(combined_err[-1500:]),
                            error_message=f"C/C++ compilation failed with exit code {exit_code}",
                        )

                    # Phase 3: Behavioral test execution with CTest
                    test_cmd = [
                        "ctest",
                        "--test-dir", "build",
                        "--output-on-failure",
                        "--verbose",
                    ]
                    exit_code, stdout, stderr, test_err = self._execute_in_sandbox(
                        test_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if test_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=test_err,
                            duration_seconds=elapsed,
                            framework="ctest",
                            error_message=f"CTest execution error: {test_err}",
                            traceback_summary=test_err,
                        )

                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")
                    parsed = self._parse_ctest_output(stdout, stderr, exit_code)

                    is_skipped = (
                        (parsed["total_count"] == 0)
                        or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0)
                        or (parsed.get("skipped_count", 0) > 0 and parsed["passed_count"] == 0)
                    )
                    is_success = (
                        exit_code == 0
                        and parsed["passed_count"] > 0
                        and parsed["failed_count"] == 0
                        and not is_skipped
                    )

                    if is_success:
                        err_msg = None
                    elif exit_code == -1:
                        err_msg = test_err or f"Execution timed out after {effective_timeout}s"
                    elif is_skipped:
                        err_msg = "Zero tests discovered or all tests skipped"
                    else:
                        err_msg = "Behavioral tests failed"

                    tb_sum = (
                        (test_err or f"TimeoutExpired: Execution timed out after {effective_timeout}s")
                        if exit_code == -1
                        else parsed["traceback_summary"]
                    )

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework="ctest",
                        skipped=is_skipped,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        traceback_summary=tb_sum,
                        error_message=err_msg,
                    )

                # Go verification: single-module go test -count=1 -json ./...
                if effective_runtime == "go":
                    go_mod = os.path.join(sandbox_dir, "go.mod")
                    if not os.path.isfile(go_mod):
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="go_test",
                            skipped=True,
                            passed_count=0,
                            failed_count=0,
                            total_count=0,
                            error_message="No go.mod module specification discovered in repository.",
                        )

                    # Check for at least one test file
                    test_files = []
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "vendor", ".gotmp")):
                            continue
                        for f in files:
                            if f.endswith("_test.go"):
                                test_files.append(f)
                    if not test_files:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="go_test",
                            skipped=True,
                            passed_count=0,
                            failed_count=0,
                            total_count=0,
                            error_message="No automated Go test files (*_test.go) discovered in repository.",
                        )

                    runner_py = (
                        "import os, subprocess, sys\n"
                        "os.makedirs('/tmp/gotmp', exist_ok=True)\n"
                        "os.makedirs('/tmp/go-cache', exist_ok=True)\n"
                        "os.makedirs('/work/.bin', exist_ok=True)\n"
                        "try:\n"
                        "    packages = subprocess.check_output(['go', 'list', './...'], text=True, stderr=subprocess.PIPE).strip().splitlines()\n"
                        "except subprocess.CalledProcessError as e:\n"
                        "    sys.stderr.write(e.stderr or e.stdout)\n"
                        "    sys.exit(e.returncode)\n"
                        "overall_exit = 0\n"
                        "for pkg in packages:\n"
                        "    bin_name = pkg.replace('/', '_').replace('.', '_') + '.test'\n"
                        "    bin_path = f'/work/.bin/{bin_name}'\n"
                        "    c = subprocess.run(['go', 'test', '-c', '-o', bin_path, pkg], capture_output=True, text=True)\n"
                        "    if c.returncode != 0:\n"
                        "        if '[no test files]' in c.stdout or '[no test files]' in c.stderr or 'no Go files' in c.stderr:\n"
                        "            print(f'{{\"Action\":\"output\",\"Package\":\"{pkg}\",\"Output\":\"?   \\\\t{pkg}\\\\t[no test files]\\\\n\"}}')\n"
                        "            print(f'{{\"Action\":\"skip\",\"Package\":\"{pkg}\",\"Elapsed\":0}}')\n"
                        "            continue\n"
                        "        print(f'{{\"ImportPath\":\"{pkg}\",\"Action\":\"build-fail\"}}')\n"
                        "        for line in (c.stdout + '\\n' + c.stderr).splitlines():\n"
                        "            if line.strip():\n"
                        "                print(f'{{\"ImportPath\":\"{pkg}\",\"Action\":\"build-output\",\"Output\":\"{line}\\\\n\"}}')\n"
                        "        print(f'{{\"Action\":\"fail\",\"Package\":\"{pkg}\",\"FailedBuild\":\"{pkg}\"}}')\n"
                        "        overall_exit = 1\n"
                        "        continue\n"
                        "    p = subprocess.run([bin_path, '-test.v', '-test.count=1'], capture_output=True, text=True)\n"
                        "    combined = p.stdout + '\\n' + p.stderr\n"
                        "    t2j = subprocess.run(['go', 'tool', 'test2json', '-p', pkg, '-t'], input=combined, capture_output=True, text=True)\n"
                        "    sys.stdout.write(t2j.stdout)\n"
                        "    if p.returncode != 0:\n"
                        "        print(f'{{\"Action\":\"fail\",\"Package\":\"{pkg}\"}}')\n"
                        "        overall_exit = 1\n"
                        "sys.exit(overall_exit)\n"
                    )

                    test_cmd = ["python", "-c", runner_py]
                    exit_code, stdout, stderr, test_err = self._execute_in_sandbox(
                        test_cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start
                    if test_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=test_err,
                            duration_seconds=elapsed,
                            framework="go_test",
                            error_message=f"Go test runner execution error: {test_err}",
                            traceback_summary=test_err,
                        )

                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")
                    parsed = self._parse_go_test_output(stdout, stderr, exit_code)

                    is_skipped = (
                        (parsed["total_count"] == 0)
                        or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0)
                        or (parsed.get("skipped_count", 0) > 0 and parsed["passed_count"] == 0)
                    )
                    is_success = (
                        exit_code == 0
                        and parsed["passed_count"] > 0
                        and parsed["failed_count"] == 0
                        and not is_skipped
                        and not parsed.get("malformed_json", False)
                        and not parsed.get("incomplete_stream", False)
                    )

                    if is_success:
                        err_msg = None
                    elif exit_code == -1:
                        err_msg = test_err or f"Execution timed out after {effective_timeout}s"
                    elif is_skipped:
                        err_msg = "Zero tests discovered or all tests skipped"
                    else:
                        err_msg = "Behavioral tests failed"

                    tb_sum = (
                        (test_err or f"TimeoutExpired: Execution timed out after {effective_timeout}s")
                        if exit_code == -1
                        else parsed["traceback_summary"]
                    )

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework="go_test",
                        skipped=is_skipped,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        traceback_summary=tb_sum,
                        error_message=err_msg,
                    )

                elif effective_runtime == "rust":
                    cargo_toml = os.path.join(sandbox_dir, "Cargo.toml")
                    if not os.path.isfile(cargo_toml):
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=-3,
                            stdout="",
                            stderr="Missing Cargo.toml in repository root for Rust runtime.",
                            duration_seconds=elapsed,
                            framework="cargo",
                            error_message="Missing Cargo.toml in repository root",
                            traceback_summary="Missing Cargo.toml in repository root for Rust runtime.",
                        )

                    has_rust_tests = False
                    for root, _, files in os.walk(sandbox_dir):
                        if any(ignored in root for ignored in (".git", "target")):
                            continue
                        rel_root = os.path.relpath(root, sandbox_dir).replace("\\", "/")
                        if rel_root.startswith("tests") and any(f.endswith(".rs") for f in files):
                            has_rust_tests = True
                            break
                        if rel_root.startswith("src") and any(f.endswith(".rs") for f in files):
                            has_rust_tests = True
                            break

                    if not has_rust_tests:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=True,
                            exit_code=0,
                            stdout="",
                            stderr="",
                            duration_seconds=elapsed,
                            framework="cargo",
                            skipped=True,
                            error_message="No Rust tests discovered in src/ or tests/",
                        )

                    if test_command:
                        cmd, parse_err = self._parse_command(test_command)
                        if parse_err:
                            elapsed = time.perf_counter() - t_start
                            return SandboxTestResult(
                                success=False,
                                exit_code=-4,
                                stdout="",
                                stderr=parse_err,
                                duration_seconds=elapsed,
                                framework="cargo",
                                error_message=f"Command parsing failed: {parse_err}",
                                traceback_summary=parse_err,
                            )
                    else:
                        cmd = ["cargo", "test", "--tests", "--", "--nocapture"]

                    val_err = self._validate_command(cmd)
                    if val_err:
                        elapsed = time.perf_counter() - t_start
                        return SandboxTestResult(
                            success=False,
                            exit_code=-5,
                            stdout="",
                            stderr=val_err,
                            duration_seconds=elapsed,
                            framework="cargo",
                            error_message=f"Command validation failed: {val_err}",
                            traceback_summary=val_err,
                        )

                    exit_code, stdout, stderr, exec_err = self._execute_in_sandbox(
                        cmd, sandbox_dir, effective_timeout, env
                    )
                    elapsed = time.perf_counter() - t_start

                    if exec_err and exit_code != -1:
                        return SandboxTestResult(
                            success=False,
                            exit_code=-6,
                            stdout="",
                            stderr=exec_err,
                            duration_seconds=elapsed,
                            framework="cargo",
                            error_message=f"Docker execution error: {exec_err}",
                            traceback_summary=exec_err,
                        )

                    stdout = self._truncate_output(stdout or "")
                    stderr = self._truncate_output(stderr or "")

                    parsed = self._parse_cargo_test_output(stdout, stderr, exit_code)

                    is_skipped = parsed["passed_count"] == 0 and parsed["failed_count"] == 0 and parsed["skipped_count"] > 0
                    is_zero_tests = parsed["passed_count"] == 0 and parsed["failed_count"] == 0 and parsed["skipped_count"] == 0

                    is_success = (
                        exit_code == 0
                        and parsed["passed_count"] > 0
                        and parsed["failed_count"] == 0
                        and not is_skipped
                        and not is_zero_tests
                        and not parsed.get("incomplete_stream", False)
                        and not exec_err
                    )

                    if is_success:
                        err_msg = None
                    elif exit_code == -1:
                        err_msg = exec_err or f"Execution timed out after {effective_timeout}s"
                    elif is_zero_tests:
                        err_msg = "Zero behavioral tests completed"
                    elif is_skipped:
                        err_msg = "All tests ignored (no passing behavioral tests)"
                    elif parsed.get("incomplete_stream", False):
                        err_msg = "Incomplete test execution stream"
                    elif parsed["failed_count"] > 0:
                        err_msg = "Behavioral tests failed"
                    else:
                        err_msg = "Cargo execution failed"

                    tb_sum = (
                        (exec_err or f"TimeoutExpired: Execution timed out after {effective_timeout}s")
                        if exit_code == -1
                        else parsed["traceback_summary"]
                    )

                    return SandboxTestResult(
                        success=is_success,
                        exit_code=exit_code,
                        stdout=stdout,
                        stderr=stderr,
                        duration_seconds=elapsed,
                        framework="cargo",
                        skipped=is_skipped or is_zero_tests,
                        passed_count=parsed["passed_count"],
                        failed_count=parsed["failed_count"],
                        total_count=parsed["total_count"],
                        failed_tests=parsed["failed_tests"],
                        passed_tests=parsed["passed_tests"],
                        assertion_errors=parsed["assertion_errors"],
                        traceback_summary=tb_sum,
                        error_message=err_msg,
                    )

                # Default Python execution (pytest / unittest)
                cmd = self._resolve_command(sandbox_dir, framework, test_command, target_file)
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

                exit_code, stdout, stderr, exec_err = self._execute_in_sandbox(
                    cmd, sandbox_dir, effective_timeout, env
                )
                elapsed = time.perf_counter() - t_start
                if exec_err and exit_code != -1:
                    return SandboxTestResult(
                        success=False,
                        exit_code=-6,
                        stdout="",
                        stderr=exec_err,
                        duration_seconds=elapsed,
                        framework=framework or "unknown",
                        error_message=f"Execution error: {exec_err}",
                        traceback_summary=exec_err,
                    )

                stdout = self._truncate_output(stdout or "")
                stderr = self._truncate_output(stderr or "")

                if framework == "pytest" or "pytest" in (test_command or ""):
                    parsed = self._parse_pytest_output(stdout, stderr, exit_code)
                else:
                    parsed = self._parse_generic_output(stdout, stderr, exit_code)

                immut_ok, immut_err = self._verify_test_files_immutable(guarded_test_hashes)
                if not immut_ok:
                    return SandboxTestResult(
                        success=False,
                        exit_code=-9,
                        stdout=stdout,
                        stderr=immut_err or "Test file immutability violation",
                        duration_seconds=elapsed,
                        framework=framework or "custom",
                        error_message=immut_err,
                        traceback_summary=immut_err or "Test file immutability violation",
                    )

                effective_cmd = cmd if isinstance(cmd, list) else ([cmd] if isinstance(cmd, str) else list(cmd))
                effective_wdir = "/work" if self.sandbox_mode == "docker" else sandbox_dir
                has_coll_errors = bool(parsed.get("collection_errors"))
                is_skipped = (not has_coll_errors) and ((exit_code == 5) or ("no tests ran" in stdout.lower()) or (parsed["total_count"] == 0) or (parsed["passed_count"] == 0 and parsed["failed_count"] == 0))
                is_success = (exit_code == 0 and parsed["passed_count"] > 0 and parsed["failed_count"] == 0 and not is_skipped and not has_coll_errors)
                if is_success:
                    err_msg = None
                elif has_coll_errors:
                    err_msg = f"Collection error: {'; '.join(parsed['collection_errors'])}"
                elif is_skipped:
                    err_msg = "Zero tests executed"
                else:
                    err_msg = "Tests failed"

                return SandboxTestResult(
                    success=is_success,
                    exit_code=exit_code,
                    stdout=stdout,
                    stderr=stderr,
                    duration_seconds=elapsed,
                    framework=framework or "custom",
                    skipped=is_skipped,
                    passed_count=parsed["passed_count"],
                    failed_count=parsed["failed_count"],
                    total_count=parsed["total_count"],
                    failed_tests=parsed["failed_tests"],
                    passed_tests=parsed["passed_tests"],
                    assertion_errors=parsed["assertion_errors"],
                    collection_errors=parsed.get("collection_errors", []),
                    traceback_summary=parsed["traceback_summary"],
                    error_message=err_msg,
                    test_command=effective_cmd,
                    working_dir=effective_wdir,
                    patched_file_path=target_file,
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

    def run_baseline_tests(
        self,
        repo_path: str,
        target_file: str,
        test_command: Optional[str] = None,
        timeout: Optional[int] = None,
        extra_files: Optional[Dict[str, str]] = None,
    ) -> SandboxTestResult:
        """
        Executes automated baseline tests for target_file inside sandbox without modifying source code.
        Reads current file content from repo_path and runs verification to discover active baseline failures.
        """
        abs_target = os.path.join(repo_path, target_file) if not os.path.isabs(target_file) else target_file
        original_code = ""
        if os.path.isfile(abs_target):
            try:
                with open(abs_target, "r", encoding="utf-8", errors="replace") as f:
                    original_code = f.read()
            except Exception as e:
                logger.warning("Could not read baseline target file '%s': %s", abs_target, e)

        return self.run_tests_with_patch(
            repo_path=repo_path,
            target_file=target_file,
            patched_code=original_code,
            test_command=test_command,
            timeout=timeout,
            extra_files=extra_files,
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

        # Default for Python: run pytest or unittest with container/host python executable
        py_exec = "python" if self.sandbox_mode == "docker" else sys.executable
        if framework == "pytest":
            # Attempt to discover tests matching target_file using canonical discovery
            try:
                from core.canonical_path import discover_relevant_tests
                discovered = discover_relevant_tests(sandbox_dir, target_file)
                if discovered:
                    return [py_exec, "-m", "pytest", discovered[0], "-v", "--tb=short", "-p", "no:cacheprovider"]
            except Exception:
                pass

            target_base = os.path.splitext(os.path.basename(target_file))[0]
            target_dir = os.path.dirname(target_file)
            cand_test_paths = [
                os.path.join(sandbox_dir, target_file) if ("test" in os.path.basename(target_file).lower()) else None,
                os.path.join(sandbox_dir, f"test_{target_base}.py"),
                os.path.join(sandbox_dir, f"{target_base}_test.py"),
                os.path.join(sandbox_dir, "tests", f"test_{target_base}.py"),
                os.path.join(sandbox_dir, target_dir, f"test_{target_base}.py") if target_dir else None,
                os.path.join(sandbox_dir, target_dir, "tests", f"test_{target_base}.py") if target_dir else None,
                os.path.join(sandbox_dir, target_dir, f"{target_base}_test.py") if target_dir else None,
            ]
            for cand in cand_test_paths:
                if cand and os.path.isfile(cand):
                    rel_test = os.path.relpath(cand, sandbox_dir).replace("\\", "/")
                    return [py_exec, "-m", "pytest", rel_test, "-v", "--tb=short", "-p", "no:cacheprovider"]
            return [py_exec, "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider"]

        if framework == "npm":
            # Use npx or npm from PATH
            if shutil.which("npx"):
                return ["npx", "npm", "test"]
            return ["npm", "test"]

        # Default fallback: python unittest discover with container/host python executable
        return [py_exec, "-m", "unittest", "discover", "-s", ".", "-p", "test*.py"]

    @staticmethod
    def _is_banner_or_separator(line: str) -> bool:
        s = line.strip()
        if not s:
            return True
        if any(s.startswith(p) for p in ("===", "___", "---", "!!!", "***")):
            return True
        # If 40% or more characters are punctuation = _ - ! * ~ #
        punct = sum(1 for c in s if c in "=_-!*~#")
        if len(s) >= 3 and punct >= len(s) * 0.4:
            return True
        return False

    def _parse_pytest_output(self, stdout: str, stderr: str, exit_code: int = 0) -> Dict[str, Any]:
        """Extracts passed/failed counts, assertion messages, collection errors, and traceback highlights from pytest output."""
        passed_tests = []
        failed_tests = []
        collection_errors = []
        assertion_errors = []
        traceback_lines = []

        # 1. Parse collection errors (e.g. ERROR collecting test_schedule.py, ImportError, etc.)
        for line in stdout.splitlines():
            line_str = line.strip()
            if "ERROR collecting " in line_str:
                m = re.search(r"ERROR collecting\s+([^\s_]+)", line_str)
                if m:
                    target = m.group(1).strip()
                    if target and not any(target in ce for ce in collection_errors):
                        collection_errors.append(f"Error collecting {target}")
            elif line_str.startswith("E   ") and any(err in line_str for err in ("ImportError:", "SyntaxError:", "ModuleNotFoundError:", "NameError:")):
                err_detail = line_str[4:].strip()
                if collection_errors and not any(err_detail in ce for ce in collection_errors):
                    collection_errors[-1] = f"{collection_errors[-1]}: {err_detail}"
                elif not collection_errors:
                    collection_errors.append(err_detail)

        # 2. Parse short test summary info section
        in_short_summary = False
        for line in stdout.splitlines():
            line_str = line.strip()
            if "=== short test summary info ===" in line_str:
                in_short_summary = True
                continue
            if in_short_summary and line_str.startswith("==="):
                in_short_summary = False
                continue

            if in_short_summary and not self._is_banner_or_separator(line_str):
                if line_str.startswith("ERROR "):
                    rest = line_str[6:].strip()
                    err_target = rest.split(" - ")[0].strip()
                    err_msg = rest[len(err_target):].lstrip(" -").strip()
                    coll_err = f"{err_target}: {err_msg}" if err_msg else err_target
                    if not any(err_target in ce for ce in collection_errors):
                        collection_errors.append(coll_err)
                elif line_str.startswith("FAILED "):
                    rest = line_str[7:].strip()
                    test_name = rest.split(" - ")[0].strip()
                    if test_name and not self._is_banner_or_separator(test_name) and test_name not in failed_tests:
                        failed_tests.append(test_name)

        # 3. Parse verbose test execution lines: e.g. tests/test_math.py::test_add PASSED
        for line in stdout.splitlines():
            line_str = line.strip()
            if self._is_banner_or_separator(line_str):
                continue
            if " PASSED" in line_str:
                test_name = line_str.split(" PASSED")[0].strip()
                if not self._is_banner_or_separator(test_name) and test_name not in passed_tests:
                    passed_tests.append(test_name)
            elif " FAILED" in line_str:
                test_name = line_str.split(" FAILED")[0].strip()
                if not self._is_banner_or_separator(test_name) and test_name not in failed_tests:
                    failed_tests.append(test_name)
            elif " ERROR" in line_str and not line_str.startswith("ERROR collecting"):
                test_name = line_str.split(" ERROR")[0].strip()
                if not self._is_banner_or_separator(test_name) and test_name not in failed_tests:
                    if "::" in test_name or "test" in test_name.lower():
                        failed_tests.append(test_name)

        # Strictly clean all test names so separators never leak
        passed_tests = [t for t in passed_tests if not self._is_banner_or_separator(t)]
        failed_tests = [t for t in failed_tests if not self._is_banner_or_separator(t)]

        # 4. Parse assertion failures & traceback section
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

        # 5. Extract summary numbers e.g. "1 failed, 4 passed in 0.12s" or "1 error in 0.12s"
        passed_count = len(passed_tests)
        failed_count = len(failed_tests)
        collected_count = None

        coll_match = re.search(r"collected\s+(\d+)\s+items?(?:\s*/\s*(\d+)\s+error)?", stdout)
        if coll_match:
            collected_count = int(coll_match.group(1))

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
            if err_m and not fail_m and (collected_count == 0 or not passed_tests):
                # Collection error: 0 tests executed
                failed_count = 0
            elif err_m and fail_m:
                failed_count += int(err_m.group(1))

        if exit_code != 0 and passed_count == 0 and failed_count == 0:
            if not collection_errors and exit_code != 5 and "no tests ran" not in stdout.lower():
                failed_count = 1
                if not failed_tests:
                    failed_tests.append("test_execution_failure")
            if not assertion_errors:
                combined_err = (stdout + "\n" + stderr).strip()
                for line in combined_err.splitlines():
                    ls = line.strip()
                    if not self._is_banner_or_separator(ls) and any(k in ls for k in ("Error:", "AssertionError", "Exception:", "FAILED", "assert ")):
                        assertion_errors.append(ls)

        total_count = passed_count + failed_count
        traceback_summary = "\n".join(traceback_lines[:40]) if traceback_lines else (stderr[:1000] if stderr else (stdout[-1000:] if exit_code != 0 else ""))

        return {
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "collected_count": collected_count if collected_count is not None else total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "collection_errors": collection_errors,
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


_check_docker_available = SandboxRunner._check_docker_available

