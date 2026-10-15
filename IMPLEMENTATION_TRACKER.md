# IntelliCodeX — Full Requirements & Implementation Tracker

> **Document Purpose**: Single source of truth mapping every requirement from the original IntelliCodeX research paper and project specification PDF to its implementation files, test evidence, remaining work, dependencies, and acceptance criteria.
>
> **Status Classifications**:
> - **Verified**: Implemented and demonstrated against explicit automated tests and runtime acceptance criteria.
> - **Partial**: Functionality exists in code but has gaps, unverified isolation, or incomplete integration.
> - **Missing**: No implementation found in codebase.
> - **Not Verified**: Insufficient evidence, mock-only coverage, or unavailable runtime.

---

## 1. System Environment & Hardware Baseline

- **Hardware Platform**: AMD Ryzen 7 7445HS (8 Cores, 16 Threads), 16 GB System RAM.
- **Confirmed GPU**: NVIDIA GeForce RTX 3050 Laptop GPU with **4096 MiB (4 GB) dedicated VRAM** (Driver 32.0.16.1656, CUDA 13.4). Integrated: AMD Radeon 740M (512 MB).
- **VRAM Constraint Note**: 4 GB VRAM fits 3B models (`qwen2.5-coder:3b` ~1.9 GB) comfortably. 7B models (`qwen2.5-coder:7b` ~4.7 GB) incur partial CPU offload spillover; dual embedding uses Ollama (`nomic-embed-text`) or CPU-fallback TF-IDF/SVD.
- **Runtime Environment**: Python 3.14.6, Windows 11 64-bit, Ollama 0.40.3 installed and active.
- **Baseline Test Suite Status**: 367 passed, 4 skipped in `pytest` (Python 3.14).

---

## 2. Requirement Traceability Matrix

### Core Requirements (PDF Sections I – VI)

| ID | Requirement Name | PDF Source | Implementation Files | Current Evidence | Remaining Work | Dependencies | Acceptance Criteria | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-CORE-01** | Source Code Ingestion | p. 4, §V; p. 5, §VI | `core/parser.py`, `core/pipeline.py` | `tests/test_parser.py` (5/5 tests passing) | None (tests & docs included by default with optional flags) | None | Traverses repository, respects `.gitignore`, skips binary files | **Verified** |
| **REQ-CORE-02** | Language Detection | p. 4, §V | `core/tree_sitter_chunker.py`, `core/ts_loader.py` | `tests/test_ts_loader.py` passes | None | REQ-CORE-01 | Correctly maps extensions to 9 supported languages | **Verified** |
| **REQ-CORE-03** | Syntax-Aware Parsing | p. 4, §V; p. 5, §VI | `core/tree_sitter_chunker.py` | `tests/test_tree_sitter_chunker.py` passes | None | REQ-CORE-01, REQ-CORE-02 | Generates Tree-sitter CST without crashing on syntax errors | **Verified** |
| **REQ-CORE-04** | Function & Class Chunking | p. 3, §III; p. 4, §V | `core/tree_sitter_chunker.py` | `tests/test_tree_sitter_chunker.py` passes | None | REQ-CORE-03 | Extracts precise boundaries of functions and classes | **Verified** |
| **REQ-CORE-05** | Context Preservation | p. 4, §V | `core/tree_sitter_chunker.py` | `tests/test_tree_sitter_chunker.py` passes | None | REQ-CORE-04 | Preserves enclosing class, scope, docstrings, and imports | **Verified** |
| **REQ-CORE-06** | Dense & Fallback Embeddings | p. 3, §IV-B; p. 4, §V | `core/embedder.py` | `tests/test_cli.py::test_create_components_ollama_fallback` passes | None | REQ-CORE-05 | Generates 768-dim Ollama vectors with automatic TF-IDF CPU fallback | **Verified** |
| **REQ-CORE-07** | FAISS Vector Store & SQLite | p. 4, §V; p. 5, §VI | `core/vectorstore.py`, `core/persistence.py`, `core/pipeline.py` | `tests/test_faiss_sqlite_persistence.py`, `tests/test_incremental_pipeline.py` (7/7 passed) | None (auto-invalidates cache on embedding model/dimension switch, purges deleted file metadata, enables IVF direct map) | REQ-CORE-06 | Persists FAISS L2/Cosine index and SQLite metadata synchronously | **Verified** |
| **REQ-CORE-08** | Import Dependency Analysis | p. 5, §V; p. 6, §VI | `core/dependency_graph.py`, `backend/dependency_graph/enhanced_graph.py` | `tests/test_dependency_graph.py` (3/3 passed) | None (handles relative imports, dot navigation, and dynamic importlib/__import__ resolution) | REQ-CORE-03 | Maps directed module imports across multi-file repositories | **Verified** |
| **REQ-CORE-09** | Call Graph & Centrality | p. 4, §IV-E; p. 5, §V | `core/call_graph.py`, `backend/dependency_graph/call_graph.py` | `tests/test_call_graph.py`, `tests/test_centrality.py` pass | None (precision caller/callee AST resolution with scope boundaries, fan-out caps, and PageRank) | REQ-CORE-08 | Builds NetworkX caller-callee graph with PageRank metrics | **Verified** |
| **REQ-CORE-10** | Natural Language RAG Q&A | p. 3, §III; p. 5, §V | `rag/query_engine.py`, `backend/api/repos.py` | `tests/test_anti_hallucination.py` (15/15 passed), `tests/test_full_system_integration.py` pass | None (AST boundary out-of-bounds line citation checks, unverified symbols/files checks, and prompt drift guards) | REQ-CORE-07, REQ-CORE-13 | Answers code queries citing valid file paths and line ranges | **Verified** |
| **REQ-CORE-11** | Repository Context Assembly | p. 5, §V; p. 6, §VI | `rag/query_engine.py`, `core/lexical_index.py` | `tests/test_graph_context_expansion.py` (2/2 passed), `tests/test_anti_hallucination.py` passes | None (dynamic token budgeting clamped 2048-8192 with safe fallback for legacy LLM drivers) | REQ-CORE-07, REQ-CORE-09 | Combines BM25+FAISS RRF with graph callers and resilient lexical fallback | **Verified** |
| **REQ-CORE-12** | Bug Localization Engine | p. 3, §IV-C; p. 5, §V | `core/bug_localizer.py`, `backend/bug_localizer/advanced_localizer.py`, `backend/api/bugs.py` | `tests/test_bug_localizer.py` (5/5 passed), `tests/test_week4_verification.py` pass | None (function and file level Ochiai SBFL, automatic CoverageRecord ingestion, multi-language stack trace parser for Python/JS/Java/Go/C++/Rust) | REQ-CORE-07, REQ-CORE-09 | Ranks suspicious files/functions using Ochiai SBFL + tracebacks | **Verified** |
| **REQ-CORE-13** | Local Qwen LLM Inference | p. 5, §V; p. 6, §VI | `core/llm_client.py` | `tests/test_quality_and_invariants.py` passes | Benchmark 3B vs 7B on 4GB VRAM hardware | Hardware, Ollama | Streams tokens locally from Qwen 2.5 Coder without internet | **Verified** |
| **REQ-CORE-14** | Root Cause Analysis (RCA) | p. 3, §III; p. 5, §V | `core/bug_localizer.py`, `backend/patch_generator/patch_engine.py` | `tests/test_bug_localizer.py` (precondition & invariant tests pass), `tests/test_patch_generator.py` pass | None (explicitly distinguishes reproduced cause from suspected cause and diagnoses violated preconditions across common error classes) | REQ-CORE-11, REQ-CORE-12, REQ-CORE-13 | Explains failure mechanism and violated preconditions | **Verified** |
| **REQ-CORE-15** | Context-Aware Patch Gen | p. 3, §IV-D; p. 5, §V | `core/patch_generator.py`, `backend/patch_generator/llm_parser.py`, `backend/patch_generator/patch_validator.py` | `tests/test_patch_generator.py` (13/13 passed) | None (multi-language Tree-sitter AST validation for JS/TS/Java/Go/Rust/C/C++, search/replace block pattern parsing, and sandbox pre-testing) | REQ-CORE-13, REQ-CORE-14 | Generates valid search/replace blocks with AST pre-validation | **Verified** |
| **REQ-CORE-16** | Developer Review Gate | p. 6, §VI | `core/code_review.py`, `backend/patch_generator/review_gate.py` | `tests/test_code_review.py`, `tests/test_patch_generator.py` pass | None (verified git commit isolates approved files from unrelated staged files) | REQ-CORE-15 | Displays diff, requires explicit user approval before disk write | **Verified** |
| **REQ-CORE-17** | Atomic Code Integration | p. 6, §VI | `core/patch_generator.py`, `backend/patch_generator/patch_applier.py` | `tests/test_patch_generator.py` (13/13 passed) | None (SHA-256 hash and content conflict detection blocks blind overwrites of concurrent disk edits, timestamped `.bak` backups created) | REQ-CORE-16 | Writes patched file with timestamped `.bak` backup | **Verified** |
| **REQ-CORE-18** | Multi-User Concurrency | p. 1, p. 5, §V | `backend/api/concurrency.py`, `core/llm_client.py` | `tests/test_concurrency.py` (6/6 passed) | None (GPUConcurrencyManager enforces serialized 4GB VRAM inference, tracks queue depth and active workers, exposes /api/concurrency/status, stress-tested under 10 parallel threads) | REQ-CORE-13 | Serializes GPU access via semaphore without server crashes | **Verified** |
| **REQ-CORE-19** | Client Interfaces (CLI/API) | p. 5, §V | `cli.py`, `backend/main.py` | `tests/test_cli.py`, `tests/test_tui_and_packaging.py` pass | None (resolved typing imports in `cli.py`) | REQ-CORE-18 | Rich interactive terminal CLI and FastAPI REST API gateway | **Verified** |
| **REQ-CORE-20** | Code Explanation & Docs | p. 3, §III; p. 6, §VII | `backend/documentation/doc_engine.py` | `tests/test_cli.py` (doc tests) passes | None | REQ-CORE-09, REQ-CORE-13 | Synthesizes verified markdown documentation for symbols/files | **Verified** |

