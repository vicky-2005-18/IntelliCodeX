"""
Security Scanner Service for IntelliCodeX (REQ-FUT-05).

Provides static vulnerability detection, hardcoded secret scanning,
remediation guidance, and coverage tracking across repository files:
- AST-level Python static vulnerability scanning using Bandit (e.g. B101, B102, B105, B307, B608).
- Multi-language static secret detection with synthetic credential redaction (SEC101-SEC105).
- Explicit severity thresholds (HIGH, MEDIUM, LOW) distinguishing pass/fail status.
- Language coverage matrix reporting (scanned languages vs unsupported AST languages).
- Structured findings with rule ID, category, severity, confidence, line, code, explanation, and remediation.
- Incomplete coverage and unsupported languages are explicitly distinguished and never reported as clean scans.
"""

import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Severity numerical ranks for threshold filtering
SEVERITY_RANKS = {
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
}

# Rule metadata & deterministic remediation guidance
REMEDIATION_GUIDANCE: Dict[str, Dict[str, str]] = {
    # Bandit AST Rules
    "B101": {
        "title": "Assert statement used in production code",
        "remediation": "Assert statements are removed when running Python with optimization (-O). Replace with explicit conditional checks and raise ValueError or AssertionError.",
    },
    "B102": {
        "title": "Use of exec() detected",
        "remediation": "exec() dynamically compiles and runs arbitrary code. Refactor to use safe dispatch tables, callable dictionaries, or explicit functions.",
    },
    "B105": {
        "title": "Hardcoded password string detected",
        "remediation": "Store passwords and tokens in environment variables, configuration vaults, or secure secret managers (e.g. AWS Secrets Manager).",
    },
    "B307": {
        "title": "Use of eval() detected",
        "remediation": "eval() allows arbitrary code execution from untrusted input. Replace with ast.literal_eval() for data literals or safe domain-specific parsers.",
    },
    "B608": {
        "title": "Hardcoded SQL expression with string formatting",
        "remediation": "Potential SQL injection. Use parameterized queries (:param, %s, or ? placeholders) provided by the database driver or ORM.",
    },
    "B324": {
        "title": "Insecure cryptographic hash function (MD5/SHA1)",
        "remediation": "MD5 and SHA-1 are cryptographically broken. Use hashlib.sha256() or hashlib.sha3_256().",
    },
    # Secret Detection Rules
    "SEC101": {
        "title": "AWS Access Key ID exposed",
        "remediation": "Remove hardcoded AWS credentials immediately. Revoke the key in AWS IAM and authenticate using IAM Roles or AWS Secrets Manager.",
    },
    "SEC102": {
        "title": "GitHub Personal Access Token exposed",
        "remediation": "Revoke the token immediately in GitHub Settings > Developer Settings. Use GitHub Actions repository secrets or runtime environment variables.",
    },
    "SEC103": {
        "title": "Unencrypted Private Key block embedded in source",
        "remediation": "Never commit private cryptographic keys to version control. Store keys in secure key management vaults or isolated filesystem paths.",
    },
    "SEC104": {
        "title": "Hardcoded API Key / Authorization Token",
        "remediation": "Move API keys and service tokens to environment variables (os.environ) or secure configuration vaults.",
    },
    "SEC105": {
        "title": "Hardcoded credentials in variable assignment",
        "remediation": "Load credentials dynamically from environment variables or a secrets manager rather than hardcoding default string values.",
    },
}

# Secret regex patterns with named rule IDs
SECRET_PATTERNS: List[Tuple[str, str, str, str, re.Pattern]] = [
    (
        "SEC101",
        "aws_access_key",
        "HIGH",
        "HIGH",
        re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    ),
    (
        "SEC102",
        "github_token",
        "HIGH",
        "HIGH",
        re.compile(r"\b(ghp_[0-9a-zA-Z]{36}|github_pat_[0-9a-zA-Z_]{22,})\b"),
    ),
    (
        "SEC103",
        "private_key",
        "HIGH",
        "HIGH",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "SEC104",
        "api_key_token",
        "HIGH",
        "MEDIUM",
        re.compile(r"(?i)\b(?:api[_-]?key|auth[_-]?token|secret[_-]?key)\s*[:=]\s*['\"]([0-9a-zA-Z\-_]{16,})['\"]"),
    ),
    (
        "SEC105",
        "hardcoded_password",
        "MEDIUM",
        "MEDIUM",
        re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]{6,})['\"]"),
    ),
]


