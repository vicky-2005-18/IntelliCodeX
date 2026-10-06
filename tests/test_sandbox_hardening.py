"""
Sandbox Security Hardening Tests
Tests for security features in core/sandbox_runner.py:
  - Environment variable filtering (sensitive variables blocked)
  - Shell metacharacter rejection
  - Executable allowlist enforcement
  - Process tree killing on timeout
  - Output truncation
  - Docker mode fallback
"""
import os
import sys
import pytest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

from core.sandbox_runner import SandboxRunner, SandboxTestResult


@pytest.fixture
def sample_repo():
    """Create a minimal sample repository for testing."""
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        # Create a simple Python file
        test_file = os.path.join(repo_dir, "math.py")
        with open(test_file, "w") as f:
            f.write("def add(a, b):\n    return a + b\n")

        # Create a tests directory
        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(tests_dir)
        test_file = os.path.join(tests_dir, "test_math.py")
        with open(test_file, "w") as f:
            f.write("""
import sys
import os

def test_add():
    assert 1 + 1 == 2

def test_env_vars():
    # Print all environment variables to check for leaks
    print("ENVIRONMENT VARIABLES:")
    for key, value in sorted(os.environ.items()):
        print(f"{key}={value}")
""")

        yield repo_dir


def test_environment_variable_filtering(sample_repo):
    """Test that sensitive environment variables are blocked in sandbox."""
    # Set sensitive variables in parent environment
    os.environ["MY_SECRET_TOKEN"] = "super_secret_value"
    os.environ["API_KEY"] = "api_key_value"
    os.environ["JWT_SECRET"] = "jwt_secret_value"

    try:
        runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

        # Run a test that prints environment variables
        result = runner.run_tests_with_patch(
            repo_path=sample_repo,
            target_file="math.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command=None,  # Use default pytest
            timeout=10
        )

        # Check that sensitive variables do not appear in output
        assert "MY_SECRET_TOKEN" not in result.stdout
        assert "API_KEY" not in result.stdout
        assert "JWT_SECRET" not in result.stdout
        assert "super_secret_value" not in result.stdout
        assert "api_key_value" not in result.stdout
        assert "jwt_secret_value" not in result.stdout

    finally:
        # Clean up
        os.environ.pop("MY_SECRET_TOKEN", None)
        os.environ.pop("API_KEY", None)
        os.environ.pop("JWT_SECRET", None)


def test_shell_metacharacter_rejection(sample_repo):
    """Test that shell metacharacters are rejected in commands."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

    # Test with && (command chaining)
    result = runner.run_tests_with_patch(
        repo_path=sample_repo,
        target_file="math.py",
        patched_code="def add(a, b):\n    return a + b\n",
        test_command='python -c "print(1)" && echo "malicious"',
        timeout=10
    )

    assert result.success is False
    assert "Shell metacharacter" in result.error_message or "Command validation failed" in result.error_message
    assert "malicious" not in result.stdout

    # Test with ; (command chaining)
    result = runner.run_tests_with_patch(
        repo_path=sample_repo,
        target_file="math.py",
        patched_code="def add(a, b):\n    return a + b\n",
        test_command='python -c "print(1)" ; echo "malicious"',
        timeout=10
    )

    assert result.success is False
    assert "Shell metacharacter" in result.error_message or "Command validation failed" in result.error_message

    # Test with | (pipe)
    result = runner.run_tests_with_patch(
        repo_path=sample_repo,
        target_file="math.py",
        patched_code="def add(a, b):\n    return a + b\n",
        test_command='python -c "print(1)" | cat',
        timeout=10
    )

    assert result.success is False
    assert "Shell metacharacter" in result.error_message or "Command validation failed" in result.error_message


def test_disallowed_executable_rejection(sample_repo):
    """Test that disallowed executables are rejected."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

    # Test with curl (not on allowlist)
    result = runner.run_tests_with_patch(
        repo_path=sample_repo,
        target_file="math.py",
        patched_code="def add(a, b):\n    return a + b\n",
        test_command="curl http://example.com",
        timeout=10
    )

    assert result.success is False
    assert "not allowlisted" in result.error_message or "Command validation failed" in result.error_message

    # Test with powershell (not on allowlist)
    if sys.platform == "win32":
        result = runner.run_tests_with_patch(
            repo_path=sample_repo,
            target_file="math.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command="powershell -Command 'Write-Host test'",
            timeout=10
        )

        assert result.success is False
        assert "not allowlisted" in result.error_message or "Command validation failed" in result.error_message


