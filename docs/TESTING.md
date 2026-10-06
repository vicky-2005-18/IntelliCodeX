# IntelliCodeX — Test Suite, Verification Guide & Quality Assurance

> **Inspection & Execution Date**: 2026-10-06
> **Environment**: Windows 11, Python 3.14
> **Automated Test Results**: **251 Passed**, 4 Skipped, 0 Failed (Duration: ~15-16 seconds)
> **Target Scope**: CLI Core, Tree-Sitter Parsers, FAISS Vector Engine, RAG, Patch Generator, Security Hardening, Anti-Hallucination, Runtime Errors Pass

---

## 1. Test Suite Organization & Execution Commands

The test suite is organized under `tests/` and covers unit, integration, persistence, graph analysis, and weekly milestone verification.

### 1.1 Test Directory Structure

```
tests/
├── conftest.py                             # Pytest fixtures, mock data, and test environments
├── test_parser.py                          # File walking, .gitignore filtering, language detection
├── test_ts_loader.py                       # Tree-Sitter grammar loader initialization across 8 languages
├── test_tree_sitter_chunker.py             # AST semantic chunking (JS, TS, Java, C, C++, Go, Rust)
├── test_dependency_graph.py                # Single-language dependency resolution
├── test_dependency_graph_multilang.py      # Multi-language import resolution (ES6, Java, C includes)
├── test_call_graph.py                      # Function-level caller-callee call graph extraction
├── test_centrality.py                      # PageRank file and symbol centrality scoring
├── test_sqlite_persistence.py              # SQLite schema, tables, and hash queries
├── test_faiss_sqlite_persistence.py        # Combined FAISS vector serialization and SQLite metadata
├── test_change_detection.py                # SHA-256 delta detection (added/modified/deleted files)
├── test_incremental_pipeline.py            # Zero-latency cached reload vs incremental re-indexing
├── test_graph_context_expansion.py         # Sub-graph expansion (callers/callees/imports) in RAG
├── test_bug_localizer.py                   # Multi-language stack trace parser & Ochiai SBFL
├── test_patch_generator.py                 # Unified Git diff generation, syntax checks, safe applier
├── test_git_hooks.py                       # Git post-commit & post-merge hook lifecycle
├── test_benchmarking.py                    # Performance profiling and ingestion throughput
├── test_cli.py                             # CLI argument parsing, interactive subcommands, fallbacks
├── test_pipeline_integration.py            # End-to-end multi-language repository ingestion
├── test_full_system_integration.py         # FastAPI REST endpoints and end-to-end query workflow
├── test_week2_verification.py              # Milestone 2 verification test suite
├── test_week3_verification.py              # Milestone 3 verification test suite (persistence & caching)
├── test_week4_verification.py              # Milestone 4 verification test suite (Ochiai & patch engine)
├── test_week5_verification.py              # Milestone 5 verification test suite (memory, personas, streaming)
├── test_anti_hallucination.py              # Anti-hallucination filter and prompt pipeline (6 tests)
├── test_auth_and_rbac.py                   # Authentication, rate limiting, and RBAC (18 tests)
├── test_cors_security.py                   # CORS origin/method/header validation (6 tests)
├── test_path_safety.py                     # Path traversal prevention for diffs and user inputs (9 tests)
├── test_sandbox_runner.py                  # Sandbox test execution (4 tests)
└── test_sandbox_hardening.py               # Sandbox security hardening (18 tests)
```

---

## 2. Test Execution Commands

### 2.0 Prerequisites: Install Development Dependencies

Before running tests, ensure development dependencies are installed:

```bash
# Install development dependencies (includes pytest and httpx for TestClient)
pip install -r requirements-dev.txt
```

### 2.1 Complete Automated Test Suite
```bash
# Run complete test suite (from intellicodex directory)
.\.venv\Scripts\pytest -v

# Run with short traceback summary
pytest --tb=short

# Run a specific test module
pytest tests/test_patch_generator.py -v

# Run CLI interaction tests
pytest tests/test_cli.py -v

# Run only Tree-Sitter chunker tests
pytest tests/test_tree_sitter_chunker.py -v
```

### 2.2 Performance Benchmarking Command
```bash
# Execute benchmarking against sample_repo
python cli.py sample_repo --benchmark
```

---

## 3. Verified Test Scenarios & Acceptance Criteria

### 3.1 Core Ingestion & AST Parsing Scenarios
* **Scenario**: Tree-Sitter AST chunking across multiple programming languages.
  - *Files*: `tests/test_ts_loader.py`, `tests/test_tree_sitter_chunker.py`
  - *Expectation*: Extract discrete function, class, and method chunks with precise start and end lines for Python, JS, TS, Java, C, C++, Go, and Rust.
  - *Result*: **PASSED** (15 tests passed).
* **Scenario**: `.gitignore` compliance and binary file exclusion.
  - *Files*: `tests/test_parser.py`
  - *Expectation*: Files matching `.gitignore` patterns (e.g. `*.pyc`, `dist/`, `.env`) are ignored.
  - *Result*: **PASSED** (4 tests passed).

### 3.2 Graph Analysis & Centrality Scenarios
* **Scenario**: Cross-module import detection and caller-callee call graph.
  - *Files*: `tests/test_dependency_graph_multilang.py`, `tests/test_call_graph.py`, `tests/test_centrality.py`
  - *Expectation*: Correctly identify imported symbols and call sites; compute PageRank scores without cycles crashing.
  - *Result*: **PASSED** (12 tests passed).

