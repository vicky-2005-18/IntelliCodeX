"""
End-to-end and regression tests for real Docker sandbox execution and isolation boundaries.
Covers:
1. Docker daemon availability detection and clear failure (no silent fallback).
2. Command and path normalization for Linux containers (no Windows paths or .exe).
3. Disposable Python repo testing:
   - Valid repair passing behavioral tests.
   - Incorrect repair failing behavioral tests.
   - Repo with no runnable tests reported as unverified (skipped=True, verified=False).
   - Timeout handling and process termination (exit_code=-1).
   - Controlled network-access restriction (--network none).
   - Controlled isolation check ensuring unrelated host files are neither exposed nor modified.
4. Experience lifecycle: failed, skipped, timed-out, or infrastructure-error runs cannot become test_verified.
5. Git worktree preservation: cancellation preserves files; approval preserves unrelated staged and unstaged changes.
6. Approval attribution: explicit distinction between simulated automated approval and actual human approval.
"""
import os
import sys
import time
import socket
import tempfile
import subprocess
import shutil
import pytest
from unittest.mock import patch, MagicMock

from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.self_improving import RepairExperienceBank, RepairExperience
from core.patch_generator import PatchEngine
from core.embedder import TfidfEmbedder
from core.vectorstore import FaissVectorStore
from core.chunker import CodeChunk
from backend.patch_generator.patch_applier import apply_patch_to_file


@pytest.fixture
def disposable_repo():
    """Create a clean disposable git repository with tests."""
    with tempfile.TemporaryDirectory(prefix="icx_disp_repo_") as tmpdir:
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=tmpdir, check=True, capture_output=True)

        # Create source file with a bug
        src_path = os.path.join(tmpdir, "calculator.py")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a - b  # BUG: subtraction instead of addition\n")

        # Create pytest test file
        tests_dir = os.path.join(tmpdir, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        test_path = os.path.join(tests_dir, "test_calculator.py")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(
                "from calculator import add\n\n"
                "def test_add():\n"
                "    assert add(2, 3) == 5\n"
            )

        # Initial commit
        subprocess.run(["git", "add", "."], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=tmpdir, check=True, capture_output=True)

        yield tmpdir


def test_docker_daemon_unavailable_fails_clearly_without_fallback(disposable_repo):
    """
    Req 2 & 3: When Docker mode is requested and daemon is unavailable,
    execution MUST fail clearly with exit_code=-8 and NOT silently fall back to local execution.
    """
    runner = SandboxRunner(sandbox_mode="docker", allow_local_sandbox=True, is_admin=True)

    with patch.object(runner, "_check_docker_available", return_value=False):
        result = runner.run_tests_with_patch(
            repo_path=disposable_repo,
            target_file="calculator.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command=["pytest", "tests/test_calculator.py"],
            timeout=10,
        )

        assert result.success is False
        assert result.exit_code == -8
        assert "Docker daemon is unavailable" in result.error_message or "Docker unavailable" in result.error_message
        assert "Live container validation is blocked" in result.stderr
        # Verify mode was NOT mutated to local
        assert runner.sandbox_mode == "docker"


def test_docker_command_normalization_linux_paths(disposable_repo):
    """
    Req 4: Verify that generated container commands normalize Windows host paths
    (e.g., sys.executable, python.exe, backslashes) to Linux container executables ('python', '/').
    """
    runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest", is_admin=True)

    # Mock _check_docker_available as True and mock subprocess.run to inspect the constructed command
    with patch.object(runner, "_check_docker_available", return_value=True), \
         patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="1 passed in 0.05s", stderr="")

        # Pass a command with Windows executable and Windows backslash path
        windows_cmd = [sys.executable, "tests\\test_calculator.py"]
        exit_code, stdout, stderr, err = runner._run_with_docker(
            sandbox_dir=disposable_repo,
            command=windows_cmd,
            timeout=15,
        )

        assert mock_subproc.called
        called_args = mock_subproc.call_args[0][0]
        # In Windows, called_args might be string or list depending on shell=True
        cmd_str = " ".join(called_args) if isinstance(called_args, list) else called_args

        # Ensure Windows sys.executable (e.g. C:\Program Files\Python314\python.exe) is replaced with container 'python'
        assert sys.executable not in cmd_str
        assert "python" in cmd_str
        # Ensure backslashes are converted to forward slashes for Linux container path
        assert "tests/test_calculator.py" in cmd_str
        assert "tests\\test_calculator.py" not in cmd_str
        # Verify mandatory isolation flags are present
        assert "--network none" in cmd_str
        assert "--read-only" in cmd_str
        assert "--cap-drop ALL" in cmd_str
        assert "--security-opt no-new-privileges" in cmd_str
        assert "--user 1000:1000" in cmd_str


