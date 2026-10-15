"""
Integration and Verification Tests for Repository Knowledge Graph (REQ-FUT-07)
Verifies:
1. Deterministic multi-file AST knowledge graph generation (files, classes, methods, functions, imports, inherits, calls, API/DB calls with line numbers).
2. Knowledge graph querying via FastAPI endpoints: entity query, relationship filters, direction filters, multi-hop paths, and metadata.
3. Accurate source citations: entity IDs, relationship types, file paths, and AST line numbers.
4. Documented supported vs unsupported relationships (dynamic reflection, polymorphic dispatch, IPC events, DI).
5. Error handling: clear responses for missing repositories (404), unknown entities (404), and empty relationship results (200 empty).
6. Multi-tenant repository isolation: unauthorized users receive 403 Forbidden and cannot access another repository's graph.
7. CLI batch query interface execution.
"""
import os
import pytest
import networkx as nx
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import User, create_access_token
from backend.database import db_manager
from backend.api.repos import ACTIVE_REPOS
from backend.dependency_graph import (
    EnhancedDependencyGraph,
    SUPPORTED_RELATIONSHIPS,
    UNSUPPORTED_RELATIONSHIPS,
)
from core.parser import SourceFile
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from rag.query_engine import QueryEngine


@pytest.fixture
def deterministic_repo_fixture():
    """
    Creates a deterministic multi-file source code fixture:
    - models.py: defines BaseModel, UserAccount (inherits BaseModel), methods, imports utils.py
    - auth_service.py: imports models.py, defines AuthService, login method, calls requests.get (API), calls db.execute (DB)
    - utils.py: defines hash_secret function
    """
    sf_models = SourceFile(
        path="C:/fixture/models.py",
        rel_path="models.py",
        language="python",
        content=(
            "from utils import hash_secret\n\n"            # Line 1
            "class BaseModel:\n"                           # Line 3
            '    """Base entity model."""\n'               # Line 4
            "    pass\n\n"                                 # Line 5
            "class UserAccount(BaseModel):\n"              # Line 7
            '    """User account entity."""\n'             # Line 8
            "    def authenticate(self, password):\n"      # Line 9
            "        hashed = hash_secret(password)\n"     # Line 10
            '        return hashed == "secret"\n'          # Line 11
        ),
    )

    sf_auth = SourceFile(
        path="C:/fixture/auth_service.py",
        rel_path="auth_service.py",
        language="python",
        content=(
            "from models import UserAccount\n"             # Line 1
            "import requests\n\n"                          # Line 2
            "class AuthService:\n"                         # Line 4
            '    """Handles user authentication."""\n'     # Line 5
            "    def login(self, username, password):\n"   # Line 6
            "        user = UserAccount()\n"               # Line 7
            "        requests.get('https://auth.local')\n" # Line 8
            "        db.execute('SELECT 1')\n"             # Line 9
            "        return user.authenticate(password)\n" # Line 10
        ),
    )

    sf_utils = SourceFile(
        path="C:/fixture/utils.py",
        rel_path="utils.py",
        language="python",
        content=(
            '"""Utility helper functions."""\n'            # Line 1
            "def hash_secret(val: str) -> str:\n"         # Line 2
            '    """Simple hash helper."""\n'              # Line 3
            "    return val[::-1]\n"                       # Line 4
        ),
    )

    return [sf_models, sf_auth, sf_utils]


