# IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine

[![Tests: 246 Passed](https://img.shields.io/badge/Tests-246%20Passed-brightgreen)](docs/TESTING.md)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![CLI: Interactive Terminal Assistant](https://img.shields.io/badge/Interface-CLI%20First-orange)](cli.py)
[![Backend: FastAPI Bridge](https://img.shields.io/badge/Backend-FastAPI-009688)](backend/main.py)
[![Architecture: Local & Privacy-Preserving](https://img.shields.io/badge/Privacy-100%25%20Local-purple)](docs/ARCHITECTURE.md)

> **A locally-hosted, privacy-preserving Retrieval-Augmented Generation (RAG) framework for multi-language codebase navigation, dependency call-graph analysis, spectrum-based bug localization, and automated code patch generation.**
> 
> *Current Semester Focus: **CLI Core & Local Intelligence Engine**. Full Web Application UI is preserved in roadmap for future development phases.*

---

## 1. Project Purpose & Target Users

IntelliCodeX is built for software engineers, security auditors, and system architects who need deep semantic understanding and automated repair capabilities across large codebases without transmitting source code to third-party cloud servers.

### Target Users:
* **Developers & Maintainers**: Rapidly understand unknown repositories, trace caller-callee hierarchies, and synthesize verified bug fix patches via the interactive terminal CLI.
* **Security Auditors & Code Reviewers**: Inspect dependency choke points, scan for vulnerabilities using dedicated security personas, and analyze reverse blast radius before refactoring.
* **Privacy-Sensitive Organizations**: Navigate and analyze proprietary code completely offline with no telemetry or data exfiltration.

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
* **Interactive CLI Tooling**: Standalone terminal interface with command loops (`fix:`, `deps:`, `callers:`, `top`, `persona`, `model`, `repo`, `hooks`).

### Important Limitations
* **Multi-Turn Patching**: Patch generation supports multi-turn refinement with sandbox test runs (up to 3 iterations) when a repository path is provided. Tests are run after each iteration; if tests pass or are skipped, refinement stops. If no repository path is provided, patch generation is single-shot without test validation.
* **Web UI Scope**: The React web UI has been detached to prioritize the CLI and core engine this semester; Web UI workspace features are scheduled for the Semester 2 roadmap.
* **Manual / Hook Sync**: Real-time incremental synchronization is triggered via Git commit hooks, CLI startup, or API endpoints; continuous filesystem background monitoring (`watchdog`) is in active development.

---

## 3. Prerequisites & Environment Configuration

### Prerequisites
* **Operating System**: Windows 10/11, Linux, or macOS.
* **Python**: Version `3.10` or higher (Tested on Python 3.12 and 3.14).
* **Git**: Installed and available on system `PATH`.
* **Ollama (Optional, for full AI features)**: [Download Ollama](https://ollama.com).

### Configuration Variables (`backend/config.py`)
All parameters can be configured via environment variables (no secret values hardcoded):

| Environment Variable | Default Value | Purpose |
| :--- | :--- | :--- |
| `JWT_SECRET` | *(Required in prod; auto-generated to `.storage/jwt_secret.key`)* | Secret key for signing auth tokens (HS256) |
| `STORAGE_DIR` | `.storage` | Local directory for SQLite metadata and FAISS indices |
| `REPOS_DIR` | `.repos` | Local directory for cloned remote repositories |
| `OLLAMA_HOST` | `http://localhost:11434` | Endpoint for local Ollama server |
| `OLLAMA_LLM_MODEL` | `qwen2.5-coder` | Active local code model |
| `OLLAMA_EMBED_MODEL`| `nomic-embed-text` | Active dense embedding model |
| `DEFAULT_EMBEDDER_BACKEND` | `ollama` | Default backend (`ollama` or `tfidf`) |
| `MONGO_URI` | `mongodb://localhost:27017` | Optional MongoDB URI (falls back to `.storage/db.json`) |
| `API_HOST` | `127.0.0.1` | Host address for uvicorn bind (Docker uses `0.0.0.0`) |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Comma-separated allowed CORS origins (security: never use `*` with credentials) |
| `TRUSTED_PROXIES` | `""` | Comma-separated list of trusted proxy IPs for reverse proxy deployments |
| `SANDBOX_MODE` | `local` | Sandbox mode for test execution: `local` (default) or `docker` |
| `SANDBOX_DOCKER_IMAGE` | `python:3.11-slim` | Docker image for sandbox mode (when `SANDBOX_MODE=docker`) |
| `ALLOW_LOCAL_SANDBOX` | `false` | Allow local sandbox in API mode (security: requires explicit opt-in) |

### Repository Storage (`.repos/`)
The `.repos/` directory contains cloned sample repositories (e.g., Django, FastAPI, transformers) used for testing and benchmarking. These repositories are:

- **Downloaded on demand** when running ingestion commands
- **Not part of the submission** (excluded via `.gitignore`)
- **Safe to delete** - they will be re-downloaded automatically when needed

If you encounter issues with sample repos, simply delete the `.repos/` directory and re-run the ingestion command.

---

### Sandbox Security Model

IntelliCodeX includes a sandbox runner for executing repository test suites when applying patches. **This is a security-critical component.**

**Local Mode (default)**:
- Tests run as your user with filesystem and network access
- Environment variables are filtered (only PATH, SYSTEMROOT, TEMP, TMP, COMSPEC, PATHEXT, LANG, LC_ALL, HOME, USERPROFILE, PYTHONPATH, PYTHONDONTWRITEBYTECODE are passed)
- Variables matching *KEY*, *TOKEN*, *SECRET*, *PASSWORD*, *CREDENTIAL* are blocked even if on the allowlist
- Shell execution is disabled; only allowlisted executables (python, pytest, npm, npx, node, go, cargo, mvn, gradle) are permitted
- Shell metacharacters (&&, ||, ;, |, >, <, `, $()) are rejected
- Process tree is killed on timeout (children first, then parent)
- Output is truncated at 1 MB to prevent resource exhaustion
- **NOT true isolation** - use only on repositories you trust
- **API security**: Local sandbox is refused unless `ALLOW_LOCAL_SANDBOX=true` (default false)
- **Command security**: User-supplied `test_command` is accepted only from admin users

**Docker Mode** (recommended for untrusted code):
- Tests run in a container with `--network none`, memory/CPU limits, read-only rootfs, PID limits, dropped capabilities (--cap-drop ALL), no new privileges (--security-opt no-new-privileges), and non-root user (1000:1000)
- Provides strong isolation for untrusted code
- Requires Docker to be installed
- Falls back to local mode with a logged warning if Docker is unavailable
- **Note**: The default `python:3.11-slim` image does not include pytest or repository dependencies. To use Docker mode effectively, build a custom image with required dependencies:

**Test Result Reporting**:
- Skipped sandbox results are reported as "not verified" (never as "validated" or "tests passed")
- CLI displays "NOT VERIFIED: NO TESTS RAN" when tests are skipped
- API payload returns `verified: false` when tests are skipped
  ```bash
  docker build -f Dockerfile.sandbox -t icx-sandbox .
  export SANDBOX_DOCKER_IMAGE=icx-sandbox
  ```
  The provided `Dockerfile.sandbox` installs pytest and git. Project-specific dependencies (numpy, scikit-learn, tree-sitter parsers, etc.) must be added by the user based on the repository being tested.


**Docker Status**: Implemented, unverified
- Docker mode infrastructure is complete with security hardening options
- Test runs with the default `python:3.11-slim` image skip tests (no pytest installed)
- Full end-to-end Docker testing requires building a custom image with project-specific dependencies
- Mock tests verify Docker detection and fallback behavior, but actual container test execution is not verified


**WARNING**: Local mode provides NO protection against:
- Reading environment variables (except those explicitly blocked)
- Network access to exfiltrate data
- Filesystem access outside the sandbox
- CPU/memory exhaustion attacks
- Side-channel attacks

For untrusted repositories, ALWAYS use Docker mode by setting `SANDBOX_MODE=docker`.

---

## Security

IntelliCodeX includes multiple security layers to protect against common vulnerabilities:

### Authentication & Authorization
- **Password Hashing**: Argon2 (bcrypt-compatible) with secure defaults
- **JWT Tokens**: HS256 algorithm with configurable `JWT_SECRET` (auto-generated to `.storage/jwt_secret.key` if not set)
- **Owner Scoping**: Users can only access their own repositories and resources
- **Rate Limiting**: Login rate limiting keyed by (username, client IP) with `TRUSTED_PROXIES` support for reverse proxy deployments
- **Migration Note**: Existing users from before the Argon2 hashing change must re-register

### Path Traversal Protection
- **Safe Path Resolution**: All user-supplied paths go through `resolve_within()` before filesystem access
- **Symlink Resolution**: Resolved paths must stay inside trusted roots after symlink following
- **UNC/Drive-Relative Path Blocking**: Rejects Windows UNC paths and drive-relative paths (`C:escape.txt`)
- **Alternate Data Stream Blocking**: Rejects Windows NTFS alternate data streams (`file.txt:stream`)
- **Git Diff Path Validation**: Scans git diffs for path traversal attempts in file headers

### CORS & API Binding
- **Explicit CORS Origins**: Only origins listed in `CORS_ORIGINS` are allowed (never `*` with credentials)
- **Method/Header Allowlisting**: Only specified HTTP methods and headers are permitted
- **Localhost Binding**: API server binds to `127.0.0.1` by default (not `0.0.0.0`)
- **Wildcard Rejection**: Rejects wildcard origins when credentials mode is enabled

### Sandbox Security Model
See the detailed Sandbox Security Model section above for local vs Docker mode security boundaries.

---

## Known Limitations

### Authentication
- **In-Memory Rate Limiting**: Rate limiter stores state in memory; resets on server restart
- **No Token Revocation**: JWT tokens cannot be revoked before expiration (use short expirations)

### Sandbox
- **Local Mode Not Isolated**: Local sandbox provides NO protection against network access, filesystem access, or CPU/memory exhaustion
- **Docker Mode Unverified**: Docker infrastructure is implemented but actual container test execution is not verified (requires custom image with pytest and project dependencies)
- **No HTTPS**: FastAPI server does not provide HTTPS; use a reverse proxy (nginx, Caddy) for production TLS

### Platform & Performance
- **Single-Process Only**: API server runs as a single process; use gunicorn/uwsgi for production multi-worker deployments
- **Symlink Tests**: 4 symlink-related tests only run on Linux or with elevated Windows privileges

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

# (Optional) Install development dependencies for testing
pip install -r requirements-dev.txt
```

### 4.2 Run IntelliCodeX Interactive CLI `[TESTED]`

* **Using Windows Launcher**: Run [`run_cli.bat`](run_cli.bat) or [`run.bat`](run.bat) (Option 1).

* **Direct Terminal Command**:
```bash
# Option A: Offline Mode (Fastest, zero external dependencies)
python cli.py sample_repo --backend tfidf

# Option B: Full AI Mode (Requires local Ollama running)
# Ensure models are pulled: ollama pull qwen2.5-coder && ollama pull nomic-embed-text
python cli.py sample_repo --backend ollama
```

### 4.3 Start Local Backend API Server (Optional) `[TESTED]`

```bash
# Launch FastAPI backend server (Port 8000)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
# Or run: run.bat (Option 3)
```
* **API Documentation**: Access Swagger UI at `http://localhost:8000/docs`.

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

* 📋 [System Requirements Specification (docs/REQUIREMENTS.md)](docs/REQUIREMENTS.md) — Problem statement, functional requirements (REQ-F-01..12), non-functional metrics, and acceptance criteria.
* 🏛️ [System Architecture & Design (docs/ARCHITECTURE.md)](docs/ARCHITECTURE.md) — Component decomposition, technology stack, sequence diagrams, and security boundaries.
* 📊 [Project Implementation Status (docs/PROJECT_STATUS.md)](docs/PROJECT_STATUS.md) — Evidence-based status matrix grounded in passing test suites and Git commit state.
* 🗺️ [Engineering Roadmap (docs/ROADMAP.md)](docs/ROADMAP.md) — Prioritized milestones, concrete next tasks, and effort estimates.
* 🧪 [Testing & Verification Guide (docs/TESTING.md)](docs/TESTING.md) — Test suite layout, execution commands, and empirical test results (238/242 passed).
* 📝 [Architecture Decision Records (docs/decisions/README.md)](docs/decisions/README.md) — Formal ADR log, guidelines, and rationale records.

---

## 7. Documentation Maintenance Checklist

When modifying the repository, consult this checklist during code reviews to prevent documentation drift:

- [ ] **Feature Added or Modified**: Update [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) with new requirement ID and update [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) status.
- [ ] **API Route or Database Schema Changed**: Update [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (router table & database schema section).
- [ ] **Setup or Dependency Changed**: Update `requirements.txt`, `README.md` (prerequisites & quick start), and [`docs/TESTING.md`](docs/TESTING.md).
- [ ] **Automated Test Added or Result Changed**: Update test count and results table in [`docs/TESTING.md`](docs/TESTING.md).
- [ ] **Architectural or Dependency Decision Made**: Create a new ADR record under [`docs/decisions/`](docs/decisions) and link it in `docs/decisions/README.md`.
- [ ] **Milestone Completed or Scope Changed**: Update [`docs/ROADMAP.md`](docs/ROADMAP.md) task statuses and milestones.