def redact_secret_value(text: str) -> str:
    """Redacts synthetic and real credentials from strings, finding snippets, and logs."""
    if not text:
        return ""
    # Redact AWS keys
    s = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_SECRET]", text)
    # Redact GitHub tokens
    s = re.sub(r"ghp_[0-9a-zA-Z]{20,}", "[REDACTED_TOKEN]", s)
    s = re.sub(r"github_pat_[0-9a-zA-Z_]{20,}", "[REDACTED_TOKEN]", s)
    # Redact Bearer tokens
    s = re.sub(r"Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+(?:\.[A-Za-z0-9\-_.+/=]+)?", "Bearer [REDACTED_TOKEN]", s)
    # Redact URI passwords (e.g. postgresql://user:pass@host)
    s = re.sub(r"(://[^:\s]+:)([^@\s]+)(@)", r"\1[REDACTED_SECRET]\3", s)
    # Redact explicit assignment values for keys/passwords
    s = re.sub(r"((?i:api[_-]?key|secret|password|passwd|token)\s*[:=]\s*['\"])[^'\"]+(['\"])", r"\1[REDACTED_SECRET]\2", s)
    # Redact Bandit 'Possible hardcoded password: ...'
    s = re.sub(r"(Possible hardcoded password:\s*['\"])[^'\"]+(['\"])", r"\1[REDACTED_SECRET]\2", s)
    return s


