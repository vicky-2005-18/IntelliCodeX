# IntelliCodeX — Project Engineering Roadmap

> **Status**: Active  
> **Last Updated**: 2026-09-17  
> **Current Scope**: Semester 1 CLI Core & Local Intelligence Engine  
> **Future Scope**: Semester 2 Web Application Workspace & Cloud Infrastructure

---

## 1. Prioritized Milestones & Dependency Flow

```mermaid
graph TD
    M1["Milestone 1: Closed-Loop Agentic Test-Driven Patching<br/>(Essential Repair Engine - Semester 1)"] --> M2["Milestone 2: Real-Time Filesystem Watcher Daemon<br/>(Core Performance - Semester 1)"]
    M2 --> M3["Milestone 3: Hybrid BM25 & Dense RRF Retrieval<br/>(Retrieval Optimization - Semester 1)"]
    M3 --> M4["Milestone 4: Advanced Terminal TUI & Packaging<br/>(CLI Experience - Semester 1)"]
    M4 --> M5["Milestone 5: Full Web Application Workspace<br/>(Visual Frontend UI - Semester 2)"]
    M5 --> M6["Milestone 6: Distributed Vector Storage & CI/CD Connectors<br/>(Enterprise Phase - Semester 2)"]
```

---

## 2. Milestone 1: Closed-Loop Agentic Test-Driven Repair (Self-Healing Code) `[ESSENTIAL - SEMESTER 1]`

* **Goal**: Enhance the patch generation pipeline from single-shot LLM prompting into an iterative, test-validated repair loop.
* **Target Priority**: High (P1)
* **Dependencies**: `core/patch_generator.py`, `core/bug_localizer.py`.

### Tasks:
1. **Task 1.1: Sandbox Test Execution Runner**
   - **File**: `core/sandbox_runner.py` (New)
   - **Description**: Execute repository test suites (`pytest`, `npm test`) inside an isolated temporary directory applying the proposed patch.
   - **Owner**: Unassigned
   - **Estimated Effort**: ~2-3 days (Estimate)
   - **Completion Criteria**: Test execution captures exit codes, failed test names, assertion failures, and tracebacks.
2. **Task 1.2: Multi-Turn Self-Correction Prompt Loop**
   - **File**: [`core/patch_generator.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/patch_generator.py)
   - **Description**: If sandboxed tests fail, feed the failing test assertions and stack trace back into `qwen2.5-coder` (up to a configurable maximum of 3 iterations).
   - **Owner**: Unassigned
   - **Estimated Effort**: ~2 days (Estimate)
   - **Completion Criteria**: Patch engine automatically re-attempts fixes upon test failure and marks patch as `test_passed` or `max_iterations_exceeded`.

---

## 3. Milestone 2: Real-Time Filesystem Watcher Daemon `[CORE PERFORMANCE - SEMESTER 1]`

* **Goal**: Synchronize modified code chunks in real-time in the background without requiring manual CLI re-indexing or server restarts.
* **Target Priority**: Medium (P2)
* **Dependencies**: `core/pipeline.py`, `backend/services/incremental_indexer.py`.

### Tasks:
1. **Task 2.1: Watchdog Background Observer Integration** `[COMPLETED ✓]`
   - **File**: [`backend/services/incremental_indexer.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/backend/services/incremental_indexer.py)
   - **Description**: Thread-safe `watchdog.observers.Observer` monitoring active repository directories for `on_modified`, `on_created`, and `on_deleted` file events with 500ms debouncing, path filtering (`.git`, `.venv`, `.bak`), and live interactive CLI synchronization (`watch:status`, `watch:stop`, `watch:start`).
   - **Status**: Completed & verified via `tests/test_file_watcher.py` (6/6 tests passed).
   - **Completion Criteria**: Saving a file in `sample_repo` triggers selective re-embedding and FAISS index update in $<200\text{ms}$.

---

## 4. Milestone 3: Hybrid BM25 & Dense Reciprocal Rank Fusion (RRF) `[RETRIEVAL OPTIMIZATION - SEMESTER 1]`