---

### Future-Scope Requirements (PDF Section VIII-B)

| ID | Requirement Name | PDF Source | Implementation Files | Current Evidence | Remaining Work | Dependencies | Acceptance Criteria | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-FUT-01** | Multi-Language Support | p. 7, §VIII-B | `core/parser.py`, `core/chunker.py`, `core/tree_sitter_chunker.py`, `core/dependency_graph.py`, `backend/dependency_graph/enhanced_graph.py`, `rag/query_engine.py`, `core/sandbox_runner.py` | `tests/test_multi_language_support.py` (7/7 passed), `tests/test_tree_sitter_chunker.py` (6/6 passed), `tests/test_dependency_graph_multilang.py` (4/4 passed), `tests/test_pipeline_integration.py` (3/3 passed), `tests/test_js_ts_sandbox.py` (11/11 passed), `tests/test_java_sandbox.py` (10/10 passed), `tests/test_c_cpp_sandbox.py` (12/12 passed), `tests/test_go_sandbox.py` (13/13 passed: 11 live container tests + 2 unit parser tests), `tests/test_rust_sandbox.py` (13/13 passed: 12 live container tests + 1 unit parser test); 85/85 multi-language tests passing. Full capability matrix and evidence in `docs/multi_language_support/EVIDENCE.md` and `docs/multi_language_sandbox/EVIDENCE.md`. | None (all 7 targeted languages Python, JS, TS, Java, C/C++, Go, and Rust fully verified for static analysis, AST chunking, KG extraction, RAG, and containerized patch verification) | REQ-CORE-01, REQ-CORE-02, REQ-CORE-03, REQ-CORE-04, REQ-CORE-05 | File discovery, syntax-aware AST chunking, import extraction, symbol disambiguation, offline hybrid RAG retrieval with file:line citations, syntax error resilience with diagnostic logs, incremental re-indexing, and multi-language knowledge graph across Python, JS, TS, Java, C/C++, Go, and Rust; containerized patch verification for Python, JavaScript, TypeScript, Java, C, C++, Go, and Rust. | **Verified** |
| **REQ-FUT-02** | Autonomous Repair Loop & Sandbox Execution | p. 7, §VIII-B | `core/patch_generator.py`, `backend/patch_generator/patch_engine.py`, `core/sandbox_runner.py`, `backend/api/patches.py` | `tests/test_sandbox_runner.py` (11/11 passed), `tests/test_sandbox_hardening.py` (20/20 passed), `tests/test_docker_sandbox_workflow.py` (10/10 passed), `tests/test_docker_live_execution.py` (6/6 passed live in container), `tests/test_js_ts_sandbox.py` (11/11 passed live in container), `tests/test_java_sandbox.py` (10/10 passed live in container), `tests/test_c_cpp_sandbox.py` (12/12 passed live in container), `tests/test_go_sandbox.py` (11/11 passed live in container + 2 unit parser tests), and `tests/test_rust_sandbox.py` (12/12 passed live in container + 1 unit parser test); 62 live Docker container tests passing (65 total in sandbox suites). | None | REQ-CORE-15, REQ-CORE-17 | Multi-turn repair loop (up to 3 iterations) using test failure stack trace, assertions, and execution output feedback; live container execution in `intellicodex-sandbox:latest` with zero container leaks across Python (`pytest`, `unittest`), JavaScript (`node --test`), TypeScript (`tsc` compile + `node --test`), Java (`javac` + JUnit Platform Console Launcher), C (`cmake` + `ctest`), C++ (`cmake` + `ctest`), Go (`go test` test binary compilation + `test2json`), and Rust (`cargo test --tests`); clear non-silent failure when Docker is offline; no Windows host path leaks into container commands; zero-test/skipped/ignored-only rejection invariant. | **Verified** |
| **REQ-FUT-03** | Continuous Repo Monitoring | p. 7, §VIII-B | `core/watcher.py`, `backend/services/incremental_indexer.py`, `core/pipeline.py`, `backend/api/repos.py`, `backend/main.py`, `cli.py` | `tests/test_continuous_monitoring.py` (8/8 passed), `tests/test_file_watcher.py` (8/8 passed); 16/16 tests passing. End-to-end evidence documented in `docs/repository_monitoring/EVIDENCE.md`. | Enhanced knowledge graph entity re-generation remains manual/on-demand (`POST /api/graph/generate`) to avoid heavy re-indexing overhead | REQ-CORE-07, REQ-CORE-08 | Live watchdog filesystem events trigger debounced incremental reindex (<200ms) with full modify, add, delete, rename, and rapid burst coalescing; dynamic `.gitignore` pattern exclusion; cross-platform path normalization; query engine freshness verified; multi-tenant repo isolation; syntax error resilience without watcher crash; REST API watch lifecycle endpoints (`/watch/start`, `/watch/stop`, `/watch/status`) and graceful server shutdown cleanup. | **Verified** |
| **REQ-FUT-04** | CI/CD Pipeline Integration | p. 7, §VIII-B | `cli.py`, `.github/workflows/intellicodex.yml`, `core/sandbox_runner.py` | `tests/test_ci_pipeline.py` (12/12 passed covering passing/failing fixtures, zero-test rejection, exit codes 0/1/2, diff application, report sanitization, and workflow YAML syntax), `tests/test_cli.py` (27/27 passed including headless `--ci` mode). Live container demo passing across 4 fixture classes in `scratch/demo_ci_run.py`. Complete evidence documented in `docs/ci_cd/EVIDENCE.md`. Remote hosted run pending user branch push. | Remote hosted GitHub Actions run pending branch push | REQ-CORE-19, REQ-FUT-02 | Non-interactive execution returning standard exit codes (0=success, 1=verification failure, 2=config/infra error); machine-readable JSON reports with sanitized diagnostics; candidate patch verification inside isolated Docker sandbox (`--network none`, read-only, non-root) on disposable clones leaving host files untouched; zero-test/skipped rejection invariant; dual-job GitHub Actions workflow (`static-analysis-and-unit-tests` + `docker-sandbox-verification`) with minimal `contents: read` permissions. | **Verified** |
| **REQ-FUT-05** | Security Vulnerability Scan | p. 7, §VIII-B | `core/security_scanner.py`, `backend/analytics/security_scanner.py`, `backend/api/analytics.py`, `core/patch_generator.py`, `core/self_improving.py`, `cli.py` | `tests/test_security_scanner.py` (3/3 passed), `tests/test_security_vulnerability_detection.py` (21/21 passed covering 7-scenario outcome matrix, Bandit AST rules B101/B102/B105/B307/B608, secret detection SEC101-SEC105, synthetic credential redaction, safe counterpart false-positive checking, severity threshold filtering HIGH vs MEDIUM, explicit policy selection strict vs secrets_only, candidate patch security gate with disposable snapshot verification, multi-tenant REST API access authorization, and experience bank security provenance without retroactive approval); 63/63 tests passing across security and CI suites. Full evidence in `docs/security_detection/EVIDENCE.md`. | None (AST scanning for non-Python languages remains explicitly unsupported/incomplete under default strict policy, rejectable unless explicit secrets_only policy is selected; hosted GitHub Actions run remains pending remote push). | REQ-CORE-03, REQ-CORE-15 | Static AST vulnerability patterns via Bandit (Python), multi-language static secret detection with synthetic credential redaction (SEC101-SEC105), explicit severity threshold filtering (HIGH/MEDIUM/LOW), structured findings (rule ID, category, severity, confidence, repo-relative file, line, explanation, remediation), explicit distinction between suspected findings and confirmed exploitability, multi-tenant REST API isolation (`/api/analytics/{repo_id}/security` rejecting cross-tenant access with 403), separate outcome fields (behavioral test verification vs security scan status vs overall CI policy outcome), candidate patch verification gate on disposable snapshot (`patched_disposable_snapshot`), distinction between scanner execution errors (exit code 2) and policy rejections (exit code 1), and experience bank security provenance preventing security-rejected candidate retrieval while preserving historical records without retroactive approval. | **Verified** |
| **REQ-FUT-06** | Architecture Optimization | p. 7, §VIII-B | `core/architecture_optimizer.py`, `backend/dependency_graph/__init__.py`, `backend/api/graph.py`, `cli.py`, `core/self_improving.py`, `core/patch_generator.py` | `tests/test_architecture_optimizer.py` (11/11 passed covering full grounded contract, cycles, bottlenecks, healthy control modules, complex components, disposable cycle-break verification, configurable thresholds, empty graph handling, and multi-tenant authorization), `tests/test_self_improving.py` (13/13 passed including security policy provenance and strict retrieval filtering); 68/68 passed across related suites. Full evidence documented in `docs/architecture_optimization/EVIDENCE.md`. | None (recommendations are structural and advisory; runtime profiling is required before claiming performance speedups) | REQ-CORE-09, REQ-CORE-13 | Detects circular dependency cycles with source import line citations, module coupling bottlenecks (Martin's $C_a, C_e, I$ metrics) with explicit distinction that high centrality alone is not a defect, and overly complex functions/classes exceeding configurable line thresholds; returns 11-field grounded contract with affected files/symbols, supporting evidence, source references, configured thresholds, proposed improvement, engineering tradeoffs, static analysis limitations, and decoupling diffs; strict separation of deterministic `measured_facts` from optional `ai_advisory`; snapshot identification with freshness/staleness disclosure; safe non-destructive operation (never automatically modifies files or applies diffs); multi-tenant REST API isolation (`/api/graph/{repo_id}/architecture-optimization` rejecting cross-tenant access with 403); and security policy provenance in experience memory blocking `secrets_only` from strict retrieval. | **Verified** |
| **REQ-FUT-07** | Knowledge Graph Generation & Application Querying | p. 7, §VIII-B | `backend/dependency_graph/enhanced_graph.py`, `backend/dependency_graph/__init__.py`, `backend/api/graph.py`, `cli.py` | `tests/test_knowledge_graph_query.py` (8/8 passed), `tests/test_dependency_graph.py` (3/3 passed); verified live via REST API (`/api/graph/{repo_id}/query`, `/entities`, `/path`, `/metadata`) and CLI (`graph:<entity>`, `graph:path`, `graph:entities`, `graph:metadata`); cross-tenant 403 authorization boundary verified. | None | REQ-CORE-08, REQ-CORE-09 | Structured AST entity-relationship graph connecting code symbols (files, classes, methods, functions, external APIs, and databases); application-level graph querying with AST line numbers, source file citations, and direction filters; shortest path resolution; tenant isolation; explicit documentation of unsupported dynamic relationships (reflection, dynamic polymorphic dispatch, IPC bus, DI). | **Verified** |
| **REQ-FUT-08** | Multi-Repository Reasoning | p. 7, §VIII-B | `core/multi_repo.py`, `backend/api/multi_repo.py`, `cli.py` | `tests/test_multi_repo.py` (13/13 passed covering namespaced indexing, collision guards, fair-allocation retrieval, cross-repo contract discovery, candidate impact analysis with disclaimers, multi-tenant authorization barriers, third-repo exclusion, empty/unavailable repo handling, and live local Ollama demonstration); complete evidence in `docs/multi_repository_reasoning/EVIDENCE.md`. | None | REQ-CORE-07, REQ-CORE-08 | Answers cross-repo queries with `[repo_id:file:lines]` citations, discovers shared microservice HTTP contracts, enforces fair-allocation candidate retrieval without large repo starvation, and provides candidate review files with explicit relationship disclaimers. | **Verified** |
| **REQ-FUT-09** | Distributed Org Memory | p. 7, §VIII-B | `core/org_memory.py`, `backend/api/org_memory.py`, `cli.py` | `tests/test_org_memory.py` (11/11 passed covering scoped items, ADR parsing, git history mining, distinction of developer decisions vs verified repairs vs unverified summaries, tenant/repo authorization barriers, lifecycle invalidation/superseding, restart persistence, atomic process locking, repair bank sync, and REST API endpoints); complete evidence in `docs/organizational_memory/EVIDENCE.md`. | None | REQ-CORE-07, REQ-CORE-10 | Historical Git commit, ADR, developer decision, and repair memory answering architectural rationale queries with citations; multi-tenant organization and repo-private isolation; atomic process-level file locking; non-automatic verification for generated text. | **Verified** |
| **REQ-FUT-10** | Self-Improving Agents | p. 7, §VIII-B | `core/self_improving.py`, `core/patch_generator.py`, `backend/api/patches.py`, `cli.py` | `tests/test_self_improving.py` (12/12 passed covering provenance, idempotency, reverted invalidation, restart persistence, concurrency, multi-tenant privacy boundaries, and failed/skipped/timed-out/infra-error rejection); 20-case held-out benchmark evaluated live in real Docker containers across 4 conditions: Cond A (25.0%, 0-shot 1-att) -> Cond B (40.0%, few-shot 1-att) -> Cond C (55.0%, 0-shot 3-att Docker loop) -> Cond D (65.0%, few-shot 3-att Docker loop). | Full results documented in Section 4 and `.storage/docker_benchmark_evaluation_results.md`. | REQ-CORE-16, REQ-CORE-15 | Dynamic in-context few-shot learning with persistent RepairExperienceBank, automatic learning on sandbox test pass and developer approval, tenant isolation, and /api/patches/experiences API | **Verified** |

---

## 3. Sandbox Execution & Verified Isolation Boundary

### A. Actual Docker Runtime State
- **Docker CLI**: Docker version 29.8.0, build `c5eb6ec`, installed at `C:\Users\vikas\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`.
- **Docker Engine API**: **Active and Verified**. Engine Version: `29.8.0`, Context: `desktop-linux`, Kernel: `6.18.33.2-microsoft-standard-WSL2`.
- **Sandbox Image**: `intellicodex-sandbox:latest` successfully built from `Dockerfile.sandbox` (Image ID: `sha256:cbec086151fbf8ef900e9b929140888e8ba24bb0ad7c20d9f20aca7965260ed4`) with Python 3.11, pytest, Node.js 20 LTS, TypeScript 7.0.2, OpenJDK 21 LTS, JUnit Platform 1.10.2, GCC 14.2.0, G++ 14.2.0, CMake 3.31.6, CTest 3.31.6, GNU Make 4.4.1, Ninja 1.12.1, Go 1.24.4 linux/amd64 (`golang-go`), and Rust 1.85.1 (`rustc 1.85.1`, `cargo 1.85.1`).
- **Live Container Validation Status**: **Verified**. 62 live container integration tests passing across Python (`tests/test_docker_live_execution.py` - 6), JavaScript/TypeScript (`tests/test_js_ts_sandbox.py` - 11), Java (`tests/test_java_sandbox.py` - 10), C/C++ (`tests/test_c_cpp_sandbox.py` - 12), Go (`tests/test_go_sandbox.py` - 11 live container tests + 2 unit parser tests), and Rust (`tests/test_rust_sandbox.py` - 12 live container tests + 1 unit parser test); 65 total tests across sandbox suites.
- **Execution Classification**:
  - **Live Container Execution**: Real Linux containers launched via `docker run` with `--network none`, `--read-only`, and unprivileged UID `1000:1000`.
  - **Local Subprocess Execution**: Fallback host execution operating with configured application-level controls, not OS-enforced container isolation.
  - **Mocked Unit Tests**: Tests mocking `subprocess.run` to verify CLI command string generation and flag validation.

### B. Fail-Safe Behavior & Absence of Silent Fallback
- `_check_docker_available()` executes `docker version --format '{{.Server.Version}}'` with a 5-second timeout.
- When `sandbox_mode == "docker"` is requested and the daemon is offline, `SandboxRunner.run_tests_with_patch` immediately returns `SandboxTestResult(success=False, exit_code=-8)` explaining that the Docker daemon is unavailable and live container validation is blocked. It **never silently executes arbitrary code locally on the host**.

### C. Container Command & Path Normalization
- Host Windows executable paths (`C:\Program Files\Python314\python.exe`, `pytest.exe`) are mapped to Linux container binary invocations (`python`, `python -m pytest`).
- Windows path backslashes (`\`) are normalized to POSIX forward slashes (`/`).
- Added `-e PYTHONPATH=/work` to container executions to guarantee immediate package discovery under `/work`.

### D. Isolation Boundary: Live Evidence vs. Configured Controls
| Control Dimension | Live Container Evidence (Tested via Real Containers) | Local Sandbox Execution (Configured Application Controls) |
| :--- | :--- | :--- |
| **Network Access** | **Verified Live**: Outbound socket connect (`8.8.8.8:53`) raises `OSError` (network unreachable) under `--network none`. | Configured control: Shared host loopback; no network sandboxing. |
| **User Privileges** | **Verified Live**: Non-root `UID 1000:GID 1000` via `--user 1000:1000`. | Configured control: Runs with host user account privileges (`vikas`). |
| **Root Filesystem** | **Verified Live**: Attempt to write to `/etc/probe.txt` raises `OSError: [Errno 30] Read-only file system` under `--read-only`. | Configured control: Host filesystem permissions apply. |
| **Writable Storage** | **Verified Live**: `--tmpfs /tmp` and volume mount `-v {sandbox_dir}:/work`. | Configured control: Disposable temporary directory (`tempfile.TemporaryDirectory`). |
| **Host Exposure** | **Verified Live**: Canary file in host temp directory is inaccessible inside container `/work`. Path traversal rejected (`exit_code=-3`). | Configured control: Strict path traversal rejection (`resolve_within`, `exit_code=-3`). |
| **Resource Limits & Cleanup** | **Verified Live**: Timeout cleanly stops execution with `exit_code=-1`; `docker kill <name>` guarantees zero container leaks (0 active containers after timeout). | Configured control: Wall-clock timeout with recursive `psutil` process-tree kill. |
| **Environment** | Minimal Debian Linux container image environment. | Strict allowlist: `PATH`, `SYSTEMROOT`, `TEMP`, `APPDATA`. Sensitive patterns (`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL`) stripped. |

> **Security Boundary Disclaimer**: Container isolation restricts unauthorized disk access, network egress, and CPU/memory exhaustion under standard Linux container guarantees. It does not provide hardware-isolated VM hypervisor security (such as microVMs or Kata containers).

---

## 4. Closed-Loop Repair Accuracy Benchmark with Real Docker Execution

### A. Benchmark Evaluation Configuration
- **Git Commit**: `5f7143f933d68bfd427b3a0ac31fb6b873f17797`
- **Model**: `qwen2.5-coder:3b` (Digest: `f72c60cabf62`, parameters: 3.1B, Q4_K_M, family: `qwen2`)
- **Inference Settings**: `temperature=0.0`, `num_ctx=8192`, `num_predict=800`, `repeat_penalty=1.1`
- **Docker Image**: `intellicodex-sandbox:latest` (ID: `sha256:94593d0182348d7d5c578f91badc9dbab1488b41e69b56c3fa14ac28a4d4bf53`)
- **Benchmark Version**: 20-case Held-Out Benchmark across 5 categories (`KeyError`, `IndexError`, `ZeroDivisionError`, `TypeError`, `AttributeError`) from `tests/benchmark_self_improving.py`
- **Experience Bank**: Frozen Snapshot (5 golden samples, zero held-out overlap, learning strictly frozen during evaluation)
- **Pre-Flight Validity**: 100% verified inside Docker (each original case fails its bug test and passes its happy-path test)

### B. Four-Condition Performance Comparison

| Condition | Demonstrations | Max Attempts | Solved | Unresolved (No Regr.) | Regression (Happy Broke) | Both Regr. & Unres. | Invalid / Infra | Total | Avg Att. | Avg Total Time (s) | Avg Prompt Tok. (Case / Gen) | Avg Output Tok. (Case / Gen) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A** | None (0-shot) | 1 | **5 (25.0%)** | 15 | 0 | 0 | 0 / 0 | 20 | 1.00 | 8.38s | 163.2 / 163.2 | 195.3 / 195.3 |
| **B** | Golden Demos | 1 | **8 (40.0%)** | 11 | 0 | 1 | 0 / 0 | 20 | 1.00 | 7.75s | 327.4 / 327.4 | 170.8 / 170.8 |
| **C** | None (0-shot) | Up to 3 | **11 (55.0%)** | 7 | 0 | 2 | 0 / 0 | 20 | 2.20 | 17.61s | 664.6 / 302.1 | 568.5 / 258.4 |
| **D** | Golden Demos | Up to 3 | **13 (65.0%)** | 6 | 1 | 0 | 0 / 0 | 20 | 2.00 | 15.09s | 711.0 / 355.5 | 465.9 / 232.9 |

> **Category Reconciliation & Diagnostic Flags**:
> - Mutually exclusive categories sum strictly to 20 cases in every condition.
> - Diagnostic flags tracked separately: Condition B had 1 case with happy-path regression (bench_typeerror_list_iteration, where both tests failed); Condition C had 2 cases where both tests failed (bench_typeerror_length_check, bench_attrerror_status_code); Condition D had 1 pure regression (bench_typeerror_list_iteration, where the bug was fixed on Turn 2 but broke the happy path).
> - Token accounting distinguishes **per-case totals** (summed across attempts per case, then averaged over 20 cases) from **per-generation averages** (total tokens divided by total LLM calls: 20 in A, 20 in B, 44 in C, 40 in D; 124 total).

### C. Pass/Fail Transitions & Analysis
1. **Demonstrations on First Attempt (Condition A -> B)**:
   - Pass rate increased from 25.0% to 40.0% (+15.0 pp).
   - Cases helped (4): `bench_keyerror_cache_lookup`, `bench_indexerror_first_token`, `bench_indexerror_last_history`, `bench_zerodiv_aspect_ratio`.
   - Cases harmed (1): `bench_typeerror_list_iteration` (few-shot demonstration prompted defensive cast that broke existing iteration logic).
2. **Docker Closed-Loop Test Feedback (Condition A -> C)**:
   - Pass rate increased from 25.0% to 55.0% (+30.0 pp) without demonstrations.
   - Recovered cases via Docker test-guided loop (6): `bench_indexerror_first_token`, `bench_indexerror_coordinate_pair`, `bench_indexerror_last_history`, `bench_zerodiv_aspect_ratio`, `bench_typeerror_string_concat`, `bench_typeerror_number_addition`.
3. **Combined Closed-Loop + In-Context Learning (Condition B -> D)**:
   - Pass rate increased from 40.0% to 65.0% (+25.0 pp).
   - Recovered cases via Docker feedback with demonstrations (5): `bench_keyerror_nested_prefs`, `bench_indexerror_split_field`, `bench_typeerror_length_check`, `bench_typeerror_number_addition`, `bench_attrerror_lowercase`.
4. **Accuracy vs. Runtime Tradeoff**:
   - Condition D achieves the highest accuracy (65.0%) with an average of 2.0 attempts and 15.09s total elapsed time per case (vs 8.38s for single-turn A).
   - The +40.0 percentage point gain (25% -> 65%) with only ~6.7s additional latency per case strongly justifies the closed-loop Docker verification loop.

5. **Evaluation Limitations & Scope**:
   - This experiment evaluated in-context prompting using a **frozen snapshot of 5 curated golden demonstrations**, not a longitudinal evaluation of dynamically accumulated learned experiences.
   - Execution was sequential (A -> B -> C -> D). Docker containers were pre-exercised via 40 pre-flight validation runs, but no formal token generation warm-up was applied prior to Condition A.
   - Claims are strictly limited to these **20 specific held-out cases** under qwen2.5-coder:3b and this configuration. Attempt limits beyond 3 were not tested.

### D. Retrieval Invariant Verification
- Verified via `tests/test_self_improving.py::test_retrieval_invariants_rejects_failed_skipped_timedout_invalidated_and_infra_errors`:
  - Failed sandbox test runs cannot be retrieved as few-shot demonstrations (`test_verified=False`).
  - Skipped test runs cannot be retrieved.
  - Timed-out container executions (`exit_code=-1`) cannot be retrieved.
  - Infrastructure error runs (`exit_code in (-6, -8)`) cannot be retrieved.
  - Invalidated experiences (`invalidate_experience`) are immediately filtered from retrieval (`is_active=False`).
  - `PatchEngine` lifecycle guarantees `record_success` is never invoked unless tests pass and are not skipped.

---

## 5. Continuous Repository Monitoring Verification (REQ-FUT-03)

### A. Architectural Scope & Synchronization Boundary
- **Filesystem Watcher**: Powered by `watchdog` library (`Observer` and `FileSystemEventHandler`) wrapped in `RepositoryWatcher` (`core/watcher.py`).
- **Debounced Processing**: Rapid burst events coalesced within a configurable debounce window (`debounce_seconds=1.0` in CLI default, `0.2s` in unit tests).
- **Incremental Indexing Pipeline**:
  - `IncrementalIndexer.sync_repository` detects modified, added, and deleted files using SHA-256 content hashes.
  - `run_pipeline_incremental` (`core/pipeline.py`) purges stale chunk records matching deleted and updated file paths from FAISS vector store and SQLite metadata, then parses and chunks new/modified files.
  - Path normalization ensures forward slashes across all stored chunk paths and incoming file notifications, preventing Windows backslash comparison misses.
  - Dynamic `.gitignore` support (`load_gitignore_patterns`, `is_ignored_by_gitignore`) guarantees user-specified gitignore patterns and dot-directories (`.git`, `.storage`, `node_modules`, `__pycache__`) are never ingested.
- **Query Freshness & Cache Invalidation**:
  - CLI: `on_reindex` callback automatically reinstantiates `QueryEngine(result.store, ...)`.
  - API: Updates `ACTIVE_REPOS[repo_id]` with fresh `store`, `engine`, `dep_graph`, and `lexical_index`.
- **Knowledge Graph Synchronization Contract**:
  - Core dependency graph (`result.graph`) and call graph (`result.call_graph`) are refreshed automatically on incremental re-indexing.
  - Full enhanced knowledge graph (`EnhancedDependencyGraph`) entity re-generation remains an on-demand explicit action (`POST /api/graph/generate`) to avoid heavy AST re-indexing overhead during live edits.

### B. Interface Lifecycle & Multi-Tenant Isolation
- **REST API Endpoints**:
  - `POST /api/repos/{repo_id}/watch/start`: Starts repository filesystem observer in background thread. Idempotent: repeated calls reuse/clean existing observer without leaking threads.
  - `POST /api/repos/{repo_id}/watch/stop`: Gracefully terminates observer and releases resources.
  - `GET /api/repos/{repo_id}/watch/status`: Returns current watching state, root path, and debounce interval.
- **Server Shutdown**: FastAPI `lifespan` hook automatically iterates over `ACTIVE_WATCHERS` and stops all observer threads cleanly.
- **Tenant Isolation**: Updates in Repository A strictly modify Repository A's vector store and chunk entries; Repository B's chunk counts, hashes, and query engines remain completely untouched.
- **Workspace Safety**: Monitoring is strictly passive/observational; it never automatically generates, applies, stages, or commits patches.

### C. Automated Test Coverage
- `tests/test_continuous_monitoring.py` (8/8 passed):
  1. `test_watcher_modify_existing_function`: Edited function content immediately reflected in top-ranked query search results.
  2. `test_watcher_add_and_delete_source_file`: Newly added file symbols retrievable; subsequent deletion purges all chunks from vector store.
  3. `test_watcher_rename_file_no_duplicate_stale_entries`: Renamed file moves chunks to new path without ghost entries or duplicates.
  4. `test_watcher_ignores_excluded_files_and_directories`: `.gitignore` rules, `.env`, and hidden files do not trigger re-indexing.
  5. `test_watcher_debounce_coalesces_rapid_edits`: 6 rapid writes within 80ms coalesce into a single re-indexing pass with final state.
  6. `test_multi_repository_isolation_under_monitoring`: Edits in Repo A leave Repo B completely unaltered.
  7. `test_syntax_error_resilience_during_watcher_sync`: Syntax errors in watched files log diagnostics without crashing watcher; fixing file restores index.
  8. `test_rest_api_watch_endpoints_lifecycle`: API watch start, status, stop, and duplicate-start idempotency verified under authenticated TestClient.
- `tests/test_file_watcher.py` (8/8 passed):
  - Path filtering, debouncing, watcher lifecycle, live incremental reindex, directory moves/deletions, and facade API.
- Complete documentation: [docs/repository_monitoring/EVIDENCE.md](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/docs/repository_monitoring/EVIDENCE.md).

---

## 8. Multi-Repository Reasoning & Namespaced Indexing Verification (REQ-FUT-08)

### A. Architectural Invariants & Retrieval Integrity
- **Namespaced Chunk Model & Collision Guard**:
  - Chunks across repositories are identified uniquely by `namespaced_id = f"{repo_id}::{chunk.chunk_id}"`.
  - Base `chunk_id` attributes are cloned, preventing cross-repo overwrites when repositories have identical file paths (`config.py`) or symbol names (`get_settings`).
  - Standardized source citations enforce `[repo_id:file_path:start_line-end_line]` format.
- **Fair-Allocation Federated Retrieval**:
  - Implements balanced per-repository candidate pooling (`max(1, ceil(top_k / num_repos)) * 2`), preventing large repositories (e.g. 15 chunks) from starving smaller microservice repositories (e.g. 1 chunk).
  - Explicit repository filtering: only requested repositories are searched; queries never silently expand to all indexed repositories.
  - Unrequested or unrelated third repositories are strictly excluded from retrieval, context assembly, and answer citations.
- **Microservice Contract Detection & Relationship Governance**:
  - Discovers cross-repository HTTP contracts across producer route definitions (`@app.get/post/put/delete`, `@app.route`) and consumer HTTP client invocations (`requests.get/post`, `httpx.get/post`, `axios`, `fetch`).
  - Strictly distinguishes **Observed Code Facts** (verified endpoint definitions and client call sites with source line citations) from **Inferred Relationships** (`basis="inferred_by_route_and_client_pattern"`).
  - Explicitly disclaims candidate impact analysis: matching symbol names or route patterns alone are not claimed as proof of runtime dependency without dynamic contract validation.
- **Multi-Tenant Authorization & Privacy**:
  - In `backend/api/multi_repo.py`, both workspace creation (`POST /api/multi-repo/workspace`) and ad-hoc multi-repo querying (`POST /api/multi-repo/query`) validate repository ownership via `get_repo_for_user`.
  - Unauthorized repositories in requested scope immediately raise HTTP 403 Forbidden; unauthorized content is strictly barred from retrieved chunks, assembled prompts, and reports.
- **Deterministic Context Assembly & Live Model Inference**:
  - Assembles structured multi-repo context deterministically without requiring an LLM.
  - Tested live with local Ollama model (`qwen2.5-coder:3b`), synthesizing multi-repo answers while retaining verified source citations.

### B. Automated Test Coverage
- `tests/test_multi_repo.py` (13/13 passed):
  1. `test_namespaced_chunk_properties`: Verifies `repo_id::chunk_id` namespacing and `[repo_id:path:start-end]` citations.
  2. `test_multi_repo_workspace_aggregation_and_namespacing`: Verifies multi-repo federation and repository identity retention.
  3. `test_cross_repo_contract_discovery`: Verifies AST route detection and client call site mapping.
  4. `test_federated_search_and_repo_filtering`: Verifies searching only selected repos and filtering unselected repos.
  5. `test_federated_ask_citations`: Verifies citation formatting and source attribution.
  6. `test_multi_repo_fastapi_endpoints`: Verifies REST API for workspace creation, contract listing, and querying.
  7. `test_cross_repository_workflow_service_and_client_contract`: Verifies complete service-client workflow, observed facts, inferred relationships, candidate impact analysis, and snapshot freshness.
  8. `test_unrelated_third_repo_exclusion`: Verifies that an unrequested 3rd repository is strictly excluded from results.
  9. `test_multi_repo_authorization_barriers`: Verifies rejection of unauthorized repositories with HTTP 403 / tenant isolation.
  10. `test_duplicate_symbol_names_retain_correct_attribution`: Verifies collision guard when different repos share identical file names and symbol names (`config.py::get_settings`).
  11. `test_fair_allocation_prevents_large_repo_starvation`: Verifies candidate allocation fairness so a large repo cannot starve a small repo.
  12. `test_empty_and_unavailable_repository_handling`: Verifies explicit notices and graceful degradation on empty or missing repositories.
  13. `test_live_local_model_demonstration_if_available`: Live local Ollama model (`qwen2.5-coder:3b`) query execution verifying prompt synthesis and citation preservation.
- Complete documentation: [docs/multi_repository_reasoning/EVIDENCE.md](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/docs/multi_repository_reasoning/EVIDENCE.md).

---

## 9. Distributed Organizational Memory Verification (REQ-FUT-09)

### A. Architectural Invariants & Memory Governance
- **Architecture & Distributed Topology Definition**:
  - In IntelliCodeX, "distributed organizational memory" designates a centralized, persistent shared memory service accessed concurrently by multiple distributed client processes (developer CLI terminals, FastAPI REST API workers, CI/CD validation pipelines) across an organization.
  - Guarded by OS-level process file locking (`file_process_lock` using `msvcrt.locking` on Windows and `fcntl.flock` on Unix) and atomic file replacement (`tempfile` + `os.replace`).
  - Implementation provides multi-process ACID persistence and tenant-isolated shared access. It is explicitly documented that this is NOT a Raft/Paxos-replicated multi-node database cluster.
- **Scoped Record Model & Knowledge Classification**:
  - `OrgMemoryItem` preserves `org_id`, `repo_id`, `scope` (`repo_private` vs `org_shared`), `verification_status`, `security_policy`, `state`, `superseded_by`, and `invalidation_reason`.
  - Distinguishes developer-authored decisions (`verification_status="developer_approved"`), verified repairs (`verification_status="verified"` with security policy provenance), and generated summaries.
  - **Non-Automatic Verification Invariant**: Generated summaries are strictly labeled `verification_status="unverified"`. Generated text never automatically becomes verified organizational knowledge without explicit developer review.
- **Multi-Tenant & Repository Access Barriers**:
  - Memory items are strictly partitioned by `org_id`. Cross-tenant queries are blocked, preventing organizational data leaks.
  - Repository-private memory (`scope="repo_private"`) is restricted to authorized developers who own or have explicit permission to access that specific repository; revoking repository access immediately denies subsequent retrieval.
- **Lifecycle Invalidation & Superseding**:
  - `invalidate_record` marks records `invalidated` with audit reason and author identity.
  - `supersede_record` links obsolete records to replacing records.
  - Invalidated and superseded records are excluded from active search results and LLM prompt context by default, while remaining available for audit review via `include_inactive=True`.
- **Durable Persistence Across Restarts**:
  - File-backed disk persistence in `.storage/org_memory/` ensures that all developer decisions, ADRs, and custom items survive application shutdown and restart.
  - Rebuilding FAISS vector index from persisted items on restart ensures continuous semantic and hybrid search capability.
- **Repair Bank Reuse Without Duplication**:
  - Reuses records from `RepairExperienceBank` directly without creating a duplicate repair store, while preserving `security_policy` (`strict` vs `secrets_only`) provenance.

### B. Automated Test Coverage
- `tests/test_org_memory.py` (11/11 passed):
  1. `test_org_memory_item_properties`: Citation formatting, metadata serialization, and embedding text synthesis.
  2. `test_adr_miner_parsing`: Discovery and parsing of Architectural Decision Records (`docs/adr/*.md`).
  3. `test_org_memory_store_search_and_filter`: Hybrid vector + lexical keyword search and memory type filtering.
  4. `test_git_history_miner_current_repo`: Mining real git commit messages, dates, authors, and touched files.
  5. `test_distinction_between_decision_repair_and_generated_summary`: Enforces that generated summaries remain `unverified`, while decisions are `developer_approved` and repairs are `verified`.
  6. `test_multitenant_and_repo_private_authorization_barriers`: Verifies hard cross-tenant isolation, repository-private access restriction, and access revocation barriers.
  7. `test_lifecycle_invalidation_and_superseding_excludes_obsolete`: Verifies that invalidated and superseded records are excluded from normal search retrieval.
  8. `test_persistence_across_application_store_restart`: Demonstrates that store shutdown and restart preserves all records, citations, and search index.
  9. `test_atomic_write_and_process_lock_safety`: Verifies OS-level process file locking (`msvcrt`/`fcntl`) and atomic file replacement preventing corruption under failed writes.
  10. `test_sync_from_repair_bank_preserves_security_policy_provenance`: Reuses `RepairExperienceBank` without duplicate storage while enforcing strict vs secrets_only policy provenance.
  11. `test_api_records_and_query_authorization_lifecycle`: Complete REST API lifecycle test: create records, query org-wide, verify unverified summary invariant, and invalidate records.
- Complete documentation: [docs/organizational_memory/EVIDENCE.md](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/docs/organizational_memory/EVIDENCE.md).

---

## 10. Automatic Test Proposal and Contract Grounding for Missing Tests

### A. Architectural Invariants & Workflow Governance
- **Requirement Propagation**:
  - Universal assumptions that all functions must preserve input collections have been removed.
  - `extract_behavioral_requirements` dynamically inspects active tests, failure stack traces, assertion details, AST docstrings, and user instructions.
  - Distinguishes intentional in-place mutation (e.g. `in-place`, `mutate`, `sort in place`) from explicit immutability requirements (e.g. `deepcopy`, `input_unchanged`, `preserve input`).
- **Missing Test Handling for File-Only Requests**:
  - `discover_relevant_tests` discovers existing tests first.
  - When no tests exist, `TestProposer.analyze_contract` retrieves repository specifications, README sections, AST docstrings, and cross-repo call sites.
  - Identifies explicitly documented behavior vs merely inferred behavior (default parameters, boundary handling, unstated exception contracts).
  - If expected behavior is ambiguous (e.g. disjunctive returns "discount amount or final price" or unstated conversion direction), formulates a focused clarification question with selectable options rather than inventing arbitrary assertions.
- **Candidate Test Generation & Docker Harness Validation**:
  - Generates candidate `pytest` test functions strictly grounded in identified sources.
  - Prepends mandatory review banner: `# [AI-GENERATED TEST PROPOSAL - REQUIRES USER REVIEW]` and adds citations (`# Grounded in: ...`) above each test function.
  - Executes candidate tests **strictly inside Docker sandbox** (`intellicodex-sandbox:latest`).
  - Checks syntax validity, imports/dependencies, and presence of meaningful assertions.
  - Distinguishes harness/dependency failures (`ModuleNotFoundError`, `SyntaxError`) from behavioral assertion failures on untouched code (`AssertionError`).
  - Candidate tests are kept in disposable storage (`<tempdir>/icx_proposed_tests/`) and never touch the host repository automatically.
- **Repair Integration & Safety Gates**:
  - Once accepted by the user, the test contract is frozen and passed to the repair loop via isolated sandbox injection (`extra_files`), leaving the user's host files untouched.
  - Expectations are never rewritten across repair turns to force a repair pass.
  - `render_patch_card` distinctly reports `"PASSES GENERATED TESTS"` with `Contract Grounding: AI-Generated Test Proposal (disposable contract)` separately from independently established existing test suites.
  - Security gates and approval blocking are fully preserved: unverified/failed candidates are rejected on normal approval attempts.

### B. Automated Test Coverage
- `tests/test_target_canonicalization_and_sandbox_regressions.py` (16 tests, 27 total across suite, 100% passed):
  - `test_contract_analysis_extracts_explicit_and_inferred_behaviors`: Verifies docstring parsing, call-site extraction, and explicit vs inferred contract classification.
  - `test_ambiguity_detection_generates_focused_clarification_question`: Verifies that ambiguous specifications produce focused clarification questions with numbered options, and that user clarification resolves ambiguity.
  - `test_test_proposer_generates_grounded_candidate_tests_with_ai_banner`: Verifies candidate tests contain the AI-generated review banner and grounding citations in disposable storage without modifying repository.
  - `test_test_proposal_docker_validation_distinguishes_harness_from_behavioral_errors`: Validates that Docker validation separates broken syntax/imports from genuine behavioral defects.
  - `test_test_freezing_and_extra_files_sandbox_execution`: Verifies that accepted tests are frozen and injected via `extra_files` into the sandbox, executing properly while leaving disk untouched.
  - `test_refinement_feedback_intentional_mutation_preserved`: Verifies that intentional in-place mutation contracts are propagated and universal immutability is not asserted.
  - `test_rejection_of_failed_candidate_approval`: Enforces that unverified or failed candidates cannot be applied by normal approval.



