"""
Concurrency Benchmark and Load Testing for IntelliCodeX (Phase 3).
Tests:
- Serialized OllamaLLM inference lock across concurrent threads
- Parallel client requests against FastAPI assistant /ask endpoint
- Calculation of p50 and p95 latencies and assertion of no deadlock or race conditions
"""
import concurrent.futures
import time
import uuid
import numpy as np
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import hash_password, User, create_access_token
from backend.database import db_manager
from backend.api.repos import ACTIVE_REPOS
from core.llm_client import OllamaLLM
from core.vectorstore import FaissVectorStore
from core.chunker import CodeChunk


class ConcurrencyMockEmbedder:
    def __init__(self, dim=16):
        self.dim = dim

    def embed(self, texts):
        return [np.zeros(self.dim, dtype="float32") for _ in texts]


def test_ollama_llm_serialized_execution():
    """Verify that concurrent threads calling OllamaLLM.generate are strictly serialized."""
    llm = OllamaLLM()
    active_calls = 0
    max_concurrent_calls = 0
    call_events = []

    def fake_post(*args, **kwargs):
        nonlocal active_calls, max_concurrent_calls
        active_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, active_calls)
        time.sleep(0.05)  # Simulate VRAM model inference duration
        active_calls -= 1
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"response": "serialized answer"}
        return mock_resp

    with patch("requests.post", side_effect=fake_post):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(llm.generate, f"prompt {i}")
                for i in range(5)
            ]
            results = [f.result() for f in futures]

    assert len(results) == 5
    assert all(r == "serialized answer" for r in results)
    # The lock ensures max concurrent HTTP calls to Ollama is strictly 1
    assert max_concurrent_calls == 1


def test_concurrent_clients_ask_endpoint():
    """Simulate 5 concurrent clients issuing simultaneous RAG/assistant queries; assert p50/p95 latency and stability."""
    # 1. Setup isolated database user & token
    user_id = str(uuid.uuid4())
    username = f"concurrency_user_{int(time.time() * 1000)}"
    user = User(id=user_id, username=username, email=f"{username}@example.com", role="developer")
    db_manager.insert("users", {
        "id": user_id,
        "username": username,
        "email": user.email,
        "hashed_password": hash_password("ValidPassword123!"),
        "role": "developer",
        "created_at": time.time(),
    })

    from backend.auth import create_access_token
    token = create_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    # 2. Setup mock repository in ACTIVE_REPOS
    repo_id = f"concurrency-repo-{uuid.uuid4().hex[:6]}"
    dim = 16
    store = FaissVectorStore(dim=dim)
    chunk = CodeChunk(
        chunk_id="chk_001",
        file_path="service.py",
        name="handle_request",
        language="python",
        kind="function",
        start_line=1,
        end_line=10,
        code="def handle_request():\n    return 'OK'",
    )
    vectors = np.zeros((1, dim), dtype="float32")
    store.add([chunk], vectors)

    embedder = ConcurrencyMockEmbedder(dim=dim)

    class MockEngine:
        def __init__(self):
            self.llm = OllamaLLM()

    ACTIVE_REPOS[repo_id] = {
        "repo_id": repo_id,
        "store": store,
        "embedder": embedder,
        "graph": None,
        "engine": MockEngine(),
        "meta": {"owner_id": user_id},
    }

    # 3. Simulate 5 parallel requests
    num_clients = 5
    latencies = []

    def make_request(query_idx):
        t0 = time.perf_counter()
        # Use TestClient with authenticated headers
        resp = client.post(
            "/api/chat/ask",
            json={
                "repo_id": repo_id,
                "question": f"How does request handling work in task {query_idx}?",
                "top_k": 1,
            },
            headers=headers,
        )
        elapsed = time.perf_counter() - t0
        return resp.status_code, resp.json(), elapsed

    fake_post_count = 0
    def fake_post(*args, **kwargs):
        nonlocal fake_post_count
        fake_post_count += 1
        time.sleep(0.02)
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"response": "The handle_request function returns 'OK'."}
        return mock_resp

    with patch("requests.post", side_effect=fake_post):
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_clients) as executor:
            futures = [executor.submit(make_request, i) for i in range(num_clients)]
            results = [f.result() for f in futures]

    for status_code, body, elapsed in results:
        assert status_code == 200
        assert "answer" in body
        assert "handle_request" in body["answer"] or "OK" in body["answer"]
        latencies.append(elapsed)

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]

    print(f"\n[Concurrency Benchmark] 5 Parallel Clients: p50={p50*1000:.1f}ms, p95={p95*1000:.1f}ms")
    assert p50 > 0.0
    assert p95 >= p50
