# IntelliCodeX — Test Suite, Verification Guide & Quality Assurance

> **Inspection & Execution Date**: 2026-09-17  
> **Environment**: Windows 11, Python 3.14 (Virtual Environment `.venv`), Node.js v20+  
> **Automated Test Results**: **91 Passed**, 0 Failed, 12 SVD Divide Warnings (Duration: 5.66 seconds)  
> **Frontend Build Status**: **Clean** (`tsc && vite build` exited with code 0)

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
└── test_week5_verification.py              # Milestone 5 verification test suite (memory, personas, streaming)
```

---

## 2. Test Execution Commands

### 2.1 Complete Automated Backend Test Suite
```bash
# Run complete test suite (from intellicodex directory)
.\.venv\Scripts\pytest -v

# Run with short traceback summary
pytest --tb=short

# Run a specific test module
pytest tests/test_patch_generator.py -v

# Run only Tree-Sitter chunker tests
pytest tests/test_tree_sitter_chunker.py -v
```

### 2.2 Complete Automated Frontend Build Verification
```bash
# Typecheck and production bundle build (from intellicodex/frontend directory)
cd frontend
npm run build
```

### 2.3 Performance Benchmarking Command
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

### 3.5 RAG Query Engine & CLI Scenarios
* **Scenario**: Conversation memory, persona prompts, token budgeting, and fallback handling.
  - *Files*: `tests/test_week5_verification.py`, `tests/test_cli.py`
  - *Expectation*: History retained across turns; model switches cleanly; offline fallback operates without Ollama.
  - *Result*: **PASSED** (19 tests passed).

---

## 4. Empirical Test Execution Record

* **Execution Timestamp**: 2026-09-17 13:07:14 IST
* **Execution Command**: `.\.venv\Scripts\pytest -v`
* **Test Summary**:
  - Total Tests: 91
  - Passed: 91 (100%)
  - Failed: 0
  - Skipped: 0
  - Execution Time: 5.66 seconds
* **Warnings Summary**:
  - 12 `RuntimeWarning: invalid value encountered in divide` in `sklearn/decomposition/_truncated_svd.py` when TruncatedSVD operates on uniform dummy test matrices where variance is zero. This is a non-fatal warning during offline fallback testing.

---

## 5. Known Limitations & Checks Not Performed

1. **Live Ollama LLM Response Quality Audit**:
   - Automated tests mock or use lightweight deterministic fallback responses for speed and reproducibility. Evaluating subjective reasoning quality of `qwen2.5-coder` on arbitrary open-domain prompts requires human developer review.
2. **MongoDB Daemon Live Connection**:
   - Automated tests assert the `LocalDiskStore` fallback when MongoDB is offline. Live cluster failover was verified with local disk persistence.
3. **End-to-End Browser UI Automation (Playwright/Cypress)**:
   - Frontend verification was performed via TypeScript static analysis (`tsc`) and Vite production bundle generation (`vite build`). Interactive browser click-through tests are executed manually.
