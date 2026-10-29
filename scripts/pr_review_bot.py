"""
IntelliCodeX Automated CI/CD Pull Request Review Bot (REQ-FUT-06, REQ-FUT-05).
Analyzes pull request changes for:
1. Static security vulnerabilities (Bandit AST scan) and hardcoded credentials.
2. Architectural cycle regressions and module coupling bottlenecks.
3. Spectrum-based fault localization (SBFL) suspiciousness risk scoring.
Generates structured Markdown review cards and posts inline feedback on PRs.
"""
import os
import sys
import json
import argparse
import subprocess
from typing import List, Dict, Any, Optional, Set

# Ensure repo root is on sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.security_scanner import SecurityScanner
from core.architecture_optimizer import ArchitectureOptimizer
from core.pipeline import ingest_repository
from core.embedder import TfidfEmbedder
from core.bug_localizer import DynamicCoverageMatrix


def get_pr_changed_files(
    repo_path: str,
    base_ref: Optional[str] = None,
    explicit_files: Optional[List[str]] = None,
) -> List[str]:
    """
    Identifies files changed in the pull request.
    Uses explicit files if provided; otherwise queries git diff.
    """
    if explicit_files:
        return [f.replace("\\", "/").lstrip("./") for f in explicit_files]

    # Try git diff against base branch or HEAD~1
    diff_targets = []
    if base_ref:
        diff_targets.extend([f"origin/{base_ref}...HEAD", f"{base_ref}...HEAD"])
    diff_targets.extend(["HEAD~1...HEAD", "HEAD"])

    for target in diff_targets:
        try:
            cmd = ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", target]
            res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=True)
            files = [line.strip().replace("\\", "/").lstrip("./") for line in res.stdout.splitlines() if line.strip()]
            if files:
                return files
        except Exception:
            continue

    # Fallback: check git status uncommitted/modified files
    try:
        cmd = ["git", "status", "--porcelain"]
        res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=True)
        files = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if line:
                parts = line.split(maxsplit=1)
                if len(parts) == 2:
                    files.append(parts[1].replace("\\", "/").lstrip("./"))
        return files
    except Exception:
        return []