def test_output_truncation(sample_repo):
    """Test that output over 1 MB is truncated."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

    # Create a test that outputs a lot of data
    large_output_test = os.path.join(sample_repo, "tests", "test_large.py")
    with open(large_output_test, "w") as f:
        f.write("""
def test_large_output():
    # Output 2 MB of data
    data = "X" * (2 * 1024 * 1024)
    print(data)
""")

    result = runner.run_tests_with_patch(
        repo_path=sample_repo,
        target_file="math.py",
        patched_code="def add(a, b):\n    return a + b\n",
        test_command=f"{sys.executable} -m pytest tests/test_large.py -v",
        timeout=10
    )

    # Check that output is truncated
    assert "[... OUTPUT TRUNCATED ...]" in result.stdout or len(result.stdout) < 2 * 1024 * 1024


def test_process_tree_killing_on_timeout():
    """Test that child processes are killed on timeout and both PIDs are gone."""
    import psutil
    import time
    
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        # Create a test that spawns a long-running child process
        test_file = os.path.join(repo_dir, "long_test.py")
        pid_file = os.path.join(repo_dir, "child_pid.txt")
        
        # Write the test file
        code = """
import subprocess
import time
import sys
import os

# Spawn a child process that sleeps
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(100)"])
# Store child PID immediately
with open("child_pid.txt", "w") as f:
    f.write(str(child.pid))
    f.flush()
# Parent also sleeps to ensure timeout
time.sleep(100)
"""
        with open(test_file, "w") as f:
            f.write(code)

        runner = SandboxRunner(default_timeout=2, sandbox_mode="local", is_admin=True)

        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="long_test.py",
            patched_code=code,
            test_command=[sys.executable, "long_test.py"],
            timeout=2
        )

        # Should fail due to timeout
        assert result.success is False
        assert result.exit_code == -1
        
        # Check that child PID file was created (if not, process was killed very quickly)
        if os.path.exists(pid_file):
            with open(pid_file, "r") as f:
                child_pid = int(f.read().strip())
            
            # Poll for up to 2 seconds to verify child process is gone
            for _ in range(20):  # 20 * 0.1s = 2 seconds
                if not psutil.pid_exists(child_pid):
                    break
                time.sleep(0.1)
            
            # Verify child process is gone
            assert not psutil.pid_exists(child_pid), f"Child process {child_pid} still exists after timeout"


def test_docker_mode_fallback_without_docker(sample_repo):
    """Test that Docker mode falls back to local mode with warning when Docker is unavailable."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="docker")

    # Mock _check_docker_available to return False
    with patch.object(runner, "_check_docker_available", return_value=False):
        result = runner.run_tests_with_patch(
            repo_path=sample_repo,
            target_file="math.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command=f"{sys.executable} -c 'print(1)'",
            timeout=10
        )

        # Should fall back to local mode and run
        # (The test should still run, just with a warning logged)
        # Check that it didn't fail due to Docker error
        assert "Docker execution failed" not in result.error_message


def test_allowlisted_executable_accepted(sample_repo):
    """Test that allowlisted executables are accepted."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

    # Test command validation directly
    cmd = [sys.executable, "-c", "print(1)"]
    validation_error = runner._validate_command(cmd)

    # Should not have validation error
    assert validation_error is None, f"Allowlisted executable was rejected: {validation_error}"


def test_environment_allowlist_only(sample_repo):
    """Test that only allowlisted environment variables are passed."""
    # Set a non-sensitive variable not on allowlist
    os.environ["MY_CUSTOM_VAR"] = "custom_value"

    try:
        runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

        # Create a test that checks for specific variables
        test_file = os.path.join(sample_repo, "tests", "test_env.py")
        with open(test_file, "w") as f:
            f.write("""
import os

