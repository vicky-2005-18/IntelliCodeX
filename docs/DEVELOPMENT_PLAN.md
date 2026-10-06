# IntelliCodeX — Comprehensive Development Plan

**Objective**: Systematically close all theoretical, functional, and empirical gaps between the IntelliCodeX research paper and the production repository implementation ([github.com/vicky-2005-18/IntelliCodeX](https://github.com/vicky-2005-18/IntelliCodeX)).

---

## 1. Where the Project Stands

### Verified & Implemented Capabilities
- **Multi-Language AST Semantic Chunking**: Concrete syntax tree extraction via Tree-Sitter across 9 languages (Python, JS, TS, TSX, Java, C, C++, Go, Rust).
- **Dual Embedding Architecture**: Local dense Ollama (`nomic-embed-text`, 768-dim) with deterministic Scikit-Learn TF-IDF + TruncatedSVD (64-dim) CPU fallback.
- **FAISS Vector Index & SQLite Persistence**: Persistent vector store, schema metadata store, and SHA-256 delta hashing enabling $<5\text{ms}$ cached reloads.
- **Hybrid Retrieval (BM25 + Dense RRF)**: Inverted BM25Okapi lexical index with camelCase/snake_case sub-tokenization fused with FAISS similarity via Reciprocal Rank Fusion.
- **Dependency & Call Graphs**: Directed NetworkX graphs computing PageRank centrality, import relationships, and caller-callee call graphs.
- **Graph-Augmented RAG**: Dynamic token budgeting, context expansion with callers/callees/imports, and multi-turn conversational memory.
- **Spectrum-Based Fault Localization (SBFL)**: Ochiai suspiciousness ranking combined with multi-language stack trace parsing.
- **Safe Patch Generation & Multi-Turn Sandbox Loop**: Deterministic code synthesis with up to 3 test repair iterations, AST syntax validation, and atomic `.bak` file replacement.
- **Live File Watcher**: Debounced `watchdog` daemon auto-reindexing filesystem changes in the background.
- **Interactive CLI & TUI Packaging**: Rich interactive terminal interface powered by `prompt_toolkit` and `rich`, packaged via `pyproject.toml`.
- **FastAPI Backend Server**: JWT authentication, role-based access control (RBAC), and CORS security hardening.

---

### Gaps Against the Research Paper

| # | Paper Claim | Current State | Target Resolution |
| :- | :--- | :--- | :--- |
| **1** | **Reliable Bug Detection** | Bug analysis query flow on `@file` could miss obvious static defects (syntax errors, undefined variables, missing imports). | Implement deterministic static checking (`ast.parse`, `pyflakes`, Tree-Sitter error nodes) preceding any LLM pass. |
| **2** | **Rich Embeddings (Code, Docs, Metadata)** | Dual embedder exists; explicit fusion of signature, docstring, leading comments, and file path needs verification and standardization. | Enrich chunk embedding representation; add verification tests for docstring-only semantic matching. |
| **3** | **Patch Engine Source of Truth** | Duplicated implementations existed in `core/patch_generator.py` and `backend/patch_generator/`. | Consolidate single source of truth in `core/patch_generator.py`, routing backend imports through core. |
| **4** | **Developer Review Gate Before Integration** | Patches could be applied directly without an explicit staging proposal and approval gate. | Implement 4-stage lifecycle: `fix` (propose) $\to$ `review` (inspect diff) $\to$ `approve`/`reject` with persistent audit log. |
| **5** | **Documentation Generation** | Automatic repository and symbol documentation not verified in the active capability matrix. | Provide dedicated `doc:<file/symbol>` command leveraging AST call-graph context and anti-hallucination quote filter. |
| **6** | **Multi-User Central Server Concurrency** | Single-process server without Ollama request serialization under concurrent load. | Introduce request semaphore / queue for Ollama; add 5-client concurrency latency benchmark. |
| **7** | **"Distributed" vs Client-Server Reality** | Paper claims "distributed", but codebase architecture is centralized client-server. | Realign paper and documentation terminology to client-server; add remote `--server` CLI flag. |
| **8** | **Security Vulnerability Scanner** | Relies on LLM security personas without deterministic static security scanning. | Wrap `bandit` for Python AST vulnerability detection; LLM provides remediation guidance. |
| **9** | **Empirical Measured Benefits** | Lacks recorded benchmark evaluation numbers for bug detection, retrieval accuracy, and patch success. | Build automated evaluation harnesses (`scripts/eval_llm.py`, retrieval benchmarks) and generate `docs/LLM_EVAL.md`. |
| **10**| **Web Client Dashboard** | React dashboard postponed to Semester 2 roadmap to focus on CLI and core engine. | Document cleanly as Semester 2 roadmap milestone in all specification docs. |
| **11**| **Docker Sandbox Isolation** | Implemented in `core/sandbox_runner.py` and `Dockerfile.sandbox` but marked unverified in live tests. | Validate `Dockerfile.sandbox` execution and update status matrix. |

---

### Documentation & Terminology Drift to Resolve
1. **Test Count Alignment**: Test suite currently passes **251 tests (4 skipped, 255 collected)** under Python 3.14. Docs and README badges must be synchronized across `README.md`, `docs/PROJECT_STATUS.md`, and `docs/TESTING.md`.
2. **File Watcher Status**: README states file watcher is "in development", whereas `docs/PROJECT_STATUS.md` documents it as complete with passing tests.
3. **Multi-Turn Patching Limitation**: Clarify that multi-turn closed-loop patching is fully implemented when repository path is provided.
4. **"Enterprise" Wording**: Remove marketing phrasing ("Enterprise") in `backend/main.py`, `backend/config.py`, `backend/services/assistant_engine.py`, and `backend/services/llm_factory.py` in favor of technical accuracy.
5. **Graphify Scope**: Exclude workspace metadata and artifact folders (`.agent`, `.agents`, `.kilo`, `.repos`, `graphify-out`) from knowledge graphs.

---

## 2. Core Architectural Principles

1. **Deterministic Tools First, LLM Second**: Syntax errors, undefined symbols, and known vulnerability patterns must be detected by static analyzers (`ast`, `pyflakes`, `bandit`, Tree-Sitter) without relying on non-deterministic LLM inference.
2. **Only Claim What Is Measured**: Every performance claim in the paper and README must correspond directly to an automated test or a measured benchmark in `docs/LLM_EVAL.md`.
3. **Single Source of Truth**: One canonical engine per responsibility (`core/patch_generator.py` for patching, `core/embedder.py` for vectors).
4. **Zero Regression Guarantee**: Every phase concludes with all test suites passing green (`pytest --collect-only -q` matching executed counts) and documentation synchronized.

---

## 3. Phased Execution Roadmap

### Phase 0: Synchronization, Cleanup & Hygiene (~0.5 Working Day)
- [x] Align test count badges and documentation across `README.md`, `docs/PROJECT_STATUS.md`, and `docs/TESTING.md` to reflect the active passing suite (254 passed, 4 skipped).
- [x] Correct status contradictions regarding background file watcher and multi-turn sandbox repair.
- [x] Strip out "Enterprise" terminology from `backend/main.py`, `backend/config.py`, `backend/services/assistant_engine.py`, and `backend/services/llm_factory.py`.
- [x] Update Graphify ignore configuration (`.gitignore`, `.graphifyignore`) to exclude `.agent`, `.agents`, `.kilo`, `.repos`, `gsd-core`, `get-shit-done`, and `graphify-out`.
- [x] Ensure git working tree is clean and synchronized.

### Phase 1: Bug-Finding Reliability & Deterministic Checks (1 to 2 Working Days)
- [x] **`core/static_checks.py`**:
  - Python AST syntax checking via `ast.parse`.
  - Undefined variable and unused/missing import detection using `pyflakes.api.checkPath` / AST visitor.
  - Multi-language AST ERROR node extraction via Tree-Sitter grammars.
  - Strict isolation: zero code execution during static analysis.
- [x] **Deterministic-First Bug Pipeline**:
  - Run static checks before sending prompts to the LLM. Label static issues explicitly (`[STATIC]`).
  - If syntax errors exist, abort function-level logic decomposition and report syntax error directly.
  - Add dedicated runtime-errors LLM pass over full line-numbered file at temperature `0.0`.
  - Refine prompt to check name/docstring contracts and runtime exceptions without default "MATCH".
- [x] **Anti-Hallucination Quote Normalization**:
  - Strip line-number prefixes (`N |`), code fences, and whitespace deltas before verifying quotes against ground-truth source.
  - Log quote rejections under `INTELLICODEX_DEBUG_PROMPT`.
- [x] **Automated Test Fixtures**:
  - Create test fixture `tests/fixtures/obvious_bugs.py` containing syntax error, undefined variable, missing import, and type mismatch. Assert exact line reporting even when LLM is mocked or offline.

### Phase 2: Closing the Paper Gaps (3 to 4 Working Days)
- [x] **2.1 Consolidate PatchEngine**:
  - Standardize `core/patch_generator.py` as canonical engine.
  - Refactor `backend/patch_generator/patch_engine.py` to import directly from `core.patch_generator` or act as a lightweight facade.
  - Verify all 16+ existing patch generator tests continue to pass.
- [x] **2.2 Enriched Chunk Embeddings**:
  - Construct chunk embedding payload: `File: {path} | Signature: {sig} | Docstring: {doc} | Comments: {comments}\n{code}`.
  - Verify `core/embedder.py` and `core/pipeline.py` serialization.
  - Add integration test proving docstring-only semantic search retrieves the correct function.
- [x] **2.3 Developer Review & Proposal Gate**:
  - Staging workflow: `fix:` synthesizes a pending proposal with sandbox validation without writing to source files.
  - Proposal management commands: `review` (list and show diff), `approve <id>` (atomic overwrite with `.bak` backup), `reject <id>` (discard).
  - Persistent JSON/SQLite audit log recording timestamp, user, file, and patch ID.
  - Expose matching FastAPI endpoints with RBAC enforcement (`/api/patches/pending`, `/approve`, `/reject`).
  - Add unit tests verifying direct unapproved file modifications are rejected.
- [x] **2.4 Documentation Generation Engine**:
  - Implement `doc:<file/symbol>` command utilizing AST call-graph hierarchy, inbound callers, and quote validation.
  - Output structured Markdown documentation. Test against mocked LLM.

### Phase 3: Central Server & Concurrency Hardening (2 to 3 Working Days)
- [ ] **Serialized LLM Ingestion Queue**:
  - Introduce an asynchronous `asyncio.Semaphore` or queue around Ollama inference to prevent connection timeouts under concurrent requests.
- [ ] **Concurrency Benchmark**:
  - Implement load test with 5 concurrent clients executing hybrid queries; record p50 and p95 latency.
- [ ] **Remote Server CLI Bridge**:
  - Add `--server <url>` and `--token <jwt>` flags to `cli.py` to allow querying remote IntelliCodeX instances over the REST API.
- [ ] **Operational Documentation**:
  - Document system limits: single-process server model, in-memory rate limiting, and reverse proxy recommendation (e.g. NGINX) for TLS/HTTPS.

### Phase 4: Quantitative Evaluation & Security Hardening (2 to 3 Working Days)
- [ ] **Empirical Bug-Finding Evaluation**:
  - Create `scripts/eval_llm.py` and `tests/fixtures/planted_bugs/` (8 intentional bugs, 6 clean functions).
  - Record True Positives, False Positives, False Negatives, and filtered hallucinations. Generate `docs/LLM_EVAL.md`.
- [ ] **Retrieval Benchmark Expansion**:
  - Expand 4-query MRR benchmark to $\ge 30$ representative queries across two repositories.
- [ ] **Patch Synthesis Benchmark**:
  - Benchmark 5–10 reference bugs, reporting sandbox pass rates.
- [ ] **Static Security Scanner**:
  - Implement `security:<file>` command wrapping `bandit` for Python AST vulnerability scanning; use LLM strictly to explain findings.
- [ ] **Docker Sandbox Verification**:
  - Build and validate `Dockerfile.sandbox` in containerized environments; update status from "unverified" to "verified".

### Phase 5: Research Paper Synchronization (1 Working Day)
- [ ] Add formal Implementation vs Paper status matrix (Verified, Partial, Future Work).
- [ ] Document hybrid deterministic static analysis + LLM inference architecture.
- [ ] Insert empirical benchmark numbers into evaluation section from `docs/LLM_EVAL.md`.
- [ ] Realign terminology: change "distributed architecture" to "client-server architecture".
- [ ] Shift unverified claims (e.g., Web UI, autonomous CI/CD agents, multi-repo distributed indexing) to Future Work.

---

## 4. Schedule & Effort Estimate

| Phase | Description | Estimated Effort | Prerequisites |
| :---: | :--- | :---: | :---: |
| **0** | Sync and cleanup | 0.5 Day | None |
| **1** | Bug-finding reliability | 1–2 Days | Phase 0 |
| **2** | Close paper gaps (Review gate, PatchEngine, Embeddings, Docs) | 3–4 Days | Phase 0 |
| **3** | Central server concurrency & remote CLI | 2–3 Days | Phase 2.3 |
| **4** | Quantitative evidence & security tooling | 2–3 Days | Phases 1 & 2 |
| **5** | Research paper updates & alignment | 1 Day | All phases |

**Total Estimated Effort**: ~10 to 14 Working Days.

---

## 5. Risk Assessment & Mitigations

1. **Slow Local LLM Inference (CPU/7B)**:
   - *Mitigation*: Leverage single whole-file context prompts rather than repetitive per-function round-trips; enforce strict token ceilings within `num_ctx`.
2. **LLM Hallucinations Despite Accurate Quotes**:
   - *Mitigation*: Ensure documentation honestly states the quote filter guarantees code presence, not semantic correctness; combine with deterministic static checkers.
3. **Local Process Sandbox Limitations**:
   - *Mitigation*: Clearly document that local sandbox uses OS process timeouts and environment restrictions; recommend Docker sandbox mode for untrusted external repositories.
4. **Prompt Inspection Security**:
   - *Mitigation*: Ensure `.storage/last_prompt.txt` remains strictly gitignored and excluded from production packages.

---

## 6. Definition of Done (DoD)

1. Every capability claimed in the paper is either accompanied by automated passing tests or explicitly designated as future work.
2. `core/patch_generator.py` is the single source of truth; zero duplicate patch engines.
3. `docs/LLM_EVAL.md` contains reproducible, empirical evaluation metrics.
4. `README.md`, `docs/PROJECT_STATUS.md`, `docs/TESTING.md`, and test badges agree with `pytest --collect-only -q` results.
5. All 251+ tests pass with zero regressions.