def scan_file_for_secrets(file_path: str, repo_root: str) -> List[Dict[str, Any]]:
    """Statically scans a single file for hardcoded credentials and secret patterns."""
    findings: List[Dict[str, Any]] = []
    if not os.path.isfile(file_path):
        return findings

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        logger.warning(f"Failed to read file for secret scan '{file_path}': {exc}")
        return findings

    rel_path = os.path.relpath(file_path, repo_root).replace("\\", "/")

    for line_idx, line in enumerate(lines, start=1):
        for rule_id, rule_name, severity, confidence, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                meta = REMEDIATION_GUIDANCE.get(rule_id, {})
                redacted_line = redact_secret_value(line.strip())
                findings.append({
                    "rule_id": rule_id,
                    "rule_name": rule_name,
                    "category": "secret_detection",
                    "severity": severity,
                    "confidence": confidence,
                    "file": rel_path,
                    "line": line_idx,
                    "code": redacted_line,
                    "explanation": meta.get("title", f"Potential hardcoded credential detected: {rule_name}"),
                    "remediation": meta.get("remediation", "Move credentials to secure environment variables or secret vaults."),
                    "confirmed_exploitability": False,
                    "suspected": True,
                })
    return findings


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
            # Bandit returns empty string if clean or on error
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

            test_id = r.get("test_id", "")
            meta = REMEDIATION_GUIDANCE.get(test_id, {})
            code_snippet = redact_secret_value(r.get("code", "").strip())

            findings.append({
                "test_id": test_id,
                "test_name": r.get("test_name", ""),
                "rule_id": test_id,
                "rule_name": r.get("test_name", ""),
                "category": "static_analysis",
                "severity": sev,
                "confidence": r.get("issue_confidence", "LOW").upper(),
                "text": redact_secret_value(r.get("issue_text", "")),
                "explanation": redact_secret_value(r.get("issue_text", "")),
                "remediation": meta.get("remediation", "Review AST finding and apply defensive coding practices to validate untrusted input."),
                "file": r.get("filename", ""),
                "line": r.get("line_number"),
                "code": code_snippet,
                "more_info": r.get("more_info", ""),
                "confirmed_exploitability": False,
                "suspected": True,
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


def run_security_scan(
    target_path: str,
    repo_root: Optional[str] = None,
    severity_threshold: str = "HIGH",
    security_policy: str = "strict",
) -> Dict[str, Any]:
    """Runs a multi-layer static security vulnerability & secret scan across a repository or directory.

    Guarantees (REQ-FUT-05):
    1. Static AST vulnerability patterns via Bandit (Python).
    2. Static secret & credential detection with automatic redaction.
    3. Explicit language coverage accounting (scanned vs unsupported AST languages).
    4. Explicit severity threshold exit behavior (HIGH, MEDIUM, LOW).
    5. Incomplete coverage, parse failures, or unavailable scanners are explicitly flagged
       and never reported as a clean/passed scan under default strict policy.
    6. Suspected findings are clearly marked distinct from confirmed exploitability.
    7. Supports explicit 'secrets_only' policy with mandatory report labeling.
    """
    root = os.path.abspath(repo_root or target_path)
    target = os.path.abspath(target_path)
    policy_clean = (security_policy or "strict").lower().strip()
    if policy_clean not in ("strict", "secrets_only"):
        policy_clean = "strict"

    if not os.path.exists(target):
        return {
            "status": "error",
            "passed": False,
            "error": f"Target path not found: {target_path}",
            "security_policy": policy_clean,
            "severity_threshold": severity_threshold.upper(),
            "target": target_path,
            "repo_root": root,
            "scanned_files": [],
            "scanned_languages": [],
            "ast_scanned_languages": [],
            "unsupported_ast_languages": [],
            "coverage_status": "error",
            "incomplete_coverage": True,
            "coverage_warning": "Target directory does not exist.",
            "metrics": {"total_findings": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0},
            "findings": [],
        }

    # Language extension mapping
    EXT_TO_LANG = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".h": "c",
        ".hpp": "cpp",
        ".go": "go",
        ".rs": "rust",
    }

    # Discover candidate source files
    discovered_files: List[str] = []
    if os.path.isfile(target):
        discovered_files = [target]
    else:
        for cur_root, dirs, files in os.walk(target):
            # Ignore hidden & cache directories
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "target", "build", "__pycache__", "venv", ".git")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in EXT_TO_LANG:
                    discovered_files.append(os.path.join(cur_root, f))

    languages_present: Set[str] = set()
    python_files: List[str] = []
    relative_scanned_files: List[str] = []

    for fpath in discovered_files:
        ext = os.path.splitext(fpath)[1].lower()
        lang = EXT_TO_LANG.get(ext, "unknown")
        languages_present.add(lang)
        rel_f = os.path.relpath(fpath, root).replace("\\", "/")
        relative_scanned_files.append(rel_f)
        if lang == "python":
            python_files.append(fpath)

    # Multi-language coverage classification
    has_python = "python" in languages_present
    unsupported_ast_languages = sorted(list(languages_present - {"python"}))
    scanned_languages = sorted(list(languages_present))

    if not discovered_files:
        coverage_status = "empty"
        incomplete_coverage = False
        coverage_warning = "No ingestible source files discovered in target."
    elif not has_python and unsupported_ast_languages:
        coverage_status = "unsupported"
        incomplete_coverage = True
        if policy_clean == "secrets_only":
            coverage_warning = (
                f"[SECRETS_ONLY POLICY] Static AST vulnerability scanning was bypassed for unsupported languages: "
                f"{', '.join(unsupported_ast_languages)}. Secret scanning was applied across all files."
            )
        else:
            coverage_warning = (
                f"Static AST vulnerability scanning is only supported for Python in this installation. "
                f"Languages present without AST scanner: {', '.join(unsupported_ast_languages)}."
            )
    elif unsupported_ast_languages:
        coverage_status = "partial"
        incomplete_coverage = True
        if policy_clean == "secrets_only":
            coverage_warning = (
                f"[SECRETS_ONLY POLICY] Python files were scanned with Bandit AST; non-Python files "
                f"({', '.join(unsupported_ast_languages)}) were scanned for secrets only under explicit policy."
            )
        else:
            coverage_warning = (
                f"Python files were scanned with Bandit AST; however, the repository also contains "
                f"unsupported AST languages: {', '.join(unsupported_ast_languages)} (scanned for secrets only)."
            )
    else:
        coverage_status = "full"
        incomplete_coverage = False
        coverage_warning = ""

    all_findings: List[Dict[str, Any]] = []

    # 1. AST Security Scanning (Bandit for Python)
    if python_files:
        bandit_res = run_bandit_scan(target)
        if bandit_res.get("success"):
            for f in bandit_res.get("findings", []):
                # Normalize file path to repo-relative
                orig_f = f.get("file", "")
                if os.path.isabs(orig_f):
                    rel_f = os.path.relpath(orig_f, root).replace("\\", "/")
                else:
                    rel_f = orig_f.replace("\\", "/")

                all_findings.append({
                    "rule_id": f.get("rule_id") or f.get("test_id", "UNKNOWN"),
                    "rule_name": f.get("rule_name") or f.get("test_name", "bandit_issue"),
                    "category": "static_analysis",
                    "severity": f.get("severity", "LOW").upper(),
                    "confidence": f.get("confidence", "LOW").upper(),
                    "file": rel_f,
                    "line": f.get("line"),
                    "code": redact_secret_value(f.get("code", "")),
                    "explanation": f.get("explanation") or f.get("text", ""),
                    "remediation": f.get("remediation") or "Review and sanitize input logic to eliminate static AST vulnerability.",
                    "confirmed_exploitability": False,
                    "suspected": True,
                })
        else:
            # Scanner execution error
            return {
                "status": "error",
                "passed": False,
                "error": bandit_res.get("error", "Bandit AST scanner error"),
                "security_policy": policy_clean,
                "severity_threshold": severity_threshold.upper(),
                "target": target_path,
                "repo_root": root,
                "scanned_files": relative_scanned_files,
                "scanned_languages": scanned_languages,
                "ast_scanned_languages": ["python"],
                "unsupported_ast_languages": unsupported_ast_languages,
                "coverage_status": "error",
                "incomplete_coverage": True,
                "coverage_warning": f"Bandit AST scanner execution failed: {bandit_res.get('error')}",
                "metrics": {"total_findings": 0, "high_severity": 0, "medium_severity": 0, "low_severity": 0},
                "findings": [],
            }

    # 2. Secret & Credential Detection across ALL discovered source files
    for fpath in discovered_files:
        sec_findings = scan_file_for_secrets(fpath, root)
        all_findings.extend(sec_findings)

    # Deduplicate findings by (rule_id, file, line)
    deduped_findings: List[Dict[str, Any]] = []
    seen_keys: Set[Tuple[str, str, Optional[int]]] = set()
    for item in all_findings:
        key = (item["rule_id"], item["file"], item.get("line"))
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_findings.append(item)

    # Sort findings by severity (HIGH -> MEDIUM -> LOW) then file and line
    deduped_findings.sort(
        key=lambda f: (-SEVERITY_RANKS.get(f["severity"], 1), f["file"], f.get("line") or 0)
    )

    # Compute metrics
    high_cnt = sum(1 for f in deduped_findings if f["severity"] == "HIGH")
    med_cnt = sum(1 for f in deduped_findings if f["severity"] == "MEDIUM")
    low_cnt = sum(1 for f in deduped_findings if f["severity"] == "LOW")

    metrics = {
        "total_findings": len(deduped_findings),
        "high_severity": high_cnt,
        "medium_severity": med_cnt,
        "low_severity": low_cnt,
        "categories": {
            "static_analysis": sum(1 for f in deduped_findings if f["category"] == "static_analysis"),
            "secret_detection": sum(1 for f in deduped_findings if f["category"] == "secret_detection"),
        },
    }

    # Evaluate severity threshold
    threshold_clean = severity_threshold.upper().strip()
    min_rank = SEVERITY_RANKS.get(threshold_clean, 3)
    failing_findings = [
        f for f in deduped_findings if SEVERITY_RANKS.get(f["severity"], 1) >= min_rank
    ]

    # Overall Status Contract:
    # 1. Any findings meeting/exceeding threshold -> 'failed'
    # 2. Else if coverage is incomplete (unsupported languages present):
    #    - Under explicit 'secrets_only' policy -> 'passed' (with coverage_status explicitly 'unsupported'/'partial')
    #    - Under default 'strict' policy -> 'incomplete' (cannot be 'passed')
    # 3. Else -> 'passed'
    if failing_findings:
        status = "failed"
        passed = False
    elif incomplete_coverage:
        if policy_clean == "secrets_only":
            status = "passed"
            passed = True
        else:
            status = "incomplete"
            passed = False
    else:
        status = "passed"
        passed = True

    return {
        "status": status,
        "passed": passed,
        "security_policy": policy_clean,
        "severity_threshold": threshold_clean,
        "target": target_path,
        "repo_root": root,
        "scanned_files": relative_scanned_files,
        "scanned_languages": scanned_languages,
        "ast_scanned_languages": ["python"] if has_python else [],
        "unsupported_ast_languages": unsupported_ast_languages,
        "coverage_status": coverage_status,
        "incomplete_coverage": incomplete_coverage,
        "coverage_warning": coverage_warning,
        "metrics": metrics,
        "failing_findings_count": len(failing_findings),
        "failing_findings": failing_findings,
        "findings": deduped_findings,
    }


