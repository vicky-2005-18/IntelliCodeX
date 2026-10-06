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
