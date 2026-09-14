# IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine

A locally-hosted, privacy-preserving RAG framework for multi-language repository understanding,
dependency call-graph analysis, spectrum-based bug localization, and automated code patch generation.

IntelliCodeX implements the full architecture described in the IntelliCodeX research paper, running completely locally on your machine with zero external data transmission.

---

## 🚀 Key Features & Implemented Architecture

| Paper Module | Core Implementation File | Status | Feature Highlights |
|---|---|---|---|
| **Multi-Language Parser** | `core/parser.py`, `core/ts_loader.py` | ✅ Complete | Python, JS, TS, TSX, Java, Go, C, C++, Rust |
| **AST & Windowed Chunker** | `core/chunker.py`, `core/tree_sitter_chunker.py` | ✅ Complete | Fine-grained Tree-Sitter AST + Markdown sectioning |
| **Embedding Generation** | `core/embedder.py` | ✅ Complete | `OllamaEmbedder` (Nomic-Embed-Text) & `TfidfEmbedder` (Offline) |
| **Vector Database Layer** | `core/vectorstore.py` | ✅ Complete | FAISS binary vector index serialization |
| **Dependency & Call Graphs** | `core/dependency_graph.py`, `core/call_graph.py` | ✅ Complete | PageRank file/symbol centrality & call-graph analysis |
| **RAG Query Engine** | `rag/query_engine.py` | ✅ Complete | Graph sub-graph expansion, token budgeting & streaming |
| **Conversation Memory** | `rag/query_engine.py::ConversationMemory` | ✅ Complete | Multi-turn dialogue history tracking & chat memory |
| **System Personas** | `rag/query_engine.py::PERSONAS` | ✅ Complete | General, Security Auditor, Code Reviewer, Refactor, Fixer |
| **Persistence & Caching** | `core/persistence.py` | ✅ Complete | SQLite metadata DB (`metadata.db`) & FAISS index persistence |
| **Fast Change Detection** | `core/persistence.py::detect_repository_changes` | ✅ Complete | SHA-256 content hashing & zero-latency startup (< 5ms) |
| **Incremental Re-Indexing** | `core/pipeline.py` | ✅ Complete | Selective re-chunking/embedding of changed files only |
| **Git Hook Generator** | `core/git_hooks.py` | ✅ Complete | Automated `post-commit` & `post-merge` background hooks |
| **Ochiai Bug Localizer** | `core/bug_localizer.py` | ✅ Complete | Spectrum-based fault localization & stack trace parsing |
| **Patch Generator Engine** | `core/patch_generator.py` | ✅ Complete | Context-aware code fix, unified git diff, physical applier |
| **Interactive CLI & Batch** | `cli.py` | ✅ Complete | Interactive prompt, batch query (`-q`), benchmarking (`--benchmark`) |

---

## 🛠️ Quick Start & Setup

### Prerequisites
- Python 3.10+ (Recommended: Python 3.12 or 3.14)
- Git

### Installation
```bash
git clone https://github.com/vicky-2005-18/intellicodex.git
cd intellicodex
pip install -r requirements.txt
```

---

## 🖥️ Running IntelliCodeX CLI

### Option 1 — Offline Mode (Fastest, zero-dependency)
```bash
python cli.py sample_repo --backend tfidf
```
Runs locally with TF-IDF+SVD vector embeddings. Instant execution, no GPU or LLM server required.

### Option 2 — Full AI Server Mode (Ollama LLM + AI Embeddings)
```bash
# 1. Install & start Ollama: https://ollama.com
ollama pull qwen2.5-coder
ollama pull nomic-embed-text
ollama serve

# 2. Run IntelliCodeX with Ollama backend
python cli.py sample_repo --backend ollama
```

### Option 3 — Non-Interactive Batch Mode (CI/CD & Scripting)
```bash
python cli.py sample_repo -q "How does user authentication work?" --backend tfidf
```

### Option 4 — Performance Benchmarking
```bash
python cli.py sample_repo --benchmark
```

### Windows Launcher Menu
Run `run.bat` or `run_cli.bat` for one-click launching on Windows.

---

## 💡 Available CLI Commands

| CLI Command | Description | Example |
|---|---|---|
| `fix:<error_or_log>` | Diagnose error log & generate automated code fix patch | `fix:KeyError in auth.py` |
| `deps:<filepath>` | Show direct & reverse file dependencies | `deps:pkg/db.py` |
| `callers:<func>` | Find caller functions of a specific symbol | `callers:connect_db` |
| `top` / `centrality` | Display top central files & functions (PageRank scores) | `top` |
| `persona <name>` | Swap AI role (`general`, `security`, `reviewer`, `refactor`, `fixer`) | `persona security` |
| `model <name>` | Switch active Ollama LLM model | `model qwen2.5-coder:7b` |
| `history` / `clear-chat` | Inspect or clear multi-turn conversation memory | `history` |
| `hooks` / `setup-hooks` | Install Git post-commit background re-indexing hooks | `hooks` |
| `repo <path_or_url>` | Switch or clone repository URL | `repo https://github.com/user/repo` |
| `files` / `ls` | List all indexed source files | `ls` |

---

## 🧪 Running Automated Tests

Run the complete test suite (90 test cases):
```bash
pytest
```

---

## 📄 License & Architecture Reference
Built as part of the IntelliCodeX semester research project.
Full technical documentation is available in `intellicodex_system_documentation.md`.
