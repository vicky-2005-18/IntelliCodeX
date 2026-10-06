"""
Security Scanner Service for IntelliCodeX (Phase 4).
Performs AST-level Python security vulnerability scanning using Bandit,
and wraps results with optional grounded LLM remediation explanations.
"""
import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def run_bandit_scan(target_path: str) -> Dict[str, Any]:
    """Runs Bandit static security scanner on a target file or directory.
    
    Returns structured dictionary with metrics, findings, and exit status.
    """
    if not os.path.exists(target_path):
        return {
            "success": False,
            "target": target_path,
            "error": f"Path not found: {target_path}",
            "findings": [],
            "metrics": {},
        }

    cmd = [sys.executable, "-m", "bandit", "-r", target_path, "-f", "json", "-q"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        out = proc.stdout.strip()
        if not out:
            # Bandit returns nothing if clean or on error
            return {
                "success": True,
                "target": target_path,
                "findings": [],
                "metrics": {"total_issues": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0},
            }

        data = json.loads(out)
        raw_results = data.get("results", [])
        findings = []
        high_cnt = 0
        med_cnt = 0
        low_cnt = 0

        for r in raw_results:
            sev = r.get("issue_severity", "LOW").upper()
            if sev == "HIGH":
                high_cnt += 1
            elif sev == "MEDIUM":
                med_cnt += 1
            else:
                low_cnt += 1

            findings.append({
                "test_id": r.get("test_id"),
                "test_name": r.get("test_name"),
                "severity": sev,
                "confidence": r.get("issue_confidence", "LOW").upper(),
                "text": r.get("issue_text", ""),
                "file": r.get("filename", ""),
                "line": r.get("line_number"),
                "code": r.get("code", "").strip(),
                "more_info": r.get("more_info", ""),
            })

        return {
            "success": True,
            "target": target_path,
            "findings": findings,
            "metrics": {
                "total_issues": len(findings),
                "high_severity": high_cnt,
                "medium_severity": med_cnt,
                "low_severity": low_cnt,
            },
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "target": target_path,
            "error": "Bandit scanner timed out after 60s",
            "findings": [],
            "metrics": {},
        }
    except Exception as e:
        return {
            "success": False,
            "target": target_path,
            "error": f"Error running security scan: {e}",
            "findings": [],
            "metrics": {},
        }


def format_security_report(scan_result: Dict[str, Any], llm=None) -> str:
    """Formats scan results into human-readable Markdown with optional LLM advice."""
    if not scan_result.get("success"):
        return f"### Security Scan Failed\n\n{scan_result.get('error', 'Unknown error')}"

    metrics = scan_result.get("metrics", {})
    findings = scan_result.get("findings", [])
    target = scan_result.get("target", "")

    lines = [
        f"### Security Audit Report: `{os.path.basename(target)}`",
        f"- **Total Issues Found**: {metrics.get('total_issues', 0)}",
        f"- **High Severity**: {metrics.get('high_severity', 0)}",
        f"- **Medium Severity**: {metrics.get('medium_severity', 0)}",
        f"- **Low Severity**: {metrics.get('low_severity', 0)}",
        "",
    ]

    if not findings:
        lines.append("No security vulnerabilities detected by Bandit static analysis.")
        return "\n".join(lines)

    lines.append("| Severity | ID | Line | Vulnerability Description |")
    lines.append("| :--- | :--- | :---: | :--- |")
    for f in findings:
        lines.append(f"| **{f['severity']}** | `{f['test_id']}` | {f['line']} | {f['text']} |")

    lines.append("\n#### Detailed Findings:")
    for idx, f in enumerate(findings, start=1):
        lines.append(f"\n**{idx}. [{f['severity']}] {f['test_name']} (Line {f['line']})**")
        lines.append(f"> {f['text']}")
        if f.get("code"):
            lines.append(f"```python\n{f['code']}\n```")

        # Use LLM strictly to explain findings and recommend remediation if available
        if llm and hasattr(llm, "generate") and f.get("code"):
            prompt = (
                f"Explain this security issue and provide minimal remediation in 2-3 sentences:\n"
                f"Issue: {f['text']} (Severity: {f['severity']})\n"
                f"Code snippet: {f['code']}\n"
            )
            try:
                explanation = llm.generate(prompt, temperature=0.1)
                if explanation and not explanation.startswith("Error"):
                    lines.append(f"**Remediation Recommendation:**\n{explanation}\n")
            except Exception:
                pass

    return "\n".join(lines)
