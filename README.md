# IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine

[![Tests: 91 Passed](https://img.shields.io/badge/Tests-91%20Passed-brightgreen)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/TESTING.md)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![FastAPI: Enterprise Backend](https://img.shields.io/badge/Backend-FastAPI-009688)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/backend/main.py)
[![Frontend: React 18 + Vite](https://img.shields.io/badge/Frontend-React%2018%20%7C%20Vite-61DAFB)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/frontend/)
[![Architecture: Local & Privacy-Preserving](https://img.shields.io/badge/Privacy-100%25%20Local-purple)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/ARCHITECTURE.md)

> **A locally-hosted, privacy-preserving Retrieval-Augmented Generation (RAG) framework for multi-language codebase navigation, dependency call-graph analysis, spectrum-based bug localization, and automated code patch generation.**

---

## 1. Project Purpose & Target Users

IntelliCodeX is built for software engineers, security auditors, and system architects who need deep semantic understanding and automated repair capabilities across large codebases without transmitting source code to third-party cloud servers.

### Target Users:
* **Developers & Maintainers**: Rapidly understand unknown repositories, trace caller-callee hierarchies, and synthesize verified bug fix patches.
* **Security Auditors & Code Reviewers**: Inspect dependency choke points, scan for vulnerabilities using dedicated security personas, and analyze reverse blast radius before refactoring.
* **Privacy-Sensitive Organizations**: Navigate and analyze proprietary code completely offline with zero telemetry or data exfiltration.

---

## 2. Current Capabilities & Important Limitations

### Implemented Capabilities (Tested & Verified)
* **Multi-Language AST Semantic Chunking**: Concrete syntax tree extraction via Tree-Sitter for Python, JavaScript, TypeScript, TSX, Java, C, C++, Go, and Rust.
* **Dual Embedding Architecture**: Dense vector representation using local Ollama (`nomic-embed-text`, 768-dim) with automatic fallback to Scikit-Learn TF-IDF + TruncatedSVD (64-dim) for CPU-only offline operation.
* **Dependency & Call-Graph Engine**: Directed NetworkX graphs computing PageRank centrality, import relationships, and caller-callee call graphs.
* **Graph-Augmented RAG Querying**: Context retrieval expanded with upstream callers, downstream callees, and imported modules; dynamic token budgeting and multi-turn conversation memory.
* **Spectrum-Based Fault Localization (SBFL)**: Ochiai suspiciousness ranking combined with multi-language stack trace parsing (Python, JS, Java, Go, Rust).
* **Safe Patch Generation & Application**: Deterministic low-temperature code synthesis, unified Git diff generation, AST syntax validation, and atomic file overwrites with timestamped `.bak` backups.
* **Zero-Latency SQLite Cache**: SHA-256 content hashing enabling $<5\text{ms}$ index reloading for unmodified repositories.

### Important Limitations
* **Single-Shot Patching**: Patch generation currently produces single-shot diffs with syntax and dry-run checks; autonomous multi-turn test iteration (running tests in a sandbox and re-prompting on failure) is scheduled for Milestone 2.
* **Analytics UI Delegation**: The web frontend's `AnalyticsPage.tsx` currently delegates rendering to the main `DashboardPage` rather than presenting dedicated custom telemetry widgets.
* **Manual / Hook Sync**: Real-time incremental synchronization is triggered via Git commit hooks, CLI startup, or API endpoints; continuous filesystem background monitoring (`watchdog`) is in active development.

---

## 3. Prerequisites & Environment Configuration

### Prerequisites
* **Operating System**: Windows 10/11, Linux, or macOS.
* **Python**: Version `3.10` or higher (Tested on Python 3.12 and 3.14).
* **Node.js**: Version `18+` (for React web dashboard).
* **Git**: Installed and available on system `PATH`.
* **Ollama (Optional, for full AI features)**: [Download Ollama](https://ollama.com).

### Configuration Variables (`backend/config.py`)
All parameters can be configured via environment variables (no secret values hardcoded):

| Environment Variable | Default Value | Purpose |
| :--- | :--- | :--- |
| `JWT_SECRET` | `intellicodex-enterprise-secret-key-2026` | Secret key for signing local auth tokens |
| `STORAGE_DIR` | `.storage` | Local directory for SQLite metadata and FAISS indices |
| `REPOS_DIR` | `.repos` | Local directory for cloned remote repositories |
| `OLLAMA_HOST` | `http://localhost:11434` | Endpoint for local Ollama server |
| `OLLAMA_LLM_MODEL` | `qwen2.5-coder` | Active local code model |
| `OLLAMA_EMBED_MODEL`| `nomic-embed-text` | Active dense embedding model |
| `DEFAULT_EMBEDDER_BACKEND` | `ollama` | Default backend (`ollama` or `tfidf`) |
| `MONGO_URI` | `mongodb://localhost:27017` | Optional MongoDB URI (falls back to `.storage/db.json`) |

---

## 4. Installation & Startup Instructions

### 4.1 Clone Repository & Setup Virtual Environment `[TESTED]`

```bash
# Clone repository
git clone https://github.com/vicky-2005-18/intellicodex.git
cd intellicodex

# Create and activate Python virtual environment
python -m venv .venv
.\.venv\Scripts\activate       # Windows (PowerShell/CMD)
# source .venv/bin/activate     # Linux / macOS

# Install dependencies
pip install -r requirements.txt
```

### 4.2 Run IntelliCodeX Interactive CLI `[TESTED]`

```bash
# Option A: Offline Mode (Fastest, zero external dependencies)
python cli.py sample_repo --backend tfidf

# Option B: Full AI Mode (Requires local Ollama running)
# Ensure models are pulled: ollama pull qwen2.5-coder && ollama pull nomic-embed-text
python cli.py sample_repo --backend ollama
```

### 4.3 Start Web Application (Backend + Frontend) `[TESTED]`

* **One-Click Windows Launcher**: Run [`run.bat`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/run.bat) and choose `Option 1` (Start Full Application).

* **Manual Startup**:
```bash
# Terminal 1 — FastAPI Backend Server (Port 8000)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — React Web App (Port 5173)
cd frontend
npm install
npm run dev
```

* **Access Points**:
  - Web UI: `http://localhost:5173`
  - REST API Swagger Docs: `http://localhost:8000/docs`

---

## 5. Minimal Usage Example (CLI)

```bash
# 1. Launch interactive CLI on sample repository
python cli.py sample_repo --backend tfidf

# 2. Ask a question about the architecture:
>> How does user authentication work?

# 3. Localize a bug and generate an automated patch:
>> fix:KeyError in auth.py

# 4. View module dependencies:
>> deps:sample_repo/auth.py

# 5. Check top central files:
>> top
```

---

## 6. Comprehensive Documentation Index

* 📋 [System Requirements Specification (docs/REQUIREMENTS.md)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/REQUIREMENTS.md) — Problem statement, functional requirements (REQ-F-01..12), non-functional metrics, and acceptance criteria.
* 🏛️ [System Architecture & Design (docs/ARCHITECTURE.md)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/ARCHITECTURE.md) — Component decomposition, technology stack, sequence diagrams, and security boundaries.
* 📊 [Project Implementation Status (docs/PROJECT_STATUS.md)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/PROJECT_STATUS.md) — Evidence-based status matrix grounded in passing test suites and Git commit state.
* 🗺️ [Engineering Roadmap (docs/ROADMAP.md)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/ROADMAP.md) — Prioritized milestones, concrete next tasks, and effort estimates.
* 🧪 [Testing & Verification Guide (docs/TESTING.md)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/TESTING.md) — Test suite layout, execution commands, and empirical test results (91/91 passed).
* 📝 [Architecture Decision Records (docs/decisions/README.md)](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/decisions/README.md) — Formal ADR log, guidelines, and rationale records.

---

## 7. Documentation Maintenance Checklist

When modifying the repository, consult this checklist during code reviews to prevent documentation drift:

- [ ] **Feature Added or Modified**: Update [`docs/REQUIREMENTS.md`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/REQUIREMENTS.md) with new requirement ID and update [`docs/PROJECT_STATUS.md`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/PROJECT_STATUS.md) status.
- [ ] **API Route or Database Schema Changed**: Update [`docs/ARCHITECTURE.md`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/ARCHITECTURE.md) (router table & database schema section).
- [ ] **Setup or Dependency Changed**: Update `requirements.txt`, `README.md` (prerequisites & quick start), and [`docs/TESTING.md`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/TESTING.md).
- [ ] **Automated Test Added or Result Changed**: Update test count and results table in [`docs/TESTING.md`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/TESTING.md).
- [ ] **Architectural or Dependency Decision Made**: Create a new ADR record under [`docs/decisions/`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/decisions/) and link it in `docs/decisions/README.md`.
- [ ] **Milestone Completed or Scope Changed**: Update [`docs/ROADMAP.md`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/docs/ROADMAP.md) task statuses and milestones.
