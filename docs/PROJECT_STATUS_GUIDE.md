# IntelliCodeX — Complete Project Status, Architecture Guide & Roadmap

> **Privacy-Preserving, Locally-Hosted AI Code Intelligence, RAG & Automated Software Maintenance Framework**

---

## 📑 Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Current Implementation Status ("What is Done")](#2-current-implementation-status-what-is-done)
  - [2.1 Core Code Ingestion & AST Parsing](#21-core-code-ingestion--ast-parsing)
  - [2.2 Graph Dependency & Call-Graph Engine](#22-graph-dependency--call-graph-engine)
  - [2.3 Vector Database & Persistence](#23-vector-database--persistence)
  - [2.4 RAG Engine & Persona System](#24-rag-engine--persona-system)
  - [2.5 Fault Localization (SBFL / Ochiai) & Patch Generator](#25-fault-localization-sbfl--ochiai--patch-generator)
  - [2.6 Enterprise Backend API (FastAPI)](#26-enterprise-backend-api-fastapi)
  - [2.7 Modern Web Frontend (React + Vite + Tailwind)](#27-modern-web-frontend-react--vite--tailwind)
  - [2.8 Interactive Multi-Command CLI](#28-interactive-multi-command-cli)
- [3. Current Focus & Identified Gaps ("What We Are Doing Right Now")](#3-current-focus--identified-gaps-what-we-are-doing-right-now)
- [4. Future Roadmap ("What to Implement Next")](#4-future-roadmap-what-to-implement-next)
  - [Phase 1: Multi-Language AST Grammar Resolution](#phase-1-multi-language-ast-grammar-resolution)
  - [Phase 2: Autonomous Multi-Turn Agentic Test-Driven Repair](#phase-2-autonomous-multi-turn-agentic-test-driven-repair)
  - [Phase 3: Dedicated Real-Time Telemetry & Analytics UI](#phase-3-dedicated-real-time-telemetry--analytics-ui)
  - [Phase 4: Real-Time File System Daemon & Watcher](#phase-4-real-time-file-system-daemon--watcher)
  - [Phase 5: Distributed Vector Storage & Enterprise Connectors](#phase-5-distributed-vector-storage--enterprise-connectors)
- [5. Step-by-Step Working Guide (End-to-End System Execution)](#5-step-by-step-working-guide-end-to-end-system-execution)
  - [Step 1: Repository Ingestion & Parsing](#step-1-repository-ingestion--parsing)
  - [Step 2: Vector Store Indexing & Hash Caching](#step-2-vector-store-indexing--hash-caching)
  - [Step 3: Context-Grounded Query Answering (RAG)](#step-3-context-grounded-query-answering-rag)
  - [Step 4: Error Trace Analysis & Bug Localization](#step-4-error-trace-analysis--bug-localization)
  - [Step 5: Safe Patch Generation & Application](#step-5-safe-patch-generation--application)
- [6. Models, Parameters & Technical Specifications](#6-models-parameters--technical-specifications)
- [7. Command & API Reference](#7-command--api-reference)

---

## 1. Executive Summary

**IntelliCodeX** is an offline-capable, developer-centric AI code assistant engineered to understand, navigate, and automatically repair software repositories. Unlike cloud-dependent solutions, IntelliCodeX processes code entirely on local hardware (or self-hosted Ollama instances), guaranteeing zero data exfiltration.

```
+-----------------------------------------------------------------------------------------+
|                                    INTELLICODEX ECOSYSTEM                               |
|                                                                                         |
|  [ React Frontend ] <----> [ FastAPI Server ] <----> [ Core Engine & Persistence ]      |
|  - Dashboard               - REST API                - AST Chunking & Tree-Sitter       |
|  - Repo Management         - Auth & JWT              - FAISS + SQLite Vectorstore       |
|  - Interactive Chat        - MongoDB / JSON          - NetworkX Dependency Graph        |
|  - Graph Explorer          - Analytics & Review      - Ochiai Bug Localization          |
|  - Patch Review Diff       - Doc Generator           - Patch Applier with .bak Backups  |
|                                                                                         |
|  [ Interactive CLI ] <-----------------------------> [ Local LLM / Ollama Backend ]     |
|  - python cli.py           (qwen2.5-coder:3b/7b  |  nomic-embed-text  |  TF-IDF SVD)    |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Current Implementation Status ("What is Done")

### 2.1 Core Code Ingestion & AST Parsing
- **Recursive Source Traversal** (`core/parser.py`): Scans project folders while respecting `.gitignore`, excluding binaries, hidden folders, and virtual environments.
- **Python AST Semantic Chunker** (`core/chunker.py`): Parses Python AST trees into `CodeChunk` objects capturing classes, functions, line ranges, docstrings, and imports.
- **Tree-Sitter Multi-Language Chunker** (`core/tree_sitter_chunker.py`, `core/ts_loader.py`): Multi-language AST chunking architecture supporting JavaScript, TypeScript, Java, C/C++, Go, and Rust with whole-file fallback.

### 2.2 Graph Dependency & Call-Graph Engine
- **Dependency Graph Analysis** (`core/dependency_graph.py`): Builds a directed `NetworkX` graph of cross-module import relationships. Computes centrality metrics (in-degree, out-degree, PageRank) to identify architectural choke points.
- **Call-Graph Extractor** (`core/call_graph.py`): Identifies caller-callee relationships across functions for subgraph context expansion during RAG queries.

### 2.3 Vector Database & Persistence
- **Dual Embedding Architecture** (`core/embedder.py`):
  - Primary: `OllamaEmbedder` with `nomic-embed-text` for dense vector representation.
  - Offline Fallback: `TfidfEmbedder` utilizing Scikit-Learn TF-IDF + TruncatedSVD dimensionality reduction.
- **Vector Store** (`core/vectorstore.py`): Fast cosine similarity search with FAISS (`IndexFlatIP` on L2-normalized embeddings).
- **SQLite Metadata Persistence** (`core/persistence.py`): Stores chunk records, SHA-256 file hashes, and serialized FAISS indices under `.storage/`.
- **Git Commit Hooks** (`core/git_hooks.py`): Automated `post-commit` / `post-merge` hook generator to trigger zero-overhead incremental re-indexing.

### 2.4 RAG Engine & Persona System
- **Advanced Query Engine** (`rag/query_engine.py`):
  - Grounded prompt templates forcing exact file and line citations.
  - Dynamic token budgeting (`max_token_budget`) preventing LLM context window overflows.
- **Multi-Turn Conversation Memory** (`ConversationMemory`): Sliding-window history tracker retaining context across multi-step technical conversations.
- **System Persona Switcher**: Supports `general`, `security` (security audit & vulnerability scan), `reviewer` (clean code review), and `architect` (system design & module boundaries).

### 2.5 Fault Localization (SBFL / Ochiai) & Patch Generator
- **Ochiai Spectrum-Based Fault Localization** (`core/bug_localizer.py`):
  - Implements the Ochiai suspiciousness formula to rank faulty statements from test execution records.
- **Multi-Language Stack Trace Parser**: Parses error traces across Python tracebacks, JavaScript/TypeScript `at file:line:col`, Java stack frames, Go runtime panics, and Rust traces.
- **Patch Engine & Diff Merging** (`core/patch_generator.py`, `backend/patch_generator/`):
  - LLM prompting at `temperature=0.1` for deterministic code repairs.
  - AST syntax validator (`ast.parse`) checking patch syntax validity before application.
  - Standard Unified Git Diff generation (`diff --git a/... b/...`).
  - Safe disk patch applier creating timestamped backup files (`.bak`) with automatic rollback.

### 2.6 Enterprise Backend API (FastAPI)
- **Modular REST Routers** (`backend/main.py`, `backend/api/`):
  - `/api/auth`: User registration, JWT login, and token verification.
  - `/api/repos`: Indexing repositories, listing files, status polling, and incremental sync.
  - `/api/chat`: Multi-turn conversational Q&A and persona-based querying.
  - `/api/bugs`: Stack trace analysis and ranked bug localization.
  - `/api/patches`: Diff generation, syntax validation, and physical disk patch application.
  - `/api/graph`: Graph nodes, edges, dependencies, and circular reference detection.
  - `/api/analytics`: Repository complexity, language breakdown, and health metrics.
  - `/api/docs`: Automatic generation of Markdown/HTML/PDF documentation and API references.
  - `/api/review`: Code smell detection, security risk scoring, and auto-generated commit messages.
- **Database Layer** (`backend/database/mongo.py`): MongoDB client with zero-config local JSON disk store fallback when MongoDB is offline.

### 2.7 Modern Web Frontend (React + Vite + Tailwind)
- **Comprehensive UI Pages** (`frontend/src/pages/`):
  - **Dashboard**: High-level repository metrics, language distribution, and system status.
  - **Repository Manager**: Index new projects, re-index, and switch active repositories.
  - **Chat Interface**: Grounded Q&A with live code citations and persona switching.
  - **Dependency Graph Visualizer**: Interactive network representation of module imports.
  - **Bug Localization Page**: Form for stack traces with ranked fault candidates.
  - **Patch Review Page**: Side-by-side Git diff viewer with "Approve & Apply" action.
  - **Doc Generator**: Markdown, HTML, and PDF export preview for repository docs.
  - **Code Review**: Interactive code smell inspector and AI commit message creator.

### 2.8 Interactive Multi-Command CLI
- Single-entry CLI (`cli.py` / `run_cli.bat`):
  - `python cli.py <repo_path> --query "How does auth work?"`
  - `python cli.py <repo_path> --trace "TypeError at auth.py:42"`
  - `python cli.py <repo_path> --fix "Fix KeyError in user dict"`
  - `python cli.py <repo_path> --graph`
  - `python cli.py <repo_path> --benchmark`

---

## 3. Current Focus & Identified Gaps ("What We Are Doing Right Now")

```
[ Active Work & Resolution Items ]
├── 1. Tree-Sitter Language Grammars (14 failing multi-language tests)
├── 2. Dedicated Analytics UI Component (replacing Dashboard wrapper in AnalyticsPage.tsx)
├── 3. Multi-Turn Test-Driven Patch Refinement Loop (self-healing code repair)
└── 4. Real-Time In-Memory File Watcher (instant embedding synchronization)
```

| Component | Current State | Target Enhancement |
| :--- | :--- | :--- |
| **Tree-Sitter Grammars** | Architecture implemented; runtime grammars missing on host environment | Bundle pre-compiled tree-sitter language libraries for JS, TS, Java, C, Go, Rust |
| **Analytics Page** | `AnalyticsPage.tsx` re-renders `DashboardPage` | Build custom telemetry widgets (Cyclomatic Complexity, Halstead score, test ratio) |
| **Patch Engine** | Single-shot patch generation | Autonomous loop: LLM $\rightarrow$ Test Runner (`pytest`) $\rightarrow$ Error Feedback $\rightarrow$ Self-Correction |
| **Change Detection** | Triggered via CLI / Git commit hooks | Background `watchdog` daemon updating embeddings on file save |

---

## 4. Future Roadmap ("What to Implement Next")

```
                 FUTURE ROADMAP PHASES
  ┌──────────────────────────────────────────────────┐
  │ Phase 1: Multi-Language Tree-Sitter Grammars     │
  └────────────────────────┬─────────────────────────┘
                           │
  ┌────────────────────────▼─────────────────────────┐
  │ Phase 2: Autonomous Agentic Test-Driven Repair   │
  └────────────────────────┬─────────────────────────┘
                           │
  ┌────────────────────────▼─────────────────────────┐
  │ Phase 3: Advanced Visual Analytics & Heatmaps    │
  └────────────────────────┬─────────────────────────┘
                           │
  ┌────────────────────────▼─────────────────────────┐
  │ Phase 4: Real-Time Live Watcher Daemon           │
  └────────────────────────┬─────────────────────────┘
                           │
  ┌────────────────────────▼─────────────────────────┐
  │ Phase 5: Distributed Vector Store Integration    │
  └──────────────────────────────────────────────────┘
```

### Phase 1: Multi-Language AST Grammar Resolution
- Install and configure native language bindings (`tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript`, `tree-sitter-java`, `tree-sitter-c`, `tree-sitter-cpp`, `tree-sitter-go`, `tree-sitter-rust`).
- Ensure all 91 test cases in the test suite pass with 100% success rate.

### Phase 2: Autonomous Multi-Turn Agentic Test-Driven Repair
- Connect the patch engine to the local test runner (`pytest`, `npm test`, `cargo test`).
- Execute test suite automatically upon generating a patch in a temporary sandbox.
- If tests fail, extract failing assertions and re-prompt `qwen2.5-coder` with execution feedback until all tests pass or iteration threshold is reached.

### Phase 3: Dedicated Real-Time Telemetry & Analytics UI
- Develop standalone analytics charts in `frontend/src/pages/AnalyticsPage.tsx`:
  - Code Churn & Complexity Distribution (Radar & Heatmap charts).
  - Security Risk Index & Technical Debt Score.
  - Bug Localization Accuracy & Mean Time to Patch (MTTP).

### Phase 4: Real-Time File System Daemon & Watcher
- Implement a background service (`watchdog`) in `backend/services/incremental_indexer.py`.
- Instantly detect file modifications in active workspaces and re-embed affected chunks in the background without user intervention.

### Phase 5: Distributed Vector Storage & Enterprise Connectors
- Add support for external vector databases (Qdrant, ChromaDB, Milvus) for repositories containing $>100,000$ files.
- Add GitHub/GitLab webhook integration for automatic Pull Request code reviews and comments.

---

## 5. Step-by-Step Working Guide (End-to-End System Execution)

```
[ Step 1: Ingestion ] ──► [ Step 2: Indexing & Hash ] ──► [ Step 3: Retrieval (RAG) ]
           │
           ▼
[ Step 4: Localization (Ochiai) ] ──► [ Step 5: Patch & Safe Backup ]
```

### Step 1: Repository Ingestion & Parsing
1. User provides a repository path (e.g. `sample_repo` or via the web UI).
2. `parser.py` filters non-code files, binaries, and virtual environments.
3. `chunker.py` analyzes the code structure via AST to extract distinct functions and classes with line number ranges and docstrings.

### Step 2: Vector Store Indexing & Hash Caching
1. Each code chunk is passed to `embedder.py` (`nomic-embed-text` or `TfidfEmbedder`).
2. High-dimensional vectors are stored in FAISS with L2 normalization.
3. Chunks and file SHA-256 hashes are persisted into SQLite (`.storage/metadata.db`).

### Step 3: Context-Grounded Query Answering (RAG)
1. User sends a technical question: *"Where is user authentication handled?"*
2. Query vector is compared against FAISS to retrieve top-$K$ matching chunks.
3. Dependency graph identifies related imports and caller functions.
4. System constructs a grounded prompt with dynamic token budgeting.
5. Ollama (`qwen2.5-coder`, temperature `0.2`) streams back a cited answer with file paths and line ranges.

### Step 4: Error Trace Analysis & Bug Localization
1. User supplies an error message or stack trace.
2. `StackTraceParser` extracts frames across Python/JS/Java/Go/Rust files.
3. `calculate_ochiai_spectrum` computes suspiciousness scores for affected modules.
4. Ranked candidate files and suspect lines are returned with confidence metrics.

### Step 5: Safe Patch Generation & Application
1. Suspect code and surrounding context are sent to `qwen2.5-coder` (temperature `0.1`).
2. The LLM generates the corrected code block and root cause explanation.
3. `patch_validator.py` confirms Python AST syntax validity.
4. `patch_applier.py` generates a unified Git diff (`diff --git a/... b/...`).
5. Upon user approval, a timestamped `.bak` backup is created, and the patch is applied directly to disk.

---

## 6. Models, Parameters & Technical Specifications

| Component | Technology / Model | Default Parameters | Rationale |
| :--- | :--- | :--- | :--- |
| **Code LLM** | `qwen2.5-coder:3b` / `7b` | `temperature=0.2` (chat), `temperature=0.1` (patch), `timeout=300s` | High-precision deterministic code generation, low hallucination |
| **Embeddings** | `nomic-embed-text` | `dim=768`, Cosine similarity | Strong semantic code representation in local environments |
| **Fallback Embedder** | Scikit-Learn TF-IDF + SVD | `dim=64`, Sparse-to-Dense | Zero external dependency fallback for offline CPU-only setups |
| **Vector DB** | FAISS (`IndexFlatIP`) | Inner Product with L2 Normalization | Fast, in-memory local vector search with file persistence |
| **Graph DB** | NetworkX (In-Memory) | Directed Graph, PageRank, Degree Centrality | Efficient architectural and import dependency resolution |
| **Database** | SQLite + MongoDB / Local JSON | File-backed `.storage/metadata.db` | High-speed cache for SHA-256 hashes and code chunks |
| **Web Server** | FastAPI + Uvicorn | Python 3.10+, CORS enabled | High-throughput asynchronous REST API |
| **Frontend UI** | React 18 + Vite + Tailwind CSS | React Router DOM, Axios, Lucide Icons | Responsive, modern dark-themed enterprise dashboard |

---

## 7. Command & API Reference

### Quick Launch Scripts (Windows)

```bat
:: Launch complete environment (Backend + Frontend)
run.bat

:: Launch FastAPI backend only
run_backend.bat

:: Launch React frontend only
run_frontend.bat

:: Launch Interactive CLI
run_cli.bat
```

### CLI Commands

```bash
# Query the codebase with RAG
python cli.py ./sample_repo --query "Explain how error handling is structured"

# Localize a bug from a stack trace
python cli.py ./sample_repo --trace "TypeError: 'NoneType' object is not subscriptable at auth.py:24"

# Generate and preview an automated patch
python cli.py ./sample_repo --fix "Fix KeyError in user session dictionary"

# Inspect architectural dependency graph
python cli.py ./sample_repo --graph

# Run system performance benchmarks
python cli.py ./sample_repo --benchmark
```

### Key REST API Endpoints

- `POST /api/repos/index` — Index a repository path
- `POST /api/chat/ask` — Ask a question with multi-turn memory & personas
- `POST /api/bugs/localize` — Submit a stack trace for Ochiai fault localization
- `POST /api/patches/generate` — Generate unified Git diff patch
- `POST /api/patches/apply` — Safely apply patch to disk with backup
- `GET  /api/graph/{repo_id}` — Fetch dependency graph topology
- `GET  /api/analytics/{repo_id}` — Retrieve complexity and health metrics
- `POST /api/docs/generate` — Generate Markdown/HTML/PDF documentation
- `POST /api/review/analyze` — Run automated code review & smell analysis
