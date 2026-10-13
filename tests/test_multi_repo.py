"""
Unit and integration tests for Multi-Repository Reasoning & Namespaced Indexing (REQ-FUT-08).
"""
import pytest
from fastapi.testclient import TestClient

from core.chunker import CodeChunk
from core.parser import SourceFile
from core.multi_repo import NamespacedChunk, CrossRepoContract, MultiRepoWorkspace
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


def test_namespaced_chunk_properties():
    base_chunk = CodeChunk(
        chunk_id="chunk-abc",
        file_path="services/auth.py",
        language="python",
        kind="function",
        name="login_handler",
        code="def login_handler(): pass",
        start_line=10,
        end_line=20,
    )
    ns = NamespacedChunk(repo_id="auth_service", chunk=base_chunk)
    assert ns.namespaced_id == "auth_service::chunk-abc"
    assert ns.file_path == "services/auth.py"
    assert ns.name == "login_handler"
    assert ns.code == "def login_handler(): pass"
    assert ns.start_line == 10
    assert ns.end_line == 20


def test_multi_repo_workspace_aggregation_and_namespacing():
    workspace = MultiRepoWorkspace(workspace_id="test-ws")

    sf_repo1 = SourceFile(
        path="/repos/repo1/auth.py",
        rel_path="auth.py",
        language="python",
        content="""
@router.post('/api/v1/auth/login')
def login():
    return {'status': 'ok'}
""",
    )

    sf_repo2 = SourceFile(
        path="/repos/repo2/client.py",
        rel_path="client.py",
        language="python",
        content="""
import requests

def call_auth():
    resp = requests.post('https://gateway.internal/api/v1/auth/login', json={})
    return resp.json()
""",
    )

    workspace.add_repository("repo_auth", source_files=[sf_repo1])
    workspace.add_repository("repo_client", source_files=[sf_repo2])

    assert len(workspace.namespaced_chunks) >= 2
    repo_ids = {nc.repo_id for nc in workspace.namespaced_chunks}
    assert repo_ids == {"repo_auth", "repo_client"}


def test_cross_repo_contract_discovery():
    workspace = MultiRepoWorkspace(workspace_id="contract-ws")

    sf_producer = SourceFile(
        path="/repos/producer/main.py",
        rel_path="main.py",
        language="python",
        content="""
@app.get('/api/users')
def get_users():
    return []
""",
    )

    sf_consumer = SourceFile(
        path="/repos/consumer/app.py",
        rel_path="app.py",
        language="python",
        content="""
def sync():
    data = requests.get('http://producer/api/users')
    return data
""",
    )

    workspace.add_repository("producer_service", source_files=[sf_producer])
    workspace.add_repository("consumer_service", source_files=[sf_consumer])

    contracts = workspace.detect_cross_repo_contracts()
    assert len(contracts) == 1
    c = contracts[0]
    assert c.producer_repo == "producer_service"
    assert c.consumer_repo == "consumer_service"
    assert c.endpoint_or_symbol == "/api/users"
    assert c.contract_type == "http_api"
    assert workspace.contract_graph.has_edge("consumer_service", "producer_service")


def test_federated_search_and_repo_filtering():
    workspace = MultiRepoWorkspace(workspace_id="search-ws")

    c1 = CodeChunk(
        chunk_id="c1",
        file_path="crypto.py",
        language="python",
        kind="function",
        name="hash_password",
        code="def hash_password(pwd): return sha256(pwd)",
        start_line=1,
        end_line=5,
    )
    c2 = CodeChunk(
        chunk_id="c2",
        file_path="billing.py",
        language="python",
        kind="function",
        name="charge_card",
        code="def charge_card(amount): return stripe.charge(amount)",
        start_line=1,
        end_line=5,
    )

    workspace.add_repository("security_repo", chunks=[c1])
    workspace.add_repository("billing_repo", chunks=[c2])

    # Unfiltered search
    results_all = workspace.search("password", top_k=5)
    assert len(results_all) > 0
    assert any(nc.repo_id == "security_repo" for nc, _ in results_all)

    # Filtered search: billing only
    results_billing = workspace.search("password", top_k=5, repo_filter=["billing_repo"])
    assert all(nc.repo_id == "billing_repo" for nc, _ in results_billing)


