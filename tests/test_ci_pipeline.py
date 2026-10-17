"""
CI/CD Pipeline Integration Tests (REQ-FUT-04).

Validates the non-interactive CI/CD pipeline entry point in `cli.py`:
1. Passing candidate patch on disposable fixture (exit code 0, verified=True).
2. Failing candidate patch on disposable fixture (exit code 1, verified=False).
3. Zero-test / unverified fixture (exit code 1, verified=False, outcome="skipped" / no tests).
4. Missing patch file or missing repo argument (exit code 2, configuration error).
5. Unsupported runtime or offline Docker daemon (exit code 2, infrastructure error).
6. Non-destructive guarantee: host repository files are never modified.
7. Machine-readable JSON report schema, outcome, diagnostics, and test counts.
8. GitHub Actions workflow YAML syntax, permissions, and structure validation.
"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch
import pytest
import yaml

import cli
from cli import (
    EXIT_SUCCESS,
    EXIT_VERIFICATION_FAILURE,
    EXIT_INFRA_OR_CONFIG_ERROR,
    _apply_diff_to_text,
    _write_ci_report,
    run_ci_pipeline,
    main,
)


@pytest.fixture
def disposable_python_repo():
    """Creates a temporary, disposable Python repository with a passing test suite."""
    temp_dir = tempfile.mkdtemp(prefix="icx_ci_test_repo_")
    src_dir = os.path.join(temp_dir, "pkg")
    test_dir = os.path.join(temp_dir, "tests")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)

    calc_file = os.path.join(src_dir, "calc.py")
    with open(calc_file, "w", encoding="utf-8") as f:
        f.write("def add(a: int, b: int) -> int:\n    return a + b\n")

    test_file = os.path.join(test_dir, "test_calc.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("from pkg.calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")

    init_src = os.path.join(src_dir, "__init__.py")
    with open(init_src, "w", encoding="utf-8") as f:
        f.write("")

    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


# =========================================================================
# 1. Exit Codes & Invariant Checks
# =========================================================================

def test_ci_constants():
    """Verify standard exit code contract values."""
    assert EXIT_SUCCESS == 0
    assert EXIT_VERIFICATION_FAILURE == 1
    assert EXIT_INFRA_OR_CONFIG_ERROR == 2


def test_ci_diff_application():
    """Verify unified diff application helper."""
    original = "line 1\nline 2\nline 3\n"
    diff = "--- a/file.py\n+++ b/file.py\n@@ -1,3 +1,3 @@\n line 1\n-line 2\n+line two\n line 3\n"
    patched = _apply_diff_to_text(original, diff)
    assert "line two" in patched
    assert "line 2" not in patched


def test_ci_diff_application_fallback_on_unrecognized():
    """When patch text is not a unified diff, it is treated as full replacement content."""
    original = "old code"
    replacement = "def new_code(): pass"
    res = _apply_diff_to_text(original, replacement)
    assert res == replacement


# =========================================================================
# 2. Pipeline Execution on Disposable Fixtures
# =========================================================================

def test_ci_pipeline_passing_fixture_invariance(disposable_python_repo, monkeypatch):
    """Passing patch achieves exit code 0, verified=True, and leaves host files untouched."""
    report_file = os.path.join(disposable_python_repo, "ci_report.json")
    original_calc = os.path.join(disposable_python_repo, "pkg", "calc.py")
    with open(original_calc, "r", encoding="utf-8") as f:
        initial_content = f.read()

    # Safe patch adding a docstring
    patch_text = "def add(a: int, b: int) -> int:\n    \"\"\"Sum two integers.\"\"\"\n    return a + b\n"

    cli_args = [
        "cli.py",
        disposable_python_repo,
        "--backend", "tfidf",
        "--ci",
        "--target-file", "pkg/calc.py",
        "--patch", patch_text,
        "--runtime", "python",
        "--sandbox", "docker",
        "--output-json", report_file,
    ]

    with patch("sys.argv", cli_args):
        exit_code = main()

    assert exit_code == EXIT_SUCCESS

    # Invariance check: original repository file is NOT modified
    with open(original_calc, "r", encoding="utf-8") as f:
        final_content = f.read()
    assert initial_content == final_content, "Host repository file was mutated!"

    # Machine-readable report verification
    assert os.path.isfile(report_file)
    with open(report_file, "r", encoding="utf-8") as f:
        report = json.load(f)

    assert report["pipeline_exit_code"] == 0
    assert report["ci_status"] == "success"
    assert report["patch_verification"]["tested"] is True
    assert report["patch_verification"]["verified"] is True
    assert report["patch_verification"]["test_counts"]["passed"] >= 1
    assert report["patch_verification"]["test_counts"]["failed"] == 0


def test_ci_pipeline_failing_fixture(disposable_python_repo):
    """Failing candidate patch must yield exit code 1, verified=False."""
    report_file = os.path.join(disposable_python_repo, "ci_report_fail.json")
    buggy_patch = "def add(a: int, b: int) -> int:\n    return a - b\n"

    cli_args = [
        "cli.py",
        disposable_python_repo,
        "--backend", "tfidf",
        "--ci",
        "--target-file", "pkg/calc.py",
        "--patch", buggy_patch,
        "--runtime", "python",
        "--sandbox", "docker",
        "--output-json", report_file,
    ]

    with patch("sys.argv", cli_args):
        exit_code = main()

    assert exit_code == EXIT_VERIFICATION_FAILURE

    assert os.path.isfile(report_file)
    with open(report_file, "r", encoding="utf-8") as f:
        report = json.load(f)

    assert report["pipeline_exit_code"] == 1
    assert report["ci_status"] == "failed"
    assert report["patch_verification"]["verified"] is False
    assert report["patch_verification"]["test_counts"]["failed"] >= 1


def test_ci_pipeline_zero_tests_fixture():
    """Repository without tests must NOT appear as verified repair (exit code 1)."""
    with tempfile.TemporaryDirectory(prefix="icx_zero_test_repo_") as empty_test_repo:
        src_file = os.path.join(empty_test_repo, "dummy.py")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write("def foo():\n    return 42\n")

        report_file = os.path.join(empty_test_repo, "ci_report_zero.json")
        patch_text = "def foo():\n    return 100\n"

        cli_args = [
            "cli.py",
            empty_test_repo,
            "--backend", "tfidf",
            "--ci",
            "--target-file", "dummy.py",
            "--patch", patch_text,
            "--runtime", "python",
            "--sandbox", "docker",
            "--output-json", report_file,
        ]

        with patch("sys.argv", cli_args):
            exit_code = main()

        assert exit_code == EXIT_VERIFICATION_FAILURE

        assert os.path.isfile(report_file)
        with open(report_file, "r", encoding="utf-8") as f:
            report = json.load(f)

        assert report["pipeline_exit_code"] == 1
        assert report["patch_verification"]["verified"] is False
        assert report["patch_verification"]["outcome"] in ("skipped", "failed", "behavioral_skipped")


# =========================================================================
# 3. Infrastructure & Configuration Errors (Exit Code 2)
# =========================================================================

def test_ci_missing_patch_file_returns_exit_code_2(disposable_python_repo):
    """Missing patch file yields configuration error exit code 2."""
    cli_args = [
        "cli.py",
        disposable_python_repo,
        "--backend", "tfidf",
        "--ci",
        "--target-file", "pkg/calc.py",
        "--patch-file", "nonexistent_patch_file.patch",
        "--runtime", "python",
    ]
    with patch("sys.argv", cli_args):
        exit_code = main()
    assert exit_code == EXIT_INFRA_OR_CONFIG_ERROR


def test_ci_invalid_runtime_returns_exit_code_2(disposable_python_repo):
    """Unsupported runtime yields configuration error exit code 2."""
    cli_args = [
        "cli.py",
        disposable_python_repo,
        "--backend", "tfidf",
        "--ci",
        "--target-file", "pkg/calc.py",
        "--patch", "def add(): pass",
        "--runtime", "unsupported_lang_xyz",
    ]
    with patch("sys.argv", cli_args):
        exit_code = main()
    assert exit_code == EXIT_INFRA_OR_CONFIG_ERROR


def test_ci_docker_daemon_offline_returns_exit_code_2(disposable_python_repo, monkeypatch):
    """When Docker daemon is unavailable, CI pipeline exits with exit code 2 (infrastructure error)."""
    from core import sandbox_runner
    monkeypatch.setattr(sandbox_runner.SandboxRunner, "_check_docker_available", staticmethod(lambda: False))
    monkeypatch.setattr(sandbox_runner, "_check_docker_available", lambda: False)

    cli_args = [
        "cli.py",
        disposable_python_repo,
        "--backend", "tfidf",
        "--ci",
        "--target-file", "pkg/calc.py",
        "--patch", "def add(): pass",
        "--runtime", "python",
        "--sandbox", "docker",
    ]
    with patch("sys.argv", cli_args):
        exit_code = main()
    assert exit_code == EXIT_INFRA_OR_CONFIG_ERROR


def test_ci_nonexistent_repository_path_returns_exit_code_2():
    """Missing repository directory yields configuration error exit code 2."""
    cli_args = [
        "cli.py",
        "this_repo_does_not_exist_xyz123",
        "--backend", "tfidf",
        "--ci",
    ]
    with patch("sys.argv", cli_args):
        exit_code = main()
    assert exit_code == EXIT_INFRA_OR_CONFIG_ERROR


# =========================================================================
# 4. Machine-Readable Report Sanitization
# =========================================================================

def test_ci_report_sanitization():
    """Verify that credentials, tokens, and secret patterns are scrubbed from diagnostics."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        report_path = os.path.join(tmp_dir, "sanitized_report.json")
        diagnostics = [
            "Error on host: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret_token",
            "Database connection failed for postgresql://admin:super_secret_password@db:5432/main",
            "Clean test failure trace: AssertionError at line 42",
        ]
        _write_ci_report(
            output_path=report_path,
            status="failed",
            exit_code=1,
            repo_path="/repos/my_repo",
            analysis={"num_files": 5, "num_chunks": 10},
            patch_report={"tested": True, "verified": False, "diagnostics": diagnostics},
            failures=["Verification check failed"],
        )

        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        diag_str = json.dumps(data["patch_verification"]["diagnostics"])
        assert "super_secret_password" not in diag_str
        assert "secret_token" not in diag_str
        assert "[REDACTED_SECRET]" in diag_str or "[REDACTED_TOKEN]" in diag_str
        assert "AssertionError at line 42" in diag_str


