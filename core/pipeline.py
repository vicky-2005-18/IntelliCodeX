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


def ingest_repository(repo_path: str, embedder: BaseEmbedder) -> IngestedRepository:
    source_files = walk_repository(repo_path)
    chunks = chunk_repository(source_files)
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
