# Evidence: Security Vulnerability Detection & Patch Security Gate (REQ-FUT-05)

> **Requirement Reference**: REQ-FUT-05 (PDF Section VIII-B, p. 7)  
> **Status**: **Verified**  
> **Test Suite**: `tests/test_security_vulnerability_detection.py` (21/21 passed), `tests/test_security_scanner.py` (3/3 passed), `tests/test_ci_pipeline.py` (12/12 passed), `tests/test_cli.py` (27/27 passed); 63/63 tests passing across security & CI suites.  
> **Verification Date**: 2026-10-15  
> **Hardware & Environment**: AMD Ryzen 7 7445HS, 16 GB RAM, NVIDIA RTX 3050 Laptop GPU (4 GB VRAM), Windows 11 64-bit, Python 3.14.6, Docker Desktop 29.8.0.

---

## 1. Existing Functionality vs. Defects Fixed

| Area | Prior Implementation / Defect | Fixed Implementation & Guarantee |
| :--- | :--- | :--- |
| **CI AST Ratio** | `ast_ratio_percent` reported `0.0%` on valid repositories despite extracting 2 AST chunks out of 2 total chunks. | Added `@property ast_ratio_percent` to `IngestedRepository` in `core/pipeline.py` and dynamic fallback calculation in `cli.py`. 2 AST chunks out of 2 total chunks now evaluates cleanly to `100.0%`. |
| **Unified Diff Application** | Diff parsing lacked strict format separation: context lines and deletion lines were unchecked, and failed diffs risked corruption or silent misinterpretation. | Implemented `apply_unified_diff` with explicit format classification. Plain replacement content (no diff syntax) is preserved. Any text with diff syntax (`diff --git`, `---`, `+++`, `@@`) is strictly parsed: malformed hunks, mismatched context lines, mismatched deletion lines, and unexpected header target paths are explicitly rejected with exact failure reasons. A failed diff is **never silently reinterpreted as full-file replacement**. |
| **Security Capability Scope** | Bandit AST scanner existed only as a standalone Python script wrapper without secret scanning, explicit multi-language accounting, or structured remediation guidance. | Established a unified security scanning engine in `core/security_scanner.py` combining Bandit AST analysis with multi-language secret detection (`SEC101`-`SEC105`), structured remediation metadata, confidence metrics, and explicit severity threshold filtering. |
| **Suspected vs Confirmed** | Static findings were not explicitly differentiated from confirmed exploits. | Every finding explicitly sets `confirmed_exploitability: False` and `suspected: True` to reflect static heuristic limits. |
| **Secret Redaction** | Synthetic or committed credentials (AWS access keys, GitHub tokens, passwords) could leak in stdout, markdown reports, or JSON logs. | Built `redact_secret_value` with patterns scrubbing AWS Access Keys, GitHub Tokens, Bearer JWTs, URI credentials, explicit variable assignments, and Bandit issue texts across reports and logs. |
| **Language Coverage Matrix** | Non-Python repositories could be reported as a clean scan despite zero AST scanner coverage. | Implemented language discovery across 14 file extensions. If unsupported AST languages (JS, TS, Java, C/C++, Go, Rust) are present without AST rules, the scan is categorized as `partial` or `unsupported` with `incomplete_coverage: True`. Incomplete scans **cannot be reported as clean or passed** (`passed: False`, `status: "incomplete"`). |
| **Candidate Security Gate** | CI verified candidate patches against unit tests in Docker, but did not gate patches against security vulnerabilities introduced in the candidate code. | Candidate patches are applied to a temporary snapshot labeled `patched_disposable_snapshot` and evaluated against `run_security_scan`. If candidate code introduces high-severity vulnerabilities or hardcoded secrets, `patch_report["security_approved"] = False`, `patch_report["verified"] = False`, and CI exits with failure (`exit_code = 1`) even if unit tests pass. |
| **Repair Experience Metadata** | Self-improving experience bank recorded `success` on test pass without tracking security verification status. | Extended `RepairExperience` dataclass with `security_approved: bool = False`. Candidates failing the security gate are explicitly marked unapproved. |
| **Multi-Tenant REST API** | Analytics router lacked a dedicated security scan endpoint with repository ownership isolation. | Added `GET` and `POST` routes at `/api/analytics/{repo_id}/security` in `backend/api/analytics.py` protected by `get_repo_for_user(repo_id, current_user)`, rejecting cross-tenant access with `403 Forbidden`. |

---

## 2. Language / Rule Capability Matrix & Limitations