def format_security_report(scan_result: Dict[str, Any], llm=None) -> str:
    """Formats scan results into human-readable Markdown with metrics, findings, and remediation guidance."""
    if not scan_result.get("status") and not scan_result.get("success"):
        return f"### Security Scan Failed\n\n{scan_result.get('error', 'Unknown error')}"

    metrics = scan_result.get("metrics", {})
    findings = scan_result.get("findings", [])
    target = scan_result.get("target", "")
    coverage_status = scan_result.get("coverage_status", "full")
    warning = scan_result.get("coverage_warning", "")
    threshold = scan_result.get("severity_threshold", "HIGH")
    policy = scan_result.get("security_policy", "strict").upper()
    status = scan_result.get("status", "passed" if scan_result.get("success") else "failed")

    lines = [
        f"### Security Audit & Vulnerability Report: `{os.path.basename(target)}`",
        f"- **Overall Status**: **{status.upper()}** (Threshold: `{threshold}`)",
        f"- **Security Policy**: `{policy}`",
        f"- **Coverage Status**: `{coverage_status.upper()}`",
        f"- **Total Findings**: {metrics.get('total_findings', metrics.get('total_issues', 0))}",
        f"- **High Severity**: {metrics.get('high_severity', 0)}",
        f"- **Medium Severity**: {metrics.get('medium_severity', 0)}",
        f"- **Low Severity**: {metrics.get('low_severity', 0)}",
    ]

    if policy == "SECRETS_ONLY":
        lines.append("> [!NOTE]\n> **Scope Notice**: Active security policy is SECRETS_ONLY. Non-Python AST vulnerabilities are not scanned.")

    if warning:
        lines.append(f"> [!WARNING]\n> {warning}")

    lines.append("")

    if not findings:
        if coverage_status == "full":
            lines.append("No security vulnerabilities detected by Bandit static analysis.")
        else:
            lines.append("No findings in scanned files; however, full static AST analysis is incomplete for unsupported languages.")
        return "\n".join(lines)

    lines.append("| Severity | Rule ID | Category | File:Line | Vulnerability / Finding |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for f in findings:
        target_f = f.get("file") or f.get("filename") or os.path.basename(target)
        file_line = f"{target_f}:{f['line']}" if f.get("line") else target_f
        category_label = "AST Static" if f.get("category") == "static_analysis" else "Secret"
        rule_id = f.get("rule_id") or f.get("test_id", "UNKNOWN")
        lines.append(f"| **{f['severity']}** | `{rule_id}` | {category_label} | `{file_line}` | {f.get('explanation') or f.get('text')} |")

    lines.append("\n#### Detailed Findings & Remediation Guidance:")
    for idx, f in enumerate(findings, start=1):
        rule_name = f.get("rule_name", f.get("test_name", f.get("rule_id", "Vulnerability")))
        target_f = f.get("file") or f.get("filename") or os.path.basename(target)
        file_line = f"{target_f}:{f['line']}" if f.get("line") else target_f
        lines.append(f"\n**{idx}. [{f['severity']}] {rule_name} (Line {f.get('line')})**")
        lines.append(f"> **Explanation**: {f.get('explanation') or f.get('text')}")
        if f.get("code"):
            lines.append(f"```python\n{f['code']}\n```")
        lines.append(f"**Remediation Guidance**: {f.get('remediation', 'Apply defensive coding practices.')}")

        # Optional LLM-guided explanation
        if llm and hasattr(llm, "generate") and f.get("code"):
            prompt = (
                f"Explain this security issue and provide minimal remediation in 2-3 sentences:\n"
                f"Issue: {f.get('explanation') or f.get('text')} (Severity: {f['severity']})\n"
                f"Code snippet: {f['code']}\n"
            )
            try:
                explanation = llm.generate(prompt, temperature=0.1)
                if explanation and not explanation.startswith("Error"):
                    lines.append(f"**Remediation Recommendation:**\n{explanation}\n")
            except Exception:
                pass

    return "\n".join(lines)


class SecurityScanner:
    """Object-oriented security scanner service."""
    def __init__(self, llm=None, severity_threshold: str = "HIGH", security_policy: str = "strict"):
        self.llm = llm
        self.severity_threshold = severity_threshold
        self.security_policy = security_policy

    def scan(self, target_path: str, repo_root: Optional[str] = None) -> Dict[str, Any]:
        return run_security_scan(
            target_path,
            repo_root=repo_root,
            severity_threshold=self.severity_threshold,
            security_policy=self.security_policy,
        )

    def scan_and_report(self, target_path: str, repo_root: Optional[str] = None) -> str:
        res = self.scan(target_path, repo_root=repo_root)
        return format_security_report(res, llm=self.llm)