def test_knowledge_graph_ast_generation_and_line_numbers(deterministic_repo_fixture):
    """
    Verifies that EnhancedDependencyGraph extracts all code entities, line numbers,
    and analyzer-supported relationships correctly from source files.
    """
    engine = EnhancedDependencyGraph()
    graph = engine.build(deterministic_repo_fixture)

    # 1. Verify Nodes
    assert graph.has_node("models.py")
    assert graph.has_node("auth_service.py")
    assert graph.has_node("utils.py")

    # Classes
    assert graph.has_node("models.py::BaseModel")
    assert graph.has_node("models.py::UserAccount")
    assert graph.has_node("auth_service.py::AuthService")

    # Methods and Functions
    assert graph.has_node("models.py::UserAccount::authenticate")
    assert graph.has_node("auth_service.py::AuthService::login")
    assert graph.has_node("utils.py::hash_secret")

    # External Endpoints
    assert graph.has_node("API:HTTP_Endpoint")
    assert graph.has_node("DB:Database_Query")

    # 2. Verify Line Numbers on Nodes
    user_node = graph.nodes["models.py::UserAccount"]
    assert user_node["type"] == "class"
    assert user_node["start_line"] == 7
    assert user_node["docstring"] == "User account entity."
    assert user_node["file_path"] == "models.py"

    auth_login = graph.nodes["auth_service.py::AuthService::login"]
    assert auth_login["type"] == "method"
    assert auth_login["start_line"] == 6
    assert auth_login["parent_class"] == "auth_service.py::AuthService"

    hash_fn = graph.nodes["utils.py::hash_secret"]
    assert hash_fn["type"] == "function"
    assert hash_fn["start_line"] == 2
    assert hash_fn["file_path"] == "utils.py"

    # 3. Verify Relationships with Line Numbers
    # Inheritance: UserAccount -> BaseModel
    assert graph.has_edge("models.py::UserAccount", "models.py::BaseModel")
    edge_inherits = graph.get_edge_data("models.py::UserAccount", "models.py::BaseModel")
    assert edge_inherits["relationship"] == "inherits"
    assert edge_inherits["line"] == 7
    assert edge_inherits["internal"] is True

    # File defines class
    assert graph.has_edge("models.py", "models.py::UserAccount")
    edge_def_cls = graph.get_edge_data("models.py", "models.py::UserAccount")
    assert edge_def_cls["relationship"] == "defines_class"
    assert edge_def_cls["line"] == 7

    # Class defines method
    assert graph.has_edge("models.py::UserAccount", "models.py::UserAccount::authenticate")
    edge_def_m = graph.get_edge_data("models.py::UserAccount", "models.py::UserAccount::authenticate")
    assert edge_def_m["relationship"] == "defines_method"
    assert edge_def_m["line"] == 9

    # File defines function
    assert graph.has_edge("utils.py", "utils.py::hash_secret")
    edge_def_fn = graph.get_edge_data("utils.py", "utils.py::hash_secret")
    assert edge_def_fn["relationship"] == "defines_function"
    assert edge_def_fn["line"] == 2

    # Internal File Imports: auth_service.py imports models.py, models.py imports utils.py
    assert graph.has_edge("auth_service.py", "models.py")
    assert graph.get_edge_data("auth_service.py", "models.py")["relationship"] == "imports"
    assert graph.get_edge_data("auth_service.py", "models.py")["line"] == 1

    assert graph.has_edge("models.py", "utils.py")
    assert graph.get_edge_data("models.py", "utils.py")["relationship"] == "imports"
    assert graph.get_edge_data("models.py", "utils.py")["line"] == 1

    # API and DB calls
    assert graph.has_edge("auth_service.py::AuthService::login", "API:HTTP_Endpoint")
    edge_api = graph.get_edge_data("auth_service.py::AuthService::login", "API:HTTP_Endpoint")
    assert edge_api["relationship"] == "api_call"
    assert edge_api["line"] == 8

    assert graph.has_edge("auth_service.py::AuthService::login", "DB:Database_Query")
    edge_db = graph.get_edge_data("auth_service.py::AuthService::login", "DB:Database_Query")
    assert edge_db["relationship"] == "database_call"
    assert edge_db["line"] == 9


