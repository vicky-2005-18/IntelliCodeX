"""
Ties the whole ingestion workflow together, matching the paper's Section VI:
Repository Import -> Parsing -> Chunking -> Embedding -> FAISS Index -> Dep Graph -> Call Graph
"""
import os
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any
from core.parser import walk_repository, SourceFile
from core.chunker import chunk_repository, CodeChunk
from core.dependency_graph import build_dependency_graph
from core.call_graph import build_call_graph
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder

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


def ingest_repository(repo_path: str, embedder: BaseEmbedder) -> IngestedRepository:
    """
    Ingests a repository directory end-to-end:
    Walks directory -> parses files -> extracts AST/windowed chunks -> generates embeddings -> loads FAISS -> builds dep & call graphs
    """
    if not os.path.exists(repo_path):
        raise FileNotFoundError(f"Repository path does not exist: '{repo_path}'")

    source_files = walk_repository(repo_path)
    if not source_files:
        raise ValueError(f"No indexable source files found in '{repo_path}'")

    languages_found: Dict[str, int] = {}
    for sf in source_files:
        languages_found[sf.language] = languages_found.get(sf.language, 0) + 1

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
