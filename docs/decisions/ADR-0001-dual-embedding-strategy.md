# ADR-0001: Dual Embedding Strategy with Offline Fallback (Ollama + TF-IDF SVD)

* **Status**: Accepted
* **Date**: 2026-09-17
* **Deciders**: IntelliCodeX Core Team
* **Technical Area**: Core Engine / Embeddings / Vector Search

## Context & Problem Statement
IntelliCodeX is designed as a privacy-preserving repository intelligence assistant that can run in diverse environments, ranging from high-performance developer workstations with GPUs and local LLM servers (Ollama) to air-gapped, resource-constrained laptops without GPUs or local model servers. If the system strictly requires a neural embedding server like Ollama with `nomic-embed-text`, users without Ollama cannot use the CLI or search features.

## Decision Drivers
- Support zero-external-dependency offline execution out-of-the-box.
- Provide dense vector semantic representations when local Ollama is active.
- Allow dynamic fallback to standard Python libraries (scikit-learn) without crashing.
- Maintain consistent cosine similarity interface in the vector database regardless of backend.

## Considered Options
1. **Ollama Dense Embeddings Only (`nomic-embed-text`)**: High semantic quality, 768 dimensions, but hard dependency on Ollama running on port 11434.
2. **Local HuggingFace Transformers Model (SentenceTransformers)**: Requires heavy PyTorch download (~2GB+), slow initialization on CPU.
3. **Dual Embedding Engine (`OllamaEmbedder` + `TfidfEmbedder` Fallback)**: Primary dense 768-dim vectors via Ollama; automatic fallback to 64-dim TF-IDF + TruncatedSVD when Ollama is offline.

## Decision Outcome
Chosen Option: **Dual Embedding Engine (`OllamaEmbedder` + `TfidfEmbedder`)**.

### Consequences
* **Positive**:
  - The CLI and backend run instantly in CPU-only offline mode with no external servers.
  - High-precision dense semantic retrieval is enabled seamlessly when Ollama is detected.
  - Consistent vector search API (`BaseEmbedder.embed(texts) -> np.ndarray`) used by FAISS.
* **Negative / Trade-offs**:
  - `TfidfEmbedder` performs lexical/keyword-focused matching rather than deep semantic abstraction.
  - Re-indexing with a different backend creates a different vector dimension (768 vs 64), requiring full or incremental re-embedding upon backend switch.

## Implementation References
- File: [`core/embedder.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/embedder.py)
- Symbols: `BaseEmbedder`, `OllamaEmbedder`, `TfidfEmbedder`
- Verification Test: [`tests/test_cli.py::test_create_components_ollama_fallback`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_cli.py)