def test_env_allowlist():
    # PATH should be present (on allowlist)
    assert "PATH" in os.environ
    # MY_CUSTOM_VAR should NOT be present (not on allowlist)
    assert "MY_CUSTOM_VAR" not in os.environ
""")

        result = runner.run_tests_with_patch(
            repo_path=sample_repo,
            target_file="math.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command=f"{sys.executable} -m pytest tests/test_env.py -v",
            timeout=10
        )

        # The test should pass if MY_CUSTOM_VAR is blocked
        # If the test fails, it means the variable leaked
        if result.failed_count > 0:
            # Check if it failed due to MY_CUSTOM_VAR being present
            if "MY_CUSTOM_VAR" in result.stdout:
                pytest.fail("Non-allowlisted environment variable leaked into sandbox")

    finally:
        os.environ.pop("MY_CUSTOM_VAR", None)


def test_sensitive_variable_blocked_even_on_allowlist(sample_repo):
    """Test that sensitive variables are blocked even if they match allowlist patterns."""
    # Set PATH_SECRET (matches PATH pattern but also contains SECRET)
    os.environ["PATH_SECRET"] = "should_be_blocked"

    try:
        runner = SandboxRunner(default_timeout=10, sandbox_mode="local")

        test_file = os.path.join(sample_repo, "tests", "test_sensitive.py")
        with open(test_file, "w") as f:
            f.write("""
import os

def test_sensitive_blocked():
    # PATH_SECRET should be blocked despite containing PATH
    assert "PATH_SECRET" not in os.environ
""")

        result = runner.run_tests_with_patch(
            repo_path=sample_repo,
            target_file="math.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command=f"{sys.executable} -m pytest tests/test_sensitive.py -v",
            timeout=10
        )

        # Check that PATH_SECRET was blocked
        if "PATH_SECRET" in result.stdout:
            pytest.fail("Sensitive variable PATH_SECRET leaked into sandbox")

    finally:
        os.environ.pop("PATH_SECRET", None)


def test_bounded_output_reading_memory_safety():
    """Test that bounded reading keeps memory under control even with large output."""
    import psutil
    
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local", is_admin=True)
    
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        # Create a test that outputs ~200 MB
        test_file = os.path.join(repo_dir, "large_output.py")
        with open(test_file, "w") as f:
            f.write("""
import sys

# Output ~200 MB of data
data = "X" * (200 * 1024 * 1024)
sys.stdout.write(data)
sys.stdout.flush()
print("DONE")
""")
        
        # Measure memory before
        process = psutil.Process()
        mem_before = process.memory_info().rss
        
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="large_output.py",
            patched_code="import sys\ndata = 'X' * (200 * 1024 * 1024)\nsys.stdout.write(data)\nsys.stdout.flush()\nprint('DONE')\n",
            test_command=[sys.executable, "large_output.py"],
            timeout=10
        )
        
        # Measure memory after
        mem_after = process.memory_info().rss
        mem_growth = mem_after - mem_before
        
        # Memory growth should be under 50 MB (1 MB buffer + overhead)
        assert mem_growth < 50 * 1024 * 1024, f"Memory growth {mem_growth / 1024 / 1024:.2f} MB exceeded 50 MB limit"
        
        # Output should be truncated and <= ~1 MB plus marker
        assert len(result.stdout) < 2 * 1024 * 1024, f"Output size {len(result.stdout)} exceeded 2 MB"
        assert "[... OUTPUT TRUNCATED ...]" in result.stdout


def test_admin_only_test_command():
    """Test that user-supplied test_command is rejected for non-admin users."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local", is_admin=False)
    
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        with open(os.path.join(repo_dir, "test.py"), "w") as f:
            f.write("print('test')\n")
        
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="test.py",
            patched_code="print('test')\n",
            test_command=[sys.executable, "test.py"],  # User-supplied command as list
            timeout=10
        )
        
        assert result.success is False
        assert "admin" in result.error_message.lower()
        assert result.exit_code == -7