def analyze_pr_changes(
    repo_path: str,
    changed_files: List[str],
    coverage_file: Optional[str] = None,
    strict_security: bool = True,
    fail_on_cycles: bool = True,
) -> Dict[str, Any]:
    """
    Performs comprehensive PR analysis:
    - Security scanner on changed files
    - Architecture dependency optimizer on full codebase, filtering to changed files
    - Dynamic coverage matrix risk scoring (if coverage report supplied)
    """
    abs_repo = os.path.abspath(repo_path)
    norm_changed = [f.replace("\\", "/").lstrip("./") for f in changed_files]
    existing_changed = [f for f in norm_changed if os.path.exists(os.path.join(abs_repo, f))]

    # 1. Security Analysis on changed files
    scanner = SecurityScanner(severity_threshold="LOW", security_policy="strict")
    pr_security_findings = []
    if existing_changed:
        for f_rel in existing_changed:
            f_abs = os.path.join(abs_repo, f_rel)
            f_res = scanner.scan(f_abs, repo_root=abs_repo)
            for finding in f_res.get("findings", []):
                finding["file_path"] = finding.get("file", f_rel).replace("\\", "/").lstrip("./")
                finding["line_number"] = finding.get("line", 1)
                pr_security_findings.append(finding)
    else:
        repo_res = scanner.scan(abs_repo, repo_root=abs_repo)
        for finding in repo_res.get("findings", []):
            finding["file_path"] = finding.get("file", "").replace("\\", "/").lstrip("./")
            finding["line_number"] = finding.get("line", 1)
            pr_security_findings.append(finding)

    high_sec_count = sum(1 for f in pr_security_findings if str(f.get("severity")).upper() == "HIGH")
    med_sec_count = sum(1 for f in pr_security_findings if str(f.get("severity")).upper() == "MEDIUM")

    # 2. Architecture & Dependency Cycle Analysis
    embedder = TfidfEmbedder(dim=16)
    ingested = ingest_repository(abs_repo, embedder=embedder)
    arch_engine = ArchitectureOptimizer()
    arch_report = arch_engine.analyze(
        dep_graph=ingested.graph,
        source_files=ingested.files,
    )
    arch_dict = arch_report.to_dict()

    # Filter cycles to those involving modified files
    pr_cycles = []
    for cycle in arch_dict.get("cycles", []):
        c_files = [f.replace("\\", "/").lstrip("./") for f in cycle]
        if any(cf in norm_changed for cf in c_files):
            pr_cycles.append({"cycle": cycle})

    # Filter bottlenecks to modified files
    pr_bottlenecks = []
    for bn in arch_dict.get("bottlenecks", []):
        bn_mod = bn.get("module", "").replace("\\", "/").lstrip("./")
        if bn_mod in norm_changed:
            pr_bottlenecks.append(bn)

    # 3. Dynamic Coverage & Risk Scoring (SBFL)
    coverage_summary = None
    high_risk_elements = []
    if coverage_file and os.path.exists(coverage_file):
        try:
            cov_matrix = DynamicCoverageMatrix.from_pytest_cov_json(
                report_data=coverage_file,
                failing_files=existing_changed,
            )
            top_suspicious = cov_matrix.get_top_suspicious_elements("ochiai", top_k=10)
            # Filter to changed files
            for el in top_suspicious:
                el_id = el.get("element_id", "")
                if any(cf in el_id for cf in norm_changed):
                    high_risk_elements.append(el)
            coverage_summary = cov_matrix.summary()
        except Exception as e:
            coverage_summary = {"error": str(e)}

    # Determine overall PR verdict
    verdict = "APPROVED"
    reasons = []

    if strict_security and high_sec_count > 0:
        verdict = "CHANGES_REQUESTED"
        reasons.append(f"{high_sec_count} HIGH severity security vulnerability/credential detected.")
    elif fail_on_cycles and len(pr_cycles) > 0:
        verdict = "CHANGES_REQUESTED"
        reasons.append(f"{len(pr_cycles)} architectural circular dependency cycle(s) detected.")
    elif med_sec_count > 0 or len(pr_bottlenecks) > 0:
        verdict = "WARNINGS"
        if med_sec_count > 0:
            reasons.append(f"{med_sec_count} MEDIUM severity security warning(s).")
        if pr_bottlenecks:
            reasons.append(f"{len(pr_bottlenecks)} high-coupling module bottleneck(s).")
    else:
        reasons.append("All automated security gates and architectural cycle constraints satisfied.")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "changed_files": norm_changed,
        "security": {
            "total_findings": len(pr_security_findings),
            "high_severity": high_sec_count,
            "medium_severity": med_sec_count,
            "findings": pr_security_findings,
        },
        "architecture": {
            "total_cycles": len(pr_cycles),
            "cycles": pr_cycles,
            "bottlenecks": pr_bottlenecks,
        },
        "coverage": {
            "summary": coverage_summary,
            "high_risk_elements": high_risk_elements,
        },
    }