* **Goal**: Combine sparse lexical keyword matching (BM25) with dense vector cosine similarity (FAISS) using Reciprocal Rank Fusion to maximize retrieval recall on exact variable and symbol lookups.
* **Target Priority**: Medium (P2)
* **Dependencies**: `core/vectorstore.py`, `rag/query_engine.py`.

### Tasks:
1. **Task 3.1: BM25 Lexical Indexer** `[COMPLETED ✓]`
   - **File**: [`core/lexical_index.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/lexical_index.py)
   - **Description**: Inverted index for exact symbol and token matching across code chunks with camelCase and snake_case sub-tokenization and BM25Okapi scoring.
   - **Status**: Completed & verified via `tests/test_hybrid_search.py`.
   - **Completion Criteria**: Benchmark retrieval accuracy demonstrated $+16.7\%$ improvement in Mean Reciprocal Rank (MRR) for exact symbol queries over pure dense search.
2. **Task 3.2: Reciprocal Rank Fusion (RRF) Scorer** `[COMPLETED ✓]`
   - **File**: [`rag/query_engine.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/rag/query_engine.py)
   - **Description**: Multi-ranker fusion via $\text{RRF}(d) = \sum_{m \in M} \frac{w_m}{k + r_m(d)}$ ($k=60$). Combined ranked results returned to query engine with interactive CLI controls (`hybrid:status`, `hybrid:on`, `hybrid:off`, `hybrid:toggle`).
   - **Status**: Completed & verified.
   - **Completion Criteria**: Combined ranked results returned to query engine and verified across 112 system tests.

---

## 5. Milestone 4: Advanced Terminal TUI & CLI Packaging `[CLI EXPERIENCE - SEMESTER 1]`

* **Goal**: Provide rich auto-completion, formatted Markdown panels, and standalone pip packaging (`pip install intellicodex`).
* **Target Priority**: Medium (P2)
* **Dependencies**: `cli.py`.

### Tasks:
1. **Task 4.1: Prompt Toolkit Auto-Completion & Rich TUI** `[COMPLETED ✓]`
   - **File**: [`cli.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/cli.py)
   - **Description**: Integrated `prompt_toolkit` with dynamic `IntelliCodeXCompleter` for command completion (`deps:`, `callers:`, `fix:`, `persona`, `model`, `repo`, `backend`, `hybrid`, `watch`), parameter suggestions (files, symbols, personas, error types), bottom status toolbar, and `rich` Markdown panels, syntax-highlighted git diffs, and formatted tables (`files`, `top`, `repos`, `hooks`).
   - **Status**: Completed & verified via `tests/test_tui_and_packaging.py`.
2. **Task 4.2: Standalone PyPI / pip Package Configuration** `[COMPLETED ✓]`
   - **File**: `pyproject.toml`
   - **Description**: Packaged IntelliCodeX as a PEP 621 compliant package with console script entry point `intellicodex = "cli:main"`. Verified via editable pip installation (`pip install -e .`) and execution.
   - **Status**: Completed & verified.

---

## 6. Milestone 5: Full Web Application Workspace `[FUTURE PHASE - SEMESTER 2]`

* **Goal**: Re-integrate and expand the web workspace with real-time WebSocket token streaming, Cytoscape graph explorer, and side-by-side patch review editor.
* **Target Priority**: Semester 2 (P3)
* **Dependencies**: Completion of Semester 1 CLI Core & Engine.

### Tasks:
1. **Task 5.1: Web Workspace Layout & Real-Time Token Streaming**
   - **Description**: Interactive chat drawer, Monocle code viewer, and WebSocket token streaming.
   - **Owner**: Unassigned
   - **Estimated Effort**: ~2 weeks (Estimate)
2. **Task 5.2: Cytoscape Graph Visualizer & Diff Editor**
   - **Description**: Interactive dependency topology with node blast radius highlighting and visual patch approval.
   - **Owner**: Unassigned
   - **Estimated Effort**: ~2 weeks (Estimate)

---

## 7. Milestone 6: Distributed Vector Storage & Enterprise CI/CD `[FUTURE PHASE - SEMESTER 2]`

* **Goal**: Modular connectors for remote vector databases (Qdrant, ChromaDB, Milvus) and automated GitHub/GitLab Pull Request code review bots.
* **Target Priority**: Semester 2 (P4)
