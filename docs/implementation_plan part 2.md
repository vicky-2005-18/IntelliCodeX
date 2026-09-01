# Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)

## Executive Summary
This implementation plan lays out a structured **10-Week (2-3 Month) Day-by-Day Roadmap** for developing the **IntelliCodeX CLI Core & RAG Engine** during **Semester 1**, followed by a **Preview Plan for Semester 2** focused on building the **Full Web Application & Cloud Server Infrastructure**.

No source code modifications are made in this step; this artifact serves as the comprehensive strategic guide and schedule for your major project.

---

## Semester 1: CLI & Core Intelligence Engine (Weeks 1 to 10)

```
[Phase 1: AST & Graph Engine] ──► [Phase 2: Hybrid RAG & Patching] ──► [Phase 3: TUI & Packaging] ──► [Phase 4: Benchmarking & Demo]
         (Weeks 1-3)                       (Weeks 4-6)                       (Weeks 7-8)                    (Weeks 9-10)
```

---

### PHASE 1: Core Engine & Multi-Language Parsing (Weeks 1 – 3)

#### **Week 1: Multi-Language Parsing & Tree-Sitter Integration** [✅ COMPLETE]
* **Day 1**: ✅ Setup tree-sitter environment, dependencies (`tree-sitter`, language bindings), and defined `core/ts_loader.py`.
* **Day 2**: ✅ Extended `core/parser.py` with multi-language support, `.gitignore` filtering, and file metadata.
* **Day 3**: ✅ Implemented Tree-Sitter AST chunking engine for JS/TS/TSX and Java in `core/tree_sitter_chunker.py`.
* **Day 4**: ✅ Expanded AST chunking for C/C++, Go, Rust, Markdown sectioning, and windowed chunking in `core/chunker.py`.
* **Day 5**: ✅ Wired Tree-Sitter chunker into `core/pipeline.py` and wrote end-to-end multi-language integration tests.
* **Day 6**: ✅ Benchmarked chunking granularity, AST chunk ratios, ingestion speed, and memory footprint in `core/benchmarking.py`.

#### **Week 2: Call-Graph & Dependency Analysis Engine**
* **Day 1**: Upgrade [dependency_graph.py](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/dependency_graph.py) to parse cross-file imports across multi-language projects (ES6 imports, Java imports, C includes).
* **Day 2**: Build symbol caller/callee extractor using AST trees to map function calls between files.
* **Day 3**: Integrate NetworkX centrality algorithms (PageRank, In-Degree/Out-Degree) to identify high-impact core files.
* **Day 4**: Design sub-graph context expansion (retrieving modified files + immediate dependent callers when querying).
* **Day 5**: Add CLI diagnostic sub-commands: `deps:<file>` and `callers:<func>` with tree outputs.
* **Day 6**: Test graph accuracy on `sample_repo` and multi-file Python/JS projects.

#### **Week 3: Index Persistence, Caching & Incremental Re-Indexing**
* **Day 1**: Create SQLite database schema (`.storage/metadata.db`) for tracking file hashes, modification timestamps, and chunk mappings.
* **Day 2**: Implement FAISS index persistence (`.storage/index.faiss`) with load/save functions on CLI boot.
* **Day 3**: Build file hashing module (MD5/SHA256) to detect modified, deleted, or added files instantly.
* **Day 4**: Implement incremental re-indexing in `pipeline.py` (only parse & re-embed changed files).
* **Day 5**: Create Git hook generator (`intellicodex setup-hooks`) for auto-indexing upon commit/pull.
* **Day 6**: Test zero-latency CLI startup when working with pre-indexed repositories.

---

### PHASE 2: Intelligent Retrieval, RAG & Automated Patch Generation (Weeks 4 – 6)

