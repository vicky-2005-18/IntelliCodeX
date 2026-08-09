"""
Ties the whole ingestion workflow together, matching the paper's Section VI:
Repository Import -> Parsing -> Chunking -> Embedding -> FAISS Index -> Dep Graph
"""
from dataclasses import dataclass
from core.parser import walk_repository
from core.chunker import chunk_repository
from core.dependency_graph import build_dependency_graph
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder


@dataclass
class IngestedRepository:
    store: FaissVectorStore
    graph: object
    num_files: int
    num_chunks: int


import os


def ingest_repository(repo_path: str, embedder: BaseEmbedder) -> IngestedRepository:
    if not os.path.exists(repo_path):
        raise FileNotFoundError(f"Repository path does not exist: '{repo_path}'")

    source_files = walk_repository(repo_path)
    if not source_files:
        raise ValueError(f"No indexable source files (.py, .js, .ts, .java, etc.) found in '{repo_path}'")

    chunks = chunk_repository(source_files)
    if not chunks:
        raise ValueError(f"No code chunks could be extracted from files in '{repo_path}'")

    graph = build_dependency_graph(source_files)

    texts = [c.as_embedding_text() for c in chunks]
    vectors = embedder.embed(texts)

    store = FaissVectorStore(dim=vectors.shape[1])
    store.add(chunks, vectors)

    return IngestedRepository(
        store=store,
        graph=graph,
        num_files=len(source_files),
        num_chunks=len(chunks),
    )
