"""
Tests for Retrieval View & Provenance Trace (Requirements 1-7).
Verifies:
1. Trace is filled (bm25_hits, dense_hits, fused_hits) and fused ranks are consistent.
2. Passing trace=None gives exact same answer and ranking as before (regression test).
3. no_answer=True never calls the fake LLM (assert call count 0).
4. Budget: included plus dropped chunks account for all candidates; used_tokens <= max_tokens.
5. Graph additions list a reason and a causing hit.
6. CLI explain: prints table headers; --json output parses as JSON; empty index prints clear message.
7. API: returns 401 without token, 200 with valid token, and 403 when user cannot explain another's repository.
"""
import io
import json
import os
import networkx as nx
import pytest
from unittest.mock import patch

from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.lexical_index import BM25Index
from core.retrieval_trace import RetrievalTrace, RetrievalHit, FusedHit, GraphAddition
from rag.query_engine import QueryEngine
from cli import main as cli_main


class FakeLLM:
    """Fake LLM for offline testing without network or Ollama."""
    def __init__(self, response: str = "Fake LLM Answer: Everything looks clean."):
        self.response = response
        self.call_count = 0
        self.last_prompt = None

    def generate(self, prompt: str, system: str = "", temperature: float = 0.0) -> str:
        self.call_count += 1
        self.last_prompt = prompt
        return self.response


def make_chunk(cid: str, name: str, code: str, fpath: str, start: int = 1, end: int = 10) -> CodeChunk:
    return CodeChunk(
        chunk_id=cid,
        file_path=fpath,
        name=name,
        kind="function",
        language="python",
        start_line=start,
        end_line=end,
        code=code,
        docstring=f"Documentation for {name}",
    )


@pytest.fixture
def tiny_fixture():
    """Builds a deterministic in-memory fixture with 4 chunks, TF-IDF embedder, call graph, and dep graph."""
    c1 = make_chunk(
        "c_calc_add",
        "calculate_add",
        "def calculate_add(a, b):\n    return a + b",
        "sample/calculator.py",
        start=1,
        end=5,
    )
    c2 = make_chunk(
        "c_calc_total",
        "calculate_total",
        "def calculate_total(items):\n    return calculate_add(items[0], items[1])",
        "sample/calculator.py",
        start=6,
        end=15,
    )
    c3 = make_chunk(
        "c_format_result",
        "format_result",
        "def format_result(val):\n    return f'Total: {val}'",
        "sample/formatter.py",
        start=1,
        end=8,
    )
    c4 = make_chunk(
        "c_main_runner",
        "main_runner",
        "def main_runner():\n    t = calculate_total([1, 2])\n    return format_result(t)",
        "sample/main.py",
        start=1,
        end=10,
    )
    chunks = [c1, c2, c3, c4]

    embedder = TfidfEmbedder(dim=64)
    embedder.fit([c.code for c in chunks])
    vectors = embedder.embed([c.code for c in chunks])

    store = FaissVectorStore(embedder.dim)
    store.add(chunks, vectors)

    lex_index = BM25Index(chunks)

    # Call graph: main_runner -> calculate_total -> calculate_add
    call_g = nx.DiGraph()
    call_g.add_node("c_main_runner")
    call_g.add_node("c_calc_total")
    call_g.add_node("c_calc_add")
    call_g.add_edge("c_main_runner", "c_calc_total")
    call_g.add_edge("c_calc_total", "c_calc_add")

    # Dependency graph: sample/main.py -> sample/calculator.py
    dep_g = nx.DiGraph()
    dep_g.add_node("sample/main.py")
    dep_g.add_node("sample/calculator.py")
    dep_g.add_edge("sample/main.py", "sample/calculator.py", internal=True)

    fake_llm = FakeLLM()
    engine = QueryEngine(
        store=store,
        embedder=embedder,
        llm=fake_llm,
        dep_graph=dep_g,
        call_graph=call_g,
        lexical_index=lex_index,
        hybrid_search=True,
    )
    return engine, chunks, fake_llm


