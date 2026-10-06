"""
Tests for Centrality Scoring (PageRank & In-Degree) in Dependency and Call Graphs
"""
import pytest
import networkx as nx
from core.parser import SourceFile
from core.chunker import chunk_file
from core.dependency_graph import build_dependency_graph, calculate_file_centrality, get_top_central_files
from core.call_graph import build_call_graph, calculate_symbol_centrality, get_top_central_symbols


def test_file_centrality_scoring():
    sf_main = SourceFile("src/main.py", "src/main.py", "python", "import utils\nimport db\n")
    sf_db = SourceFile("src/db.py", "src/db.py", "python", "# db layer\n")
    sf_utils = SourceFile("src/utils.py", "src/utils.py", "python", "# utils layer\n")
    sf_api = SourceFile("src/api.py", "src/api.py", "python", "import db\nimport utils\n")

    graph = build_dependency_graph([sf_main, sf_db, sf_utils, sf_api])
    scores = calculate_file_centrality(graph)

    assert "src/db.py" in scores
    assert "src/utils.py" in scores
    top = get_top_central_files(graph, top_n=2)
    assert len(top) == 2


def test_symbol_centrality_scoring():
    code1 = """
def main():
    helper()
    helper()

def helper():
    return 42
"""
    sf = SourceFile("main.py", "main.py", "python", code1, has_tree_sitter=True)
    chunks = chunk_file(sf)
    call_g = build_call_graph(chunks, [sf])

    scores = calculate_symbol_centrality(call_g)
    assert len(scores) > 0
    top_syms = get_top_central_symbols(call_g, top_n=2)
    assert len(top_syms) > 0