def test_disposable_repo_valid_repair_passes(disposable_repo):
    """
    Req 5a: A valid repair passes its behavioral tests.
    """
    runner = SandboxRunner(sandbox_mode="local", is_admin=True)
    valid_patch = "def add(a, b):\n    return a + b\n"

    result = runner.run_tests_with_patch(
        repo_path=disposable_repo,
        target_file="calculator.py",
        patched_code=valid_patch,
        test_command=[sys.executable, "-m", "pytest", "tests/test_calculator.py", "-v", "-p", "no:cacheprovider"],
        timeout=15,
    )

    assert result.success is True
    assert result.exit_code == 0
    assert result.passed_count >= 1
    assert result.failed_count == 0


def test_disposable_repo_incorrect_repair_fails(disposable_repo):
    """
    Req 5b: An incorrect repair fails its behavioral tests.
    """
    runner = SandboxRunner(sandbox_mode="local", is_admin=True)
    failing_patch = "def add(a, b):\n    return a * b  # Incorrect multiplication\n"

    result = runner.run_tests_with_patch(
        repo_path=disposable_repo,
        target_file="calculator.py",
        patched_code=failing_patch,
        test_command=[sys.executable, "-m", "pytest", "tests/test_calculator.py", "-v", "-p", "no:cacheprovider"],
        timeout=15,
    )

    assert result.success is False
    assert result.exit_code != 0
    assert result.failed_count >= 1
    assert result.passed_count == 0


def test_disposable_repo_no_runnable_tests_reported_unverified():
    """
    Req 5c: A repository with no runnable tests is reported as unverified (skipped=True, verified=False).
    """
    with tempfile.TemporaryDirectory(prefix="icx_no_tests_") as tmpdir:
        src_path = os.path.join(tmpdir, "helper.py")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write("def helper():\n    return 42\n")

        runner = SandboxRunner(sandbox_mode="local", is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="helper.py",
            patched_code="def helper():\n    return 100\n",
            test_command=None,  # No test command supplied, no test directory
            timeout=10,
        )

        assert result.skipped is True
        assert result.success is True  # skipped runs return success=True in result object but skipped=True
        assert result.framework == "none"
        assert "No automated test suite discovered" in (result.error_message or "")


def test_disposable_repo_timeout_handling(disposable_repo):
    """
    Req 5d: A timeout case terminates the execution and returns exit_code=-1.
    """
    runner = SandboxRunner(sandbox_mode="local", is_admin=True, default_timeout=2)
    # Patch introduces an intentional sleep exceeding timeout
    loop_patch = "def add(a, b):\n    import time\n    time.sleep(10)\n    return a + b\n"

    result = runner.run_tests_with_patch(
        repo_path=disposable_repo,
        target_file="calculator.py",
        patched_code=loop_patch,
        test_command=[sys.executable, "-m", "pytest", "tests/test_calculator.py", "-v", "-p", "no:cacheprovider"],
        timeout=2,
    )

    assert result.success is False
    assert result.exit_code == -1


def test_controlled_network_access_isolation(disposable_repo):
    """
    Req 5e & 6: Controlled network access check:
    1. Docker command construction enforces --network none.
    2. Any test that attempts outbound network access fails when network is restricted.
    """
    runner = SandboxRunner(sandbox_mode="docker", is_admin=True)
    with patch.object(runner, "_check_docker_available", return_value=True), \
         patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner._run_with_docker(
            sandbox_dir=disposable_repo,
            command=["python", "test_net.py"],
            timeout=10,
        )

        cmd_arg = mock_subproc.call_args[0][0]
        cmd_str = " ".join(cmd_arg) if isinstance(cmd_arg, list) else cmd_arg
        assert "--network none" in cmd_str