| Language / Domain | Detection Technique | Supported Rule IDs / Patterns | Severity | Confidence | Remediation Guidance Provided | Known Limitations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Python** | Static AST Inspection (Bandit) | `B101` (assert in prod), `B102` (exec), `B105` (hardcoded password), `B307` (eval), `B608` (SQL injection format), `B324` (insecure MD5/SHA1) | HIGH / MEDIUM / LOW | HIGH / MEDIUM / LOW | Yes (e.g. `ast.literal_eval`, parameterized queries, env vars) | Dynamic code generation, runtime monkeypatching, and external framework decorators are not resolved statically. |
| **All Languages** (Python, JS, TS, Java, C, C++, Go, Rust, etc.) | Static Pattern & Entropy Regex | `SEC101` (AWS Access Key ID `AKIA...`) | HIGH | HIGH | Yes (AWS IAM / Secrets Manager guidance) | Statically scans text; does not verify if synthetic key is live or active on AWS. |
| **All Languages** | Static Pattern Regex | `SEC102` (GitHub PAT `ghp_...`, `github_pat_...`) | HIGH | HIGH | Yes (GitHub Secrets / env var guidance) | Scans syntax patterns; does not query GitHub API to verify validity. |
| **All Languages** | Static Block Regex | `SEC103` (Private Key Block `-----BEGIN ... PRIVATE KEY-----`) | HIGH | HIGH | Yes (Key management vault guidance) | Unencrypted private keys in source only. Encrypted vaults not inspected. |
| **All Languages** | Heuristic Assignment Regex | `SEC104` (API Key / Auth Token assignment) | HIGH | MEDIUM | Yes (Environment variable guidance) | High entropy tokens in unusual variable names might evade heuristic regex. |
| **All Languages** | Heuristic Assignment Regex | `SEC105` (Hardcoded password / pwd / passwd) | MEDIUM | MEDIUM | Yes (Config vault guidance) | Common test variable names may yield suspected warnings; threshold filterable. |
| **JS / TS / Java / C / C++ / Go / Rust** | AST Vulnerability Scan | N/A | N/A | N/A | N/A | **Unsupported**: Dedicated static AST vulnerability analyzers (e.g. Semgrep, SpotBugs, Gosec, Clippy) are not bundled in this baseline installation. Files are scanned for secrets only and flagged as `partial` or `unsupported` coverage. |
| **Dependency Advisories** | Software Composition Analysis | N/A | N/A | N/A | N/A | Out of scope for static source scanner; external advisory databases (e.g. OSV, CVE API) are not queried offline. |
| **LLM Remediation** | Local Inference (Qwen 2.5) | Optional prompt-driven remediation diff synthesis | Informational | N/A | Yes | LLM remediation is non-deterministic and auxiliary; static findings remain primary ground truth. |

> [!WARNING]
> **Static Scanning Boundary**: A clean scan (`status: passed`, `0 findings`) proves only that no targeted static AST rules or credential patterns matched in the scanned files. It **does not prove the absolute absence of vulnerabilities, logical flaws, or zero-day exploits**.

---

## 3. Files Changed and Why

1. `core/pipeline.py`:
   - Added `@property def ast_ratio_percent(self) -> float` on `IngestedRepository` so the ratio of AST chunks to total chunks is dynamically and accurately computed (resolving the 0.0% reporting defect).
2. `core/security_scanner.py`:
   - Comprehensive multi-layer scanner service:
     - Multi-language source file discovery across 14 extensions.
     - AST Python scanning via Bandit with repo-relative path normalization.
     - Static secret scanning engine for `SEC101` through `SEC105`.
     - `redact_secret_value` helper scrubbing AWS keys, GitHub tokens, Bearer tokens, URI credentials, and variable assignments in finding snippets and reports.
     - Explicit severity thresholds (`HIGH`, `MEDIUM`, `LOW`) with fail/incomplete/pass contract.
     - Incomplete coverage and unsupported language tracking (flagged as `partial` or `unsupported`; never reported as clean).
     - Deterministic `REMEDIATION_GUIDANCE` mapping and markdown report formatter (`format_security_report`).
3. `cli.py`:
   - Implemented `apply_unified_diff(original_text, diff_text, expected_target_file=None)` strictly rejecting malformed diffs, mismatched context lines, mismatched deletion lines, and target path mismatches while preserving plain replacement code.
   - Updated `_apply_diff_to_text` to delegate cleanly to `apply_unified_diff`.
   - Updated `run_ci_pipeline` to:
     - Scan repository quality with `run_security_scan(repo_path, severity_threshold=security_threshold)`.
     - Create a temporary disposable snapshot labeled `patched_disposable_snapshot` when candidate patch verification is requested.
     - Run `run_security_scan` on the candidate snapshot and record `patch_report["security_status"]`, `patch_report["security_approved"]`, and `patch_report["candidate_snapshot"]`.
     - Gate candidate patch: if security gate fails, set `patch_report["verified"] = False` and fail CI pipeline (`exit_code = 1`) even if unit tests pass.
   - Added CLI arguments `--security` and `--security-threshold` (`HIGH`, `MEDIUM`, `LOW`).
   - Updated interactive command `security:` to invoke `run_security_scan` across repository or file.
   - Updated `_render_ci_summary` to display Candidate Snapshot and Patch Security Status.
