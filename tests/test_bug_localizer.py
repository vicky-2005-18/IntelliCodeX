"""
Unit Tests for Stack Trace Parser and Advanced Bug Localizer (Phase 2)
"""
from backend.bug_localizer import StackTraceParser, AdvancedBugLocalizer

from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.chunker import CodeChunk


def test_stack_trace_parser():
    parser = StackTraceParser()
    py_trace = """Traceback (most recent call last):
  File "server/api.py", line 45, in legacy_ingest
    return ingest_repo(req)
ValueError: Invalid path"""
    
    info = parser.parse(py_trace)
    assert info["error_type"] == "ValueError"
    assert len(info["parsed_frames"]) == 1
    assert info["parsed_frames"][0]["file_path"] == "server/api.py"
    assert info["parsed_frames"][0]["line_number"] == 45


def test_bug_localizer_scoring():
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="auth.py::login",
        file_path="auth.py",
        language="python",
        kind="function",
        name="login",
        start_line=10,
        end_line=20,
        code="def login(user, pwd):\n    if not user:\n        raise ValueError('Invalid user')\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    localizer = AdvancedBugLocalizer(store, embedder)
    res = localizer.localize("ValueError: Invalid user at auth.py line 12")

    assert res["error_type"] == "ValueError"
    assert len(res["candidates"]) > 0
    assert res["candidates"][0]["file_path"] == "auth.py"
    assert res["candidates"][0]["confidence_score"] > 0.5


def test_bug_localizer_without_stack_trace_sbfl():
    """Verifies logical bug localization without stack traces using Ochiai spectrum scores."""
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="billing/calc.py::compute_tax",
        file_path="billing/calc.py",
        language="python",
        kind="function",
        name="compute_tax",
        start_line=5,
        end_line=15,
        code="def compute_tax(subtotal, rate):\n    return subtotal * rate\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    # Function-level spectrum score
    spectrum = {"billing/calc.py::compute_tax": 0.88}
    localizer = AdvancedBugLocalizer(store, embedder, spectrum_scores=spectrum)

    # Natural language query without stack trace
    res = localizer.localize("Tax calculation returns incorrect discount value under high load")
    assert len(res["candidates"]) > 0
    top = res["candidates"][0]
    assert top["file_path"] == "billing/calc.py"
    assert top["ochiai_score"] == 0.88
    assert "Suspected cause (SBFL & Static Reasoning)" in res["root_cause_explanation"]
    assert "Ochiai SBFL spectrum scoring" in top["explanation"]


def test_bug_localizer_direct_coverage_records():
    """Verifies that BugLocalizer automatically calculates spectrum scores from CoverageRecords."""
    from backend.bug_localizer import CoverageRecord
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="data/pipeline.py::transform",
        file_path="data/pipeline.py",
        language="python",
        kind="function",
        name="transform",
        start_line=1,
        end_line=20,
        code="def transform(df):\n    return df.dropna()\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    records = [
        CoverageRecord(element_id="data/pipeline.py", failing_exec_count=3, passing_exec_count=1)
    ]
    # 3 failing, 9 passing -> ef=3, ep=1, nf=3, np=9 -> 3 / sqrt(3 * 4) = 3 / sqrt(12) = 0.866
    localizer = AdvancedBugLocalizer(
        store,
        embedder,
        coverage_records=records,
        total_failing=3,
        total_passing=9,
    )
    assert "data/pipeline.py" in localizer.spectrum_scores
    assert round(localizer.spectrum_scores["data/pipeline.py"], 2) == 0.87

    res = localizer.localize("Data transform drops invalid columns unexpectedly")
    assert res["candidates"][0]["ochiai_score"] == round(localizer.spectrum_scores["data/pipeline.py"], 3)


def test_root_cause_precondition_invariant_diagnosis():
    """Verifies REQ-CORE-14 root cause analysis explains violated preconditions."""
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="api/orders.py::get_order",
        file_path="api/orders.py",
        language="python",
        kind="function",
        name="get_order",
        start_line=10,
        end_line=25,
        code="def get_order(order_id):\n    return orders[order_id]\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    localizer = AdvancedBugLocalizer(store, embedder)
    res = localizer.localize('Traceback (most recent call last):\n  File "api/orders.py", line 12, in get_order\nKeyError: 999')
    assert "Violated invariant: Required mapping key is missing" in res["root_cause_explanation"]
    assert "Reproduced cause (Stack Trace)" in res["root_cause_explanation"]

