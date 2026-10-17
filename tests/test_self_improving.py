"""
Unit and integration tests for Self-Improving Agents & In-Context Few-Shot Learning (REQ-FUT-10).
"""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from core.self_improving import (
    RepairExperience,
    RepairExperienceBank,
    global_experience_bank,
)
from core.patch_generator import PatchEngine
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
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


def test_experience_bank_bootstrapping():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        assert len(bank.experiences) >= 4
        stats = bank.get_stats()
        assert stats["total_experiences"] >= 4
        assert "KeyError" in stats["error_types_breakdown"]
        assert "IndexError" in stats["error_types_breakdown"]


def test_record_success_and_recurring_increment():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # Record first occurrence
        exp1 = bank.record_success(
            error_type="TypeError",
            error_description="TypeError: unsupported operand type(s) for +: 'int' and 'str'",
            original_code="def add(a, b): return a + b",
            fixed_code="def add(a, b): return int(a) + int(b)",
            explanation="Cast both operands to integer before addition.",
            source="sandbox_pass",
        )
        assert exp1.success_count == 1
        assert exp1.error_type == "TypeError"

        # Record identical recurring fix
        exp2 = bank.record_success(
            error_type="TypeError",
            error_description="Another TypeError in add function",
            original_code="def add(a, b): return a + b",
            fixed_code="def add(a, b): return int(a) + int(b)",
            explanation="Cast operands to int.",
            source="developer_approval",
        )
        assert exp2.experience_id == exp1.experience_id
        assert exp2.success_count == 2
        assert exp2.source == "developer_approval"


def test_few_shot_retrieval_and_formatting():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # Retrieve for KeyError
        shots = bank.retrieve_few_shots(error_type="KeyError", limit=1)
        assert len(shots) == 1
        assert shots[0].error_type == "KeyError"

        # Format prompt
        formatted = bank.format_few_shot_prompt(error_type="KeyError", limit=1)
        assert "Verified Past Repair Demonstrations" in formatted
        assert "Original Flawed Code" in formatted
        assert "Verified Correct Code" in formatted
        assert "KeyError" in formatted


def test_prompt_injection_in_patch_engine():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        embedder = TfidfEmbedder(dim=16)
        store = FaissVectorStore(dim=16)
        engine = PatchEngine(
            store=store,
            embedder=embedder,
            llm=None,
            experience_bank=bank,
        )

        prompt = engine._build_llm_prompt(
            error_report="KeyError: 'auth_token' missing in dictionary",
            file_path="auth.py",
            snippet="def auth(data): return data['auth_token']",
            rag_context="",
            localization={"error_type": "KeyError"},
        )

        assert "Verified Past Repair Demonstrations" in prompt
        assert "KeyError" in prompt
        assert ".get(" in prompt


def test_apply_patch_records_into_experience_bank():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # Create a dummy target file
        target_rel = "calculator.py"
        target_abs = os.path.join(tmp_dir, target_rel)
        with open(target_abs, "w", encoding="utf-8") as f:
            f.write("def div(a, b):\n    return a / b\n")

        embedder = TfidfEmbedder(dim=16)
        store = FaissVectorStore(dim=16)
        engine = PatchEngine(
            store=store,
            embedder=embedder,
            llm=None,
            repo_path=tmp_dir,
            experience_bank=bank,
        )

        patch_rec = {
            "patch_id": "test-patch-123",
            "target_file": target_rel,
            "original_code": "def div(a, b):\n    return a / b\n",
            "suggested_patch": "def div(a, b):\n    return a / b if b != 0 else 0.0\n",
            "snippet_patch": "def div(a, b):\n    return a / b if b != 0 else 0.0\n",
            "explanation": "Guarded against division by zero.",
            "error_type": "ZeroDivisionError",
            "sandbox_validation": {
                "verified": True,
                "test_status": "passed",
                "iterations_count": 1,
            },
            "security_validation": {
                "security_status": "passed",
                "security_approved": True,
                "security_policy": "strict",
            },
        }

        ok, msg = engine.apply_patch(patch_rec, approved_by="senior_dev")
        assert ok is True

        # Verify experience was recorded
        stats = bank.get_stats()
        assert stats["total_successful_repairs"] > 4
        shots = bank.retrieve_few_shots(error_type="ZeroDivisionError")
        assert any("if b != 0" in s.fixed_code for s in shots)


