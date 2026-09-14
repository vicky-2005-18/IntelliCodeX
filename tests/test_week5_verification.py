"""
Week 5 Comprehensive Milestone Verification Suite
Tests ConversationMemory multi-turn dialogue tracking, System Persona selector,
dynamic token budgeting, token streaming generator, and model switching engine.
"""
import pytest
from unittest.mock import MagicMock
from rag.query_engine import (
    ConversationMemory,
    QueryEngine,
    PERSONAS,
    format_context,
)
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.chunker import CodeChunk
from core.llm_client import OllamaLLM


def test_week5_conversation_memory():
    """1. Verifies multi-turn dialogue memory retention, max turn truncation, and formatting."""
    memory = ConversationMemory(max_turns=3)
    assert len(memory) == 0

    memory.add_turn("How does auth work?", "Authentication is handled in auth.py.")
    memory.add_turn("Where is login defined?", "login() is defined at auth.py:10.")
    assert len(memory) == 2

    formatted = memory.format_history()
    assert "Turn 1 User: How does auth work?" in formatted
    assert "Turn 2 User: Where is login defined?" in formatted

    # Max turn sliding window truncation
    memory.add_turn("Turn 3 query", "Turn 3 ans")
    memory.add_turn("Turn 4 query", "Turn 4 ans")
    assert len(memory) == 3
    assert "How does auth work?" not in memory.format_history()
    assert "Turn 4 query" in memory.format_history()


    memory.clear()
    assert len(memory) == 0


def test_week5_system_personas():
    """2. Verifies System Persona selector and custom system prompt setting."""
    embedder = TfidfEmbedder(dim=8)
    store = FaissVectorStore(dim=8)
    engine = QueryEngine(store, embedder)

    assert engine.active_persona == "general"
    assert "IntelliCodeX" in engine.system_prompt

    engine.set_persona("security")
    assert engine.active_persona == "security"
    assert "Security Auditor" in engine.system_prompt

    engine.set_persona("reviewer")
    assert engine.active_persona == "reviewer"
    assert "Code Reviewer" in engine.system_prompt

    with pytest.raises(ValueError):
        engine.set_persona("unknown_persona_xyz")


def test_week5_token_budgeting():
    """3. Verifies dynamic token budgeting in format_context."""
    c1 = CodeChunk(
        chunk_id="f1.py::func1",
        file_path="f1.py",
        language="python",
        kind="function",
        name="func1",
        start_line=1,
        end_line=50,
        code="def func1():\n" + ("    x = 1\n" * 100)
    )
    c2 = CodeChunk(
        chunk_id="f2.py::func2",
        file_path="f2.py",
        language="python",
        kind="function",
        name="func2",
        start_line=1,
        end_line=50,
        code="def func2():\n" + ("    y = 2\n" * 100)
    )

    results = [(c1, 0.9), (c2, 0.8)]
    # Small token budget should truncate context
    formatted_budgeted = format_context(results, max_token_budget=50)
    assert "truncated due to token budget" in formatted_budgeted


def test_week5_streaming_and_multi_turn_ask():
    """4. Verifies streaming token generator and multi-turn ask history integration."""
    embedder = TfidfEmbedder(dim=8)
    chunk = CodeChunk(
        chunk_id="db.py::connect",
        file_path="db.py",
        language="python",
        kind="function",
        name="connect",
        start_line=1,
        end_line=5,
        code="def connect(): pass\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    mock_llm = MagicMock()
    mock_llm.generate.return_value = "Connected to DB successfully."
    mock_llm.stream_generate.return_value = iter(["Connected ", "to ", "DB ", "successfully."])

    engine = QueryEngine(store, embedder, llm=mock_llm)

    # 1. Ask turn 1
    resp1 = engine.ask("How to connect?")
    assert resp1["answer"] == "Connected to DB successfully."
    assert len(engine.memory) == 1

    # 2. Stream ask turn 2
    tokens = list(engine.stream_ask("What parameters does it take?"))
    assert "".join(tokens) == "Connected to DB successfully."
    assert len(engine.memory) == 2

    # Verify conversation history was passed to mock_llm.generate
    call_args = mock_llm.stream_generate.call_args[0][0]
    assert "Turn 1 User: How to connect?" in call_args


def test_week5_model_switching():
    """5. Verifies dynamic model switching on OllamaLLM and QueryEngine."""
    llm = OllamaLLM(model="qwen2.5-coder")
    assert llm.model == "qwen2.5-coder"

    llm.set_model("llama3.2")
    assert llm.model == "llama3.2"

    embedder = TfidfEmbedder(dim=8)
    store = FaissVectorStore(dim=8)
    engine = QueryEngine(store, embedder, llm=llm)

    engine.set_model("codellama:13b")
    assert llm.model == "codellama:13b"
