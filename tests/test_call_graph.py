"""
Tests for Symbol Call Graph Engine
"""
import pytest
import networkx as nx
from core.parser import SourceFile
from core.chunker import chunk_file
from core.call_graph import extract_function_calls, build_call_graph, find_callers_of_symbol, find_callees_of_chunk


def test_extract_function_calls_python():
    sf = SourceFile(
        path="/tmp/main.py",
        rel_path="main.py",
        language="python",
        content="def main():\n    user = fetch_user(42)\n    db.save(user)\n",
        has_tree_sitter=True
    )
    calls = extract_function_calls(sf)
    names = [c["name"] for c in calls]
    assert "fetch_user" in names
    assert "save" in names


def test_extract_function_calls_javascript():
    sf = SourceFile(
        path="/tmp/app.js",
        rel_path="app.js",
        language="javascript",
        content="function handle() {\n    let data = parseJson(input);\n    api.send(data);\n}",
        has_tree_sitter=True
    )
    calls = extract_function_calls(sf)
    names = [c["name"] for c in calls]
    assert "parseJson" in names
    assert "send" in names


def test_build_call_graph_cross_function():
    sf1 = SourceFile(
        path="/tmp/service.py",
        rel_path="service.py",
        language="python",
        content="""
def process_order(order_id):
    return compute_total(order_id)

def compute_total(order_id):
    return 100
""",
        has_tree_sitter=True
    )

    chunks = chunk_file(sf1)
    call_g = build_call_graph(chunks, [sf1])

    assert isinstance(call_g, nx.DiGraph)
    assert call_g.number_of_nodes() >= 2

    # Check caller lookup for compute_total
    callers = find_callers_of_symbol(call_g, "compute_total")
    assert any("process_order" in c for c in callers)
