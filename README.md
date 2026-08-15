# IntelliCodeX — Working MVP

A locally-hosted, privacy-preserving RAG framework for repository understanding,
bug localization, and patch generation. This is a real, running implementation
of the architecture described in the IntelliCodeX paper (Section V), built to
be extended module-by-module.

## What's implemented right now

| Paper module | File | Status |
|---|---|---|
| Repository Parser | `core/parser.py` | ✅ working |
| Semantic Chunking Engine | `core/chunker.py` | ✅ working (Python AST; other languages fall back to whole-file — see "Next steps") |
| Embedding Generation | `core/embedder.py` | ✅ working — `OllamaEmbedder` (real) + `TfidfEmbedder` (offline fallback) |
| Vector Database Layer | `core/vectorstore.py` | ✅ working (FAISS) |
| Dependency Analysis Engine | `core/dependency_graph.py` | ✅ working (Python imports → `networkx` graph) |
| Local AI Server | `server/api.py` | ✅ working (FastAPI, multi-repo) |
| Bug Localization Engine | `rag/query_engine.py::localize_bug` | ✅ working (RAG over stack trace as query) |
| Patch Generation Engine | — | ⏳ not yet built — see Next Steps |

This has been tested end-to-end against a sample repo (`sample_repo/`), both
via the CLI and the FastAPI server, in both offline (TF-IDF) and — once you
have Ollama running — real embedding mode.

## Setup

```bash
pip install -r requirements.txt
```

### Option A — offline / no LLM (fastest way to see it work)
```bash
python cli.py sample_repo --backend tfidf
```
This uses a local TF-IDF+SVD embedder (scikit-learn) — no internet, no GPU,
no server needed. Good for development and demoing the retrieval + dependency
graph without waiting on model downloads.

### Option B — real local LLM (matches the paper's architecture)
```bash
# 1. Install Ollama: https://ollama.com
# For 4GB VRAM GPUs (e.g. RTX 3050):
ollama pull qwen2.5-coder:3b
ollama pull nomic-embed-text
ollama cp qwen2.5-coder:3b qwen2.5-coder

# For 8GB+ VRAM GPUs:
# ollama pull qwen2.5-coder

ollama serve

# 2. Run IntelliCodeX against it
python cli.py sample_repo --backend ollama
```

### Windows One-Click Launcher
You can also use the included Windows batch files to launch interactive sessions:
- **`run_cli.bat`**: Directly launches the interactive Ollama CLI.
- **`run.bat`**: Launcher menu for Full Application, Backend API, Frontend UI, or Interactive CLI.

### Running Unit Tests
To run the automated test suite:
```bash
pytest
```

### Run as a server (multi-user, matches "Distributed AI Infrastructure")
```bash
uvicorn server.api:app --reload --port 8000
```
Then:
```bash
curl -X POST localhost:8000/ingest -H "Content-Type: application/json" \
  -d '{"repo_id": "myrepo", "repo_path": "sample_repo", "backend": "tfidf"}'

curl -X POST localhost:8000/query -H "Content-Type: application/json" \
  -d '{"repo_id": "myrepo", "question": "how does authentication work?"}'
```

## Try it on your own repo
```bash
python cli.py /path/to/any/python/repo --backend tfidf
```

## Architecture (as built)

```
Repository -> parser.py (walk + detect language)
           -> chunker.py (AST -> function/class/method CodeChunks)
           -> embedder.py (TF-IDF or Ollama nomic-embed-text)
           -> vectorstore.py (FAISS index)
           -> dependency_graph.py (networkx import graph, in parallel)

Query -> query_engine.py: embed question -> FAISS search -> assemble context
       -> llm_client.py (Ollama qwen2.5-coder) -> grounded, cited answer
```

## Next steps (to go from MVP to the full paper scope)

1. **Multi-language chunking** — swap the fallback in `chunker.py` for real
   `tree-sitter` grammars (Python, JS/TS, Java, Go, C/C++) so non-Python repos
   get proper function/class-level chunks instead of whole-file blocks.
2. **Patch Generation Engine** — new module: take `localize_bug()` output,
   prompt the LLM for a unified diff, validate it applies cleanly (`git apply
   --check`), and hand it to the developer for review.
3. **Call-graph dependency analysis** — extend `dependency_graph.py` beyond
   imports to actual function-call edges (who calls this function?).
4. **Persistence** — FAISS index + chunk metadata currently live in memory;
   add `faiss.write_index` / SQLite so a server restart doesn't re-embed
   everything.
5. **Incremental re-indexing** — watch the repo (or hook into git commits) and
   only re-chunk/re-embed changed files instead of full re-ingestion.
6. **Auth + multi-tenancy** on the FastAPI server if this will actually be
   shared across a team.

## Project structure
```
intellicodex/
├── core/
│   ├── parser.py          # repo walking, language detection
│   ├── chunker.py         # AST-based semantic chunking
│   ├── dependency_graph.py
│   ├── embedder.py        # Ollama + TF-IDF backends
│   ├── vectorstore.py     # FAISS wrapper
│   ├── llm_client.py      # Ollama generation client
│   └── pipeline.py        # ties ingestion together
├── rag/
│   └── query_engine.py    # RAG query + bug localization
├── server/
│   └── api.py             # FastAPI multi-user server
├── sample_repo/           # tiny repo for testing (has a deliberate bug)
├── cli.py                 # interactive CLI
└── requirements.txt
```