def test_federated_ask_citations():
    workspace = MultiRepoWorkspace(workspace_id="ask-ws")

    c1 = CodeChunk(
        chunk_id="c1",
        file_path="user_api.py",
        language="python",
        kind="function",
        name="get_user",
        code="def get_user(uid): pass",
        start_line=5,
        end_line=15,
    )
    workspace.add_repository("repo_a", chunks=[c1])

    result = workspace.ask("How to get user?")
    assert result["workspace_id"] == "ask-ws"
    assert len(result["retrieved_chunks"]) >= 1
    citation = result["retrieved_chunks"][0]["citation"]
    assert citation == "[repo_a:user_api.py:5-15]"
    assert "repo_a" in result["participating_repositories"]


def test_multi_repo_fastapi_endpoints(client, auth_headers):
    # Setup mock active repos in ACTIVE_REPOS cache
    from backend.api.repos import ACTIVE_REPOS

    c_auth = CodeChunk(
        chunk_id="c-auth",
        file_path="auth.py",
        language="python",
        kind="function",
        name="login",
        code="def login(): pass",
        start_line=1,
        end_line=10,
    )
    c_shop = CodeChunk(
        chunk_id="c-shop",
        file_path="shop.py",
        language="python",
        kind="function",
        name="checkout",
        code="def checkout(): pass",
        start_line=1,
        end_line=10,
    )

    class MockStore:
        def __init__(self, chunks):
            self.chunks = chunks

    ACTIVE_REPOS["repo_1"] = {
        "repo_id": "repo_1",
        "store": MockStore([c_auth]),
        "source_files": [SourceFile(path="/r1/auth.py", rel_path="auth.py", language="python", content="@app.get('/api/me')\ndef me(): pass")],
        "meta": {"repo_path": "/r1", "user_id": "usr_admin"},
    }
    ACTIVE_REPOS["repo_2"] = {
        "repo_id": "repo_2",
        "store": MockStore([c_shop]),
        "source_files": [SourceFile(path="/r2/client.py", rel_path="client.py", language="python", content="requests.get('/api/me')")],
        "meta": {"repo_path": "/r2", "user_id": "usr_admin"},
    }

    # 1. Create Workspace
    payload = {
        "workspace_id": "ws-e2e",
        "repo_ids": ["repo_1", "repo_2"],
        "name": "E2E Workspace",
    }
    res = client.post("/api/multi-repo/workspace", json=payload, headers=auth_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["workspace_id"] == "ws-e2e"
    assert set(data["repositories"]) == {"repo_1", "repo_2"}
    assert len(data["discovered_contracts"]) == 1
    assert data["discovered_contracts"][0]["endpoint_or_symbol"] == "/api/me"

    # 2. Get Contracts
    res_c = client.get("/api/multi-repo/ws-e2e/contracts", headers=auth_headers)
    assert res_c.status_code == 200
    contracts_data = res_c.json()
    assert contracts_data["contracts_count"] == 1

    # 3. Query multi-repo workspace
    query_payload = {
        "workspace_id": "ws-e2e",
        "question": "What is the checkout and login flow?",
        "top_k": 3,
    }
    res_q = client.post("/api/multi-repo/query", json=query_payload, headers=auth_headers)
    assert res_q.status_code == 200
    q_data = res_q.json()
    assert "retrieved_chunks" in q_data
    assert len(q_data["retrieved_chunks"]) > 0
    assert "ws-e2e" == q_data["workspace_id"]

    # 4. List Workspaces
    res_list = client.get("/api/multi-repo/workspaces", headers=auth_headers)
    assert res_list.status_code == 200
    assert any(ws["workspace_id"] == "ws-e2e" for ws in res_list.json())
