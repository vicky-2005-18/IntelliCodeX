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


def test_call_graph_self_and_cls_resolution():
    code = """
class BaseHandler:
    def base_helper(self):
        return 1

class CustomHandler(BaseHandler):
    def handle(self):
        self.base_helper()
        self.step()

    def step(self):
        pass

class Unrelated:
    def step(self):
        pass
"""
    sf = SourceFile(
        path="/tmp/handler.py",
        rel_path="handler.py",
        language="python",
        content=code,
        has_tree_sitter=True
    )
    chunks = chunk_file(sf)
    cg = build_call_graph(chunks, [sf], legacy=False)

    # find edges from CustomHandler.handle
    handle_nodes = [n for n in cg.nodes if "CustomHandler.handle" in n or "CustomHandler::handle" in n]
    assert handle_nodes, "handle node should exist"
    handle_node = handle_nodes[0]

    callees = list(cg.successors(handle_node))
    callee_str = " ".join(callees)

    # self.base_helper() resolved to BaseHandler::base_helper
    assert "base_helper" in callee_str
    # self.step() resolved to CustomHandler::step, NOT Unrelated::step
    assert "CustomHandler::step" in callee_str or "CustomHandler" in callee_str
    assert "Unrelated" not in callee_str


def test_call_graph_deduplication_most_specific_chunk():
    code = """
class MathService:
    def compute(self, x):
        return self.internal_calc(x)

    def internal_calc(self, x):
        return x * 2
"""
    sf = SourceFile(
        path="/tmp/math.py",
        rel_path="math.py",
        language="python",
        content=code,
        has_tree_sitter=True
    )
    chunks = chunk_file(sf)
    cg = build_call_graph(chunks, [sf], legacy=False)

    # There should only be ONE edge for internal_calc, originating from the method compute,
    # NOT duplicated on the enclosing MathService class chunk.
    class_chunks = [c.chunk_id for c in chunks if c.kind == "class"]
    for cls_id in class_chunks:
        if cls_id in cg:
            succs = list(cg.successors(cls_id))
            assert not any("internal_calc" in s for s in succs), "Class chunk should not have duplicate edge"


def test_call_graph_unknown_receiver_dropped():
    code = """
class Target:
    def get(self, k):
        return k

class KnownService:
    def execute(self):
        return 42

def worker(req):
    # req is unknown receiver -> should drop .get() call
    req.get("key")
    # known receiver instantiated from KnownService -> should link
    svc = KnownService()
    svc.execute()
"""
    sf = SourceFile(
        path="/tmp/worker.py",
        rel_path="worker.py",
        language="python",
        content=code,
        has_tree_sitter=True
    )
    chunks = chunk_file(sf)
    cg = build_call_graph(chunks, [sf], legacy=False)

    # get() on unknown receiver req should NOT link to Target::get
    target_get_nodes = [n for n in cg.nodes if "Target::get" in n or "Target.get" in n]
    for t_node in target_get_nodes:
        callers = list(cg.predecessors(t_node))
        assert not any("worker" in c for c in callers), "Unknown receiver call should be dropped"

    # KnownService::execute should be linked from worker
    exec_nodes = [n for n in cg.nodes if "execute" in n]
    assert any(any("worker" in c for c in cg.predecessors(en)) for en in exec_nodes)


def test_call_graph_fan_out_cap_and_legacy_flag():
    code = """
class A:
    def dispatch(self): pass
class B:
    def dispatch(self): pass
class C:
    def dispatch(self): pass
class D:
    def dispatch(self): pass

def runner():
    dispatch()
"""
    sf = SourceFile(
        path="/tmp/fanout.py",
        rel_path="fanout.py",
        language="python",
        content=code,
        has_tree_sitter=True
    )
    chunks = chunk_file(sf)

    # In precision mode (legacy=False), dispatch matches 4 candidates (> 3 cap) -> dropped
    cg_precision = build_call_graph(chunks, [sf], legacy=False)
    runner_nodes = [n for n in cg_precision.nodes if "runner" in n]
    assert runner_nodes
    assert len(list(cg_precision.successors(runner_nodes[0]))) == 0

    # In legacy mode (legacy=True), fan-out is not capped -> all 4 linked
    cg_legacy = build_call_graph(chunks, [sf], legacy=True)
    runner_nodes_leg = [n for n in cg_legacy.nodes if "runner" in n]
    assert len(list(cg_legacy.successors(runner_nodes_leg[0]))) == 4


def test_cached_index_rebuilt_on_graph_version_mismatch(tmp_path):
    import os
    from core.embedder import TfidfEmbedder
    from core.pipeline import ingest_repository

    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()
    py_file = repo_dir / "app.py"
    py_file.write_text("def run():\n    return 42\n", encoding="utf-8")

    embedder = TfidfEmbedder(dim=8)

    # 1. Ingest with legacy_call_graph=True -> fresh indexing (saves graph_version=1)
    res1 = ingest_repository(str(repo_dir), embedder, save_to_disk=True, legacy_call_graph=True)
    assert res1.indexing_mode == "fresh"

    # 2. Ingest again with legacy_call_graph=True -> 100% cached
    res2 = ingest_repository(str(repo_dir), embedder, save_to_disk=True, legacy_call_graph=True)
    assert res2.indexing_mode == "cached"

    # 3. Ingest with modern default (legacy_call_graph=False, expected_graph_version=2)
    # Graph format mismatch detected -> cache invalidated -> rebuilt with indexing_mode="fresh"
    res3 = ingest_repository(str(repo_dir), embedder, save_to_disk=True, legacy_call_graph=False)
    assert res3.indexing_mode == "fresh"

    # 4. Ingest again with default -> cached under graph_version=2
    res4 = ingest_repository(str(repo_dir), embedder, save_to_disk=True, legacy_call_graph=False)
    assert res4.indexing_mode == "cached"

