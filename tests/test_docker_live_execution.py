"""
Live Docker Container Execution Tests for IntelliCodeX
These tests execute real containers against Docker Desktop Linux Engine
without mocking Docker availability or execution.
"""
import os
import sys
import time
import subprocess
import tempfile
import pytest

from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.self_improving import RepairExperienceBank

IMAGE_NAME = "intellicodex-sandbox:latest"


def is_live_docker_available() -> bool:
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    return runner._check_docker_available()


pytestmark = pytest.mark.skipif(
    not is_live_docker_available(),
    reason="Live Docker daemon is not running on this host"
)


def get_active_sandbox_containers() -> list:
    res = subprocess.run(
        ["docker", "ps", "-a", "--filter", "name=icx-sandbox", "--format", "{{.ID}} {{.Names}} {{.Status}}"],
        capture_output=True,
        text=True
    )
    return [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]


@pytest.fixture
def live_disposable_repo():
    with tempfile.TemporaryDirectory(prefix="icx_live_repo_") as repo_dir:
        src_file = os.path.join(repo_dir, "math_ops.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def multiply(a, b):\n    return a + b  # BUG: addition instead of multiplication\n")

        tests_dir = os.path.join(repo_dir, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        test_file = os.path.join(tests_dir, "test_math_ops.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(
                "from math_ops import multiply\n\n"
                "def test_multiply():\n"
                "    assert multiply(3, 4) == 12\n"
            )
        yield repo_dir


def test_live_docker_correct_repair_passes(live_disposable_repo):
    """Live container validation: correct repair passes behavioral tests inside container."""
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    valid_patch = "def multiply(a, b):\n    return a * b\n"

    result = runner.run_tests_with_patch(
        repo_path=live_disposable_repo,
        target_file="math_ops.py",
        patched_code=valid_patch,
        test_command=["pytest", "tests/test_math_ops.py", "-v", "-p", "no:cacheprovider"],
        timeout=15,
    )

    assert result.success is True
    assert result.exit_code == 0
    assert result.passed_count >= 1
    assert result.failed_count == 0


def test_live_docker_incorrect_repair_fails(live_disposable_repo):
    """Live container validation: incorrect repair fails behavioral tests inside container."""
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    invalid_patch = "def multiply(a, b):\n    return a - b\n"

    result = runner.run_tests_with_patch(
        repo_path=live_disposable_repo,
        target_file="math_ops.py",
        patched_code=invalid_patch,
        test_command=["pytest", "tests/test_math_ops.py", "-v", "-p", "no:cacheprovider"],
        timeout=15,
    )

    assert result.success is False
    assert result.exit_code != 0
    assert result.failed_count >= 1
    assert any("assert -1 == 12" in err for err in result.assertion_errors)


def test_live_docker_no_runnable_tests_reported_unverified():
    """Live container validation: repo with no runnable tests is reported unverified."""
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    with tempfile.TemporaryDirectory(prefix="icx_live_notests_") as no_tests_dir:
        f_path = os.path.join(no_tests_dir, "lib.py")
        with open(f_path, "w", encoding="utf-8") as f:
            f.write("def foo(): return 1\n")

        result = runner.run_tests_with_patch(
            repo_path=no_tests_dir,
            target_file="lib.py",
            patched_code="def foo(): return 2\n",
            test_command=None,
            timeout=10,
        )

        assert result.skipped is True
        assert result.framework == "none"
        assert "No automated test suite discovered" in (result.error_message or "")


def test_live_docker_timeout_and_container_cleanup(live_disposable_repo):
    """Live container validation: timeout terminates and leaves no running container."""
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True, default_timeout=3)
    timeout_patch = "def multiply(a, b):\n    import time\n    time.sleep(30)\n    return a * b\n"

    result = runner.run_tests_with_patch(
        repo_path=live_disposable_repo,
        target_file="math_ops.py",
        patched_code=timeout_patch,
        test_command=["pytest", "tests/test_math_ops.py", "-v", "-p", "no:cacheprovider"],
        timeout=3,
    )

    assert result.exit_code == -1
    assert result.success is False

    # Verify the specific container created for this test was not leaked
    target_container = getattr(result, "container_name", None) or getattr(runner, "last_container_name", None)
    assert target_container, "Container name should be tracked for docker execution"
    time.sleep(1)
    ps_chk = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"name={target_container}"],
        capture_output=True,
        text=True,
    )
    assert ps_chk.stdout.strip() == "", f"Container {target_container} was leaked"


def test_live_docker_controlled_network_restriction(live_disposable_repo):
    """Live container validation: network call is blocked inside container."""
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    net_test = os.path.join(live_disposable_repo, "tests", "test_network.py")
    with open(net_test, "w", encoding="utf-8") as f:
        f.write(
            "import socket\n"
            "import pytest\n\n"
            "def test_egress_blocked():\n"
            "    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "    s.settimeout(2.0)\n"
            "    with pytest.raises(OSError):\n"
            "        s.connect(('8.8.8.8', 53))\n"
        )

    valid_patch = "def multiply(a, b):\n    return a * b\n"
    result = runner.run_tests_with_patch(
        repo_path=live_disposable_repo,
        target_file="math_ops.py",
        patched_code=valid_patch,
        test_command=["pytest", "tests/test_network.py", "-v", "-p", "no:cacheprovider"],
        timeout=10,
    )

    assert result.success is True
    assert result.passed_count == 1


def test_live_docker_controlled_host_isolation_and_readonly_rootfs(live_disposable_repo):
    """Live container validation: host file is unexposed and container rootfs is read-only."""
    runner = SandboxRunner(sandbox_mode="docker", docker_image=IMAGE_NAME, is_admin=True)
    host_canary = os.path.join(tempfile.gettempdir(), f"host_canary_{int(time.time())}.txt")
    with open(host_canary, "w", encoding="utf-8") as f:
        f.write("HOST_CANARY_SECRET_DATA")

    try:
        iso_test = os.path.join(live_disposable_repo, "tests", "test_iso.py")
        with open(iso_test, "w", encoding="utf-8") as f:
            f.write(
                "import os\n\n"
                "def test_fs_isolation():\n"
                f"    assert not os.path.exists('/work/{os.path.basename(host_canary)}')\n"
                "    try:\n"
                "        with open('/etc/probe.txt', 'w') as f:\n"
                "            f.write('fail')\n"
                "        assert False, 'Should fail to write to read-only rootfs'\n"
                "    except OSError:\n"
                "        pass\n"
            )

        valid_patch = "def multiply(a, b):\n    return a * b\n"
        result = runner.run_tests_with_patch(
            repo_path=live_disposable_repo,
            target_file="math_ops.py",
            patched_code=valid_patch,
            test_command=["pytest", "tests/test_iso.py", "-v", "-p", "no:cacheprovider"],
            timeout=10,
        )

        assert result.success is True
        assert result.passed_count == 1
        with open(host_canary, "r", encoding="utf-8") as f:
            assert f.read() == "HOST_CANARY_SECRET_DATA"
    finally:
        if os.path.exists(host_canary):
            os.remove(host_canary)
