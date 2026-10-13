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