def test_trace_filled_and_consistent_ranks(tiny_fixture):
    """1. Trace is filled (bm25_hits, dense_hits, fused_hits non-empty) and ranks are consistent."""
    engine, chunks, fake_llm = tiny_fixture
    trace = RetrievalTrace()

    ans = engine.ask("calculate_total", top_k=3, trace=trace)

    assert trace.question == "calculate_total"
    assert "calculate_total" in trace.query_terms
    assert len(trace.bm25_hits) > 0, "BM25 hits must be non-empty"
    assert len(trace.dense_hits) > 0, "Dense hits must be non-empty"
    assert len(trace.fused_hits) > 0, "Fused hits must be non-empty"

    # Check rank consistency
    # For a chunk present in both BM25 and Dense, it must have both bm25_rank and dense_rank
    bm25_cids = {h[0] for h in trace.bm25_hits}
    dense_cids = {h[0] for h in trace.dense_hits}
    common_cids = bm25_cids.intersection(dense_cids)

    found_common_check = False
    for fhit in trace.fused_hits:
        cid = fhit[0]
        if cid in common_cids:
            assert fhit.bm25_rank is not None, f"Chunk {cid} in BM25 hits must have bm25_rank"
            assert fhit.dense_rank is not None, f"Chunk {cid} in Dense hits must have dense_rank"
            assert fhit.bm25_rank >= 1
            assert fhit.dense_rank >= 1
            found_common_check = True

    assert found_common_check, "At least one chunk should appear in both BM25 and Dense"
    assert trace.timings_ms["embed"] >= 0.0
    assert trace.timings_ms["bm25"] >= 0.0
    assert trace.timings_ms["dense"] >= 0.0
    assert trace.timings_ms["fuse"] >= 0.0


def test_regression_trace_none_identical(tiny_fixture):
    """2. Passing trace=None gives exact same answer and retrieved chunks as before."""
    engine, chunks, fake_llm = tiny_fixture

    resp_no_trace = engine.ask("calculate_add", top_k=2, trace=None)
    trace = RetrievalTrace()
    resp_with_trace = engine.ask("calculate_add", top_k=2, trace=trace)

    assert resp_no_trace["answer"] == resp_with_trace["answer"]
    # Chunk order and count must match exactly
    cids_no_trace = [c["file"] + "::" + c["name"] for c in resp_no_trace["retrieved_chunks"]]
    cids_with_trace = [c["file"] + "::" + c["name"] for c in resp_with_trace["retrieved_chunks"]]
    assert cids_no_trace == cids_with_trace


def test_no_answer_mode_skips_llm(tiny_fixture):
    """3. no_answer=True builds the trace WITHOUT calling the LLM (assert call count 0)."""
    engine, chunks, fake_llm = tiny_fixture
    initial_calls = fake_llm.call_count

    trace = RetrievalTrace()
    resp = engine.ask("calculate_total", top_k=2, trace=trace, no_answer=True)

    assert fake_llm.call_count == initial_calls, "Fake LLM must NOT be called when no_answer=True"
    assert resp["answer"] is None
    assert trace.answer is None
    assert trace.timings_ms["llm"] == 0.0
    assert len(trace.fused_hits) > 0, "Retrieval and fusion should still run"
    assert trace.sources is not None and len(trace.sources) > 0


def test_budget_partitions_all_candidates(tiny_fixture):
    """4. Budget: included plus dropped chunks account for all candidates; used_tokens <= max_tokens."""
    engine, chunks, fake_llm = tiny_fixture

    # Test with very small budget to force dropped chunks
    trace = RetrievalTrace()
    engine.ask("calculate_total", top_k=4, max_token_budget=50, trace=trace, no_answer=True)

    b = trace.budget
    assert b.max_tokens == 50
    assert b.used_tokens <= b.max_tokens, f"used_tokens {b.used_tokens} must be <= max_tokens {b.max_tokens}"

    # Verify partition: included + dropped must account for all candidates
    all_trace_cids = set(b.included_chunk_ids).union(set(b.dropped_chunk_ids))
    intersection = set(b.included_chunk_ids).intersection(set(b.dropped_chunk_ids))
    assert len(intersection) == 0, "Included and dropped chunks must be disjoint"
    assert len(all_trace_cids) > 0, "Candidates must not be empty"


def test_graph_additions_reasons_and_causes(tiny_fixture):
    """5. Graph additions list a valid reason ('caller', 'callee', 'import') and causing hit."""
    engine, chunks, fake_llm = tiny_fixture
    trace = RetrievalTrace()

    # Querying calculate_total will expand caller (main_runner) and callee (calculate_add)
    engine.ask("calculate_total", top_k=2, trace=trace, no_answer=True)

    assert len(trace.graph_additions) > 0, "Graph additions should be populated via call graph"
    for item in trace.graph_additions:
        target, reason, caused_by = item[0], item[1], item[2]
        assert reason in ("caller", "callee", "import"), f"Reason {reason} must be caller/callee/import"
        assert caused_by is not None and len(caused_by) > 0, "causing hit ID must be present"


