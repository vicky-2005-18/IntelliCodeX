"""
Tests for Graph-Augmented Sub-Graph Context Expansion in Query Engine
"""
import pytest
import networkx as nx
from core.parser import SourceFile
from core.chunker import chunk_file
from core.embedder import TfidfEmbedder
from core.vectorstore import FaissVectorStore
from core.dependency_graph import build_dependency_graph
from core.call_graph import build_call_graph
from rag.query_engine import QueryEngine, expand_retrieved_context


def test_graph_context_expansion():
    sf1 = SourceFile("src/service.py", "src/service.py", "python", "def process():\n    return calculate()\n", has_tree_sitter=True)
    sf2 = SourceFile("src/calc.py", "src/calc.py", "python", "def calculate():\n    return 42\n", has_tree_sitter=True)

    chunks = chunk_file(sf1) + chunk_file(sf2)
    embedder = TfidfEmbedder()
    texts = [c.as_embedding_text() for c in chunks]
    vectors = embedder.embed(texts)

    store = FaissVectorStore(dim=vectors.shape[1])
    store.add(chunks, vectors)

    dep_g = build_dependency_graph([sf1, sf2])
    call_g = build_call_graph(chunks, [sf1, sf2])

    engine = QueryEngine(store=store, embedder=embedder, dep_graph=dep_g, call_graph=call_g)
    results = engine.retrieve_expanded("process", top_k=1)

    assert len(results) >= 1
    # Check that expanded results include context reason tags
    reasons = [r["reason"] for r in results]
    assert "Direct Vector Match" in reasons
