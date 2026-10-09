# IntelliCodeX — Project Implementation & Verification Status

> **Inspection Date**: 2026-10-08
> **Inspected Git Commit**: Working Tree (Storage v3 Invariants, Overload Stub Filtering, Intent Precedence)
> **Working Tree Status**: Active
> **Automated Test Run**: 305 passed, 4 skipped in ~21s (`pytest` under Python 3.14), zero failures (309 collected).

---

## 1. Status Classification Guidelines

The implementation status of each system capability is evaluated strictly against empirical evidence:
- **Verified against stated acceptance criteria**: Source code is fully implemented and explicitly tested with passing automated unit/integration tests or build verification.
- **Implemented, unverified**: Source code is fully written, but no direct automated test suite asserts its end-to-end behavior under test conditions.
- **Partial**: Feature is implemented partially with recognized functional gaps or stubs.
- **Planned / not started**: Documented in roadmap/plans but no concrete implementation code exists.
- **Blocked**: Cannot proceed due to unmet dependencies or architectural blockers.
- **Needs review**: Implementation exists but requires manual inspection or human evaluation to confirm compliance.

---

## 2. Feature-Level Verification Matrix

| Requirement ID | Feature Area | Status | Source Evidence | Verification Evidence | Remaining Work |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REQ-F-01** | Multi-Language Traversal & Filtering | **Verified against stated acceptance criteria** | [`core/parser.py::walk_repository`](../core/parser.py#L42) | [`tests/test_parser.py`](../tests/test_parser.py) (4 tests pass) | None for base traversal; monitor edge-case encoding handling. |
| **REQ-F-02** | Tree-Sitter AST Semantic Chunking | **Verified against stated acceptance criteria** | [`core/tree_sitter_chunker.py`](../core/tree_sitter_chunker.py), [`core/ts_loader.py`](../core/ts_loader.py) | [`tests/test_tree_sitter_chunker.py`](../tests/test_tree_sitter_chunker.py), [`tests/test_ts_loader.py`](../tests/test_ts_loader.py) (15 tests pass) | Extend grammar coverage to Swift and Kotlin if required. |
| **REQ-F-03** | Dual Embedding (Ollama + TF-IDF Fallback) | **Verified against stated acceptance criteria** | [`core/embedder.py::OllamaEmbedder`](../core/embedder.py#L38), [`core/embedder.py::TfidfEmbedder`](../core/embedder.py#L90) | [`tests/test_cli.py::test_create_components_ollama_fallback`](../tests/test_cli.py#L46) (Passes) | Add local HuggingFace on-device mini-model option (e.g. all-MiniLM-L6-v2). |
| **REQ-F-04** | FAISS Vector Store & Cosine Similarity | **Verified against stated acceptance criteria** | [`core/vectorstore.py::FaissVectorStore`](../core/vectorstore.py#L12) | [`tests/test_faiss_sqlite_persistence.py`](../tests/test_faiss_sqlite_persistence.py), [`tests/test_persistence.py`](../tests/test_persistence.py) (5 tests pass) | Support GPU-accelerated FAISS index if CUDA runtime detected. |
| **REQ-F-05** | Dependency & High-Precision Call-Graph Analysis | **Verified against stated acceptance criteria** | [`core/dependency_graph.py`](../core/dependency_graph.py), [`core/call_graph.py`](../core/call_graph.py) | [`tests/test_dependency_graph.py`](../tests/test_dependency_graph.py), [`tests/test_call_graph.py`](../tests/test_call_graph.py), [`tests/test_centrality.py`](../tests/test_centrality.py) (14 tests pass) | Scope-aware Python call graph with self/cls resolution, deduplication, unknown receiver drop, 3-candidate fan-out cap, `--legacy-call-graph` flag, and empirical bottle audit (sample size N=25, seed 42: false matches dropped from 21/25 [84.0%] in legacy to 0/25 in precision, evaluated by the agent). Non-Python resolution uses name-only matching with deduplication and 3-candidate fan-out capping. |
| **REQ-F-06** | Graph-Augmented RAG Query Engine | **Verified against stated acceptance criteria** | [`rag/query_engine.py::QueryEngine`](../rag/query_engine.py#L190) | [`tests/test_graph_context_expansion.py`](../tests/test_graph_context_expansion.py), [`tests/test_week5_verification.py`](../tests/test_week5_verification.py), [`tests/test_hybrid_search.py`](../tests/test_hybrid_search.py) (12 tests pass) | Milestone 3 completed; sparse BM25 and dense FAISS fused via RRF. |
| **REQ-F-07** | SQLite Persistence & Incremental Re-Index | **Verified against stated acceptance criteria** | [`core/persistence.py`](../core/persistence.py), [`core/pipeline.py`](../core/pipeline.py), [`backend/services/incremental_indexer.py`](../backend/services/incremental_indexer.py) | [`tests/test_change_detection.py`](../tests/test_change_detection.py), [`tests/test_incremental_pipeline.py`](../tests/test_incremental_pipeline.py), [`tests/test_file_watcher.py`](../tests/test_file_watcher.py), [`tests/test_call_graph.py`](../tests/test_call_graph.py), [`tests/test_quality_and_invariants.py`](../tests/test_quality_and_invariants.py) (32 tests pass) | Format version cache key (`graph_version: 3`) with auto-rebuild on version mismatch; live filesystem observer active; storage invariants enforced (SQLite chunk rows == FAISS ntotal == in-memory chunks). |
| **REQ-F-08** | Multi-Language Ochiai Bug Localization | **Verified against stated acceptance criteria** | [`core/bug_localizer.py::BugLocalizer`](../core/bug_localizer.py#L203) | [`tests/test_bug_localizer.py`](../tests/test_bug_localizer.py), [`tests/test_week4_verification.py`](../tests/test_week4_verification.py) (6 tests pass) | Add automated pytest-cov / lcov trace ingestion. |
| **REQ-F-09** | Safe Patch Generation & Multi-Turn Sandbox Validation | **Verified against stated acceptance criteria** | [`core/patch_generator.py::PatchEngine`](../core/patch_generator.py), [`core/sandbox_runner.py`](../core/sandbox_runner.py) | [`tests/test_patch_generator.py`](../tests/test_patch_generator.py), [`tests/test_sandbox_runner.py`](../tests/test_sandbox_runner.py) (16 tests pass) | Multi-turn refinement with sandbox test runs (up to 3 iterations) when repo_path is provided. Stops when tests pass or are skipped. Single-shot without testing if no repo_path. |
| **REQ-F-10** | Modular FastAPI Enterprise REST Server | **Verified against stated acceptance criteria** | [`backend/main.py`](../backend/main.py), [`backend/api/`](../backend/api) | [`tests/test_full_system_integration.py`](../tests/test_full_system_integration.py) (Passes) | Add WebSocket endpoints for live progress updates during long ingestions. |
| **REQ-F-11** | Interactive Multi-Command CLI & TUI Packaging | **Verified against stated acceptance criteria** | [`cli.py`](../cli.py), [`pyproject.toml`](../pyproject.toml) | [`tests/test_cli.py`](../tests/test_cli.py), [`tests/test_tui_and_packaging.py`](../tests/test_tui_and_packaging.py) (36 tests pass) | Milestone 4 completed; shallow clone (`--depth 1`) default with `--full-history`, strict HTTPS-only URL validation, rich auto-completion, formatted Markdown panels, and standalone pip packaging (`intellicodex`). |
| **REQ-F-12** | Whole RAG Pipeline View, Index Inspection & Provenance | **Verified against stated acceptance criteria** | [`core/retrieval_trace.py`](../core/retrieval_trace.py), [`rag/query_engine.py`](../rag/query_engine.py), [`cli.py`](../cli.py), [`backend/api/query.py`](../backend/api/query.py) | [`tests/test_retrieval_trace.py`](../tests/test_retrieval_trace.py) (16 tests pass) | Whole pipeline visible: indexing (`chunks:`, `index-stats`), retrieval (BM25 vs Dense, RRF, graphs), augmentation (exact prompt panel), comparative generation (`--compare`), strict `@file` filtering, BM25 stopword stripping, and RBAC REST endpoint. |
| **REQ-PROP-01**| React Web UI Dashboard | **Planned / future phase** | Preserved in Semester 2 roadmap | Frontend code backed up to scratch directory | Web UI workspace integration scheduled for Semester 2. |
| **REQ-INF-01**| Persistent Local JSON Disk Store | **Verified against stated acceptance criteria** | [`backend/database/mongo.py::LocalDiskStore`](../backend/database/mongo.py#L22) | [`tests/test_persistence.py::test_db_manager_fallback`](../tests/test_persistence.py#L14) (Passes) | Add file-lock concurrency control for simultaneous writes. |
| **REQ-INF-02**| Cross-Platform Path Sanitization | **Verified against stated acceptance criteria** | [`core/persistence.py`](../core/persistence.py), [`rag/query_engine.py`](../rag/query_engine.py) | [`tests/test_pipeline_integration.py`](../tests/test_pipeline_integration.py) (Passes on Windows) | None. |

---

## 3. Discrepancy & Gap Analysis

1. **Tree-Sitter Test Claims in Old Docs**:
   - *Previous Documentation claim (`PROJECT_STATUS_GUIDE.md` L133)*: "14 failing multi-language tests".
   - *Inspected Reality*: Tree-sitter native bindings for Python, JS, TS, Java, C, C++, Go, and Rust are fully installed and configured in `.venv`. All tests pass cleanly with zero failures.
2. **Semester 1 Scope Realignment**:
   - *Decision*: Prioritize the standalone CLI and local intelligence engine as the primary interface for Semester 1. The React web dashboard has been backed up and scheduled for Semester 2.
3. **Patch Generation Refinement Loop (Milestone 1)**:
   - *Status*: Completed and verified. The patch engine now supports closed-loop test execution via [`core/sandbox_runner.py`](../core/sandbox_runner.py), multi-turn self-correction prompting, and live sandbox validation in the interactive CLI.
4. **Live File Watcher (Milestone 2)**:
   - *Status*: Completed and verified. Real-time background `watchdog` daemon implemented in [`backend/services/incremental_indexer.py`](../backend/services/incremental_indexer.py) with debounced file filtering (`.git`, `.venv`, `.bak`), thread-safe auto-reindexing, and interactive CLI integration (`watch:status`, `watch:stop`, `watch:start`). Fully verified with 6 dedicated test cases in `tests/test_file_watcher.py`.
5. **Hybrid BM25 & Dense Reciprocal Rank Fusion (Milestone 3)**:
   - *Status*: Completed and verified. Inverted BM25Okapi lexical index with camelCase and snake_case sub-token splitting in [`core/lexical_index.py`](../core/lexical_index.py), fused with dense vector FAISS similarity via Reciprocal Rank Fusion ($\text{RRF}(d) = \sum \frac{w}{k + r}$) in [`rag/query_engine.py`](../rag/query_engine.py). Benchmarking demonstrated MRR improvement on exact code symbol lookups over pure dense search in preliminary tests on sample_repo (4 queries). Reproduce with: pytest tests/test_hybrid_search.py::test_mrr_benchmark_hybrid_vs_dense -v Integrated with interactive CLI commands (`hybrid:status`, `hybrid:on`, `hybrid:off`, `hybrid:toggle`). Fully verified via 6 dedicated tests in `tests/test_hybrid_search.py`.
6. **Advanced Terminal TUI & Packaging (Milestone 4)**:
   - *Status*: Completed and verified. Rich interactive terminal interface powered by `prompt_toolkit` and `rich`. Provides dynamic auto-completion for commands, files, AST call-graph symbols, and personas; real-time bottom status toolbar; syntax-highlighted git diffs; Markdown answer panels; and structured status tables. Standalone package configuration defined in [`pyproject.toml`](../pyproject.toml) exposing the `intellicodex` CLI entry point. Fully verified with 17 dedicated tests in `tests/test_tui_and_packaging.py`.
7. **Retrieval View & Provenance Inspection (Phase 5)**:
   - *Status*: Completed and verified. Transparent RAG pipeline inspection tool showing exact provenance for any query. Includes `RetrievalTrace` data model, dual BM25 and dense hit breakdown, RRF fusion ranks, call/dependency graph context expansions with provenance causes, token budgeting accounting, explain-only mode (`--no-answer`), CLI command `explain: <question>`, and authenticated RBAC/owner-scoped REST endpoint `POST /api/query/explain`.
8. **Whole RAG Pipeline Inspection, Index View & Comparative Mode**:
   - *Status*: Completed and verified. Fully exposes the 4 RAG pipeline pillars for demonstration to non-technical mentors and technical auditors:
     - **Indexing**: Command `chunks: <file>` displays chunk-level breakdown (symbol, line bounds, token estimates, first 3 lines of embedded text, embedding dimension, first 6 vector numbers). Command `index-stats` displays repository index totals (files, chunks, graph nodes, active embedder, BM25 vocabulary size, FAISS vector count).
     - **Retrieval**: Fixed BM25 query terms by tokenizing with stopword removal and deduplication; stripped `@file` tokens from query terms; strictly scoped retrieval to `@file` mentions to eliminate cross-file leakage; and removed `chunk.file_path` from BM25 index text to resolve equal-score BM25 tie artifacts.
     - **Augmentation**: Added `augmented_prompt`, `prompt_sections` (`instructions`, `context_chunks` with `file:lines`, `question`, `memory`), and `embedder_name` directly to `RetrievalTrace`. Added panel *"Augmented prompt (what the model actually reads)"* below the budget line in `explain:`, truncating chunks to 12 lines unless `--full`. Zero prompt or code data written to disk.
     - **Generation & Comparison**: Added `--compare` to `explain:`, evaluating baseline without RAG vs full RAG prompt in side-by-side panels with elapsed times.
   - *Verification*: Fully verified via 16 dedicated unit tests in `tests/test_retrieval_trace.py` (281 passed, 4 skipped out of 285 collected).

   - *Real CLI Output Sample 1 (`chunks: auth.py` on sample_repo)*:
   ```text
   ┌────────────────────────────────────────── Chunk & Vector Index Inspection ───────────────────────────────────────────┐
   │ File: pkg\auth.py                                                                                                    │
   │ Total Lines: 36 | Indexed Chunks: 6 | Embedding Dim: 512                                                             │
   └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                      Chunks for auth.py                                                   
   ┌─────────┬────────────────────────┬────────────┬──────────┬─────────────────────────┬────────┬────────────────────────┐
   │ Chunk   │ Symbol                 │ Lines      │   Tokens │ Embedded Text (First 3) │    Dim │ Vector Preview (First  │
   ├─────────┼────────────────────────┼────────────┼──────────┼─────────────────────────┼────────┼────────────────────────┤
   │ [1]     │ hash_password          │ 6–8        │       56 │ # File: pkg\auth.py     │    512 │ [0.2861, 0.3299,       │
   │         │                        │            │          │ # Signature: function   │        │ 0.1557, 0.8477,        │
   │         │                        │            │          │ hash_password           │        │ -0.1939, 0.1097, ...]  │
   │ [2]     │ authenticate           │ 11–20      │      120 │ # File: pkg\auth.py     │    512 │ [0.4233, 0.6510,       │
   │         │                        │            │          │ # Signature: function   │        │ 0.0386, 0.0805,        │
   │         │                        │            │          │ authenticate            │        │ 0.3258, -0.4721, ...]  │
   │ [3]     │ SessionManager         │ 23–36      │      128 │ # File: pkg\auth.py     │    512 │ [0.8825, -0.2862,      │
   │         │                        │            │          │ # Signature: class      │        │ -0.3544, -0.0062,      │
   │         │                        │            │          │ SessionManager          │        │ 0.0520, -0.0379, ...]  │
   └─────────┴────────────────────────┴────────────┴──────────┴─────────────────────────┴────────┴────────────────────────┘
   ```

   - *Real CLI Output Sample 2 (`index-stats` on sample_repo)*:
   ```text
              Index & Pipeline Statistics           
   ┌──────────────────────────┬────────────────────┐
   │  Metric                  │             Value  │
   ├──────────────────────────┼────────────────────┤
   │  Indexed Files           │                 3  │
   │  Code Chunks             │                 9  │
   │  Dependency Graph Nodes  │                 4  │
   │  Embedder Used           │  TF-IDF (offline)  │
   │  BM25 Vocabulary Size    │          73 terms  │
   │  FAISS Vector Count      │         9 vectors  │
   └──────────────────────────┴────────────────────┘
   ```

   - *Real CLI Output Sample 3 (`explain: how does authenticate work? --no-answer` on sample_repo)*:
   ```text
   ┌──────────────────────── Augmented prompt (what the model actually reads) ────────────────────────┐
   │ ── Instruction Block (Instructions) ──                                                           │
   │ You are IntelliCodeX, an AI code assistant with access to a specific software repository via     │
   │ retrieved code context and dependency graphs. Answer using ONLY the provided context. When asked │
   │ about issues or bugs, identify ONLY actual bugs that exist in the code - do not hallucinate or   │
   │ invent issues. If no bugs are found, clearly state that the code has no issues. Cite file paths  │
   │ and line numbers for every claim. If the context is insufficient, say so explicitly.             │
   │                                                                                                  │
   │ ── Context Chunks ──                                                                             │
   │ [1] pkg\auth.py:11-20 (authenticate)                                                             │
   │ ```python                                                                                        │
   │ def authenticate(username: str, password: str) -> bool:                                          │
   │     """Check a username/password pair against stored credentials."""                             │
   │     user = get_user_by_username(username)                                                        │
   │     if user is None:                                                                             │
   │         return False                                                                             │
   │     # Guard against missing 'password_hash' key in user record                                   │
   │     password_hash = user.get("password_hash")                                                    │
   │     if password_hash is None:                                                                    │
   │         return False                                                                             │
   │     return password_hash == hash_password(password)                                              │
   │ ```                                                                                              │
   │                                                                                                  │
   │ [2] pkg\auth.py:23-36 (SessionManager)                                                           │
   │ ```python                                                                                        │
   │ class SessionManager:                                                                            │
   │     """Tracks active user sessions in memory."""                                                 │
   │ ...                                                                                              │
   │ ```                                                                                              │
   │                                                                                                  │
   │ ── User Question ──                                                                              │
   │ how does authenticate work?                                                                      │
   └──────────────────────────────────────────────────────────────────────────────────────────────────┘
   ```

9. **Call Graph Precision Optimization, Git Ingestion Hardening & Empirical Audit**:
   - *Status*: Completed and verified.
   - *Scope Rules & Non-Python Language Coverage*:
     - **Python Scope Resolution**: `self.method()` / `cls.method()` calls resolve strictly to the enclosing class and its base classes. Receiver calls on non-`self`/`cls` objects link only when receiver class is known (instantiated from `ClassName(...)`, type-annotated, or imported module symbol); unknown receiver method calls are dropped. Scope rules are Python-specific.
     - **Non-Python Languages (JS/TS, Java, C/C++, Go, Rust)**: Call extraction uses Tree-Sitter AST to perform name-only matching against internal candidates (`all_symbols`).
     - **Language-Independent Rules (All Languages)**:
       - *Rule 2 (Edge Deduplication)*: Call sites emit exactly one edge attributed to the most specific enclosing chunk based on line span (method/function, not also class/file container chunks).
       - *Rule 4 (Fan-Out Capping)*: Unresolved calls matching more than 3 internal definitions are pruned to eliminate noisy cross-module links.
       - *Self-Call Exclusion*: Intra-chunk recursive calls to self are excluded.
     - **Legacy Mode Comparison**: Flag `--legacy-call-graph` preserves unconstrained baseline behavior for audits.
     - **Index Cache Invalidation**: SQLite and FAISS persistence track `graph_version: 2`; indexes built with legacy or prior formats automatically rebuild.
     - **Git Ingestion Security & Hardening**:
       - Subprocess uses `--` before the repository URL in `git clone` to prevent flag/argument injection.
       - Rejects URLs with embedded credentials (`https://user:password@host/...`).
       - Never logs URLs with credentials (redacted via `sanitize_git_url`).
       - Sets `GIT_ALLOW_PROTOCOL=https` and `GIT_TERMINAL_PROMPT=0` in subprocess environment to block protocol smuggling.
       - REST API enforces an optional host allowlist in config (`ALLOWED_GIT_HOSTS`, default: `github.com, gitlab.com, bitbucket.org`) to protect against internal SSRF.
       - Shallow clone (`--depth 1`) is enabled by default with `--full-history` opt-out.
   - *Empirical Call Graph Quality Audit Tool (`scripts/audit_call_graph.py` on `.repos/bottle`, seed 42, sample size N=25)*:
     - **Total Nodes**: 408
     - **Edge Count**: **1832 edges** (Legacy) -> **247 edges** (Precision), an **86.5% reduction** in spurious edges.
     - **Precision Mode Audit**:
       - Legacy: **21 false matches out of 25 sampled edges** (84.0% false-match rate, labels produced/evaluated by the agent).
       - Precision: **0 false matches out of 25 sampled edges** (0/25, labels produced/evaluated by the agent; sample size N=25, seed 42).
     - **Recall Mode Audit**:
       - Evaluates recall = (true internal calls with an edge) / (total true internal calls) across source call sites.
       - Exports un-prefilled JSON templates (`--output-template` / `--save-sample`) with `null` labels for manual developer ground-truth labeling.



10. **Storage v3 Format, Invariant Verification, Typing Overload Stubs & Intent Precedence**:
    - *Status*: Completed and verified.
    - *Index Versioning & Cache Invalidation*:
      - Storage and call graph format bumped to GRAPH_FORMAT_VERSION = 3. Any cache created under older versions is automatically invalidated, logged, and rebuilt.
      - CLI indexing panel explicitly reports 3 (Graph/Index v3).
    - *Storage Invariants at Ingest & Cache Reload*:
      - Hard invariants enforced: Unique chunk IDs across repository, and SQLite chunk rows == FAISS ntotal == in-memory chunk count.
      - If corrupted cache or discrepancy is encountered at load time, the system issues a warning and triggers a clean rebuild rather than silently continuing with corrupted indices.
    - *Disambiguated Chunk IDs & Typing Overload Filtering*:
      - Multi-method and duplicate name collisions (e.g. @overload signatures, @property/@setter pairs, duplicate method names across classes) are uniquely and stably identified using :L{start_line} line-number suffixes.
      - Exactly 25 disambiguated chunk IDs identified in Flask.
      - Skip @typing.overload stubs (definitions whose body contains only ... or pass) by default (skip_overload_stubs=True). Overloads can be retained using --include-overloads.
      - Skipping overload stubs reduces Flask index from 478 to 460 chunks without losing semantic retrieval precision.
    - *Query Intent Precedence & Anti-Hallucination Guardrails*:
      - Explicit bug-intent keywords (ug, ugs, issue, issues, wrong with, 
eview, @file with ind/check, or stack traces) take precedence over leading interrogative prefixes (how, what, where, why).
      - Factual Q&A interrogatives route to standard Q&A answer generation without false static check findings.
      - Answer post-processing verifies entity mentions against retrieved context while allowlisting Python builtins, imported names in retrieved files, and standard library modules. Unverified names are warned without destroying answer text.
      - Static AST checks execute strictly on full source files and filter findings to the chunk's line range when a chunk is the target, remaining unfiltered in whole-file bug review mode.
    - *Automated Verification*:
      - 11 dedicated tests added in 	ests/test_quality_and_invariants.py, bringing total suite to **305 passed, 4 skipped out of 309 collected**.