#### **Week 4: Hybrid Search & Advanced Retrieval Engine**
* **Day 1**: Implement BM25 lexical search engine alongside FAISS vector store.
* **Day 2**: Implement Reciprocal Rank Fusion (RRF) to merge Dense (FAISS) + Sparse (BM25) search rankings.
* **Day 3**: Build Context Window Compression & Token Budgeter in `rag/query_engine.py` to prevent LLM context overflow.
* **Day 4**: Implement Cross-Encoder reranker heuristic for top-K retrieved code blocks.
* **Day 5**: Implement multi-query expansion (splitting complex developer questions into targeted search sub-queries).
* **Day 6**: Evaluate retrieval precision and recall on complex multi-file bug queries.

#### **Week 5: Patch Generation Engine (Unified Diffs)**
* **Day 1**: Create new module `core/patch_engine.py` for automated patch synthesis.
* **Day 2**: Design zero-shot / few-shot prompts for generating standard Git Unified Diffs (`--- a/file +++ b/file`).
* **Day 3**: Build diff parser and syntax validator to verify patch structural integrity before execution.
* **Day 4**: Implement `git apply --check` dry-run validation to test if patches apply cleanly to the codebase.
* **Day 5**: Integrate patch generation into `localize_bug()` workflow in `rag/query_engine.py`.
* **Day 6**: Test end-to-end bug localization -> unified diff patch output on sample buggy repo.

#### **Week 6: Interactive Patch Application & Safety Workflow**
* **Day 1**: Build interactive CLI patch review prompt (`[A]pply patch, [R]eject, [E]dit prompt, [D]iff preview`).
* **Day 2**: Implement side-by-side terminal diff viewer using visual indicators.
* **Day 3**: Add Git branch creation (`git checkout -b fix/intellicodex-...`) and automatic commit creation.
* **Day 4**: Build automated backup & rollback command (`intellicodex patch undo`).
* **Day 5**: Add automated test execution pipeline (auto-run `pytest` or `npm test` after applying patch).
* **Day 6**: Validate complete automated bug localization -> patch creation -> test verification flow.

---

### PHASE 3: Rich Terminal UI (TUI), UX & CLI Packaging (Weeks 7 – 8)

#### **Week 7: Advanced Terminal UI with `rich` & `prompt_toolkit`**
* **Day 1**: Integrate Python `rich` library into [cli.py](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/cli.py) (colored panels, tables, spin loaders, markdown rendering).
* **Day 2**: Add auto-completion, command history, and persistent shell sessions using `prompt_toolkit`.
* **Day 3**: Build interactive fuzzy-search file and symbol browser inside CLI (`files`, `symbols`).
* **Day 4**: Enhance multi-repo management commands (`repo list`, `repo switch`, `repo status`, `repo remove`).
* **Day 5**: Implement streaming response tokens for Ollama LLM queries (typewriter effect in terminal).
* **Day 6**: Polish command help screens, error handling, and offline/online backend badges.

#### **Week 8: Global Configuration & CLI Packaging (`pip install`)**
* **Day 1**: Implement centralized config management (`~/.intellicodex/config.json`) for default models, backends, and paths.
* **Day 2**: Add support for switching remote OpenAI/Anthropic/Ollama API base URLs dynamically via CLI commands.
* **Day 3**: Create `pyproject.toml` / `setup.py` setup for packaging IntelliCodeX as a standalone CLI application.
* **Day 4**: Bind `intellicodex` entry point command to invoke `cli.py` directly from any terminal prompt.
* **Day 5**: Verify cross-platform terminal compatibility (Windows CMD/PowerShell, Linux Bash/Zsh, macOS).
* **Day 6**: Write CLI user guide and publish documentation in `docs/cli_guide.md`.

---

### PHASE 4: Benchmarking, Testing & Semester Final Demo (Weeks 9 – 10)

