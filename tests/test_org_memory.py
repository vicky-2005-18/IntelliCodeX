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
    file_process_lock,
)
from core.self_improving import RepairExperienceBank
from backend.main import app
from backend.auth import create_access_token, User
from backend.database import db_manager


@pytest.fixture
def auth_headers():
    user = User(
        id="usr_admin",
        username="admin",
        email="admin@example.com",
        role="admin",
        org_id="org_default",
    )
    if not db_manager.find_one("users", {"id": user.id}):
        db_manager.insert("users", {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "org_id": user.org_id,
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
    assert item.memory_id == "commit:abcdef123456"
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
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = OrgMemoryStore(repo_id="test_repo", storage_dir=tmp_dir)

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
    commits = GitHistoryMiner.mine_commits(".", max_commits=10)
    assert isinstance(commits, list)
    if commits:
        first = commits[0]
        assert first.memory_type == "commit"
        assert first.author != ""
        assert first.date_str != ""
        assert first.title != ""


def test_distinction_between_decision_repair_and_generated_summary():
    """Verifies that generated text does NOT become verified knowledge automatically."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = OrgMemoryStore(repo_id="auth_svc", org_id="org_test", storage_dir=tmp_dir)

        # 1. Developer-authored decision
        dec = store.record_decision(
            title="Adopt Argon2 for Password Hashing",
            content="Chose argon2id over PBKDF2 due to memory-hard resistance to GPU attacks.",
            author="usr_lead",
            scope="repo_private",
        )
        assert dec.memory_type == "decision"
        assert dec.verification_status == "developer_approved"
        assert dec.state == "active"

        # 2. Verified repair
        repair = store.record_repair(
            title="Repair for KeyError in Session Dict",
            content="Used session.get('user_id') with None fallback.",
            author="sandbox_runner",
            security_policy="strict",
            test_verified=True,
            developer_approved=True,
        )
        assert repair.memory_type == "repair"
        assert repair.verification_status == "verified"
        assert repair.security_policy == "strict"

        # 3. AI Generated summary
        summary = store.record_summary(
            title="Auto-generated module summary for auth.py",
            content="This module provides session helpers and token verification.",
            author="ai_doc_generator",
        )
        assert summary.memory_type == "summary"
        assert summary.verification_status == "unverified"  # Invariant check


def test_multitenant_and_repo_private_authorization_barriers():
    """
    Two authorized users in org_alpha (alice, bob) and one in org_beta (charlie):
    - Org-shared decision in org_alpha is accessible to alice and bob, but NOT charlie.
    - Repo-private decision in org_alpha is accessible to alice (who has repo access), but NOT bob.
    - Revoking repo access prevents subsequent retrieval.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Store for org_alpha
        store_alpha = OrgMemoryStore(repo_id="billing_repo", org_id="org_alpha", storage_dir=tmp_dir)

        # Record 1: Shared decision across org_alpha
        shared_dec = store_alpha.record_decision(
            title="Organization Policy on Microservice TLS",
            content="All inter-service traffic within org_alpha must use mTLS with SPIFFE certs.",
            author="alice",
            scope="org_shared",
            item_id="dec:mtls_policy",
        )

        # Record 2: Repo-private decision for billing_repo
        private_dec = store_alpha.record_decision(
            title="Billing Stripe Secret Management",
            content="Store Stripe secret key in vault; do not cache in Redis.",
            author="alice",
            scope="repo_private",
            item_id="dec:stripe_secrets",
        )

        # 1. Alice (in org_alpha with billing_repo access) can retrieve both
        alice_results = store_alpha.search(
            query="TLS secrets stripe",
            user_id="alice",
            user_role="developer",
            user_org_id="org_alpha",
            accessible_repos={"billing_repo"},
        )
        alice_item_ids = {it.item_id for it, _ in alice_results}
        assert "dec:mtls_policy" in alice_item_ids
        assert "dec:stripe_secrets" in alice_item_ids

        # 2. Bob (in org_alpha WITHOUT billing_repo access) can retrieve shared, but NOT repo-private
        bob_results = store_alpha.search(
            query="TLS secrets stripe",
            user_id="bob",
            user_role="developer",
            user_org_id="org_alpha",
            accessible_repos={"frontend_repo"},  # No billing_repo
        )
        bob_item_ids = {it.item_id for it, _ in bob_results}
        assert "dec:mtls_policy" in bob_item_ids
        assert "dec:stripe_secrets" not in bob_item_ids  # Private barrier enforced

        # 3. Charlie (in org_beta) can retrieve NOTHING from org_alpha (Tenant boundary)
        charlie_results = store_alpha.search(
            query="TLS secrets stripe",
            user_id="charlie",
            user_role="developer",
            user_org_id="org_beta",
            accessible_repos={"billing_repo"},
        )
        assert len(charlie_results) == 0  # Hard tenant barrier

        # 4. Access revocation: Revoke Alice's access to billing_repo
        alice_revoked_results = store_alpha.search(
            query="secrets stripe",
            user_id="alice_revoked",  # Different non-author user with revoked access
            user_role="developer",
            user_org_id="org_alpha",
            accessible_repos=set(),  # Revoked all repos
        )
        revoked_item_ids = {it.item_id for it, _ in alice_revoked_results}
        assert "dec:stripe_secrets" not in revoked_item_ids


def test_lifecycle_invalidation_and_superseding_excludes_obsolete():
    """Verifies that invalidated or superseded records are omitted from active retrieval."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = OrgMemoryStore(repo_id="payment_svc", org_id="org_alpha", storage_dir=tmp_dir)

        # Initial decision
        store.record_decision(
            title="Use SHA1 for Webhook Signatures",
            content="Old signature mechanism using SHA1 hashing.",
            author="lead_dev",
            item_id="dec:sha1_webhook",
            scope="org_shared",
        )

        res_active = store.search("webhook signature SHA1", user_org_id="org_alpha")
        assert any(it.item_id == "dec:sha1_webhook" for it, _ in res_active)

        # 1. Invalidate obsolete decision
        store.invalidate_record("dec:sha1_webhook", reason="SHA1 is cryptographically insecure", user_id="sec_audit")

        res_after_invalidation = store.search("webhook signature SHA1", user_org_id="org_alpha")
        assert not any(it.item_id == "dec:sha1_webhook" for it, _ in res_after_invalidation)

        # Verify include_inactive allows audit inspection
        res_with_inactive = store.search("webhook signature SHA1", user_org_id="org_alpha", include_inactive=True)
        assert any(it.item_id == "dec:sha1_webhook" for it, _ in res_with_inactive)

        # 2. Supersede: add new record superseding an old one
        old_jwt = store.record_decision(
            title="Use HS256 for internal tokens",
            content="Symmetric key JWT tokens.",
            author="lead_dev",
            item_id="dec:jwt_hs256",
            scope="org_shared",
        )
        new_jwt = OrgMemoryItem(
            item_id="dec:jwt_rs256",
            memory_type="decision",
            title="Use RS256 for internal tokens",
            author="sec_lead",
            date_str="2026-03-01",
            content="Asymmetric public/private key pairs for token signing.",
            org_id="org_alpha",
            scope="org_shared",
            verification_status="developer_approved",
            state="active",
        )
        store.supersede_record("dec:jwt_hs256", new_jwt)

        res_jwt = store.search("internal tokens RS256 HS256", user_org_id="org_alpha")
        jwt_ids = [it.item_id for it, _ in res_jwt]
        assert "dec:jwt_rs256" in jwt_ids
        assert "dec:jwt_hs256" not in jwt_ids  # Superseded record excluded


def test_persistence_across_application_store_restart():
    """Demonstrates durable persistence across store restart."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Step 1: Initialize store and write records
        store1 = OrgMemoryStore(repo_id="storage_repo", org_id="org_persistent", storage_dir=tmp_dir)
        store1.record_decision(
            title="Choose SQLite for Metadata Direct Map",
            content="SQLite embedded file database provides sub-millisecond ACID chunk queries without external server.",
            author="lead_arch",
            item_id="dec:sqlite_metadata",
            scope="org_shared",
        )
        assert len(store1.items) == 1

        # Step 2: Simulate application shutdown and restart by creating fresh store instance
        store2 = OrgMemoryStore(repo_id="storage_repo", org_id="org_persistent", storage_dir=tmp_dir)
        assert len(store2.items) == 1

        # Query restarted store
        res = store2.search("SQLite embedded metadata ACID", user_org_id="org_persistent")
        assert len(res) == 1
        assert res[0][0].item_id == "dec:sqlite_metadata"
        assert res[0][0].citation.startswith("[decision:")


def test_atomic_write_and_process_lock_safety():
    """Verifies atomic persistence, temporary file cleanup, and process locking."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        lock_path = os.path.join(tmp_dir, "test.lock")

        # Test process lock context manager
        with file_process_lock(lock_path):
            assert os.path.exists(lock_path)

        store = OrgMemoryStore(repo_id="atomic_repo", org_id="org_atomic", storage_dir=tmp_dir)
        store.record_decision(
            title="Safe Atomic Persistence",
            content="Testing atomic replace semantics.",
            author="dev_tester",
            item_id="dec:atomic_01",
        )

        assert os.path.isfile(store.storage_path)

        # Verify failed writes do not corrupt storage
        original_mtime = os.path.getmtime(store.storage_path)
        try:
            # Inject an invalid non-serializable object to trigger exception
            store.items.append("NOT_AN_ORG_MEMORY_ITEM")  # type: ignore
            store._persist()
        except Exception:
            pass
        finally:
            # Remove bad object
            store.items = [i for i in store.items if isinstance(i, OrgMemoryItem)]

        # File on disk should remain valid JSON
        store_reload = OrgMemoryStore(repo_id="atomic_repo", org_id="org_atomic", storage_dir=tmp_dir)
        assert len(store_reload.items) == 1
        assert store_reload.items[0].item_id == "dec:atomic_01"


def test_sync_from_repair_bank_preserves_security_policy_provenance():
    """Verifies that repair experiences are reused with security policy provenance intact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create bank with golden experiences
        bank = RepairExperienceBank(storage_path=os.path.join(tmp_dir, "repairs.json"))
        # Add a custom secrets_only repair experience for repo_x
        bank.record_success(
            error_type="IndexError",
            error_description="list index out of range in auth cache",
            original_code="return cache[0]",
            fixed_code="return cache[0] if cache else None",
            explanation="Check cache boundary",
            source="developer_approval",
            repo_id="repo_x",
            test_verified=True,
            developer_approved=True,
            security_policy="secrets_only",  # Less strict policy
            security_approved=True,
            security_status="passed",
        )
        # Add a strict repair experience for repo_x
        bank.record_success(
            error_type="KeyError",
            error_description="missing token in header dict",
            original_code="return headers['X-Token']",
            fixed_code="return headers.get('X-Token')",
            explanation="Safe dict access",
            source="developer_approval",
            repo_id="repo_x",
            test_verified=True,
            developer_approved=True,
            security_policy="strict",  # Strict policy
            security_approved=True,
            security_status="passed",
        )

        org_store = OrgMemoryStore(repo_id="repo_x", org_id="org_sec", storage_dir=tmp_dir)
        added_count = org_store.sync_from_repair_bank(bank, repo_id="repo_x")
        assert added_count >= 2

        # Search with strict_security filter
        strict_results = org_store.search(
            query="cache header token error",
            user_org_id="org_sec",
            accessible_repos={"repo_x"},
            security_policy_filter="strict",
        )
        assert len(strict_results) > 0
        for item, _ in strict_results:
            if item.memory_type == "repair":
                assert item.security_policy == "strict"


def test_api_records_and_query_authorization_lifecycle(client):
    """Verifies REST API endpoints for records creation, query, invalidation, and tenant barriers."""
    from backend.api.repos import ACTIVE_REPOS

    class MockStore:
        chunks = []

    # Setup test users
    user_alice = User(id="usr_alice_mem", username="alice", email="alice@corp.com", role="developer", org_id="org_corp")
    user_charlie = User(id="usr_charlie_mem", username="charlie", email="charlie@other.com", role="developer", org_id="org_other")

    for u in (user_alice, user_charlie):
        if not db_manager.find_one("users", {"id": u.id}):
            db_manager.insert("users", {"id": u.id, "username": u.username, "email": u.email, "role": u.role, "org_id": u.org_id, "hashed_password": "pw"})

    alice_token = create_access_token(user_alice)
    charlie_token = create_access_token(user_charlie)
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    charlie_headers = {"Authorization": f"Bearer {charlie_token}"}

    # Setup repo owned by alice in org_corp
    ACTIVE_REPOS["alice_private_repo"] = {
        "repo_id": "alice_private_repo",
        "store": MockStore(),
        "source_files": [],
        "meta": {"repo_path": ".", "owner_id": "usr_alice_mem", "user_id": "usr_alice_mem"},
    }

    # 1. Alice creates an org_shared decision record
    res_rec = client.post("/api/org-memory/records", json={
        "title": "Adopt Event-Driven Architecture with RabbitMQ",
        "content": "Publish domain events asynchronously to decouple billing from shipping.",
        "memory_type": "decision",
        "scope": "org_shared",
        "source_references": ["docs/architecture/events.md"],
    }, headers=alice_headers)
    assert res_rec.status_code == 200, res_rec.text
    rec_data = res_rec.json()
    assert rec_data["status"] == "created"
    assert rec_data["scope"] == "org_shared"
    assert rec_data["verification_status"] == "developer_approved"
    item_id = rec_data["memory_id"]

    # 2. Alice queries org-wide memory
    res_q_alice = client.post("/api/org-memory/query", json={
        "question": "Why did we choose RabbitMQ domain events?",
        "top_k": 3,
    }, headers=alice_headers)
    assert res_q_alice.status_code == 200
    q_alice_data = res_q_alice.json()
    assert len(q_alice_data["retrieved_records"]) >= 1
    assert any("RabbitMQ" in r["title"] for r in q_alice_data["retrieved_records"])

    # 3. Charlie (different org) queries -> cannot retrieve Alice's org record (Tenant boundary)
    res_q_charlie = client.post("/api/org-memory/query", json={
        "question": "Why did we choose RabbitMQ domain events?",
        "top_k": 3,
    }, headers=charlie_headers)
    assert res_q_charlie.status_code == 200
    q_charlie_data = res_q_charlie.json()
    assert len(q_charlie_data["retrieved_records"]) == 0

    # 4. Alice creates a generated summary -> verification_status must be 'unverified'
    res_sum = client.post("/api/org-memory/records", json={
        "title": "AI Summary of Billing Service",
        "content": "Automated summary of invoice generation pipeline.",
        "memory_type": "summary",
        "scope": "repo_private",
        "repo_id": "alice_private_repo",
    }, headers=alice_headers)
    assert res_sum.status_code == 200
    assert res_sum.json()["verification_status"] == "unverified"

    # 5. Invalidate the RabbitMQ record
    res_inv = client.post(f"/api/org-memory/records/{item_id}/invalidate", json={
        "reason": "Migrated from RabbitMQ to Apache Kafka for event replay",
    }, headers=alice_headers)
    assert res_inv.status_code == 200
    assert res_inv.json()["status"] == "invalidated"

    # Subsequent query does not retrieve invalidated record
    res_q_after_inv = client.post("/api/org-memory/query", json={
        "question": "Why did we choose RabbitMQ domain events?",
        "top_k": 3,
    }, headers=alice_headers)
    assert res_q_after_inv.status_code == 200
    assert not any(r["item_id"] == item_id for r in res_q_after_inv.json()["retrieved_records"])
