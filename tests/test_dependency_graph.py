"""
Unit Tests for Enhanced Dependency Graph (Phase 4)
"""
from backend.dependency_graph import EnhancedDependencyGraph

from core.parser import SourceFile


def test_enhanced_graph_builder():
    sf1 = SourceFile(path="/app/main.py", rel_path="main.py", language="python", content="import helper\nclass App:\n    pass\n")
    sf2 = SourceFile(path="/app/helper.py", rel_path="helper.py", language="python", content="def util():\n    pass\n")

    graph_engine = EnhancedDependencyGraph()
    graph = graph_engine.build([sf1, sf2])

    assert graph.has_node("main.py")
    assert graph.has_node("helper.py")
    assert graph.has_edge("main.py", "helper.py")

    cy = graph_engine.export_cytoscape()
    assert len(cy["nodes"]) >= 2
    assert len(cy["edges"]) >= 1
