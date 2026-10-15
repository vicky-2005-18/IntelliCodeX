"""
Unit & Integration Tests for Architecture Optimization & Refactoring Engine (REQ-FUT-06)
Tests circular dependency detection, package coupling metrics, bottleneck detection,
decoupling refactoring recommendations, and REST API/CLI integration.
"""
import os
import tempfile
import networkx as nx
import pytest
from unittest.mock import patch

from core.parser import SourceFile
from core.architecture_optimizer import (
    ArchitectureOptimizer,
    ArchitectureReport,
    ModuleCoupling,
    RefactoringRecommendation,
)


def test_architecture_optimizer_detects_cycles():
    """Verifies that circular dependency cycles (A -> B -> C -> A) are detected and refactoring advice is generated."""
    g = nx.DiGraph()
    # Add cycle: mod_a -> mod_b -> mod_c -> mod_a
    g.add_edge("mod_a.py", "mod_b.py", relationship="imports")
    g.add_edge("mod_b.py", "mod_c.py", relationship="imports")
    g.add_edge("mod_c.py", "mod_a.py", relationship="imports")
    # Add non-cyclic leaf
    g.add_edge("mod_c.py", "leaf.py", relationship="imports")

    optimizer = ArchitectureOptimizer()
    report = optimizer.analyze(g)

    assert isinstance(report, ArchitectureReport)
    assert len(report.cycles) == 1
    cycle = report.cycles[0]
    assert len(cycle) == 3
    assert set(cycle) == {"mod_a.py", "mod_b.py", "mod_c.py"}

    # Must generate cycle_break recommendation
    cycle_recs = [r for r in report.recommendations if r.type == "cycle_break"]
    assert len(cycle_recs) == 1
    assert "Dependency Inversion" in cycle_recs[0].strategy
    assert "Deferred / Lazy Import" in cycle_recs[0].strategy
    assert report.health_score < 100.0


def test_architecture_optimizer_coupling_and_bottlenecks():
    """Verifies Afferent (Ca), Efferent (Ce), Instability (I) calculations and God component bottleneck detection."""
    g = nx.DiGraph()
    # god_module has 6 dependents (Ca=6) and 6 dependencies (Ce=6)
    for i in range(6):
        g.add_edge(f"caller_{i}.py", "god_module.py", relationship="imports")
        g.add_edge("god_module.py", f"callee_{i}.py", relationship="imports")

    optimizer = ArchitectureOptimizer(high_coupling_threshold=5)
    report = optimizer.analyze(g)

    assert "god_module.py" in report.coupling_metrics
    god_metric = report.coupling_metrics["god_module.py"]
    assert god_metric.afferent_coupling == 6
    assert god_metric.efferent_coupling == 6
    assert god_metric.instability == 0.5  # 6 / (6 + 6) = 0.5
    assert god_metric.is_bottleneck is True

    # Check that bottleneck was captured
    bottleneck_modules = [b.module for b in report.bottlenecks]
    assert "god_module.py" in bottleneck_modules

    # Check god component refactoring recommendation
    god_recs = [r for r in report.recommendations if r.type == "god_component_split"]
    assert len(god_recs) == 1
    assert god_recs[0].target == "god_module.py"
    assert "Facade Pattern" in god_recs[0].strategy


def test_architecture_optimizer_with_source_files_and_diff():
    """Verifies that source file code is parsed to generate a suggested decoupling diff."""
    g = nx.DiGraph()
    g.add_edge("user_service.py", "order_service.py", relationship="imports")
    g.add_edge("order_service.py", "user_service.py", relationship="imports")

    sf_user = SourceFile(
        path="C:/tmp/user_service.py",
        rel_path="user_service.py",
        content="from order_service import get_user_orders\n\ndef get_user(uid):\n    return uid\n",
        language="python",
    )
    sf_order = SourceFile(
        path="C:/tmp/order_service.py",
        rel_path="order_service.py",
        content="from user_service import get_user\n\ndef get_user_orders(uid):\n    user = get_user(uid)\n    return []\n",
        language="python",
    )

    optimizer = ArchitectureOptimizer()
    report = optimizer.analyze(g, source_files=[sf_user, sf_order])

    assert len(report.cycles) == 1
    cycle_rec = report.recommendations[0]
    assert cycle_rec.suggested_diff is not None
    assert "--- a/" in cycle_rec.suggested_diff
    assert "+++ b/" in cycle_rec.suggested_diff
    assert "# Deferred to avoid circular import" in cycle_rec.suggested_diff


