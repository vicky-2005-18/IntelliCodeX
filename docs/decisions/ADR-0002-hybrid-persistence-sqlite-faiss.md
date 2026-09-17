# ADR-0002: Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors)

* **Status**: Accepted
* **Date**: 2026-09-17
* **Deciders**: IntelliCodeX Core Team
* **Technical Area**: Persistence & Storage

## Context & Problem Statement
Re-parsing large software repositories and re-computing embeddings on every CLI execution or server start incurs unacceptable latency (seconds to minutes). We need persistent storage that:
1. Detects added, modified, and deleted files instantaneously using SHA-256 content hashes.
2. Supports instant reloading (< 10ms) when code is unchanged.
3. Supports incremental re-indexing (only re-chunking and re-embedding changed files).
4. Persists structured chunk metadata (file paths, line numbers, docstrings, imports) alongside high-dimensional vector indices.

## Decision Drivers
- Zero-latency startup for previously indexed repositories.
- Zero server maintenance overhead (no mandatory background database servers for basic CLI use).
- Efficient vector similarity search at low memory footprints.

## Considered Options
1. **In-Memory Volatile Store**: Rebuild on every launch; slow and CPU-intensive for large codebases.
2. **Dedicated Cloud/Distributed Vector Store (Pinecone / Milvus / Qdrant)**: Requires network access, API keys, or external daemon management; violates strict offline local privacy requirement.
3. **Hybrid SQLite + FAISS Local Persistence**: Store relational chunk metadata, file modification times, and SHA-256 hashes in SQLite (`.storage/metadata.db`); persist vector index binaries via `faiss.write_index` (`.storage/<repo_id>.faiss`).

## Decision Outcome
Chosen Option: **Hybrid SQLite + FAISS Local Persistence**.

### Consequences
* **Positive**:
  - File-based persistence under `.storage/` with zero configuration.
  - Startup time for pre-indexed repositories drops to near 0ms (`<5ms`).
  - Incremental updates only re-embed delta files while reconstructing retained vectors from FAISS.
* **Negative / Trade-offs**:
  - SQLite concurrency is limited for heavily concurrent multi-threaded writes (mitigated by single-writer patterns).
  - FAISS index reconstruction requires standard flat indexing structures (`IndexFlatIP`).

## Implementation References
- File: [`core/persistence.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/persistence.py)
- File: [`core/vectorstore.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/vectorstore.py)
- Symbols: `get_db_connection`, `save_index`, `load_index`, `detect_repository_changes`, `FaissVectorStore.save`, `FaissVectorStore.load`
- Verification Tests: [`tests/test_faiss_sqlite_persistence.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_faiss_sqlite_persistence.py), [`tests/test_incremental_pipeline.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_incremental_pipeline.py)