4. `core/self_improving.py`:
   - Added `security_approved: bool = False` to `RepairExperience` dataclass, `from_dict`, and `record_success` method to ensure passing behavioral tests are never equated with security approval in repair experience metadata.
5. `backend/analytics/security_scanner.py`:
   - Re-exported `run_security_scan` and `format_security_report` for backend service callers.
6. `backend/api/analytics.py`:
   - Added `GET` and `POST` routes for `/api/analytics/{repo_id}/security` enforcing tenant isolation and ownership via `get_repo_for_user(repo_id, current_user)`, returning 403 on unauthorized cross-tenant requests.
7. `tests/test_security_vulnerability_detection.py`:
   - 15 regression and validation test cases covering AST ratio calculation, diff application error cases, vulnerable Python fixtures, safe counterpart false-positive checks, secret detection and redaction, threshold exit behavior, unsupported language coverage, candidate security gate failure despite passing unit tests, and multi-tenant REST API isolation.

---

## 4. Exact Commands, Expected Findings, and Actual Results

### Test Suite Execution
```powershell
& "C:\Program Files\Python314\python.exe" -m pytest tests/test_security_vulnerability_detection.py -v
```
**Expected Findings**: All 21 tests pass.
**Actual Output**:
```
tests/test_security_vulnerability_detection.py::test_ast_ratio_percent_calculation PASSED [  4%]
tests/test_security_vulnerability_detection.py::test_unified_diff_application_clean PASSED [  9%]
tests/test_security_vulnerability_detection.py::test_unified_diff_rejects_mismatched_context PASSED [ 14%]
tests/test_security_vulnerability_detection.py::test_unified_diff_rejects_mismatched_deletion PASSED [ 19%]
tests/test_security_vulnerability_detection.py::test_unified_diff_rejects_unexpected_target_path PASSED [ 23%]
tests/test_security_vulnerability_detection.py::test_unified_diff_rejects_malformed_diff PASSED [ 28%]
tests/test_security_vulnerability_detection.py::test_plain_replacement_code_preserved PASSED [ 33%]
tests/test_security_vulnerability_detection.py::test_failed_diff_never_falls_back_to_replacement PASSED [ 38%]
tests/test_security_vulnerability_detection.py::test_bandit_vulnerable_python_fixture PASSED [ 42%]
tests/test_security_vulnerability_detection.py::test_safe_counterpart_python_fixture PASSED [ 47%]
tests/test_security_vulnerability_detection.py::test_secret_detection_and_redaction PASSED [ 52%]
tests/test_security_vulnerability_detection.py::test_severity_threshold_filtering PASSED [ 57%]
tests/test_security_vulnerability_detection.py::test_incomplete_coverage_non_python_repo PASSED [ 61%]
tests/test_security_vulnerability_detection.py::test_candidate_patch_fails_security_gate_despite_passing_tests PASSED [ 66%]
tests/test_security_vulnerability_detection.py::test_rest_api_security_endpoint_authorization PASSED [ 71%]
tests/test_security_vulnerability_detection.py::test_matrix_scenario_1_tests_pass_supported_security_pass PASSED [ 76%]
tests/test_security_vulnerability_detection.py::test_matrix_scenario_3_tests_pass_incomplete_coverage_strict PASSED [ 80%]
tests/test_security_vulnerability_detection.py::test_matrix_scenario_4_tests_fail_security_pass PASSED [ 85%]
tests/test_security_vulnerability_detection.py::test_matrix_scenario_5_scanner_infrastructure_error PASSED [ 90%]
tests/test_security_vulnerability_detection.py::test_matrix_scenario_6_explicit_narrower_secrets_only_policy PASSED [ 95%]
tests/test_security_vulnerability_detection.py::test_matrix_scenario_7_historical_experience_provenance_and_exclusion PASSED [100%]

============================= 21 passed in 5.74s ==============================
```

### Full Regression Verification
```powershell
& "C:\Program Files\Python314\python.exe" -m pytest tests/test_security_scanner.py tests/test_ci_pipeline.py tests/test_cli.py -v
```
**Expected Findings**: All 42 tests pass across security scanner, CI pipeline, and CLI test suites.
**Actual Output**:
- `tests/test_security_scanner.py`: 3 passed.
- `tests/test_ci_pipeline.py`: 12 passed.
- `tests/test_cli.py`: 27 passed.
- Total: 42 passed in 11.67s (Combined with test_security_vulnerability_detection: 63/63 passed in 14.67s).