# =========================================================================
# 5. GitHub Actions Workflow Configuration Validation
# =========================================================================

def test_github_actions_workflow_yaml_validity():
    """Validates syntax and security structure of .github/workflows/intellicodex.yml."""
    workflow_path = os.path.join(".github", "workflows", "intellicodex.yml")
    assert os.path.isfile(workflow_path), f"Workflow file not found at {workflow_path}"

    with open(workflow_path, "r", encoding="utf-8") as f:
        wf = yaml.safe_load(f)

    assert "name" in wf
    assert ("on" in wf or True in wf)
    assert "permissions" in wf
    # Minimal permission: only read access to contents
    assert wf["permissions"] == {"contents": "read"}

    # Must contain both unit analysis job and docker verification job
    jobs = wf.get("jobs", {})
    assert "static-analysis-and-unit-tests" in jobs
    assert "docker-sandbox-verification" in jobs

    # Docker sandbox verification job should depend on static/unit analysis
    docker_job = jobs["docker-sandbox-verification"]
    assert "needs" in docker_job
    assert "static-analysis-and-unit-tests" in docker_job["needs"]

    # Check runner
    assert docker_job["runs-on"] == "ubuntu-latest"


def test_ci_pipeline_patch_file_with_multiline_content(disposable_python_repo):
    """Verifies that --patch-file with real multiline Python content passes CI verification."""
    patch_file_path = os.path.join(disposable_python_repo, "patch_to_apply.py")
    with open(patch_file_path, "w", encoding="utf-8") as f:
        f.write(
            "def add(a: int, b: int) -> int:\n"
            "    \"\"\"Sum two integers with multiline docstring.\"\"\"\n"
            "    result = a + b\n"
            "    return result\n"
        )

    cli_args = [
        "cli.py",
        disposable_python_repo,
        "--backend", "tfidf",
        "--ci",
        "--target-file", "pkg/calc.py",
        "--patch-file", patch_file_path,
        "--runtime", "python",
        "--sandbox", "local",
    ]
    with patch("sys.argv", cli_args):
        exit_code = main()

    assert exit_code == EXIT_SUCCESS, f"Expected EXIT_SUCCESS (0), got {exit_code}"


def test_github_actions_workflow_uses_patch_file_fixture():
    """Verifies that .github/workflows/intellicodex.yml uses --patch-file instead of inline escaping."""
    workflow_path = os.path.join(".github", "workflows", "intellicodex.yml")
    with open(workflow_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "--patch-file .github/fixtures/utils_patch.py" in content, (
        "Workflow must use --patch-file with multiline fixture for shell-independent execution"
    )
    fixture_path = os.path.join(".github", "fixtures", "utils_patch.py")
    assert os.path.isfile(fixture_path), f"Fixture file must exist at {fixture_path}"
    with open(fixture_path, "r", encoding="utf-8") as f:
        fixture_content = f.read()
    assert "ci_verified" in fixture_content
