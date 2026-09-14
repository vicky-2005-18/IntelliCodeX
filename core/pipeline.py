import os
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any
import numpy as np
from core.parser import walk_repository, SourceFile
from core.chunker import chunk_repository, CodeChunk
from core.dependency_graph import build_dependency_graph
from core.call_graph import build_call_graph
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.persistence import (
    get_repo_id,
    save_index,
    load_index,
    detect_repository_changes,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestedRepository:
    store: FaissVectorStore
    graph: Any
    num_files: int
    num_chunks: int
    languages_found: Dict[str, int] = field(default_factory=dict)
    ast_chunks_count: int = 0
    files: List[SourceFile] = field(default_factory=list)
    call_graph: Any = None


def ingest_repository(
    repo_path: str,
    embedder: BaseEmbedder,
    force_reindex: bool = False,
    save_to_disk: bool = True
) -> IngestedRepository:
    """
    Ingests a repository directory with incremental re-indexing & disk caching support:
    1. Detects file changes via SHA-256 hashes in SQLite.
    2. If unchanged and cached index exists -> Loads instantly from disk (near 0ms latency).
    3. If partially changed -> Re-chunks & re-embeds changed/added files only, reusing retained FAISS vectors.
    4. If fresh index or force_reindex -> Performs full end-to-end ingestion.
    """
    if not os.path.exists(repo_path):
        raise FileNotFoundError(f"Repository path does not exist: '{repo_path}'")

    source_files = walk_repository(repo_path)
    if not source_files:
        raise ValueError(f"No indexable source files found in '{repo_path}'")

    languages_found: Dict[str, int] = {}
    for sf in source_files:
        languages_found[sf.language] = languages_found.get(sf.language, 0) + 1

    repo_id = get_repo_id(repo_path)
    backend_name = "ollama" if embedder.__class__.__name__ == "OllamaEmbedder" else "tfidf"

    if not force_reindex:
        delta = detect_repository_changes(repo_path, source_files)
        if not delta.is_fresh_index:
            cached_data = load_index(repo_path)
            if cached_data is not None:
                meta, cached_chunks, cached_store = cached_data

                # Case A: 100% unchanged -> zero computation reload
                if not delta.has_changes():
                    logger.info(f"[*] Loaded 100% cached index for '{repo_path}' ({len(cached_chunks)} chunks).")
                    if hasattr(embedder, "fit") and callable(getattr(embedder, "fit")) and not getattr(embedder, "_fitted", True):
                        embedder.fit([c.as_embedding_text() for c in cached_chunks])

                    graph = build_dependency_graph(source_files)
                    call_g = build_call_graph(cached_chunks, source_files)
                    ast_count = sum(1 for c in cached_chunks if c.kind in ("function", "class", "method", "interface", "enum", "type", "struct", "section"))


                    return IngestedRepository(
                        store=cached_store,
                        graph=graph,
                        num_files=len(source_files),
                        num_chunks=len(cached_chunks),
                        languages_found=languages_found,
                        ast_chunks_count=ast_count,
                        files=source_files,
                        call_graph=call_g,
                    )

                # Case B: Partial changes -> incremental re-indexing
                logger.info(f"[*] Incremental update for '{repo_path}': +{len(delta.added)} added, ~{len(delta.modified)} modified, -{len(delta.deleted)} deleted")
                stale_files = set(delta.deleted + [sf.rel_path for sf in delta.modified])

                # Extract retained chunks and reconstruct their vectors from FAISS
                retained_chunks = []
                retained_vec_list = []
                for idx, c in enumerate(cached_chunks):
                    if c.file_path not in stale_files and idx < cached_store.index.ntotal:
                        retained_chunks.append(c)
                        vec = cached_store.index.reconstruct(idx)
                        retained_vec_list.append(vec)

                # Chunk changed/added files
                changed_files = delta.added + delta.modified
                new_chunks = chunk_repository(changed_files) if changed_files else []

                if new_chunks:
                    if hasattr(embedder, "dim") and getattr(embedder, "dim", None) != cached_store.dim:
                        embedder.dim = cached_store.dim
                        if hasattr(embedder, "_svd"):
                            from sklearn.decomposition import TruncatedSVD
                            embedder._svd = TruncatedSVD(n_components=cached_store.dim)
                            embedder._fitted = False

                    if hasattr(embedder, "fit") and callable(getattr(embedder, "fit")) and not getattr(embedder, "_fitted", True):
                        embedder.fit([c.as_embedding_text() for c in cached_chunks + new_chunks])

                    new_texts = [c.as_embedding_text() for c in new_chunks]
                    new_vectors = embedder.embed(new_texts)
                else:
                    new_vectors = np.zeros((0, cached_store.dim), dtype="float32")


                # Combine retained + new
                all_chunks = retained_chunks + new_chunks
                if retained_vec_list and len(new_vectors) > 0:
                    retained_matrix = np.array(retained_vec_list, dtype="float32")
                    all_vectors = np.vstack([retained_matrix, new_vectors])
                elif retained_vec_list:
                    all_vectors = np.array(retained_vec_list, dtype="float32")
                elif len(new_vectors) > 0:
                    all_vectors = new_vectors
                else:
                    all_vectors = np.zeros((0, embedder.dim), dtype="float32")

                if len(all_chunks) > 0:
                    dim = all_vectors.shape[1] if len(all_vectors) > 0 else embedder.dim
                    store = FaissVectorStore(dim=dim)
                    store.add(all_chunks, all_vectors)
                else:
                    store = FaissVectorStore(dim=embedder.dim)

                graph = build_dependency_graph(source_files)
                call_g = build_call_graph(all_chunks, source_files)
                ast_chunks_count = sum(1 for c in all_chunks if c.kind in ("function", "class", "method", "interface", "enum", "type", "struct", "section"))

                if save_to_disk:
                    save_index(repo_path, backend_name, source_files, all_chunks, store)

                return IngestedRepository(
                    store=store,
                    graph=graph,
                    num_files=len(source_files),
                    num_chunks=len(all_chunks),
                    languages_found=languages_found,
                    ast_chunks_count=ast_chunks_count,
                    files=source_files,
                    call_graph=call_g,
                )

    # Full Ingestion (Fresh or force_reindex)
    chunks = chunk_repository(source_files)
    if not chunks:
        raise ValueError(f"No code chunks could be extracted from files in '{repo_path}'")

    ast_chunks_count = sum(1 for c in chunks if c.kind in ("function", "class", "method", "interface", "enum", "type", "struct", "section"))
    graph = build_dependency_graph(source_files)
    call_g = build_call_graph(chunks, source_files)

    texts = [c.as_embedding_text() for c in chunks]
    vectors = embedder.embed(texts)

    store = FaissVectorStore(dim=vectors.shape[1])
    store.add(chunks, vectors)

    if save_to_disk:
        save_index(repo_path, backend_name, source_files, chunks, store)

    logger.info(f"Ingested '{repo_path}': {len(source_files)} files, {len(chunks)} chunks ({ast_chunks_count} AST), call graph: {call_g.number_of_nodes()} nodes.")

    return IngestedRepository(
        store=store,
        graph=graph,
        num_files=len(source_files),
        num_chunks=len(chunks),
        languages_found=languages_found,
        ast_chunks_count=ast_chunks_count,
        files=source_files,
        call_graph=call_g,
    )