---

## 5. Outcome Matrix (7 Integration Scenarios)

The table below summarizes the exact behavior and field values across all 7 integration scenarios:

| # | Scenario | Behavioral Status | Behavioral Verified | Security Status | Security Coverage | Security Policy | Security Approved | Overall Policy | Verified Repair | Candidate Outcome | Exit Code |
| :-: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :-: |
| **1** | **Tests pass + supported security checks pass** | `passed` | `True` | `passed` | `full` | `strict` | `True` | `passed` | `True` | `passed` | `0` |
| **2** | **Tests pass + high-severity finding** | `passed` | `True` | `failed` | `full` | `strict` | `False` | `failed` | `False` | `security_rejected` | `1` |
| **3** | **Tests pass + incomplete AST coverage (strict)** | `passed` | `True` | `incomplete` | `unsupported` (or `partial`) | `strict` | `False` | `failed` | `False` | `incomplete_coverage` | `1` |
| **4** | **Tests fail + security checks pass** | `failed` | `False` | `passed` | `full` | `strict` | `True` | `failed` | `False` | `behavioral_failed` | `1` |
| **5** | **Security scanner execution/infrastructure error** | `untested` / `error` | `False` | `error` | `error` | `strict` | `False` | `failed` | `False` | `error` | `2` |
| **6** | **Explicit narrower policy (`secrets_only`)** | `passed` | `True` | `passed` | `unsupported` (labeled) | `secrets_only` | `True` | `passed` | `True` | `passed` | `0` |
| **7** | **Historical experience lacking security fields** | `test_verified` | `True` | `unscanned` | `unknown` | N/A | `False` (not retroapproved) | N/A | `False` for security gate | N/A | N/A |

### Key Guarantees:
1. **No Fact Overwriting**: Passing behavioral tests are **never overwritten as failed tests** when a security finding occurs. Both `behavioral_status: "passed"` and `security_status: "failed"` are recorded faithfully.
2. **Honest Incompleteness**: Unsupported AST languages under strict policy report `status: "incomplete"` and `outcome: "incomplete_coverage"` (exit code 1). They are **never reported as a clean scan**.
3. **Infrastructure Error Separation**: Scanner execution crashes or timeouts yield `status: "error"` and exit code 2 (`EXIT_INFRA_OR_CONFIG_ERROR`), distinct from policy rejections (exit code 1).
4. **Experience Provenance**:
   - Historical records lacking security metadata load with `security_status: "unscanned"` and `security_approved: False`. They are **never retroactively approved**.
   - `retrieve_few_shots` excludes security-rejected candidates (`security_status == "failed"`) from standard few-shot retrieval.
   - Calling `retrieve_few_shots(require_security_approved=True)` retrieves only verified repairs, safely filtering out unscanned historical records without breaking regular behavioral matching.
   - `PatchEngine` (`generate_and_verify_patch`) never records candidates with `security_status == "failed"` to `RepairExperienceBank`.

---

## 6. CLI Usage & Policy Examples

### A. Repository Security Scan (Default Strict Policy)
```powershell
python cli.py path/to/repo --security --security-threshold HIGH
```
- Scans Python files with Bandit AST and all discovered source files for hardcoded secrets (`SEC101`-`SEC105`).
- Exits 0 if full AST coverage and no findings meet or exceed HIGH severity.
- Exits 1 if findings meet threshold, or if unsupported AST languages (e.g., TS, Go, Rust) are present without AST scanner.

### B. Repository Security Scan (Explicit Secrets-Only Policy)
```powershell
python cli.py path/to/repo --security --security-policy secrets_only --security-threshold HIGH
```
- Restricts policy scope to secret patterns across all files. Bypasses AST coverage requirement for non-Python languages while explicitly printing:
  `> [!NOTE]`
  `> Scope Notice: Active security policy is SECRETS_ONLY. Non-Python AST vulnerabilities are not scanned.`

### C. Headless CI Pipeline with Candidate Patch (Default Strict Policy)
```powershell
python cli.py path/to/repo --ci --target-file pkg/calc.py --patch-file cand.patch --runtime python --sandbox docker --output-json report.json
```
- Verifies patch in Docker sandbox and on candidate snapshot `patched_disposable_snapshot`.
- Produces separate `behavioral_status`, `security_status`, `overall_policy`, and `outcome` fields in `report.json`.

---

## 7. Blocked Checks & Limitations
- **Offline / Static Invariance**: Scanners execute statically on local files. No remote advisory feeds (OSV, NVD) or external network targets were contacted.
- **Hosted GitHub Actions**: Remote execution of `.github/workflows/intellicodex.yml` remains blocked pending remote repository push by the user. Local validation of workflow structure, schema, and CI pipeline CLI execution is verified.

