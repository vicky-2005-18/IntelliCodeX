import os
import threading
import time
from unittest.mock import MagicMock
import pytest

from core.cli.state import CLISessionState
from core.cli import CLISessionState as ExportedCLISessionState


def test_session_state_export():
    assert CLISessionState is ExportedCLISessionState



def test_session_state_initialization():
    mock_embedder = MagicMock()
    mock_engine = MagicMock()
    mock_engine.memory = MagicMock()
    mock_engine.hybrid_search = True

    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo_abc12345",
        backend="tfidf",
        model_name="qwen2.5-coder:3b",
        embedder=mock_embedder,
        llm=None,
        engine=mock_engine,
    )

    assert state.repo_path == "sample_repo"
    assert state.repo_id == "sample_repo_abc12345"
    assert state.backend == "tfidf"
    assert state.model_name == "qwen2.5-coder:3b"
    assert state.embedder is mock_embedder
    assert state.llm is None
    assert state.engine is mock_engine
    assert state.watcher is None
    assert state.active_file_filter is None
    assert state.persona == "general"
    # Should inherit engine memory if not explicitly provided
    assert state.memory is mock_engine.memory


def test_session_state_initialization_defaults_and_repo_id_fallback():
    # If repo_id is empty/None, CLISessionState should resolve it
    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=None,
    )
    assert state.repo_id != ""
    assert "sample_repo" in state.repo_id
    assert state.persona == "general"
    assert state.memory is None


def test_session_state_switch_file_filter():
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "model", None, None, None)
    
    state.set_file_filter("auth.py")
    assert state.active_file_filter == "auth.py"

    state.set_file_filter("   ")
    assert state.active_file_filter is None

    state.set_file_filter("core/pipeline.py")
    assert state.active_file_filter == "core/pipeline.py"

    state.set_file_filter(None)
    assert state.active_file_filter is None


def test_session_state_switch_model():
    mock_llm = MagicMock()
    state = CLISessionState("sample_repo", "sample_repo", "ollama", "qwen2.5-coder:3b", None, mock_llm, None)

    state.switch_model("qwen2.5-coder:7b")
    assert state.model_name == "qwen2.5-coder:7b"
    mock_llm.set_model.assert_called_once_with("qwen2.5-coder:7b")

    # LLM without set_model but with model attribute
    class SimpleLLM:
        def __init__(self):
            self.model = "old"

    simple_llm = SimpleLLM()
    state.llm = simple_llm
    state.switch_model("deepseek-coder:6.7b")
    assert state.model_name == "deepseek-coder:6.7b"
    assert simple_llm.model == "deepseek-coder:6.7b"

    # LLM is None
    state.llm = None
    state.switch_model("llama3:8b")
    assert state.model_name == "llama3:8b"


def test_session_state_switch_backend():
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "none", None, None, None)
    assert state.backend == "tfidf"

    state.switch_backend("ollama")
    assert state.backend == "ollama"

    state.switch_backend("tfidf")
    assert state.backend == "tfidf"


def test_session_state_switch_persona():
    mock_engine = MagicMock()
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "none", None, None, mock_engine)
    assert state.persona == "general"

    state.set_persona("security")
    assert state.persona == "security"
    mock_engine.set_persona.assert_called_once_with("security")

    # When engine is None
    state.engine = None
    state.set_persona("refactor")
    assert state.persona == "refactor"


def test_session_state_switch_repo():
    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True

    state = CLISessionState(
        "old_repo",
        "old_repo_id",
        "tfidf",
        "none",
        None,
        None,
        None,
        watcher=mock_watcher,
        active_file_filter="auth.py",
    )

    state.switch_repo("new_repo", "new_repo_id")
    assert state.repo_path == "new_repo"
    assert state.repo_id == "new_repo_id"
    assert state.active_file_filter is None
    # Previous watcher must be stopped and cleared
    mock_watcher.stop.assert_called_once()
    assert state.watcher is None

    # Switch repo without explicit repo_id
    state.switch_repo("sample_repo")
    assert state.repo_path == "sample_repo"
    assert "sample_repo" in state.repo_id


def test_session_state_get_summary():
    mock_engine = MagicMock()
    mock_engine.hybrid_search = True
    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True

    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo_123",
        backend="ollama",
        model_name="qwen2.5-coder:3b",
        embedder=MagicMock(),
        llm=MagicMock(),
        engine=mock_engine,
        watcher=mock_watcher,
        active_file_filter="main.py",
        persona="review",
    )

    summary = state.get_summary()
    assert summary["repo_path"] == "sample_repo"
    assert summary["repo_id"] == "sample_repo_123"
    assert summary["backend"] == "ollama"
    assert summary["model_name"] == "qwen2.5-coder:3b"
    assert summary["active_file_filter"] == "main.py"
    assert summary["persona"] == "review"
    assert summary["watcher_active"] is True
    assert summary["hybrid_search"] is True
    assert summary["has_llm"] is True
    assert summary["has_embedder"] is True
    assert summary["has_engine"] is True


def test_session_state_set_watcher():
    old_watcher = MagicMock()
    new_watcher = MagicMock()

    state = CLISessionState("repo", "repo_id", "tfidf", "none", None, None, None, watcher=old_watcher)
    assert state.watcher is old_watcher

    state.set_watcher(new_watcher)
    old_watcher.stop.assert_called_once()
    assert state.watcher is new_watcher

    state.set_watcher(None)
    new_watcher.stop.assert_called_once()
    assert state.watcher is None


def test_session_state_thread_safety():
    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo_id",
        backend="tfidf",
        model_name="qwen2.5-coder:3b",
        embedder=MagicMock(),
        llm=MagicMock(),
        engine=MagicMock(),
    )

    errors = []

    def worker_mutator(worker_id: int):
        for i in range(100):
            try:
                state.switch_model(f"model-{worker_id}-{i}")
                state.set_persona(f"persona-{worker_id}")
                state.set_file_filter(f"file_{worker_id}_{i}.py")
                summary = state.get_summary()
                assert summary["model_name"].startswith(f"model-")
            except Exception as e:
                errors.append(e)

    def worker_reader():
        for _ in range(100):
            try:
                with state.lock:
                    s = state.get_summary()
                    assert "repo_path" in s
                time.sleep(0.0001)
            except Exception as e:
                errors.append(e)

    threads = [
        threading.Thread(target=worker_mutator, args=(1,)),
        threading.Thread(target=worker_mutator, args=(2,)),
        threading.Thread(target=worker_reader),
        threading.Thread(target=worker_reader),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Encountered thread safety errors: {errors}"