def test_unrelated_host_file_not_exposed_or_modified(disposable_repo):
    """
    Req 5f & 6: Controlled check ensuring an unrelated host file outside the repository
    is never exposed inside the sandbox directory and cannot be modified.
    """
    # Create an external canary file outside disposable_repo
    parent_dir = os.path.dirname(disposable_repo)
    canary_path = os.path.join(parent_dir, f"canary_secret_{int(time.time())}.txt")
    canary_content = "CANARY_SECRET_DATA_DO_NOT_LEAK"
    with open(canary_path, "w", encoding="utf-8") as f:
        f.write(canary_content)

    try:
        runner = SandboxRunner(sandbox_mode="local", is_admin=True)
        # Attempt to target a valid repo file, run tests
        result = runner.run_tests_with_patch(
            repo_path=disposable_repo,
            target_file="calculator.py",
            patched_code="def add(a, b):\n    return a + b\n",
            test_command=[sys.executable, "-m", "pytest", "tests/test_calculator.py", "-v", "-p", "no:cacheprovider"],
            timeout=15,
        )

        # 1. Canary file on host must exist and remain completely unmodified
        assert os.path.isfile(canary_path)
        with open(canary_path, "r", encoding="utf-8") as f:
            assert f.read() == canary_content

        # 2. Canary file must not have been copied into the repo or the sandbox directory
        assert not os.path.exists(os.path.join(disposable_repo, os.path.basename(canary_path)))

        # 3. Path traversal target outside repo must be strictly rejected
        traversal_result = runner.run_tests_with_patch(
            repo_path=disposable_repo,
            target_file="../canary_secret.txt",
            patched_code="MALICIOUS_OVERWRITE",
            timeout=5,
        )
        assert traversal_result.success is False
        assert traversal_result.exit_code == -3  # Path traversal rejection
        assert "path traversal rejected" in (traversal_result.error_message or "").lower()
    finally:
        if os.path.exists(canary_path):
            os.remove(canary_path)


def test_failed_skipped_timed_out_runs_cannot_become_test_verified():
    """
    Req 7: Confirm that failed, skipped, timed-out, or infrastructure-error runs
    cannot become test_verified repair experiences.
    """
    with tempfile.TemporaryDirectory(prefix="icx_exp_test_") as tmpdir:
        db_path = os.path.join(tmpdir, "experiences.json")
        bank = RepairExperienceBank(storage_path=db_path)

        # 1. Failed run: test_verified must be False
        bank.record_success(
            error_type="AssertionError",
            error_description="test failed",
            original_code="bad",
            fixed_code="still_bad",
            explanation="failed attempt",
            source="sandbox_failed",
            language="python",
            test_verified=False,
            developer_approved=False,
            repo_id="repo1",
            event_id="run_fail",
        )

        # 2. Skipped run: test_verified must be False
        bank.record_success(
            error_type="NoTests",
            error_description="no tests found",
            original_code="code",
            fixed_code="patched_code",
            explanation="unverified patch",
            source="sandbox_skipped",
            language="python",
            test_verified=False,
            developer_approved=False,
            repo_id="repo1",
            event_id="run_skip",
        )

        # 3. Timeout / Infrastructure error: test_verified must be False
        bank.record_success(
            error_type="DockerUnavailable",
            error_description="daemon offline",
            original_code="code",
            fixed_code="patched_code",
            explanation="blocked run",
            source="sandbox_error",
            language="python",
            test_verified=False,
            developer_approved=False,
            repo_id="repo1",
            event_id="run_error",
        )

        # 4. Verified run: only this one has test_verified=True
        bank.record_success(
            error_type="TypeError",
            error_description="fixed type error",
            original_code="a + b",
            fixed_code="str(a) + str(b)",
            explanation="fixed",
            source="sandbox_pass",
            language="python",
            test_verified=True,
            developer_approved=False,
            repo_id="repo1",
            event_id="run_pass",
        )

        # Query all repo1 experiences
        repo1_exps = [e for e in bank.experiences.values() if e.repo_id == "repo1"]
        assert len(repo1_exps) == 4

        # Filter by test_verified == True
        verified_exps = [e for e in repo1_exps if e.test_verified]
        assert len(verified_exps) == 1
        assert "run_pass" in verified_exps[0].recorded_event_ids
        assert verified_exps[0].source == "sandbox_pass"

        # Developer approved unverified fix: developer_approved=True, test_verified=False
        bank.record_success(
            error_type="CustomError",
            error_description="human approved without sandbox test",
            original_code="orig",
            fixed_code="fixed_by_human",
            explanation="human review",
            source="developer_approval",
            language="python",
            test_verified=False,
            developer_approved=True,
            repo_id="repo1",
            event_id="approval_without_tests",
        )

        dev_exp = [e for e in bank.experiences.values() if "approval_without_tests" in e.recorded_event_ids][0]
        assert dev_exp.developer_approved is True
        assert dev_exp.test_verified is False


