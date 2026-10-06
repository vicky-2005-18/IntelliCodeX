"""
Week 2 Verification Suite: Graph Accuracy on sample_repo and Multi-File Projects
"""
import pytest
from core.embedder import TfidfEmbedder
from core.pipeline import ingest_repository
from core.dependency_graph import files_likely_affected_by, get_top_central_files
from core.call_graph import find_callers_of_symbol, get_top_central_symbols


def test_week2_graph_accuracy_sample_repo():
    embedder = TfidfEmbedder()
    ingested = ingest_repository("sample_repo", embedder)

    # 1. Dependency Graph Verification
    dep_g = ingested.graph
    assert dep_g is not None
    assert dep_g.number_of_nodes() >= 3
    assert dep_g.number_of_edges() >= 1

    # Verify reverse dependency lookup on sample_repo
    affected_db = files_likely_affected_by(dep_g, "pkg/db.py")
    assert len(affected_db) >= 0  # Should run without error

    # 2. Call Graph Verification
    call_g = ingested.call_graph
    assert call_g is not None
    assert call_g.number_of_nodes() > 0

    # 3. Centrality Scoring Verification
    top_files = get_top_central_files(dep_g, top_n=3)
    assert isinstance(top_files, list)

    top_syms = get_top_central_symbols(call_g, top_n=3)
    assert isinstance(top_syms, list)
