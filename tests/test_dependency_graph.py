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


def test_core_dependency_graph_relative_and_dynamic_imports():
    from core.dependency_graph import build_dependency_graph, extract_file_imports, resolve_import_to_file

    sf_main = SourceFile(
        path="/app/pkg/main.py",
        rel_path="pkg/main.py",
        language="python",
        content="""
from .utils import helper
from . import config
import importlib
dyn = importlib.import_module("pkg.service")
builtin_dyn = __import__("pkg.service")
from ..root_helper import root_func
"""
    )
    sf_utils = SourceFile(path="/app/pkg/utils.py", rel_path="pkg/utils.py", language="python", content="def helper(): pass\n")
    sf_config = SourceFile(path="/app/pkg/config.py", rel_path="pkg/config.py", language="python", content="DEBUG = True\n")
    sf_service = SourceFile(path="/app/pkg/service.py", rel_path="pkg/service.py", language="python", content="def run(): pass\n")
    sf_root = SourceFile(path="/app/root_helper.py", rel_path="root_helper.py", language="python", content="def root_func(): pass\n")

    files = [sf_main, sf_utils, sf_config, sf_service, sf_root]
    graph = build_dependency_graph(files)

    # Verify nodes
    for sf in files:
        assert graph.has_node(sf.rel_path)

    # Verify edges resolved accurately
    assert graph.has_edge("pkg/main.py", "pkg/utils.py"), "Relative import 'from .utils import helper' should resolve to pkg/utils.py"
    assert graph.has_edge("pkg/main.py", "pkg/config.py"), "Package relative import 'from . import config' should resolve to pkg/config.py"
    assert graph.has_edge("pkg/main.py", "pkg/service.py"), "Dynamic import 'importlib.import_module(\"pkg.service\")' should resolve to pkg/service.py"
    assert graph.has_edge("pkg/main.py", "root_helper.py"), "Parent relative import 'from ..root_helper' should resolve to root_helper.py"


def test_enhanced_graph_relative_and_dynamic_imports():
    sf_api = SourceFile(
        path="/app/backend/api.py",
        rel_path="backend/api.py",
        language="python",
        content="""
from .models import Item
import importlib
h = importlib.import_module("backend.handlers")
"""
    )
    sf_models = SourceFile(path="/app/backend/models.py", rel_path="backend/models.py", language="python", content="class Item: pass\n")
    sf_handlers = SourceFile(path="/app/backend/handlers.py", rel_path="backend/handlers.py", language="python", content="def handle(): pass\n")

    engine = EnhancedDependencyGraph()
    graph = engine.build([sf_api, sf_models, sf_handlers])

    assert graph.has_edge("backend/api.py", "backend/models.py")
    assert graph.has_edge("backend/api.py", "backend/handlers.py")

