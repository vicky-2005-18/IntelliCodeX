"""
Unit and integration tests for IntelliCodeX CI/CD PR Review Bot.
Tests change detection, security scanning, architecture cycle detection,
dynamic coverage risk ranking, and GitHub markdown card formatting.
"""
import os
import tempfile
import json
import pytest

from scripts.pr_review_bot import (
    get_pr_changed_files,
    analyze_pr_changes,
    generate_pr_markdown_report,
)


@pytest.fixture
def disposable_repo():
    """Creates a temporary repository structure for PR bot testing."""
    with tempfile.TemporaryDirectory(prefix="icx_pr_bot_") as tmp_dir:
        # Create sample files
        pkg_dir = os.path.join(tmp_dir, "pkg")
        os.makedirs(pkg_dir, exist_ok=True)

        f_clean = os.path.join(pkg_dir, "clean_module.py")
        with open(f_clean, "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")

        f_sec = os.path.join(pkg_dir, "vuln_module.py")
        with open(f_sec, "w", encoding="utf-8") as f:
            # Contains hardcoded secret and eval (HIGH severity findings)
            f.write('API_KEY = "sk-live-1234567890abcdef1234567890abcdef"\ndef run_cmd(u):\n    eval(u)\n')

        # Create two cyclic files
        f_cyc_a = os.path.join(pkg_dir, "cycle_a.py")
        f_cyc_b = os.path.join(pkg_dir, "cycle_b.py")
        with open(f_cyc_a, "w", encoding="utf-8") as f:
            f.write("import pkg.cycle_b\ndef func_a():\n    return 1\n")
        with open(f_cyc_b, "w", encoding="utf-8") as f:
            f.write("import pkg.cycle_a\ndef func_b():\n    return 2\n")

        yield tmp_dir


def test_get_pr_changed_files_explicit():
    """Verifies that explicit file lists are normalized and preserved."""
    explicit = ["pkg\\clean_module.py", "./pkg/vuln_module.py"]
    res = get_pr_changed_files(".", explicit_files=explicit)
    assert res == ["pkg/clean_module.py", "pkg/vuln_module.py"]


def test_analyze_clean_pr_changes(disposable_repo):
    """Verifies that changes without vulnerabilities or cycles are APPROVED."""
    analysis = analyze_pr_changes(
        repo_path=disposable_repo,
        changed_files=["pkg/clean_module.py"],
        strict_security=True,
        fail_on_cycles=True,
    )
    assert analysis["verdict"] == "APPROVED"
    assert analysis["security"]["high_severity"] == 0
    assert analysis["architecture"]["total_cycles"] == 0

    md = generate_pr_markdown_report(analysis)
    assert "PASSED / APPROVED" in md
    assert "No security vulnerabilities" in md


def test_analyze_vulnerable_pr_changes_requests_changes(disposable_repo):
    """Verifies that a PR introducing high severity vulnerabilities is rejected (CHANGES_REQUESTED)."""
    analysis = analyze_pr_changes(
        repo_path=disposable_repo,
        changed_files=["pkg/vuln_module.py"],
        strict_security=True,
        fail_on_cycles=True,
    )
    assert analysis["verdict"] == "CHANGES_REQUESTED"
    assert analysis["security"]["high_severity"] >= 1
    assert any("HIGH severity security vulnerability" in r for r in analysis["reasons"])

    md = generate_pr_markdown_report(analysis)
    assert "CHANGES REQUESTED (BLOCKED)" in md
    assert "vuln_module.py" in md


def test_analyze_cyclic_dependency_pr_changes(disposable_repo):
    """Verifies that a PR participating in a circular dependency cycle is flagged."""
    analysis = analyze_pr_changes(
        repo_path=disposable_repo,
        changed_files=["pkg/cycle_a.py"],
        strict_security=False,
        fail_on_cycles=True,
    )
    # The cycle between cycle_a and cycle_b is detected
    cycles = analysis["architecture"]["cycles"]
    assert len(cycles) >= 1
    assert any("cycle_a" in str(c.get("cycle", [])) for c in cycles)
    assert analysis["verdict"] == "CHANGES_REQUESTED"

    md = generate_pr_markdown_report(analysis)
    assert "Circular Dependencies Involving PR Files" in md


def test_analyze_pr_with_dynamic_coverage_report(disposable_repo):
    """Verifies that PR analysis includes SBFL Ochiai risk scores when coverage is provided."""
    cov_path = os.path.join(disposable_repo, "cov_sample.json")
    with open(cov_path, "w", encoding="utf-8") as f:
        json.dump({
            "files": {
                "pkg/clean_module.py": {
                    "executed_lines": [1, 2],
                    "missing_lines": [],
                    "summary": {"covered_lines": 2}
                }
            }
        }, f)

    analysis = analyze_pr_changes(
        repo_path=disposable_repo,
        changed_files=["pkg/clean_module.py"],
        coverage_file=cov_path,
    )
    assert analysis["coverage"]["summary"] is not None

    md = generate_pr_markdown_report(analysis)
    assert "IntelliCodeX Autonomous PR Review Bot" in md