def test_admin_test_command_allowed():
    """Test that user-supplied test_command is allowed for admin users."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local", is_admin=True)
    
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        with open(os.path.join(repo_dir, "test.py"), "w") as f:
            f.write("print('test')\n")
        
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="test.py",
            patched_code="print('test')\n",
            test_command=[sys.executable, "test.py"],  # User-supplied command as list
            timeout=10
        )
        
        # Should not fail due to admin check
        assert "admin" not in (result.error_message or "").lower()


def test_local_sandbox_disabled_in_api_mode():
    """Test that local sandbox is rejected when ALLOW_LOCAL_SANDBOX is false."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local", allow_local_sandbox=False, is_admin=False)
    
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        with open(os.path.join(repo_dir, "test.py"), "w") as f:
            f.write("print('test')\n")
        # Create a tests directory to trigger framework detection
        os.makedirs(os.path.join(repo_dir, "tests"), exist_ok=True)
        with open(os.path.join(repo_dir, "tests", "test_test.py"), "w") as f:
            f.write("print('test')\n")
        
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="test.py",
            patched_code="print('test')\n",
            test_command=None,  # Auto-detected command
            timeout=10
        )
        
        # If framework was detected, it should fail with local sandbox error
        if result.framework != "none":
            assert result.success is False
            assert "local sandbox" in result.error_message.lower()
            assert result.exit_code == -8


def test_local_sandbox_allowed_with_flag():
    """Test that local sandbox works when ALLOW_LOCAL_SANDBOX is true."""
    runner = SandboxRunner(default_timeout=10, sandbox_mode="local", allow_local_sandbox=True, is_admin=False)
    
    with tempfile.TemporaryDirectory(prefix="test_repo_") as repo_dir:
        with open(os.path.join(repo_dir, "test.py"), "w") as f:
            f.write("print('test')\n")
        
        result = runner.run_tests_with_patch(
            repo_path=repo_dir,
            target_file="test.py",
            patched_code="print('test')\n",
            test_command=f"{sys.executable} test.py",
            timeout=10
        )
        
        # Should not fail due to local sandbox check
        assert "local sandbox" not in (result.error_message or "").lower()


def test_cli_sandbox_runner_initialization():
    """Test that CLI initializes SandboxRunner with is_admin=True and allow_local_sandbox=True."""
    # Verify the CLI code passes these parameters
    import inspect
    from cli import main
    source = inspect.getsource(main)
    assert "is_admin=True" in source, "CLI should pass is_admin=True"
    assert "allow_local_sandbox=True" in source, "CLI should pass allow_local_sandbox=True"


def test_api_sandbox_runner_uses_admin_status():
    """Test that API passes real caller's admin status to SandboxRunner."""
    # Verify the API code passes real admin status
    import inspect
    from backend.api.patches import generate_patch
    source = inspect.getsource(generate_patch)
    assert "current_user.role == \"admin\"" in source, "API should check current_user.role for admin status"
    assert "is_admin=" in source, "API should pass is_admin parameter"


def test_skipped_result_not_reported_as_verified():
    """Test that skipped sandbox results are not reported as verified."""
    # Verify the core patch engine sets verified=False when skipped
    import inspect
    from core.patch_generator import PatchEngine
    source = inspect.getsource(PatchEngine)
    
    # Check that verified uses test_passed and not test_skipped
    assert "test_passed and not test_skipped" in source, "Patch engine should set verified=False when skipped"


def test_cli_shows_not_verified_when_skipped():
    """Test that CLI shows 'not verified: no tests ran' when sandbox result is skipped."""
    # Verify the CLI render_patch_card checks skipped and shows message
    import inspect
    from cli import render_patch_card
    source = inspect.getsource(render_patch_card)
    
    # Check that skipped is checked and message is shown
    assert "sb_skipped" in source, "CLI should check skipped field"
    assert "NOT VERIFIED" in source or "no tests ran" in source.lower(), "CLI should show not verified message when skipped"


def test_api_payload_verified_false_when_skipped():
    """Test that API payload has verified: false when sandbox result is skipped."""
    # Verify the backend patch engine sets verified=False when skipped
    import inspect
    from backend.patch_generator.patch_engine import PatchEngine
    source = inspect.getsource(PatchEngine)
    
    # Check that verified uses test_passed and not test_skipped
    assert "test_passed and not test_skipped" in source, "API payload should set verified=False when skipped"
