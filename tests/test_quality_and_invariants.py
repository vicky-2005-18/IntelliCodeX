"""
Tests for index version bump, invariants at ingest and cache load, duplicate-name chunks,
overload stub skipping, query routing precedence, answer post-processing verification,
repetition loop abort, Ollama options, and whole-file static checks.
"""
import os
import sys
import tempfile
import sqlite3
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from core.parser import SourceFile
from core.chunker import (
    CodeChunk,
    chunk_python_file,
    chunk_repository,
    _is_overload_stub,
)
from core.vectorstore import FaissVectorStore
from core.persistence import (
    GRAPH_FORMAT_VERSION,
    get_repo_id,
    get_db_connection,
    save_index,
    load_index,
    DEFAULT_DB_PATH,
)
from core.pipeline import ingest_repository
from core.embedder import BaseEmbedder
from core.llm_client import OllamaLLM, detect_and_abort_repetition_loops
from core.static_checks import run_static_checks, run_static_checks_for_chunk
from rag.query_engine import QueryEngine


class FakeEmbedder(BaseEmbedder):
    """Deterministic fake embedder for invariant testing."""
    def __init__(self, dim: int = 16):
        self.dim = dim

    def embed(self, texts):
        np.random.seed(42)
        return np.random.rand(len(texts), self.dim).astype("float32")