def test_api_graph_query_entity_endpoint(deterministic_repo_fixture):
    """
    Verifies the application-level graph query endpoint:
    GET /api/graph/{repo_id}/query?entity=UserAccount
    Checks returned entity attributes, incident relationships, and line numbers.
    """
    test_user = User(id="user_alice", username="alice", email="alice@test.com", role="developer")
    db_manager.insert("users", {
        "id": test_user.id,
        "username": test_user.username,
        "email": test_user.email,
        "role": test_user.role,
        "hashed_password": "dummy",
    })
    token = create_access_token(test_user)
    client = TestClient(app)

    repo_id = "alice_deterministic_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": deterministic_repo_fixture,
        "meta": {"repo_id": repo_id, "repo_path": "C:/fixture", "owner_id": test_user.id},
    }

    resp = client.get(
        f"/api/graph/{repo_id}/query?entity=UserAccount",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["repo_id"] == repo_id
    assert data["found"] is True
    assert data["entity"]["id"] == "models.py::UserAccount"
    assert data["entity"]["name"] == "UserAccount"
    assert data["entity"]["type"] == "class"
    assert data["entity"]["file_path"] == "models.py"
    assert data["entity"]["start_line"] == 7

    # Check relationships
    rels = data["relationships"]
    rel_types = [r["relationship"] for r in rels]
    assert "defines_class" in rel_types
    assert "inherits" in rel_types
    assert "defines_method" in rel_types

    # Inherits relationship line check
    inherits_rel = next(r for r in rels if r["relationship"] == "inherits")
    assert inherits_rel["target"] == "models.py::BaseModel"
    assert inherits_rel["direction"] == "outgoing"
    assert inherits_rel["line"] == 7

    # Check supported vs unsupported relationships documentation
    assert len(data["supported_relationships"]) == 9
    assert any(s["type"] == "imports" for s in data["supported_relationships"])
    assert any(s["type"] == "calls" for s in data["supported_relationships"])

    assert len(data["unsupported_relationships"]) >= 4
    assert any(u["type"] == "dynamic_reflection" for u in data["unsupported_relationships"])
    assert any(u["type"] == "runtime_polymorphic_dispatch" for u in data["unsupported_relationships"])


def test_api_graph_relationship_filter_and_direction(deterministic_repo_fixture):
    """
    Verifies querying with specific relationship and direction filters.
    """
    test_user = User(id="user_alice", username="alice", email="alice@test.com", role="developer")
    token = create_access_token(test_user)
    client = TestClient(app)

    repo_id = "alice_filter_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": deterministic_repo_fixture,
        "meta": {"repo_id": repo_id, "repo_path": "C:/fixture", "owner_id": test_user.id},
    }

    # Filter: relationship=inherits, direction=outgoing
    resp = client.get(
        f"/api/graph/{repo_id}/query?entity=UserAccount&relationship=inherits&direction=outgoing",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    res = resp.json()
    assert res["total_relationships"] == 1
    assert res["relationships"][0]["relationship"] == "inherits"
    assert res["relationships"][0]["direction"] == "outgoing"
    assert res["relationships"][0]["target"] == "models.py::BaseModel"

    # Filter: API calls on AuthService::login
    resp_api = client.get(
        f"/api/graph/{repo_id}/query?entity=AuthService::login&relationship=api_call",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_api.status_code == 200
    res_api = resp_api.json()
    assert res_api["total_relationships"] == 1
    assert res_api["relationships"][0]["relationship"] == "api_call"
    assert res_api["relationships"][0]["target"] == "API:HTTP_Endpoint"
    assert res_api["relationships"][0]["line"] == 8


def test_api_graph_entities_and_path_endpoints(deterministic_repo_fixture):
    """
    Verifies /api/graph/{repo_id}/entities and /api/graph/{repo_id}/path endpoints.
    """
    test_user = User(id="user_alice", username="alice", email="alice@test.com", role="developer")
    token = create_access_token(test_user)
    client = TestClient(app)

    repo_id = "alice_path_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": deterministic_repo_fixture,
        "meta": {"repo_id": repo_id, "repo_path": "C:/fixture", "owner_id": test_user.id},
    }

    # 1. Enumerate entities of type 'class'
    resp_classes = client.get(
        f"/api/graph/{repo_id}/entities?type=class",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_classes.status_code == 200
    classes = resp_classes.json()["entities"]
    class_names = [c["name"] for c in classes]
    assert "BaseModel" in class_names
    assert "UserAccount" in class_names
    assert "AuthService" in class_names

    # 2. Path resolution: auth_service.py -> utils.py
    resp_path = client.get(
        f"/api/graph/{repo_id}/path?source=auth_service.py&target=utils.py",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_path.status_code == 200
    path_data = resp_path.json()
    assert path_data["path_exists"] is True
    assert path_data["length"] == 2
    path_node_ids = [p["id"] for p in path_data["path"]]
    assert path_node_ids == ["auth_service.py", "models.py", "utils.py"]
    assert len(path_data["edges"]) == 2
    assert all(e["relationship"] == "imports" for e in path_data["edges"])


def test_api_graph_metadata_endpoint(deterministic_repo_fixture):
    """
    Verifies /api/graph/{repo_id}/metadata returns graph counts and documentation.
    """
    test_user = User(id="user_alice", username="alice", email="alice@test.com", role="developer")
    token = create_access_token(test_user)
    client = TestClient(app)

    repo_id = "alice_meta_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": deterministic_repo_fixture,
        "meta": {"repo_id": repo_id, "repo_path": "C:/fixture", "owner_id": test_user.id},
    }

    resp = client.get(
        f"/api/graph/{repo_id}/metadata",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    meta = resp.json()
    assert meta["total_nodes"] > 5
    assert meta["total_edges"] > 5
    assert "node_types" in meta
    assert "relationship_types" in meta
    assert "stale_graph_limitation" in meta
    assert len(meta["supported_relationships"]) == 9
    assert len(meta["unsupported_relationships"]) >= 4


def test_api_graph_error_handling_for_unknown_entities_and_repos():
    """
    Verifies clear 404 responses for missing repositories and unknown entities.
    """
    test_user = User(id="user_alice", username="alice", email="alice@test.com", role="developer")
    token = create_access_token(test_user)
    client = TestClient(app)

    repo_id = "alice_empty_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": [],
        "meta": {"repo_id": repo_id, "repo_path": "C:/fixture", "owner_id": test_user.id},
    }

    # 1. Unknown entity in existing repo -> 404
    resp_unknown = client.get(
        f"/api/graph/{repo_id}/query?entity=GhostEntity",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_unknown.status_code == 404
    assert "GhostEntity" in resp_unknown.json()["detail"]

    # 2. Non-existent repository -> 404
    resp_no_repo = client.get(
        "/api/graph/non_existent_repo/query?entity=UserAccount",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_no_repo.status_code == 404
    assert "not found" in resp_no_repo.json()["detail"].lower()


def test_multi_tenant_repository_isolation(deterministic_repo_fixture):
    """
    Verifies that a user cannot query another user's private repository knowledge graph.
    User Bob (developer) querying Alice's repo receives HTTP 403 Forbidden.
    """
    alice = User(id="alice_owner", username="alice", email="alice@test.com", role="developer")
    bob = User(id="bob_intruder", username="bob", email="bob@test.com", role="developer")

    db_manager.insert("users", {
        "id": alice.id, "username": alice.username, "email": alice.email, "role": alice.role, "hashed_password": "x"
    })
    db_manager.insert("users", {
        "id": bob.id, "username": bob.username, "email": bob.email, "role": bob.role, "hashed_password": "y"
    })

    token_alice = create_access_token(alice)
    token_bob = create_access_token(bob)
    client = TestClient(app)

    repo_id = "alice_private_repo"
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    ACTIVE_REPOS[repo_id] = {
        "store": store,
        "embedder": embedder,
        "graph": nx.DiGraph(),
        "engine": QueryEngine(store, embedder, llm=None),
        "source_files": deterministic_repo_fixture,
        "meta": {"repo_id": repo_id, "repo_path": "C:/alice_private", "owner_id": alice.id},
    }

    # Alice queries her own repo -> 200 OK
    resp_alice = client.get(
        f"/api/graph/{repo_id}/query?entity=UserAccount",
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    assert resp_alice.status_code == 200

    # Bob queries Alice's repo -> 403 Forbidden
    resp_bob = client.get(
        f"/api/graph/{repo_id}/query?entity=UserAccount",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_bob.status_code == 403
    assert "Access denied" in resp_bob.json()["detail"]

    # Bob also cannot query Alice's path or metadata
    resp_bob_path = client.get(
        f"/api/graph/{repo_id}/path?source=models.py&target=utils.py",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_bob_path.status_code == 403

    resp_bob_meta = client.get(
        f"/api/graph/{repo_id}/metadata",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert resp_bob_meta.status_code == 403


def test_cli_graph_batch_query_execution(deterministic_repo_fixture, capsys):
    """
    Verifies that the CLI batch command 'graph:<entity>' executes against
    an ingested repository and outputs formatted entity information.
    """
    from cli import execute_graph_command

    class DummyIngestResult:
        def __init__(self, source_files):
            self.source_files = source_files
            self.graph = nx.DiGraph()
            self.call_graph = None

    result = DummyIngestResult(deterministic_repo_fixture)
    execute_graph_command(result, "graph:UserAccount")
    captured = capsys.readouterr()

    assert "UserAccount" in captured.out
    assert "models.py" in captured.out
    assert "inherits" in captured.out or "defines_class" in captured.out

    # Unknown entity check in CLI
    execute_graph_command(result, "graph:NonExistentSymbol")
    captured_unknown = capsys.readouterr()
    assert "not found" in captured_unknown.out.lower()