### 3.3 Persistence & Incremental Re-Indexing Scenarios
* **Scenario**: Zero-latency cached reload vs selective delta update.
  - *Files*: `tests/test_change_detection.py`, `tests/test_incremental_pipeline.py`, `tests/test_week3_verification.py`
  - *Expectation*: Unmodified repository loads in $<10\text{ms}$; adding 1 file only re-embeds that 1 file while retaining remaining vectors in FAISS.
  - *Result*: **PASSED** (14 tests passed).

### 3.4 Fault Localization & Patch Synthesis Scenarios
* **Scenario**: Multi-language stack trace parsing and Ochiai spectrum calculation.
  - *Files*: `tests/test_bug_localizer.py`, `tests/test_week4_verification.py`
  - *Expectation*: Parse Python, JS, Java, Go, Rust tracebacks; calculate Ochiai scores according to formula $e_f / \sqrt{n_f(e_f+e_p)}$.
  - *Result*: **PASSED** (6 tests passed).
* **Scenario**: Patch generation, syntax validation, and `.bak` backup file creation.
  - *Files*: `tests/test_patch_generator.py`
  - *Expectation*: Synthesize unified diff, reject invalid syntax via `ast.parse`, create timestamped backup on disk.
  - *Result*: **PASSED** (8 tests passed).

### 3.6 Security Hardening Scenarios
* **Scenario**: Authentication, rate limiting, and RBAC.
  - *Files*: `tests/test_auth_and_rbac.py`
  - *Expectation*: Argon2 password hashing, JWT token generation (HS256), owner scoping, login rate limiting keyed by (username, client IP), TRUSTED_PROXIES support, user promotion endpoint, unique Argon2 salts.
  - *Result*: **PASSED** (19 tests passed).
* **Scenario**: CORS security validation.
  - *Files*: `tests/test_cors_security.py`
  - *Expectation*: Explicit origin/method/header validation, wildcard rejection with credentials, localhost-only binding.
  - *Result*: **PASSED** (6 tests passed).
* **Scenario**: Path traversal prevention.
  - *Files*: `tests/test_path_safety.py`
  - *Expectation*: Prevent escape from trusted roots via symlink resolution, UNC paths, drive-relative paths, alternate data streams, and git diff path validation.
  - *Result*: **PASSED** (51 tests passed; 1 skipped on non-Windows for ADS test).
* **Scenario**: Sandbox security hardening.
  - *Files*: `tests/test_sandbox_hardening.py`
  - *Expectation*: Environment variable filtering, no shell execution, executable allowlisting, process tree killing, output truncation, admin-only test_command, ALLOW_LOCAL_SANDBOX enforcement, skipped result reporting.
  - *Result*: **PASSED** (19 tests passed).
* **Scenario**: Sandbox runner integration.
  - *Files*: `tests/test_sandbox_runner.py`
  - *Expectation*: Local and Docker mode execution, timeout handling, admin flag support.
  - *Result*: **PASSED** (8 tests passed).

### 3.5 RAG Query Engine & CLI Scenarios
* **Scenario**: Conversation memory, persona prompts, token budgeting, and fallback handling.
  - *Files*: `tests/test_week5_verification.py`, `tests/test_cli.py`
  - *Expectation*: History retained across turns; model switches cleanly; offline fallback operates without Ollama.
  - *Result*: **PASSED** (19 tests passed).
* **Scenario**: Anti-hallucination filter and prompt pipeline improvements.
  - *Files*: `tests/test_anti_hallucination.py`
  - *Expectation*: Context formatting renders contiguous line-numbered blocks per file; conversation memory excludes assistant answers for analysis questions; LLM receives num_ctx and temperature settings; anti-hallucination filter removes claims with nonexistent quotes; file scope can clear history.
  - *Result*: **PASSED** (6 tests passed).

---

## 4. Empirical Test Execution Record

* **Execution Timestamp**: 2026-10-04
* **Execution Command**: `pytest -q` (verified from clean venv using extracted submission zip)
* **Test Summary**:
  - Total Tests: 250
  - Passed: 246 (98.4%)
  - Failed: 0
  - Skipped: 4 (1.6%)
  - Execution Time: ~15-16 seconds
* **Skipped Tests**:
  - 4 symlink-related tests require Linux or elevated Windows privileges (test_symlink_safe_directory resolution in `test_path_safety.py` and `test_incremental_pipeline.py`)
* **Warnings Summary**:
  - 17 `RuntimeWarning: invalid value encountered in divide` in `sklearn/decomposition/_truncated_svd.py` when TruncatedSVD operates on uniform dummy test matrices where variance is zero. This is a non-fatal warning during offline fallback testing.

---

## 5. Known Limitations & Checks Not Performed

1. **Live Ollama LLM Response Quality Audit**:
   - Automated tests mock or use lightweight deterministic fallback responses for speed and reproducibility. Evaluating subjective reasoning quality of `qwen2.5-coder` on arbitrary open-domain prompts requires human developer review.
2. **MongoDB Daemon Live Connection**:
   - Automated tests assert the `LocalDiskStore` fallback when MongoDB is offline. Live cluster failover was verified with local disk persistence.
3. **End-to-End Browser UI Automation (Playwright/Cypress)**:
   - Frontend verification was performed via TypeScript static analysis (`tsc`) and Vite production bundle generation (`vite build`). Interactive browser click-through tests are executed manually.
