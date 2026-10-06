"""
Tests for Bandit AST Security Scanner (Phase 4).
Tests:
- Detection of AST vulnerabilities (B105 hardcoded passwords, B307 eval, B608 SQL formatting)
- Clean code reporting with 0 issues
- Markdown report formatting and LLM remediation advice
"""
import os
import tempfile
import pytest
from unittest.mock import MagicMock

from core.security_scanner import run_bandit_scan, format_security_report


def test_bandit_scan_vulnerable_python_file():
    """Verify Bandit catches hardcoded password and eval in Python code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "vulnerable.py")
        with open(test_file, "w") as f:
            f.write(
                "import os\n\n"
                "PASSWORD = 'SuperSecretPassword123!'\n"
                "def dangerous(user_input):\n"
                "    return eval(user_input)\n"
            )

        result = run_bandit_scan(test_file)
        assert result["success"] is True
        assert result["metrics"]["total_issues"] >= 1
        finding_tests = [f["test_name"] for f in result["findings"]]
        # Either hardcoded_password_string or eval_used
        assert any("eval" in t or "password" in t for t in finding_tests)


def test_bandit_scan_clean_python_file():
    """Verify clean file produces zero findings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "clean.py")
        with open(test_file, "w") as f:
            f.write(
                "def add(a: int, b: int) -> int:\n"
                "    return a + b\n"
            )

        result = run_bandit_scan(test_file)
        assert result["success"] is True
        assert result["metrics"]["total_issues"] == 0
        assert len(result["findings"]) == 0

        report = format_security_report(result)
        assert "No security vulnerabilities detected" in report


def test_format_security_report_with_mock_llm():
    """Verify format_security_report attaches LLM remediation advice."""
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Do not use eval(). Use ast.literal_eval() instead for safety."

    scan_result = {
        "success": True,
        "target": "server.py",
        "metrics": {"total_issues": 1, "high_severity": 1, "medium_severity": 0, "low_severity": 0},
        "findings": [{
            "test_id": "B307",
            "test_name": "eval",
            "severity": "HIGH",
            "line": 4,
            "text": "Use of possibly insecure function - consider using safer ast.literal_eval.",
            "code": "eval(data)",
        }],
    }

    report = format_security_report(scan_result, llm=mock_llm)
    assert "High Severity" in report
    assert "B307" in report
    assert "Remediation Recommendation" in report
    assert "ast.literal_eval" in report
    mock_llm.generate.assert_called_once()