def generate_pr_markdown_report(analysis: Dict[str, Any], pr_title: str = "Pull Request") -> str:
    """Formats analysis results into a structured GitHub Pull Request Markdown review card."""
    verdict = analysis.get("verdict", "APPROVED")
    reasons = analysis.get("reasons", [])
    changed_files = analysis.get("changed_files", [])
    sec = analysis.get("security", {})
    arch = analysis.get("architecture", {})
    cov = analysis.get("coverage", {})

    status_badge = {
        "APPROVED": "✅ **PASSED / APPROVED**",
        "WARNINGS": "⚠️ **APPROVED WITH WARNINGS**",
        "CHANGES_REQUESTED": "❌ **CHANGES REQUESTED (BLOCKED)**",
    }.get(verdict, "ℹ️ **REVIEW NOTE**")

    lines = [
        "## 🤖 IntelliCodeX Autonomous PR Review Bot\n",
        f"### Verdict: {status_badge}\n",
        f"**Summary**: {' '.join(reasons)}\n",
        f"**Touched Files Analyzed**: `{len(changed_files)}` files\n",
    ]

    # Security Section
    sec_findings = sec.get("findings", [])
    lines.append("### 🔒 Security & Credential Audit")
    if not sec_findings:
        lines.append("✅ **Clean**: No security vulnerabilities or hardcoded secrets detected in modified files.\n")
    else:
        lines.append(f"Found **{len(sec_findings)}** security finding(s) (`{sec.get('high_severity', 0)}` HIGH, `{sec.get('medium_severity', 0)}` MEDIUM):\n")
        lines.append("| Severity | Rule | Location | Description | Remediation |")
        lines.append("|:---:|:---:|:---|:---|:---|")
        for f in sec_findings[:10]:
            sev = f.get("severity", "LOW")
            sev_icon = "🔴" if sev == "HIGH" else ("🟡" if sev == "MEDIUM" else "⚪")
            rule = f.get("rule_id", "SEC")
            loc = f"`{f.get('file_path')}:{f.get('line_number')}`"
            desc = f.get("explanation", "").replace("|", "-")
            rem = f.get("remediation", "").replace("|", "-")
            lines.append(f"| {sev_icon} **{sev}** | `{rule}` | {loc} | {desc} | {rem} |")
        lines.append("")

    # Architecture Section
    cycles = arch.get("cycles", [])
    bottlenecks = arch.get("bottlenecks", [])
    lines.append("### 🏛️ Architecture & Circular Dependency Audit")
    if not cycles and not bottlenecks:
        lines.append("✅ **Clean**: No circular dependency cycles or high-coupling bottlenecks introduced.\n")
    else:
        if cycles:
            lines.append(f"⚠️ **Circular Dependencies Involving PR Files ({len(cycles)})**:")
            for idx, c in enumerate(cycles, 1):
                cycle_str = " ➔ ".join(f"`{f}`" for f in c.get("cycle", []))
                lines.append(f"- **Cycle {idx}**: {cycle_str}")
                if c.get("recommendation"):
                    lines.append(f"  * *Refactoring Advice*: {c.get('recommendation')}")
            lines.append("")
        if bottlenecks:
            lines.append(f"⚠️ **High Coupling Bottlenecks ({len(bottlenecks)})**:")
            for b in bottlenecks:
                lines.append(f"- Module `{b.get('module')}`: Afferent $C_a={b.get('afferent_coupling')}$, Efferent $C_e={b.get('efferent_coupling')}$, Instability $I={b.get('instability', 0.0):.2f}$")
            lines.append("")

    # SBFL Spectrum Risk Assessment Section
    high_risk = cov.get("high_risk_elements", [])
    if high_risk:
        lines.append("### 📊 Spectrum-Based Risk Ranking (Ochiai SBFL)")
        lines.append("The following modified elements have execution history in failing tests:\n")
        lines.append("| Element | Ochiai Suspiciousness | Failing Execs ($e_f$) | Passing Execs ($e_p$) |")
        lines.append("|:---|:---:|:---:|:---:|")
        for el in high_risk[:5]:
            lines.append(f"| `{el.get('element_id')}` | **{el.get('ochiai'):.3f}** | {el.get('ef')} | {el.get('ep')} |")
        lines.append("")

    lines.append("---\n*Automated review generated by [IntelliCodeX](https://github.com/vicky-2005-18/IntelliCodeX) Continuous Maintenance Framework.*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="IntelliCodeX PR Review Bot")
    parser.add_argument("--repo", default=".", help="Target repository directory path")
    parser.add_argument("--base-ref", default=None, help="Base git branch reference (e.g. main, master)")
    parser.add_argument("--files", nargs="*", default=None, help="Specific list of modified files")
    parser.add_argument("--coverage", default=None, help="Path to pytest-cov JSON coverage report")
    parser.add_argument("--output-md", default="pr_review_comment.md", help="Output markdown path for PR comment")
    parser.add_argument("--output-json", default="pr_review.json", help="Output JSON analysis summary path")
    parser.add_argument("--strict", action="store_true", default=True, help="Fail workflow on HIGH security issues or cycles")
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo)
    print(f"[*] IntelliCodeX PR Review Bot starting for: {repo_path}")

    changed_files = get_pr_changed_files(repo_path, base_ref=args.base_ref, explicit_files=args.files)
    print(f"[*] Detected {len(changed_files)} modified file(s): {', '.join(changed_files[:5])}{'...' if len(changed_files) > 5 else ''}")

    analysis = analyze_pr_changes(
        repo_path=repo_path,
        changed_files=changed_files,
        coverage_file=args.coverage,
        strict_security=args.strict,
        fail_on_cycles=args.strict,
    )

    md_content = generate_pr_markdown_report(analysis)

    # Write output files
    if args.output_md:
        with open(args.output_md, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"[*] Generated PR review Markdown comment: {args.output_md}")

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2)
        print(f"[*] Generated PR review JSON report: {args.output_json}")

    # Output to GitHub Step Summary if running in GitHub Actions
    gh_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if gh_summary:
        try:
            with open(gh_summary, "a", encoding="utf-8") as f:
                f.write(f"\n{md_content}\n")
        except Exception as e:
            print(f"[!] Could not append to GITHUB_STEP_SUMMARY: {e}")

    print(f"\n[*] PR Review Verdict: {analysis['verdict']}")
    if analysis["verdict"] == "CHANGES_REQUESTED":
        print(f"[!] Blocking PR merge due to gate failures: {', '.join(analysis['reasons'])}")
        sys.exit(1)
    else:
        print(f"[+] PR Review passed verification gate.")
        sys.exit(0)


if __name__ == "__main__":
    main()