def test_architecture_optimizer_markdown_and_dict_serialization():
    """Verifies Markdown export and dictionary serialization for REST API / CLI."""
    g = nx.DiGraph()
    g.add_edge("a.py", "b.py", relationship="imports")
    g.add_edge("b.py", "a.py", relationship="imports")

    optimizer = ArchitectureOptimizer()
    report = optimizer.analyze(g)

    data = report.to_dict()
    assert data["cycles_count"] == 1
    assert "health_score" in data
    assert len(data["recommendations"]) == 1

    md = report.format_markdown()
    assert "# Architecture Optimization & Health Report" in md
    assert "Circular Dependency Cycles Detected" in md
    assert "a.py <-> b.py" in md


def test_api_architecture_optimization_endpoint():
    """Verifies FastAPI /api/graph/{repo_id}/architecture-optimization returns 200 with complete report."""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.auth import User, create_access_token
    from backend.database import db_manager
    from core.vectorstore import FaissVectorStore
    from core.embedder import TfidfEmbedder
    from rag.query_engine import QueryEngine
    from backend.api.repos import ACTIVE_REPOS

    test_user = User(id="arch_user", username="archdev", email="arch@test.com", role="developer")
    db_manager.insert("users", {
        "id": test_user.id,
        "username": test_user.username,
        "email": test_user.email,
        "role": test_user.role,
        "hashed_password": "dummy",
    })
    token = create_access_token(test_user)
    client = TestClient(app)

    repo_id = "test_arch_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    # Synthetic source files with cycle: a.py <-> b.py
    sf_a = SourceFile("C:/tmp/a.py", "a.py", "import b\ndef fa(): pass\n", "python")
    sf_b = SourceFile("C:/tmp/b.py", "b.py", "import a\ndef fb(): pass\n", "python")

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": [sf_a, sf_b],
        "meta": {"repo_id": repo_id, "repo_path": "C:/tmp", "owner_id": test_user.id},
    }

    resp = client.get(
        f"/api/graph/{repo_id}/architecture-optimization",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    res = resp.json()
    assert res["repo_id"] == repo_id
    assert "cycles" in res
    assert "recommendations" in res
    assert "health_score" in res


def test_cli_arch_batch_command(capsys):
    """Verifies that running 'cli.py sample_repo --backend tfidf -q arch' executes architecture analysis."""
    from cli import main
    with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf", "-q", "arch"]):
        ret = main()
        assert ret == 0

    captured = capsys.readouterr()
    assert "Architecture Optimization" in captured.out
    assert "Health Score" in captured.out


def _create_deterministic_fixture_repo(root_dir: str):
    """
    Creates a deterministic test repository fixture:
    1. Cyclic pair: service_a.py <-> service_b.py
    2. High-coupling module: hub_module.py (Ca=6, Ce=6)
    3. Healthy comparison module: healthy_module.py (Ca=0, Ce=1, clean 8-line function)
    4. Complex component: monolith_component.py (function with 95 lines)
    """
    os.makedirs(root_dir, exist_ok=True)

    # 1. Cyclic pair
    with open(os.path.join(root_dir, "service_a.py"), "w", encoding="utf-8") as f:
        f.write("from service_b import process_order\n\ndef create_user(uid):\n    return process_order(uid)\n")

    with open(os.path.join(root_dir, "service_b.py"), "w", encoding="utf-8") as f:
        f.write("from service_a import create_user\n\ndef process_order(uid):\n    return {'user_id': uid}\n")

    # 2. Callers and Callees for hub_module
    for i in range(6):
        callee_name = f"callee_{i}.py"
        with open(os.path.join(root_dir, callee_name), "w", encoding="utf-8") as f:
            f.write(f"def do_task_{i}():\n    return {i}\n")

    hub_imports = "\n".join([f"import callee_{i}" for i in range(6)])
    with open(os.path.join(root_dir, "hub_module.py"), "w", encoding="utf-8") as f:
        f.write(f"{hub_imports}\n\ndef dispatch_all():\n    return [callee_0.do_task_0()]\n")

    for i in range(6):
        caller_name = f"caller_{i}.py"
        with open(os.path.join(root_dir, caller_name), "w", encoding="utf-8") as f:
            f.write(f"import hub_module\ndef call_{i}():\n    return hub_module.dispatch_all()\n")

    # 3. Healthy module (depends only on leaf_util, no cycles, small function)
    with open(os.path.join(root_dir, "leaf_util.py"), "w", encoding="utf-8") as f:
        f.write("def helper_add(a, b):\n    return a + b\n")

    with open(os.path.join(root_dir, "healthy_module.py"), "w", encoding="utf-8") as f:
        f.write("import leaf_util\n\ndef compute_total(items):\n    acc = 0\n    for item in items:\n        acc = leaf_util.helper_add(acc, item)\n    return acc\n")

    # 4. Complex component (function spanning 95 lines)
    long_func_body = "\n".join([f"    step_{i} = {i} * 2" for i in range(92)])
    with open(os.path.join(root_dir, "monolith_component.py"), "w", encoding="utf-8") as f:
        f.write(f"def monolithic_executor():\n{long_func_body}\n    return step_0\n")


def test_grounded_recommendation_contract_on_deterministic_fixture():
    """
    Verifies that the architecture optimizer returns the full grounded recommendation contract:
    - Circular dependency: affected files, cycle edges, line citations, tradeoffs, limitations
    - High-coupling bottleneck: hub_module flagged; healthy_module explicitly spared
    - Complex component: monolithic_executor detected with line counts and start/end locations
    - Measured facts separated from AI advisory
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        _create_deterministic_fixture_repo(tmp_dir)

        # Ingest files as SourceFile objects and build dependency graph
        g = nx.DiGraph()
        source_files = []
        for fname in sorted(os.listdir(tmp_dir)):
            if fname.endswith(".py"):
                fpath = os.path.join(tmp_dir, fname)
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                sf = SourceFile(path=fpath, rel_path=fname, content=content, language="python")
                source_files.append(sf)

        # Build imports into DiGraph
        # 1. Cycle: service_a <-> service_b
        g.add_edge("service_a.py", "service_b.py", relationship="imports")
        g.add_edge("service_b.py", "service_a.py", relationship="imports")
        # 2. Hub module: 6 callers, 6 callees
        for i in range(6):
            g.add_edge(f"caller_{i}.py", "hub_module.py", relationship="imports")
            g.add_edge("hub_module.py", f"callee_{i}.py", relationship="imports")
        # 3. Healthy module
        g.add_edge("healthy_module.py", "leaf_util.py", relationship="imports")

        optimizer = ArchitectureOptimizer(
            high_coupling_threshold=5,
            complexity_lines_threshold=80,
        )
        report = optimizer.analyze(
            dep_graph=g,
            source_files=source_files,
            llm=None,
            repo_id="fixture_repo",
            snapshot_id="commit_abc123",
            is_stale=False,
        )

        assert isinstance(report, ArchitectureReport)

        # 1. Snapshot Info
        assert report.snapshot_info["repo_id"] == "fixture_repo"
        assert report.snapshot_info["snapshot_id"] == "commit_abc123"
        assert report.snapshot_info["is_stale"] is False

        # 2. Measured Facts separation
        assert "detected_cycles" in report.measured_facts
        assert "coupling_metrics" in report.measured_facts
        assert "complex_components" in report.measured_facts
        assert report.measured_facts["cycle_count"] == 1

        # 3. AI advisory unavailable status
        assert report.ai_advisory["status"] == "unavailable"
        assert "Deterministic analysis executed without LLM" in report.ai_advisory["notice"]

        # 4. Check Circular Dependency finding contract
        cycle_recs = [r for r in report.recommendations if r.finding_type == "circular_dependency"]
        assert len(cycle_recs) == 1
        rec_cycle = cycle_recs[0]
        assert set(rec_cycle.affected_files) == {"service_a.py", "service_b.py"}
        assert len(rec_cycle.source_locations) >= 1
        assert any("service_a" in loc["file"] or "service_b" in loc["file"] for loc in rec_cycle.source_locations)
        assert rec_cycle.supporting_evidence["length"] == 2
        assert rec_cycle.confidence == "high"
        assert "Tradeoffs" in rec_cycle.tradeoffs or "file count" in rec_cycle.tradeoffs
        assert "Static AST" in rec_cycle.limitations

        # 5. Check High Coupling Bottleneck finding contract
        bottleneck_recs = [r for r in report.recommendations if r.finding_type == "high_coupling_bottleneck"]
        assert len(bottleneck_recs) == 1
        rec_hub = bottleneck_recs[0]
        assert rec_hub.target == "hub_module.py"
        assert rec_hub.supporting_evidence["afferent_coupling_ca"] == 6
        assert rec_hub.supporting_evidence["efferent_coupling_ce"] == 6
        assert rec_hub.supporting_evidence["instability_i"] == 0.5
        assert "High centrality alone is NOT an inherent design defect" in rec_hub.limitations

        # Negative Check: healthy_module.py MUST NOT be flagged
        flagged_targets = [r.target for r in report.recommendations]
        assert "healthy_module.py" not in flagged_targets
        assert "leaf_util.py" not in flagged_targets

        # 6. Check Complex Component finding contract
        cc_recs = [r for r in report.recommendations if r.finding_type == "complex_component"]
        assert len(cc_recs) == 1
        rec_cc = cc_recs[0]
        assert "monolith_component.py::monolithic_executor" == rec_cc.target
        assert rec_cc.supporting_evidence["line_count"] > 80
        assert rec_cc.supporting_evidence["symbol_type"] == "function"
        assert rec_cc.source_locations[0]["line"] == 1
        assert "Extract Method" in rec_cc.proposed_improvement

        # 7. Markdown serialization
        md = report.format_markdown()
        assert "# Architecture Optimization & Health Report" in md
        assert "fixture_repo" in md
        assert "commit_abc123" in md
        assert "service_a.py <-> service_b.py" in md
        assert "hub_module.py" in md
        assert "monolithic_executor" in md


def test_disposable_copy_cycle_break_verification():
    """
    Verifies that when a circular dependency cycle is removed in a disposable copy,
    the updated architecture analysis confirms 0 cycles without reporting the cycle recommendation.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        _create_deterministic_fixture_repo(tmp_dir)

        # Baseline: with cycle
        g_baseline = nx.DiGraph()
        g_baseline.add_edge("service_a.py", "service_b.py", relationship="imports")
        g_baseline.add_edge("service_b.py", "service_a.py", relationship="imports")
        optimizer = ArchitectureOptimizer()
        rep_baseline = optimizer.analyze(dep_graph=g_baseline)
        assert len(rep_baseline.cycles) == 1
        assert len([r for r in rep_baseline.recommendations if r.finding_type == "circular_dependency"]) == 1

        # Disposable copy: remove circular import in service_b.py
        with open(os.path.join(tmp_dir, "service_b.py"), "w", encoding="utf-8") as f:
            # Replaced 'from service_a import create_user' with standalone logic
            f.write("def process_order(uid):\n    return {'user_id': uid, 'status': 'processed'}\n")

        # Re-parse source files
        source_files_fixed = []
        for fname in ["service_a.py", "service_b.py"]:
            fpath = os.path.join(tmp_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            source_files_fixed.append(SourceFile(path=fpath, rel_path=fname, content=content, language="python"))

        # In updated graph, edge from service_b to service_a no longer exists
        g_fixed = nx.DiGraph()
        g_fixed.add_edge("service_a.py", "service_b.py", relationship="imports")

        rep_fixed = optimizer.analyze(dep_graph=g_fixed, source_files=source_files_fixed)
        assert len(rep_fixed.cycles) == 0
        cycle_recs_fixed = [r for r in rep_fixed.recommendations if r.finding_type == "circular_dependency"]
        assert len(cycle_recs_fixed) == 0
        assert rep_fixed.health_score > rep_baseline.health_score


def test_architecture_optimizer_configurable_thresholds():
    """Verifies that custom thresholds adaptively control bottleneck and complexity findings."""
    g = nx.DiGraph()
    # hub module with Ca=6, Ce=6
    for i in range(6):
        g.add_edge(f"caller_{i}.py", "hub.py", relationship="imports")
        g.add_edge("hub.py", f"callee_{i}.py", relationship="imports")

    sf_complex = SourceFile(
        path="C:/tmp/comp.py",
        rel_path="comp.py",
        content="def big_func():\n" + "\n".join([f"    y_{i} = {i}" for i in range(90)]) + "\n    return y_0\n",
        language="python",
    )

    # Threshold 1: Strict (high_coupling=5, complexity=80) -> flags both
    opt_strict = ArchitectureOptimizer(high_coupling_threshold=5, complexity_lines_threshold=80)
    rep_strict = opt_strict.analyze(g, source_files=[sf_complex])
    assert len(rep_strict.bottlenecks) == 1
    assert len(rep_strict.complex_components) == 1

    # Threshold 2: Relaxed (high_coupling=10, complexity=120) -> flags neither
    opt_relaxed = ArchitectureOptimizer(high_coupling_threshold=10, complexity_lines_threshold=120)
    rep_relaxed = opt_relaxed.analyze(g, source_files=[sf_complex])
    assert len(rep_relaxed.bottlenecks) == 0
    assert len(rep_relaxed.complex_components) == 0


def test_architecture_optimizer_empty_and_isolated_graph():
    """Verifies graceful handling of empty or single-node graphs without crashing."""
    optimizer = ArchitectureOptimizer()

    # Empty graph
    rep_empty = optimizer.analyze(dep_graph=nx.DiGraph())
    assert rep_empty.total_modules == 0
    assert rep_empty.total_dependencies == 0
    assert len(rep_empty.cycles) == 0
    assert len(rep_empty.bottlenecks) == 0
    assert rep_empty.health_score == 100.0

    # Single isolated node
    g_iso = nx.DiGraph()
    g_iso.add_node("standalone.py")
    rep_iso = optimizer.analyze(dep_graph=g_iso)
    assert rep_iso.total_modules == 1
    assert rep_iso.total_dependencies == 0
    assert len(rep_iso.cycles) == 0
    assert rep_iso.health_score == 100.0


def test_architecture_optimization_api_authorization_and_freshness():
    """
    Verifies that the FastAPI endpoint enforces repository authorization (403 for unauthorized users)
    and reports snapshot freshness / staleness metadata.
    """
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.auth import User, create_access_token
    from backend.database import db_manager
    from core.vectorstore import FaissVectorStore
    from core.embedder import TfidfEmbedder
    from rag.query_engine import QueryEngine
    from backend.api.repos import ACTIVE_REPOS

    owner_user = User(id="owner_1", username="ownerdev", email="owner@test.com", role="developer")
    other_user = User(id="other_2", username="otherdev", email="other@test.com", role="developer")

    db_manager.insert("users", {"id": owner_user.id, "username": owner_user.username, "email": owner_user.email, "role": owner_user.role, "hashed_password": "pw"})
    db_manager.insert("users", {"id": other_user.id, "username": other_user.username, "email": other_user.email, "role": other_user.role, "hashed_password": "pw"})

    owner_token = create_access_token(owner_user)
    other_token = create_access_token(other_user)
    client = TestClient(app)

    repo_id = "tenant_private_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": [SourceFile("C:/tmp/a.py", "a.py", "import b\n", "python")],
        "meta": {"repo_id": repo_id, "repo_path": "C:/tmp", "owner_id": owner_user.id, "commit_hash": "sha_112233"},
        "graph_is_stale": True,
    }

    # 1. Unauthorized tenant access -> 403 Forbidden
    resp_unauth = client.get(
        f"/api/graph/{repo_id}/architecture-optimization",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp_unauth.status_code == 403

    # 2. Authorized owner access -> 200 OK with staleness warning and snapshot metadata
    resp_auth = client.get(
        f"/api/graph/{repo_id}/architecture-optimization",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_auth.status_code == 200
    data = resp_auth.json()
    assert data["snapshot_info"]["repo_id"] == repo_id
    assert data["snapshot_info"]["snapshot_id"] == "sha_112233"
    assert data["snapshot_info"]["is_stale"] is True
    assert "Watched filesystem changes" in data["snapshot_info"]["stale_warning"]
    assert "measured_facts" in data
    assert "ai_advisory" in data