def test_patches_experiences_fastapi_endpoints(client, auth_headers):
    # 1. GET experiences
    res = client.get("/api/patches/experiences", headers=auth_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "stats" in data
    assert "experiences" in data
    assert data["stats"]["total_experiences"] >= 4

    # 2. POST new experience
    new_exp_payload = {
        "error_type": "ValueError",
        "error_description": "ValueError: invalid literal for int() with base 10: ''",
        "original_code": "def parse_int(s): return int(s)",
        "fixed_code": "def parse_int(s): return int(s.strip()) if s and s.strip().isdigit() else 0",
        "explanation": "Validate string is non-empty and isdigit before int parsing.",
        "source": "manual",
    }
    res_post = client.post("/api/patches/experiences", json=new_exp_payload, headers=auth_headers)
    assert res_post.status_code == 200, res_post.text
    exp_data = res_post.json()
    assert exp_data["error_type"] == "ValueError"
    assert exp_data["source"] == "manual"


def test_experience_lifecycle_provenance_and_idempotency():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # 1. Distinct provenance: sandbox pass
        e_sandbox = bank.record_success(
            error_type="IndexError",
            error_description="list index out of range",
            original_code="return items[0]",
            fixed_code="return items[0] if items else None",
            explanation="Check items length before indexing.",
            source="sandbox_pass",
            test_verified=True,
            developer_approved=False,
            event_id="test-run-1",
        )
        assert e_sandbox.source == "sandbox_pass"
        assert e_sandbox.test_verified is True
        assert e_sandbox.developer_approved is False

        # 2. Approval alone does NOT imply tests passed
        e_dev = bank.record_success(
            error_type="CustomTypeError",
            error_description="unsupported operand type(s)",
            original_code="return a + b",
            fixed_code="return str(a) + str(b)",
            explanation="Cast to string.",
            source="developer_approval",
            test_verified=False,
            developer_approved=True,
            event_id="approval-1",
        )
        assert e_dev.source == "developer_approval"
        assert e_dev.test_verified is False
        assert e_dev.developer_approved is True

        # 3. Idempotency: repeated recording of same event_id does not inflate count
        initial_count = e_sandbox.success_count
        e_again = bank.record_success(
            error_type="IndexError",
            error_description="list index out of range",
            original_code="return items[0]",
            fixed_code="return items[0] if items else None",
            explanation="Check items length before indexing.",
            source="sandbox_pass",
            test_verified=True,
            developer_approved=False,
            event_id="test-run-1",  # duplicate event
        )
        assert e_again.success_count == initial_count

        # 4. Invalidation of reverted fixes excludes them from few-shot retrieval
        assert len(bank.retrieve_few_shots(error_type="CustomTypeError")) > 0
        bank.invalidate_experience(e_dev.experience_id, reason="reverted by dev")
        assert len(bank.retrieve_few_shots(error_type="CustomTypeError")) == 0


def test_experience_persistence_and_concurrency():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank1 = RepairExperienceBank(storage_path=storage_file)
        bank1.record_success(
            error_type="KeyError",
            error_description="Key 'user' missing",
            original_code="return d['user']",
            fixed_code="return d.get('user', 'guest')",
            explanation="Use get() with fallback",
            source="sandbox_pass",
            test_verified=True,
            event_id="persist-1",
        )

        # Simulate restart by loading in a new instance from disk
        bank2 = RepairExperienceBank(storage_path=storage_file)
        shots = bank2.retrieve_few_shots(error_type="KeyError")
        assert any("return d.get('user', 'guest')" in s.fixed_code for s in shots)

        # Concurrency test: multiple threads writing concurrently
        import concurrent.futures

        def record_concurrent(idx):
            bank2.record_success(
                error_type="ConcurrentError",
                error_description=f"Error {idx}",
                original_code=f"def f_{idx}(): pass",
                fixed_code=f"def f_{idx}(): return {idx}",
                explanation="Fix concurrency",
                source="sandbox_pass",
                test_verified=True,
                event_id=f"event-{idx}",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(record_concurrent, i) for i in range(15)]
            concurrent.futures.wait(futures)

        # Verify all records persisted safely without corruption
        bank3 = RepairExperienceBank(storage_path=storage_file)
        stats = bank3.get_stats()
        assert stats["total_experiences"] >= 15


def test_tenant_isolation_multi_repo():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # Repo A adds private repair with proprietary code
        bank.record_success(
            error_type="SecretError",
            error_description="proprietary token issue",
            original_code="SECRET_KEY = 'proprietary-algo-internal'",
            fixed_code="SECRET_KEY = get_secret_vault()",
            explanation="Load from vault",
            repo_id="repo-secret-alpha",
            is_public=False,
            test_verified=True,
            developer_approved=True,
        )

        # Repo B searches - must NOT see Repo A's private fix
        shots_repo_b = bank.retrieve_few_shots(error_type="SecretError", repo_id="repo-public-beta")
        assert len(shots_repo_b) == 0

        # Repo A searches - can see its own private fix
        shots_repo_a = bank.retrieve_few_shots(error_type="SecretError", repo_id="repo-secret-alpha")
        assert len(shots_repo_a) == 1
        assert "get_secret_vault()" in shots_repo_a[0].fixed_code


def test_custom_ingestion_validation(client, auth_headers):
    # 1. Unauthenticated ingestion rejected
    bad_res = client.post("/api/patches/experiences", json={"error_type": "KeyError"})
    assert bad_res.status_code in [401, 403]

    # 2. Ingestion with invalid error_type rejected
    invalid_type_payload = {
        "error_type": "Invalid!Error@Type$$",
        "error_description": "Invalid format test description",
        "original_code": "x = 1",
        "fixed_code": "x = 2",
        "explanation": "Test explanation rationale",
    }
    res_bad_type = client.post("/api/patches/experiences", json=invalid_type_payload, headers=auth_headers)
    assert res_bad_type.status_code == 400

    # 3. Ingestion with invalid Python syntax rejected
    invalid_syntax_payload = {
        "error_type": "SyntaxError",
        "error_description": "Invalid syntax test description",
        "original_code": "def foo(): pass",
        "fixed_code": "def foo( invalid python code syntax ??? :::",
        "explanation": "Test explanation rationale",
    }
    res_bad_syntax = client.post("/api/patches/experiences", json=invalid_syntax_payload, headers=auth_headers)
    assert res_bad_syntax.status_code == 400


def test_language_and_token_budget_boundaries():
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # Add JavaScript experience
        bank.record_success(
            error_type="TypeError",
            error_description="Cannot read property of undefined",
            original_code="const x = user.profile.name;",
            fixed_code="const x = user?.profile?.name;",
            explanation="Use optional chaining",
            language="javascript",
            test_verified=True,
        )

        # Query for python: JS experience should not be returned
        shots_py = bank.retrieve_few_shots(error_type="TypeError", language="python")
        assert not any(s.language == "javascript" for s in shots_py)

        # Query for javascript: JS experience should be returned
        shots_js = bank.retrieve_few_shots(error_type="TypeError", language="javascript")
        assert any(s.language == "javascript" for s in shots_js)

        # Enforce token budget: prompt must respect max_tokens_budget
        prompt = bank.format_few_shot_prompt(error_type="KeyError", max_tokens_budget=50)
        # 50 tokens ~ 200 chars limit on demonstration body
        assert len(prompt) < 1000


def test_retrieval_invariants_rejects_failed_skipped_timedout_invalidated_and_infra_errors():
    """Requirement 7: Verify that failed, skipped, timed-out, invalidated, and infrastructure-error experiences cannot be retrieved."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # 1. Direct retrieval tests on bank: unverified or unapproved experiences
        bank.record_success(
            error_type="KeyError",
            error_description="Failed test run should not be demonstration",
            original_code="bad_code_failed()",
            fixed_code="still_bad()",
            explanation="Did not pass",
            source="sandbox_fail",
            test_verified=False,
            developer_approved=False,
            is_public=True,
        )
        bank.record_success(
            error_type="KeyError",
            error_description="Skipped test run should not be demonstration",
            original_code="bad_code_skipped()",
            fixed_code="skipped_fix()",
            explanation="Skipped tests",
            source="sandbox_skipped",
            test_verified=False,
            developer_approved=False,
            is_public=True,
        )
        bank.record_success(
            error_type="KeyError",
            error_description="Timed out container run should not be demonstration",
            original_code="bad_code_timeout()",
            fixed_code="timed_out_fix()",
            explanation="Timed out",
            source="sandbox_timeout",
            test_verified=False,
            developer_approved=False,
            is_public=True,
        )
        bank.record_success(
            error_type="KeyError",
            error_description="Docker infrastructure error should not be demonstration",
            original_code="bad_code_infra()",
            fixed_code="infra_error_fix()",
            explanation="Docker failed",
            source="docker_infra_error",
            test_verified=False,
            developer_approved=False,
            is_public=True,
        )

        # Retrieve for KeyError: none of the unverified / failed records may be returned
        shots = bank.retrieve_few_shots(error_type="KeyError", limit=10)
        for s in shots:
            assert s.test_verified or s.developer_approved or s.source == "golden_sample"
            assert s.source not in ("sandbox_fail", "sandbox_skipped", "sandbox_timeout", "docker_infra_error")
            assert "bad_code" not in s.original_code

        # 2. Invalidation test: an approved fix is invalidated and must immediately be excluded
        valid_exp = bank.record_success(
            error_type="KeyError",
            error_description="Approved fix later found defective",
            original_code="broken_code()",
            fixed_code="reverted_fix()",
            explanation="Reverted",
            source="developer_approval",
            test_verified=True,
            developer_approved=True,
            is_public=True,
        )
        # Before invalidation: retrieved
        before = bank.retrieve_few_shots(error_type="KeyError", limit=10)
        assert any(e.experience_id == valid_exp.experience_id for e in before)

        # Invalidate experience
        bank.invalidate_experience(valid_exp.experience_id, reason="reverted due to regression")

        # After invalidation: MUST NOT be retrieved
        after = bank.retrieve_few_shots(error_type="KeyError", limit=10)
        assert not any(e.experience_id == valid_exp.experience_id for e in after)

        # 3. PatchEngine lifecycle test: PatchEngine must never record failed/skipped/timed-out runs
        from unittest.mock import MagicMock
        from core.sandbox_runner import SandboxTestResult

        mock_runner = MagicMock()
        mock_bank = MagicMock(spec=RepairExperienceBank)

        from core.vectorstore import FaissVectorStore
        from core.embedder import TfidfEmbedder
        engine = PatchEngine(
            store=FaissVectorStore(dim=16),
            embedder=TfidfEmbedder(dim=16),
            llm=None,
            sandbox_runner=mock_runner,
            experience_bank=mock_bank,
        )

        # Scenario A: Test failed
        mock_runner.run_tests_with_patch.return_value = SandboxTestResult(
            success=False, exit_code=1, stdout="", stderr="FAILED test", duration_seconds=0.5, framework="pytest"
        )
        engine.generate_and_verify_patch(
            repo_id="test-repo", error_report="KeyError: 'k'", target_file="mod.py", max_iterations=1
        )
        mock_bank.record_success.assert_not_called()

        # Scenario B: Test skipped
        mock_runner.run_tests_with_patch.return_value = SandboxTestResult(
            success=False, skipped=True, exit_code=0, stdout="", stderr="SKIPPED", duration_seconds=0.1, framework="pytest"
        )
        engine.generate_and_verify_patch(
            repo_id="test-repo", error_report="KeyError: 'k'", target_file="mod.py", max_iterations=1
        )
        mock_bank.record_success.assert_not_called()

        # Scenario C: Container timeout (exit_code -1)
        mock_runner.run_tests_with_patch.return_value = SandboxTestResult(
            success=False, exit_code=-1, stdout="", stderr="Timed out", duration_seconds=30.0, framework="pytest"
        )
        engine.generate_and_verify_patch(
            repo_id="test-repo", error_report="KeyError: 'k'", target_file="mod.py", max_iterations=1
        )
        mock_bank.record_success.assert_not_called()

        # Scenario D: Infrastructure error (exit_code -8 or -6)
        mock_runner.run_tests_with_patch.return_value = SandboxTestResult(
            success=False, exit_code=-8, stdout="", stderr="Docker daemon unavailable", duration_seconds=0.1, framework="pytest"
        )
        engine.generate_and_verify_patch(
            repo_id="test-repo", error_report="KeyError: 'k'", target_file="mod.py", max_iterations=1
        )
        mock_bank.record_success.assert_not_called()


def test_security_policy_provenance_and_strict_retrieval():
    """
    Verifies that RepairExperienceBank enforces security policy provenance:
    1. Historical records without security_policy deserialize as 'unscanned' and are never upgraded automatically.
    2. Candidate approved under 'secrets_only' cannot satisfy a 'strict' security retrieval requirement.
    3. Candidate approved under 'strict' satisfies both strict and secrets_only retrieval.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage_file = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=storage_file)

        # 1. Historical record without security_policy
        raw_historical = {
            "experience_id": "hist-001",
            "error_type": "KeyError",
            "error_description": "legacy key error",
            "original_code": "return d['x']",
            "fixed_code": "return d.get('x')",
            "explanation": "safe get",
            "source": "sandbox_pass",
            "language": "python",
            "test_verified": True,
            "developer_approved": True,
        }
        exp_hist = RepairExperience.from_dict(raw_historical)
        assert exp_hist.security_policy == "unscanned"
        assert exp_hist.security_approved is False
        assert exp_hist.security_status == "unscanned"
        bank.experiences[exp_hist.experience_id] = exp_hist

        # 2. Record approved under secrets_only policy (partial coverage)
        exp_secrets = bank.record_success(
            error_type="KeyError",
            error_description="key error in ts",
            original_code="return obj['x']",
            fixed_code="return obj?.x",
            explanation="optional chaining",
            source="sandbox_pass",
            language="typescript",
            test_verified=True,
            developer_approved=False,
            security_approved=True,
            security_status="passed",
            security_coverage="partial",
            security_policy="secrets_only",
            event_id="sec-secrets-1",
        )
        assert exp_secrets.security_policy == "secrets_only"

        # 3. Record approved under strict policy (full AST + secret coverage)
        exp_strict = bank.record_success(
            error_type="KeyError",
            error_description="key error in python",
            original_code="return data['x']",
            fixed_code="return data.get('x')",
            explanation="use get",
            source="sandbox_pass",
            language="python",
            test_verified=True,
            developer_approved=False,
            security_approved=True,
            security_status="passed",
            security_coverage="full",
            security_policy="strict",
            event_id="sec-strict-1",
        )
        assert exp_strict.security_policy == "strict"

        # Test A: secrets_only cannot satisfy strict retrieval requirement
        retrieved_strict_ts = bank.retrieve_few_shots(
            error_type="KeyError",
            language="typescript",
            required_security_policy="strict",
        )
        # exp_secrets has secrets_only policy, so it must NOT be retrieved under strict
        assert not any(e.experience_id == exp_secrets.experience_id for e in retrieved_strict_ts)

        # Test B: secrets_only CAN satisfy secrets_only retrieval requirement
        retrieved_secrets_ts = bank.retrieve_few_shots(
            error_type="KeyError",
            language="typescript",
            required_security_policy="secrets_only",
        )
        assert any(e.experience_id == exp_secrets.experience_id for e in retrieved_secrets_ts)

        # Test C: strict approval satisfies both strict and secrets_only
        retrieved_strict_py = bank.retrieve_few_shots(
            error_type="KeyError",
            language="python",
            required_security_policy="strict",
        )
        assert any(e.experience_id == exp_strict.experience_id for e in retrieved_strict_py)

        retrieved_sec_py = bank.retrieve_few_shots(
            error_type="KeyError",
            language="python",
            required_security_policy="secrets_only",
        )
        assert any(e.experience_id == exp_strict.experience_id for e in retrieved_sec_py)

        # Test D: Historical unscanned record cannot satisfy strict or generic security_approved
        retrieved_approved = bank.retrieve_few_shots(
            error_type="KeyError",
            require_security_approved=True,
        )
        assert not any(e.experience_id == "hist-001" for e in retrieved_approved)