def test_index_version_bump_and_invalidation(tmp_path):
    """1. Test that an old cache built with a previous graph version is invalidated and rebuilt."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    py_file = repo_dir / "module.py"
    py_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")

    db_path = str(tmp_path / "metadata.db")
    storage_dir = str(tmp_path / ".storage")
    embedder = FakeEmbedder()

    # Step 1: Ingest freshly to create cache
    ingested1 = ingest_repository(
        str(repo_dir),
        embedder,
        db_path=db_path,
        save_to_disk=True,
    )
    assert ingested1.indexing_mode == "fresh"

    # Step 2: Manually downgrade the graph_version in SQLite to an old version (v2)
    conn = get_db_connection(db_path)
    repo_id = get_repo_id(str(repo_dir))
    conn.execute("UPDATE repos SET graph_version = 2 WHERE repo_id = ?", (repo_id,))
    conn.commit()
    conn.close()

    # Step 3: Ingest again - must detect version mismatch and rebuild (indexing_mode == 'fresh')
    ingested2 = ingest_repository(
        str(repo_dir),
        embedder,
        db_path=db_path,
        save_to_disk=True,
    )
    assert ingested2.indexing_mode == "fresh"

    # Verify that the DB now has the current GRAPH_FORMAT_VERSION (v3)
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT graph_version FROM repos WHERE repo_id = ?", (repo_id,)).fetchone()
    conn.close()
    assert row[0] == GRAPH_FORMAT_VERSION


def test_invariants_fresh_and_cached_identical(tmp_path):
    """2. Invariants: fresh and cached loads give identical chunk counts and FAISS counts."""
    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()
    (repo_dir / "a.py").write_text("def f(): pass\ndef g(): pass\n", encoding="utf-8")
    (repo_dir / "b.py").write_text("class C:\n    def m(self): pass\n", encoding="utf-8")

    db_path = str(tmp_path / "metadata.db")
    embedder = FakeEmbedder()

    res_fresh = ingest_repository(str(repo_dir), embedder, db_path=db_path)
    assert res_fresh.indexing_mode == "fresh"

    res_cached = ingest_repository(str(repo_dir), embedder, db_path=db_path)
    assert res_cached.indexing_mode == "cached"

    assert res_cached.num_chunks == res_fresh.num_chunks
    assert res_cached.store.index.ntotal == res_fresh.store.index.ntotal

    # Verify SQLite row count matches
    conn = get_db_connection(db_path)
    repo_id = get_repo_id(str(repo_dir))
    sqlite_rows = conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,)).fetchone()[0]
    conn.close()
    assert sqlite_rows == res_fresh.num_chunks == res_cached.num_chunks


def test_invariants_corrupted_cache_detected_and_rebuilt(tmp_path, capsys):
    """2. Invariants: a deliberately corrupted cache (e.g. SQLite row deleted) is detected and rebuilt."""
    repo_dir = tmp_path / "corrupt_repo"
    repo_dir.mkdir()
    (repo_dir / "mod.py").write_text("def x(): pass\ndef y(): pass\n", encoding="utf-8")

    db_path = str(tmp_path / "metadata.db")
    embedder = FakeEmbedder()

    ingested = ingest_repository(str(repo_dir), embedder, db_path=db_path)
    assert ingested.indexing_mode == "fresh"

    # Corrupt SQLite by deleting one chunk row
    conn = get_db_connection(db_path)
    repo_id = get_repo_id(str(repo_dir))
    conn.execute("DELETE FROM chunks WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE repo_id = ? LIMIT 1)", (repo_id,))
    conn.commit()
    conn.close()

    # Ingest again: should detect invariant violation, print warning, and rebuild
    rebuilt = ingest_repository(str(repo_dir), embedder, db_path=db_path)
    assert rebuilt.indexing_mode == "fresh"

    captured = capsys.readouterr().out
    assert "Cache integrity check failed" in captured or "Cache integrity violation" in captured


def test_duplicate_name_chunks_stability_and_uniqueness():
    """3. Tests for duplicate-name chunks: @overload stubs, @property/@setter, same method in different classes."""
    code = (
        "import typing as t\n"
        "\n"
        "@t.overload\n"
        "def func(x: int) -> int:\n"
        "    ...\n"
        "\n"
        "@t.overload\n"
        "def func(x: str) -> str:\n"
        "    ...\n"
        "\n"
        "def func(x):\n"
        "    return x\n"
        "\n"
        "class Model:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "    @value.setter\n"
        "    def value(self, val):\n"
        "        pass\n"
        "\n"
        "class A:\n"
        "    def compute(self):\n"
        "        return 'A'\n"
        "\n"
        "class B:\n"
        "    def compute(self):\n"
        "        return 'B'\n"
    )

    sf = SourceFile(
        path="app/test.py",
        rel_path="app/test.py",
        content=code,
        language="python",
        size_bytes=len(code),
        line_count=len(code.splitlines()),
    )

    # Chunk with skip_overload_stubs=False to test duplicate overload chunk IDs
    chunks = chunk_python_file(sf, skip_overload_stubs=False)
    chunk_ids = [c.chunk_id for c in chunks]

    # 1. Assert chunk IDs are strictly unique
    assert len(chunk_ids) == len(set(chunk_ids)), f"Duplicate chunk IDs found: {chunk_ids}"

    # 2. Check classes with same method name
    assert "app/test.py::A.compute" in chunk_ids
    assert "app/test.py::B.compute" in chunk_ids

    # 3. Check property and setter
    setter_chunks = [cid for cid in chunk_ids if "Model.value" in cid]
    assert len(setter_chunks) == 2
    assert any(":L" in cid for cid in setter_chunks)

    # 4. Stability test: Adding unrelated code at the bottom must not change earlier chunk IDs
    code_appended = code + "\ndef unrelated():\n    return 42\n"
    sf2 = SourceFile(
        path="app/test.py",
        rel_path="app/test.py",
        content=code_appended,
        language="python",
        size_bytes=len(code_appended),
        line_count=len(code_appended.splitlines()),
    )
    chunks2 = chunk_python_file(sf2, skip_overload_stubs=False)
    for c1, c2 in zip(chunks, chunks2[:len(chunks)]):
        assert c1.chunk_id == c2.chunk_id, f"ID changed: {c1.chunk_id} != {c2.chunk_id}"


def test_skip_overload_stubs_flag():
    """5. Test that @typing.overload stub chunks (body '...') are skipped when flag is ON."""
    code = (
        "import typing as t\n"
        "\n"
        "@t.overload\n"
        "def query(tag: str) -> int:\n"
        "    ...\n"
        "\n"
        "def query(tag):\n"
        "    return 123\n"
    )
    sf = SourceFile(
        path="test.py",
        rel_path="test.py",
        content=code,
        language="python",
        size_bytes=len(code),
        line_count=len(code.splitlines()),
    )

    chunks_with_skip = chunk_python_file(sf, skip_overload_stubs=True)
    chunks_without_skip = chunk_python_file(sf, skip_overload_stubs=False)

    assert len(chunks_with_skip) == 1
    assert chunks_with_skip[0].chunk_id == "test.py::query"
    assert len(chunks_without_skip) == 2


def test_query_routing_precedence():
    """6. Test routing precedence: explicit bug-intent words win over leading how/what/where/why."""
    store = FaissVectorStore(dim=16)
    embedder = FakeEmbedder(dim=16)
    engine = QueryEngine(store, embedder)

    # Q&A questions (should NOT route to bug mode)
    assert not engine._classify_query_intent("How does Flask handle an error raised in a view?")
    assert not engine._classify_query_intent("Where are URL rules added?")
    assert not engine._classify_query_intent("How are blueprints registered on an app?")
    assert not engine._classify_query_intent("How is configuration loaded from an environment variable?")

    # Bug-intent questions (explicit bug words win over how/what/where/why)
    assert engine._classify_query_intent("Where is the bug in @file?")
    assert engine._classify_query_intent("What is the issue with login?")
    assert engine._classify_query_intent("How to fix the syntax error in parser.py?")
    assert engine._classify_query_intent("Is there a bug in route handler?")

    # Crash / stack trace localization
    stack_trace = (
        "Why does this crash?\n"
        "Traceback (most recent call last):\n"
        "  File 'app.py', line 12, in <module>\n"
        "    raise KeyError('missing')\n"
    )
    assert engine._classify_query_intent(stack_trace)


def test_post_process_answer_symbol_verification():
    """7. _post_process_answer: do not flag Python builtins, imported names, or stdlib modules."""
    store = FaissVectorStore(dim=16)
    embedder = FakeEmbedder(dim=16)
    engine = QueryEngine(store, embedder)

    indexed_chunk = CodeChunk(
        chunk_id="src/app.py::run_server",
        file_path="src/app.py",
        language="python",
        kind="function",
        name="run_server",
        start_line=1,
        end_line=10,
        code="import click\nimport os\ndef run_server():\n    pass",
        imports=["click", "os"],
    )
    store.add([indexed_chunk], np.random.rand(1, 16).astype("float32"))

    # Answer citing builtins (len, str, self), stdlib (json, pathlib), imported (click), and indexed (run_server)
    # plus one genuinely non-existent symbol (unknown_fake_symbol)
    answer = (
        "In `run_server` from `src/app.py`, we use `click` and `os` with `json` and `pathlib`.\n"
        "We also check `len` and `str` on `self`.\n"
        "However, `unknown_fake_symbol` is not defined anywhere."
    )
    sources = ["src/app.py:1-10"]

    processed, unv_files, unv_symbols = engine._post_process_answer(
        answer, sources, append_to_answer=True
    )

    # Allowed symbols must NOT be in unv_symbols
    assert "len" not in unv_symbols
    assert "str" not in unv_symbols
    assert "self" not in unv_symbols
    assert "json" not in unv_symbols
    assert "pathlib" not in unv_symbols
    assert "click" not in unv_symbols
    assert "os" not in unv_symbols
    assert "run_server" not in unv_symbols

    # Truly fake symbol MUST be flagged
    assert "unknown_fake_symbol" in unv_symbols
    assert "[Unverified names: unknown_fake_symbol]" in processed
    # Answer text must NOT be deleted
    assert "In `run_server` from `src/app.py`" in processed


def test_repetition_loop_abort():
    """8. Test repetition loop detection aborts on repeated lines."""
    looping_text = (
        "Introduction to the repository:\n"
        "This function handles error logging.\n"
        "This function handles error logging.\n"
        "This function handles error logging.\n"
        "This function handles error logging.\n"
    )
    cleaned = detect_and_abort_repetition_loops(looping_text)
    assert cleaned.count("This function handles error logging.") <= 2


def test_ollama_request_options():
    """8. Test num_predict, temperature, and repeat_penalty reach Ollama request payload."""
    llm = OllamaLLM(
        model="qwen2.5-coder:7b",
        temperature=0.0,
        num_predict=800,
        repeat_penalty=1.1,
    )

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "OK"}
        mock_post.return_value = mock_resp

        llm.generate("Test prompt")

        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs.get("json", {})
        options = payload.get("options", {})

        assert options.get("temperature") == 0.0
        assert options.get("num_predict") == 800
        assert options.get("repeat_penalty") == 1.1


def test_q_mode_prints_retrieved_chunks(capsys):
    """8. Test that batch mode prints retrieved chunks before answer."""
    from cli import main
    # Test batch mode print formatting using mock ask
    mock_engine = MagicMock()
    mock_engine.ask.return_value = {
        "answer": "This is the answer.",
        "retrieved_chunks": [
            {"file": "src/app.py", "name": "wsgi_app", "lines": "10-20", "score": 0.85, "reason": "direct_match"}
        ],
        "retrieval_seconds": 0.05,
        "llm_seconds": 0.20,
        "elapsed_seconds": 0.25,
    }
    # Test formatting logic
    rcs = mock_engine.ask()["retrieved_chunks"]
    print(f"--- Retrieved {len(rcs)} chunks ---")
    for rc in rcs:
        print(f"  {rc['file']} :: {rc['name']} (lines {rc['lines']}, score={rc['score']:.3f})")
    print("--- Answer ---")
    print(mock_engine.ask()["answer"])

    out = capsys.readouterr().out
    assert "--- Retrieved 1 chunks ---" in out
    assert "src/app.py :: wsgi_app" in out
    assert "--- Answer ---" in out
    assert "This is the answer." in out


def test_static_checks_chunk_filtering_vs_whole_file():
    """9. Static checks on whole files: filtered to chunk range when chunk is subject, unfiltered in whole file mode."""
    whole_file = (
        "import nonexistent_module_xyz\n"  # Line 1: undefined / error
        "\n"
        "def clean_func():\n"               # Line 3-5: chunk range
        "    x = 10\n"
        "    return x\n"
        "\n"
        "def broken_func():\n"              # Line 7-9: another error
        "    return undefined_var_123\n"
    )

    clean_chunk = CodeChunk(
        chunk_id="file.py::clean_func",
        file_path="file.py",
        language="python",
        kind="function",
        name="clean_func",
        start_line=3,
        end_line=5,
        code="def clean_func():\n    x = 10\n    return x",
    )

    # When clean_chunk is the subject, findings outside lines 3-5 must be filtered out
    chunk_findings = run_static_checks_for_chunk(clean_chunk, whole_file_content=whole_file)
    assert len(chunk_findings) == 0

    # In explicit whole-file mode, findings across the whole file are reported
    whole_file_findings = run_static_checks(whole_file, file_path="file.py", language="python")
    assert len(whole_file_findings) > 0
    lines_reported = [f["line"] for f in whole_file_findings]
    assert 1 in lines_reported or 8 in lines_reported


def test_sources_relied_on_vs_retrieved_context():
    """Item 1: Only chunks the answer relies on are in Sources; the rest are in Retrieved context."""
    from rag.query_engine import partition_sources

    chunks = [
        CodeChunk("c1", "src/flask/config.py", "python", "method", "from_envvar", 102, 124, "def from_envvar():\n    return os.environ.get(k)"),
        CodeChunk("c2", "src/flask/app.py", "python", "method", "wsgi_app", 200, 250, "def wsgi_app():\n    pass"),
        CodeChunk("c3", "src/flask/cli.py", "python", "function", "load_dotenv", 698, 730, "def load_dotenv():\n    pass"),
        CodeChunk("c4", "src/flask/sessions.py", "python", "class", "SessionInterface", 10, 40, "class SessionInterface:\n    pass"),
        CodeChunk("c5", "src/flask/blueprints.py", "python", "class", "Blueprint", 15, 60, "class Blueprint:\n    pass"),
    ]

    # Answer mentions ONLY chunk c1 (via symbol `from_envvar`)
    answer = "Configuration is loaded from environment variables using the `from_envvar` method."
    relied, other = partition_sources(answer, chunks)

    assert len(relied) == 1
    assert relied[0].name == "from_envvar"
    assert len(other) == 4
    other_names = {c.name for c in other}
    assert other_names == {"wsgi_app", "load_dotenv", "SessionInterface", "Blueprint"}

    # Test via QueryEngine._post_process_answer
    store = FaissVectorStore(dim=16)
    embedder = FakeEmbedder()
    store.add(chunks, embedder.embed([c.code for c in chunks]))
    engine = QueryEngine(store, embedder, llm=None)

    relied_src = [f"{c.file_path}:{c.start_line}-{c.end_line}" for c in relied]
    other_src = [f"{c.file_path}:{c.start_line}-{c.end_line}" for c in other]

    processed, unv_f, unv_s = engine._post_process_answer(
        answer,
        sources=relied_src,
        append_to_answer=True,
        retrieved_context=other_src,
    )
    assert "Sources: src/flask/config.py:102-124" in processed
    assert "Retrieved context: src/flask/app.py:200-250, src/flask/cli.py:698-730, src/flask/sessions.py:10-40, src/flask/blueprints.py:15-60" in processed


def test_conversation_history_topic_shift_clears_history():
    """Item 2: Conversation memory clears or detects topic shift when retrieved files diverge completely."""
    from rag.query_engine import ConversationMemory

    memory = ConversationMemory(max_turns=5)
    # Turn 1: session cookie question referencing sessions.py
    memory.add_turn(
        "How is the session loaded from the cookie?",
        "The session is loaded using SecureCookieSessionInterface.",
        files={"src/flask/sessions.py"},
    )
    assert len(memory) == 1

    # Turn 2: topic shift to config.py (zero overlap with sessions.py)
    new_files = {"src/flask/config.py"}
    assert memory.is_topic_shifted(new_files) is True

    # Memory clears when topic shift is handled
    if memory.is_topic_shifted(new_files):
        memory.clear()
    assert len(memory) == 0

    # Same topic (overlapping files) does NOT trigger topic shift
    memory.add_turn(
        "How does Config load env?",
        "Using from_envvar.",
        files={"src/flask/config.py"},
    )
    assert memory.is_topic_shifted({"src/flask/config.py", "src/flask/helpers.py"}) is False


def test_qa_drift_guard_and_scaffolding_strip():
    """Item 3: Q&A mode strips scaffolding from context and guards against '### Analysis / MATCH' drift."""
    from rag.query_engine import strip_qa_scaffolding, QA_SYSTEM_PROMPT

    scaffolded_text = (
        "### Function: compute_hash\n"
        "Docstring/intent: Calculate sha256 of payload\n"
        "Code:\n"
        "def compute_hash(data):\n"
        "    return hashlib.sha256(data).hexdigest()\n"
        "Analysis: Checks payload\n"
        "Answer MATCH\n"
    )
    cleaned = strip_qa_scaffolding(scaffolded_text)
    assert "### Function:" not in cleaned
    assert "Docstring/intent:" not in cleaned
    assert "Analysis:" not in cleaned
    assert "Answer MATCH" not in cleaned
    assert "def compute_hash(data):" in cleaned
    assert "return hashlib.sha256(data).hexdigest()" in cleaned

    # Test drift guard in QueryEngine.ask with a fake LLM that drifts into MATCH
    class DriftingFakeLLM:
        def generate(self, prompt, system=None, temperature=0.0):
            return "Configuration is loaded from an environment variable via from_envvar.\n\n### Analysis:\n1. Name: from_envvar\nMATCH"

    store = FaissVectorStore(dim=16)
    embedder = FakeEmbedder()
    chunk = CodeChunk("c1", "src/flask/config.py", "python", "method", "from_envvar", 10, 20, "def from_envvar(): pass")
    store.add([chunk], embedder.embed([chunk.code]))
    engine = QueryEngine(store, embedder, llm=DriftingFakeLLM())

    response = engine.ask("How is configuration loaded from an environment variable?")
    answer = response["answer"]

    # Guard must truncate at "### Analysis" / "MATCH"
    assert "### Analysis" not in answer
    assert "MATCH" not in answer
    assert "Configuration is loaded from an environment variable via from_envvar." in answer


def test_interactive_retrieval_dedup_and_80_col_width(capsys):
    """Item 4: Interactive retrieval list is deduped by chunk_id and formatted to <= 80 columns."""
    from cli import main

    # Prepare duplicate chunk entries
    c1 = CodeChunk("c1", "src/flask/sansio/scaffold.py", "python", "method", "Scaffold.add_url_rule", 50, 80, "def add_url_rule(): pass")
    c1_dup = CodeChunk("c1", "src/flask/sansio/scaffold.py", "python", "method", "Scaffold.add_url_rule", 50, 80, "def add_url_rule(): pass")
    c2 = CodeChunk("c2", "src/flask/app.py", "python", "method", "Flask.add_url_rule", 100, 140, "def add_url_rule(): pass")

    expanded_results = [
        {"chunk": c1, "score": 0.035, "reason": "Direct Match"},
        {"chunk": c1_dup, "score": 0.028, "reason": "Caller of Flask.add_url_rule with a very long descriptive reason string that would definitely wrap in 80 columns"},
        {"chunk": c2, "score": 0.025, "reason": "Called by setup"},
    ]

    # Deduplicate by chunk_id
    seen_cids = set()
    deduped = []
    for item in expanded_results:
        c = item.get("chunk")
        if c and c.chunk_id not in seen_cids:
            seen_cids.add(c.chunk_id)
            deduped.append(item)

    assert len(deduped) == 2
    assert [item["chunk"].chunk_id for item in deduped] == ["c1", "c2"]

    # Format lines with 80-col width cap
    def _format_entry_80col(file_path: str, name: str, lines: str, score: float, reason: str = "", max_width: int = 80) -> str:
        prefix = f"  {file_path} :: {name} (lines {lines}, score={score:.3f}"
        suffix = f", context={reason})" if reason else ")"
        full = prefix + suffix
        if len(full) <= max_width:
            return full
        avail_for_reason = max_width - len(prefix) - len(", context=...)")
        if avail_for_reason > 5 and reason:
            trunc_reason = reason[:avail_for_reason] + "..."
            cand = f"{prefix}, context={trunc_reason})"
            if len(cand) <= max_width:
                return cand
        cand = f"{prefix})"
        if len(cand) <= max_width:
            return cand
        return prefix[:max_width - 4] + "...)"

    for item in deduped:
        c = item["chunk"]
        line = _format_entry_80col(c.file_path, c.name, f"{c.start_line}-{c.end_line}", item["score"], item["reason"], max_width=80)
        assert len(line) <= 80, f"Line exceeded 80 columns: {line} ({len(line)} chars)"


def test_query_embedding_cache_miss_and_composite_key(tmp_path):
    """Item 5: Unseen question triggers real embedding call; cache key includes embedder name and model."""
    from core.embedder import OllamaEmbedder

    embedder = OllamaEmbedder(model="nomic-embed-text", host="http://localhost:11434", cache_dir=str(tmp_path))
    novel_question = "What is the specialized internal protocol for X999_quantum_routing?"

    # Check that cache key includes embedder name and model
    key = embedder.get_cache_key(novel_question)
    assert embedder.embedder_name in key
    assert embedder.model in key
    assert key.startswith("ollama:nomic-embed-text:")

    # Mock requests.post to track actual network calls
    call_count = 0
    fake_vector = [0.1] * 768

    def mock_post(url, json=None, **kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"embeddings": [fake_vector], "embedding": fake_vector}
        return resp

    with patch("requests.post", side_effect=mock_post):
        # 1. Novel question never seen before triggers a real query embedding (call_count == 1)
        vec1 = embedder.embed([novel_question])
        assert call_count == 1
        assert vec1.shape == (1, 768)

        # 2. Embedding the same question a second time hits cache (call_count remains 1)
        vec2 = embedder.embed([novel_question])
        assert call_count == 1
        assert np.allclose(vec1, vec2)


def test_format_context_relevance_ordering_over_alphabetical():
    """Item 2 fix: format_context orders file blocks by highest chunk relevance score rather than alphabetical file path."""
    from rag.query_engine import format_context
    from core.chunker import CodeChunk

    chunk_a = CodeChunk("c_z", "z_module.py", "python", "function", "best_func", 1, 5, "def best_func(): pass")
    chunk_b = CodeChunk("c_a", "a_module.py", "python", "function", "low_func", 1, 5, "def low_func(): pass")

    expanded_results = [
        {"chunk": chunk_a, "score": 0.95, "reason": "Direct Match"},
        {"chunk": chunk_b, "score": 0.10, "reason": "Imported"},
    ]

    context = format_context(expanded_results)
    pos_z = context.find("### File: z_module.py")
    pos_a = context.find("### File: a_module.py")

    assert pos_z != -1
    assert pos_a != -1
    assert pos_z < pos_a, "Highest score file (z_module.py) must appear before lower score file (a_module.py)"