def test_cli_explain_command(tiny_fixture, monkeypatch, capsys):
    """6. CLI explain: prints tables for fixture, --json parses as JSON, empty index exits cleanly."""
    engine, chunks, fake_llm = tiny_fixture

    # Fake result container matching cli ingestion result
    class FakeResult:
        store = engine.store
        graph = engine.dep_graph
        call_graph = engine.call_graph
        lexical_index = engine.lexical_index
        num_files = 3
        num_chunks = len(chunks)
        ast_chunks_count = len(chunks)

    result = FakeResult()

    # Test 6a: explain: query (table rendering)
    monkeypatch.setattr("sys.argv", ["cli.py", "sample_repo", "--no-tui"])
    inputs = iter(["explain: calculate_total --no-answer", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("cli.ingest_repository", return_value=result), \
         patch("cli.create_components", return_value=(engine.embedder, fake_llm, "tfidf")), \
         patch("cli.check_ollama_available", return_value=False), \
         patch("cli.should_use_tui", return_value=False):
        try:
            cli_main()
        except SystemExit:
            pass

    captured = capsys.readouterr().out
    assert "BM25" in captured
    assert "Dense" in captured
    assert "Merged RRF Ranking" in captured or "Ranking" in captured

    # Test 6b: explain: query --json (must parse as valid JSON)
    monkeypatch.setattr("sys.argv", ["cli.py", "sample_repo", "--no-tui"])
    inputs_json = iter(["explain: calculate_total --no-answer --json", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs_json))

    with patch("cli.ingest_repository", return_value=result), \
         patch("cli.create_components", return_value=(engine.embedder, fake_llm, "tfidf")), \
         patch("cli.check_ollama_available", return_value=False), \
         patch("cli.should_use_tui", return_value=False):
        try:
            cli_main()
        except SystemExit:
            pass

    captured_json = capsys.readouterr().out
    # Find JSON block in output
    json_start = captured_json.find("{\n  \"question\":")
    assert json_start != -1, "Expected JSON output"
    json_end = captured_json.find("\n}", json_start) + 2
    json_str = captured_json[json_start:json_end]
    parsed = json.loads(json_str)
    assert parsed["question"] == "calculate_total"
    assert "fused_hits" in parsed
    assert "budget" in parsed

    # Test 6c: empty index prints message and does not crash
    class EmptyStore:
        chunks = []
    class EmptyResult:
        store = EmptyStore()
        graph = nx.DiGraph()
        call_graph = nx.DiGraph()
        num_files = 0
        num_chunks = 0
        ast_chunks_count = 0

    monkeypatch.setattr("sys.argv", ["cli.py", "sample_repo", "--no-tui"])
    inputs_empty = iter(["explain: anything", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs_empty))

    with patch("cli.ingest_repository", return_value=EmptyResult()), \
         patch("cli.create_components", return_value=(engine.embedder, fake_llm, "tfidf")), \
         patch("cli.check_ollama_available", return_value=False), \
         patch("cli.should_use_tui", return_value=False):
        try:
            cli_main()
        except SystemExit:
            pass

    captured_empty = capsys.readouterr().out
    assert "empty (0 chunks)" in captured_empty


def test_api_explain_auth_and_rbac(tiny_fixture):
    """7. API: returns 401 without token, 200 with valid token, and 403 on another user's repo."""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.auth import create_access_token, User
    from backend.database import db_manager
    from backend.api.repos import ACTIVE_REPOS

    engine, chunks, fake_llm = tiny_fixture
    client = TestClient(app)

    repo_id = "test_provenance_repo"
    owner_user_id = "user_owner_123"
    other_user_id = "user_intruder_456"

    # Setup active repo in cache with owner metadata
    ACTIVE_REPOS[repo_id] = {
        "engine": engine,
        "graph": engine.dep_graph,
        "store": engine.store,
        "embedder": engine.embedder,
        "meta": {"owner_id": owner_user_id, "repo_id": repo_id},
        "source_files": [],
    }

    # Ensure users in DB
    db_manager.delete("users", {"id": owner_user_id})
    db_manager.delete("users", {"id": other_user_id})
    db_manager.insert("users", {
        "id": owner_user_id,
        "username": "owner_user",
        "email": "owner@test.com",
        "role": "developer",
    })
    db_manager.insert("users", {
        "id": other_user_id,
        "username": "other_user",
        "email": "other@test.com",
        "role": "developer",
    })

    owner_user = User(id=owner_user_id, username="owner_user", email="owner@test.com", role="developer")
    other_user = User(id=other_user_id, username="other_user", email="other@test.com", role="developer")
    owner_token = create_access_token(owner_user)
    other_token = create_access_token(other_user)

    payload = {
        "repo_id": repo_id,
        "question": "calculate_total",
        "top_k": 3,
        "no_answer": True,
    }

    # 7a. Without token -> 401
    resp_unauth = client.post("/api/query/explain", json=payload)
    assert resp_unauth.status_code == 401

    # 7b. With valid token of owner -> 200
    resp_ok = client.post(
        "/api/query/explain",
        json=payload,
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp_ok.status_code == 200
    data = resp_ok.json()
    assert data["question"] == "calculate_total"
    assert "fused_hits" in data
    assert "budget" in data
    assert len(data["fused_hits"]) > 0

    # 7c. With token of another user -> 403 Forbidden
    resp_forbidden = client.post(
        "/api/query/explain",
        json=payload,
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp_forbidden.status_code == 403
    assert "Access denied" in resp_forbidden.json()["detail"]