#### **Week 9: System Benchmarking & Quality Assurance**
* **Day 1**: Benchmark retrieval accuracy (MRR - Mean Reciprocal Rank, Recall@K).
* **Day 2**: Test bug localization performance against open-source repo benchmark datasets.
* **Day 3**: Measure ingestion latency, FAISS index build times, and RAM usage on large repos (>50k LOC).
* **Day 4**: Write automated integration tests covering all CLI commands and pipeline components.
* **Day 5**: Perform edge-case testing (handling binary files, giant files, empty repos, missing Git).
* **Day 6**: Optimize performance bottlenecks (parallel batch embedding, FAISS indexing optimizations).

#### **Week 10: Final Semester Documentation, Presentation & Demo**
* **Day 1**: Update architecture diagrams and system documentation ([intellicodex_system_documentation.md](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/intellicodex_system_documentation.md)).
* **Day 2**: Create high-quality terminal GIF / video recordings demonstrating CLI capabilities.
* **Day 3**: Prepare major project report chapters (Abstract, Problem Statement, CLI RAG Architecture, Results).
* **Day 4**: Prepare slide deck for academic project defense & supervisor evaluation.
* **Day 5**: Conduct live dry-run presentation of IntelliCodeX CLI.
* **Day 6**: Tag release `v1.0.0-cli` on GitHub and mark Semester 1 complete! 🎉

---

## Semester 2 Preview: Web Application & Cloud Architecture (Next Semester)

In Semester 2, IntelliCodeX will evolve from a local CLI tool into a modern, web-based visual code intelligence workspace.

```
┌────────────────────────────────────────────────────────────────────────┐
│                      SEMESTER 2 WEB APP ARCHITECTURE                  │
│                                                                        │
│  [ React / Next.js Web UI ] ◄──WebSockets/REST──► [ FastAPI Server ]   │
│              │                                          │              │
│      (Monocle Code View,                       (Ingest, Vector DB,     │
│    Interactive D3 Graph,                       LLM Orchestrator,       │
│    Visual Patch Editor)                        Celery Task Queue)      │
└────────────────────────────────────────────────────────────────────────┘
```

### High-Level Semester 2 Timeline (10 Weeks Preview)

* **Weeks 1–2: REST API & Real-Time Streaming Backend**
  * Expand FastAPI backend ([server/api.py](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/server/api.py)) with endpoints for repositories, search, patching, and graph export.
  * Implement WebSocket handlers for real-time LLM token streaming and background ingestion progress updates.

* **Weeks 3–4: Web Application Setup & Core Layout (Next.js / React)**
  * Initialize sleek web frontend with modern dark-mode, glassmorphism UI design system.
  * Build responsive layout with Sidebar Repository Navigator, Chat Drawer, and Main Workspace Panel.

* **Weeks 5–6: Interactive Code View & Graph Visualization**
  * Integrate Monaco Editor / Syntax Highlighting code viewer with inline bug citations.
  * Build interactive force-directed Dependency Graph visualizer using D3.js or Cytoscape.js.

* **Weeks 7–8: Visual Patch Inspector & Code Editor**
  * Build side-by-side diff viewer for generated patches with inline code edit and accept/reject controls.
  * Add multi-session history, saved chats, and prompt library management.

* **Weeks 9–10: Multi-User Authentication, Containerization & Final Web Demo**
  * Implement JWT authentication, multi-repository workspace isolation, and background task queues (Redis + Celery).
  * Dockerize full stack (`docker-compose.yml` for Frontend, FastAPI Server, Ollama, Vector DB).
  * Final Major Project Defense & Live Web App Showcase.

---

## Verification Plan

### Manual Verification of Plan
1. **Review Schedule Alignment**: Confirm 10-week schedule aligns with academic semester timelines (2-3 months).
2. **Resource & Technical Check**: Verify required local AI models (`qwen2.5-coder:3b`, `nomic-embed-text`) run smoothly on target hardware.
3. **Weekly Progress Tracking**: Use weekly milestone checklists to verify completion of CLI sub-modules before moving to next phase.
