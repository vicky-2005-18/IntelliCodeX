"""
Unit and integration tests for Distributed Organizational Memory (REQ-FUT-09).
"""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from core.org_memory import (
    OrgMemoryItem,
    GitHistoryMiner,
    ADRMiner,
    OrgMemoryStore,
)
from backend.main import app
from backend.auth import create_access_token, User


@pytest.fixture
def auth_headers():
    from backend.database import db_manager
    user = User(
        id="usr_admin",
        username="admin",
        email="admin@example.com",
        role="admin",
    )
    if not db_manager.find_one("users", {"id": user.id}):
        db_manager.insert("users", {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "hashed_password": "dummy",
        })
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    return TestClient(app)


def test_org_memory_item_properties():
    item = OrgMemoryItem(
        item_id="commit:abcdef123456",
        memory_type="commit",
        title="Refactor auth to use argon2",
        author="Dev Lead",
        date_str="2026-03-10",
        content="Switched password hashing algorithm from bcrypt to argon2-cffi.",
        files_touched=["backend/auth.py", "requirements.txt"],
    )
    assert item.citation == "[commit:abcdef12]"
    assert "argon2" in item.as_embedding_text()
    d = item.to_dict()
    assert d["title"] == "Refactor auth to use argon2"
    assert d["author"] == "Dev Lead"


def test_adr_miner_parsing():
    with tempfile.TemporaryDirectory() as tmp_dir:
        adr_dir = os.path.join(tmp_dir, "docs", "adr")
        os.makedirs(adr_dir, exist_ok=True)
        adr_path = os.path.join(adr_dir, "0001-use-faiss.md")
        with open(adr_path, "w", encoding="utf-8") as f:
            f.write("""# ADR 1: Use FAISS for Dense Vector Indexing

## Status
Accepted

## Context
We need sub-millisecond local dense vector similarity search without requiring cloud vector databases or massive memory overhead on 4GB VRAM devices.

## Decision
We chose FAISS with IndexFlatIP / IndexIVFFlat direct map for vector indexing, combined with SQLite for chunk metadata storage.

## Consequences
Faster similarity queries and zero cloud dependency; requires local disk persistence for index serialization.
""")

        adrs = ADRMiner.mine_adrs(tmp_dir)
        assert len(adrs) == 1
        adr = adrs[0]
        assert adr.memory_type == "adr"
        assert "FAISS" in adr.title
        assert adr.metadata["status"] == "Accepted"
        assert "[adr:docs/adr/0001-use-faiss.md]" in adr.citation
        assert "sub-millisecond" in adr.content


def test_org_memory_store_search_and_filter():
    store = OrgMemoryStore(repo_id="test_repo")

    adr_item = OrgMemoryItem(
        item_id="adr:docs/adr/0002-jwt.md",
        memory_type="adr",
        title="ADR 2: Stateless JWT Authentication",
        author="Security Architect",
        date_str="2026-02-15",
        content="Adopt PyJWT with RS256/HS256 tokens for stateless session verification across microservices.",
        metadata={"file_path": "docs/adr/0002-jwt.md"},
    )
    commit_item = OrgMemoryItem(
        item_id="commit:1234567890ab",
        memory_type="commit",
        title="fix(billing): handle stripe webhook idempotency",
        author="Billing Engineer",
        date_str="2026-02-20",
        content="Ensure duplicate webhook events do not charge customer accounts twice.",
        files_touched=["services/billing.py"],
    )

    store.add_custom_item(adr_item)
    store.add_custom_item(commit_item)

    # General search
    res = store.search("stateless authentication JWT", top_k=5)
    assert len(res) > 0
    assert res[0][0].memory_type == "adr"
    assert "JWT" in res[0][0].title

    # Type filtered search
    res_commit = store.search("webhook", top_k=5, memory_type_filter="commit")
    assert len(res_commit) == 1
    assert res_commit[0][0].item_id == "commit:1234567890ab"

    # Query with ask()
    ask_res = store.ask("Why did we adopt JWT?")
    assert ask_res["repo_id"] == "test_repo"
    assert len(ask_res["citations"]) > 0
    assert "[adr:docs/adr/0002-jwt.md]" in ask_res["citations"]
    assert "JWT" in ask_res["answer"]


def test_git_history_miner_current_repo():
    # Mine recent commits from current repository
    commits = GitHistoryMiner.mine_commits(".", max_commits=10)
    assert isinstance(commits, list)
    if commits:
        first = commits[0]
        assert first.memory_type == "commit"
        assert first.author != ""
        assert first.date_str != ""
        assert first.title != ""


def test_org_memory_fastapi_endpoints(client, auth_headers):
    from backend.api.repos import ACTIVE_REPOS

    class MockStore:
        chunks = []

    ACTIVE_REPOS["repo_mem_test"] = {
        "repo_id": "repo_mem_test",
        "store": MockStore(),
        "source_files": [],
        "meta": {"repo_path": ".", "user_id": "usr_admin"},
    }

    # 1. Ingest org memory
    res_ingest = client.post("/api/org-memory/repo_mem_test/ingest?max_commits=15", headers=auth_headers)
    assert res_ingest.status_code == 200, res_ingest.text
    ingest_data = res_ingest.json()
    assert ingest_data["status"] == "success"
    assert "commits_count" in ingest_data

    # 2. Query org memory
    query_payload = {
        "question": "What recent commits or architectural decisions were made?",
        "top_k": 3,
    }
    res_q = client.post("/api/org-memory/repo_mem_test/query", json=query_payload, headers=auth_headers)
    assert res_q.status_code == 200, res_q.text
    q_data = res_q.json()
    assert q_data["repo_id"] == "repo_mem_test"
    assert "answer" in q_data
    assert "retrieved_records" in q_data

    # 3. ADRs endpoint
    res_adrs = client.get("/api/org-memory/repo_mem_test/adrs", headers=auth_headers)
    assert res_adrs.status_code == 200
    assert "adrs" in res_adrs.json()

    # 4. Timeline endpoint
    res_timeline = client.get("/api/org-memory/repo_mem_test/timeline?limit=10", headers=auth_headers)
    assert res_timeline.status_code == 200
    t_data = res_timeline.json()
    assert "timeline" in t_data
    assert isinstance(t_data["timeline"], list)