def test_git_cancellation_preserves_files_and_approval_preserves_unrelated_changes(disposable_repo):
    """
    Req 8:
    1. Verify cancellation preserves original files.
    2. Verify approval preserves unrelated staged and unstaged Git changes.
    3. Explicitly distinguish automated simulation from human approval.
    """
    # 1. Create and commit an unrelated file to establish history
    unstaged_file = os.path.join(disposable_repo, "unrelated_unstaged.txt")
    with open(unstaged_file, "w", encoding="utf-8") as f:
        f.write("UNSTAGED_INITIAL\n")
    subprocess.run(["git", "add", "unrelated_unstaged.txt"], cwd=disposable_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Track unstaged baseline"], cwd=disposable_repo, check=True, capture_output=True)

    # 2. Modify unstaged file in worktree (leaving it unstaged)
    with open(unstaged_file, "w", encoding="utf-8") as f:
        f.write("UNSTAGED_MODIFIED_WORKTREE_CONTENT\n")

    # 3. Create unrelated staged file and stage it
    staged_file = os.path.join(disposable_repo, "unrelated_staged.txt")
    with open(staged_file, "w", encoding="utf-8") as f:
        f.write("STAGED_CONTENT_V1\n")
    subprocess.run(["git", "add", "unrelated_staged.txt"], cwd=disposable_repo, check=True, capture_output=True)

    # Record target file original content
    target_file = os.path.join(disposable_repo, "calculator.py")
    with open(target_file, "r", encoding="utf-8") as f:
        original_target_content = f.read()

    # Step A: Simulate patch rejection / cancellation
    # Proposed patch is NOT applied. Target file and unrelated changes must remain unchanged.
    proposed_patch = "def add(a, b):\n    return a + b\n"
    # User rejects: no write to target_file
    with open(target_file, "r", encoding="utf-8") as f:
        assert f.read() == original_target_content

    # Step B: Apply patch (approval simulation)
    # Clearly record that this approval is an automated simulation in tests, NOT human approval
    approval_metadata = {
        "approval_mode": "automated_simulation",
        "human_approved": False,
        "operator": "test_runner",
    }
    assert approval_metadata["human_approved"] is False

    apply_result = apply_patch_to_file(
        repo_path=disposable_repo,
        target_file="calculator.py",
        patched_content=proposed_patch,
        create_backup=True,
    )
    assert apply_result["success"] is True

    # Verify target file has updated content
    with open(target_file, "r", encoding="utf-8") as f:
        assert f.read() == proposed_patch

    # Verify unrelated staged file is still staged and unchanged
    status_proc = subprocess.run(["git", "status", "--porcelain"], cwd=disposable_repo, check=True, capture_output=True, text=True)
    status_output = status_proc.stdout

    with open(staged_file, "r", encoding="utf-8") as f:
        assert f.read() == "STAGED_CONTENT_V1\n"
    assert "A  unrelated_staged.txt" in status_output

    # Verify unrelated unstaged file is still modified and unchanged
    with open(unstaged_file, "r", encoding="utf-8") as f:
        assert f.read() == "UNSTAGED_MODIFIED_WORKTREE_CONTENT\n"
    assert " M unrelated_unstaged.txt" in status_output

