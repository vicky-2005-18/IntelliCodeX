"""
Focused regression tests for the central Patch Approval Gate (REQ-CORE-16, REQ-CORE-17, REQ-FUT-02, REQ-FUT-05).

Validates:
1. Missing verification metadata blocks application.
2. Skipped or zero-test execution blocks application.
3. Failed execution (failures, timeouts, collection errors, pre-flight rejection) blocks application.
4. Contradictory "verified" status cannot override contradictory execution evidence.
5. Security failure or scanner error blocks application.
6. Incomplete coverage under strict security policy blocks application.
7. Explicitly approved secrets_only policy allows application while preserving provenance.
8. Valid behavioral and security approval applies cleanly.
9. Source files remain completely unchanged after every rejection (no edits, no backups, no git commits, no experience bank records).
10. Entry points (interactive CLI, saved proposals, backend REST API) all enforce the central gate.
11. force=True does NOT bypass verification.
"""
import hashlib
import os
import tempfile
import uuid
from typing import Dict, Any
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from core.patch_generator import PatchEngine, evaluate_patch_approval_gate
from core.self_improving import RepairExperienceBank
from backend.main import app
from backend.database.mongo import db_manager


def _compute_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@pytest.fixture
def disposable_repo():
    """Provides an isolated disposable workspace with a target source file."""
    with tempfile.TemporaryDirectory(prefix="icx_gate_test_") as tmp_dir:
        target_rel = "app.py"
        target_abs = os.path.join(tmp_dir, target_rel)
        original_code = "def handle(val):\n    return val.strip()\n"
        with open(target_abs, "w", encoding="utf-8") as f:
            f.write(original_code)

        bank_path = os.path.join(tmp_dir, "repairs.json")
        bank = RepairExperienceBank(storage_path=bank_path)

        engine = PatchEngine(
            store=None,
            embedder=None,
            llm=None,
            repo_path=tmp_dir,
            experience_bank=bank,
        )

        yield {
            "tmp_dir": tmp_dir,
            "target_rel": target_rel,
            "target_abs": target_abs,
            "original_code": original_code,
            "original_hash": _compute_sha256(original_code),
            "bank": bank,
            "engine": engine,
        }


def _make_base_candidate(disposable_repo, suggested_patch=None) -> Dict[str, Any]:
    suggested = suggested_patch or "def handle(val):\n    return val.strip() if val else ''\n"
    return {
        "patch_id": f"patch-{uuid.uuid4().hex[:8]}",
        "repo_id": "test_repo",
        "target_file": disposable_repo["target_rel"],
        "original_code": disposable_repo["original_code"],
        "original_hash": disposable_repo["original_hash"],
        "suggested_patch": suggested,
        "snippet_patch": suggested,
        "file_read_from_disk": True,
        "explanation": "Safely handle None or empty input strings.",
        "error_type": "AttributeError",
        "status": "pending",
    }


# =========================================================================
# 1. Missing Verification Metadata
# =========================================================================

def test_missing_verification_metadata_blocks_application(disposable_repo):
    """Candidate missing sandbox_validation metadata entirely must be rejected."""
    cand = _make_base_candidate(disposable_repo)
    cand.pop("sandbox_validation", None)

    # Central gate function check
    ok_gate, gate_msg = evaluate_patch_approval_gate(cand)
    assert ok_gate is False
    assert "missing sandbox verification metadata" in gate_msg

    # PatchEngine.apply_patch check
    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert "missing sandbox verification metadata" in msg

    # File on disk must remain unchanged
    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 2. Skipped or Zero-Test Execution
# =========================================================================

def test_skipped_test_execution_blocks_application(disposable_repo):
    """Candidate with test_status='skipped' or skipped=True must be rejected."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": False,
        "test_status": "skipped",
        "skipped": True,
        "iterations_count": 1,
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert "skipped" in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


def test_zero_test_execution_blocks_application(disposable_repo):
    """Candidate where 0 tests executed/passed must be rejected even if success flag is True."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": True,
        "test_status": "passed",
        "iterations_count": 1,
        "test_result": {
            "success": True,
            "exit_code": 0,
            "passed_count": 0,
            "failed_count": 0,
            "total_count": 0,
            "passed_tests": [],
            "failed_tests": [],
            "collection_errors": [],
        },
    }
    cand["security_validation"] = {
        "security_status": "passed",
        "security_approved": True,
        "security_policy": "strict",
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert "zero tests" in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 3. Failed Execution (failures, timeouts, collection errors, pre-flight)
# =========================================================================

@pytest.mark.parametrize("failure_scenario, sb_payload, expected_err", [
    (
        "test_failure",
        {
            "verified": False,
            "test_status": "failed",
            "test_result": {"success": False, "exit_code": 1, "failed_count": 1, "failed_tests": ["test_handle"]},
        },
        "failed test verification",
    ),
    (
        "timeout",
        {
            "verified": False,
            "test_status": "timed-out",
            "test_result": {"success": False, "exit_code": -1, "error_message": "Command timed out after 30 seconds"},
        },
        "timed out",
    ),
    (
        "collection_error",
        {
            "verified": False,
            "test_status": "collection_error",
            "test_result": {"success": False, "exit_code": 2, "collection_errors": ["SyntaxError in test_app.py"]},
        },
        "collection error",
    ),
    (
        "pre_flight_rejection",
        {
            "verified": False,
            "test_status": "pre_flight_rejected",
            "test_result": {
                "success": False,
                "exit_code": -1,
                "failed_tests": ["candidate_interface_validation"],
                "error_message": "Candidate validation rejected: interface dropped handle()",
            },
        },
        "pre-flight",
    ),
])
def test_failed_execution_scenarios_block_application(disposable_repo, failure_scenario, sb_payload, expected_err):
    """Failed, timed out, collection error, and pre-flight rejected executions must be rejected."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = sb_payload
    cand["security_validation"] = {
        "security_status": "passed",
        "security_approved": True,
        "security_policy": "strict",
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert expected_err in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 4. Contradictory "verified" Status
# =========================================================================

def test_contradictory_verified_status_does_not_override_execution_failure(disposable_repo):
    """status='verified' in patch_record or verified=True must NOT bypass failing execution evidence."""
    cand = _make_base_candidate(disposable_repo)
    cand["status"] = "verified"
    cand["sandbox_validation"] = {
        "verified": True,  # Claims verified
        "test_status": "passed",  # Claims passed
        "test_result": {
            "success": False,  # But underlying execution failed!
            "exit_code": 1,
            "failed_count": 2,
            "failed_tests": ["test_case_1", "test_case_2"],
            "passed_count": 0,
        },
    }
    cand["security_validation"] = {
        "security_status": "passed",
        "security_approved": True,
        "security_policy": "strict",
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert "failing test" in msg.lower() or "success=false" in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 5. Security Failure or Error
# =========================================================================

def test_security_failure_blocks_application(disposable_repo):
    """Candidate passing behavioral tests but introducing a security vulnerability must be blocked."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": True,
        "test_status": "passed",
        "passed_count": 1,
        "test_result": {"success": True, "exit_code": 0, "passed_count": 1, "failed_count": 0},
    }
    cand["security_validation"] = {
        "security_status": "failed",
        "security_approved": False,
        "security_policy": "strict",
        "failing_findings_count": 1,
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert "security scan failed" in msg.lower() or "failed security scan" in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


def test_security_scanner_error_blocks_application(disposable_repo):
    """Candidate with scanner infrastructure error must block normal patch application."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": True,
        "test_status": "passed",
        "passed_count": 1,
    }
    cand["security_validation"] = {
        "security_status": "error",
        "security_approved": False,
        "security_policy": "strict",
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
    assert ok is False
    assert "error during scan" in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 6. Incomplete Coverage Under Strict Policy
# =========================================================================

def test_incomplete_coverage_under_strict_policy_blocks_application(disposable_repo):
    """Incomplete security coverage (e.g. unsupported AST) must block application under strict policy."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": True,
        "test_status": "passed",
        "passed_count": 1,
    }
    cand["security_validation"] = {
        "security_status": "incomplete",
        "security_approved": False,
        "security_coverage": "unsupported",
        "security_policy": "strict",
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, force=False, security_policy="strict")
    assert ok is False
    assert "incomplete security coverage" in msg.lower()

    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 7. Explicitly Approved secrets_only Policy
# =========================================================================

def test_explicitly_approved_secrets_only_policy_allows_application(disposable_repo):
    """Explicitly approved candidate under secrets_only policy applies cleanly while preserving provenance."""
    cand = _make_base_candidate(disposable_repo)
    cand["error_type"] = "SecretsPolicyTestError"
    cand["sandbox_validation"] = {
        "verified": True,
        "test_status": "passed",
        "passed_count": 2,
    }
    cand["security_validation"] = {
        "security_status": "passed",
        "security_approved": True,
        "security_coverage": "unsupported",
        "security_policy": "secrets_only",
    }

    # 1. Under default strict policy, it must be rejected because it was only evaluated for secrets_only
    ok_strict, msg_strict = disposable_repo["engine"].apply_patch(cand, force=False, security_policy="strict")
    assert ok_strict is False
    assert "secrets_only" in msg_strict

    # 2. Under explicit secrets_only policy, it applies successfully
    ok, msg = disposable_repo["engine"].apply_patch(cand, approved_by="sec_admin", force=False, security_policy="secrets_only")
    assert ok is True
    assert "Successfully applied" in msg

    # File on disk must now reflect the patch
    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == cand["suggested_patch"]

    # Verify experience bank preserves policy provenance ('secrets_only')
    shots = disposable_repo["bank"].retrieve_few_shots(
        error_type="SecretsPolicyTestError",
        repo_id=cand.get("repo_id"),
        required_security_policy="secrets_only",
    )
    assert len(shots) > 0
    assert shots[0].security_policy == "secrets_only"
    assert shots[0].security_coverage == "unsupported"


# =========================================================================
# 8. Valid Behavioral and Security Approval
# =========================================================================

def test_valid_behavioral_and_security_approval_applies_cleanly(disposable_repo):
    """Candidate with consistent passing behavioral tests and clean security pass applies cleanly."""
    cand = _make_base_candidate(disposable_repo)
    cand["error_type"] = "ValidStrictApprovalError"
    cand["sandbox_validation"] = {
        "verified": True,
        "test_status": "passed",
        "iterations_count": 1,
        "passed_count": 3,
        "test_result": {
            "success": True,
            "exit_code": 0,
            "passed_count": 3,
            "failed_count": 0,
            "total_count": 3,
            "passed_tests": ["test_empty", "test_whitespace", "test_valid"],
            "failed_tests": [],
            "collection_errors": [],
        },
    }
    cand["security_validation"] = {
        "security_status": "passed",
        "security_approved": True,
        "security_coverage": "full",
        "security_policy": "strict",
        "failing_findings_count": 0,
    }

    ok, msg = disposable_repo["engine"].apply_patch(cand, approved_by="lead_dev", force=False)
    assert ok is True
    assert "Successfully applied" in msg

    # File was modified
    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == cand["suggested_patch"]

    # Backup file was created
    backups = [f for f in os.listdir(disposable_repo["tmp_dir"]) if f.startswith("app.py.bak")]
    assert len(backups) == 1

    # Recorded in experience bank with full strict security provenance
    shots = disposable_repo["bank"].retrieve_few_shots(
        error_type="ValidStrictApprovalError",
        repo_id=cand.get("repo_id"),
        required_security_policy="strict",
    )
    assert len(shots) > 0
    assert shots[0].security_approved is True
    assert shots[0].security_policy == "strict"
    assert shots[0].test_verified is True


# =========================================================================
# 9. Invariant: Source Files Unchanged After Every Rejection
# =========================================================================

def test_source_files_unchanged_after_every_rejection(disposable_repo):
    """Verifies invariant: every rejected candidate leaves source files untouched, creates no backups, and records no repair experiences."""
    rejection_payloads = [
        # Missing validation
        {},
        # Skipped validation
        {"sandbox_validation": {"verified": False, "test_status": "skipped"}},
        # Failed execution
        {"sandbox_validation": {"verified": False, "test_status": "failed", "test_result": {"success": False, "failed_count": 1}}},
        # Timed out
        {"sandbox_validation": {"verified": False, "test_status": "timed-out"}},
        # Zero tests
        {"sandbox_validation": {"verified": True, "test_status": "passed", "passed_count": 0}},
        # Security failed
        {
            "sandbox_validation": {"verified": True, "test_status": "passed", "passed_count": 1},
            "security_validation": {"security_status": "failed", "security_approved": False, "security_policy": "strict"},
        },
        # Security unscanned under strict
        {
            "sandbox_validation": {"verified": True, "test_status": "passed", "passed_count": 1},
            "security_validation": {"security_status": "unscanned", "security_approved": False, "security_policy": "strict"},
        },
    ]

    for idx, extra in enumerate(rejection_payloads):
        cand = _make_base_candidate(disposable_repo, suggested_patch=f"# evil payload {idx}\n")
        cand["error_type"] = "RejectionInvariantError"
        cand.update(extra)

        ok, msg = disposable_repo["engine"].apply_patch(cand, force=False)
        assert ok is False, f"Payload {idx} should have been rejected but passed: {msg}"

        # Target file content must be exactly original
        with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
            assert f.read() == disposable_repo["original_code"]

        # No backup files must exist
        backups = [f for f in os.listdir(disposable_repo["tmp_dir"]) if f.startswith("app.py.bak")]
        assert len(backups) == 0

        # No experiences should have been recorded for this error
        shots = disposable_repo["bank"].retrieve_few_shots(error_type="RejectionInvariantError")
        assert len(shots) == 0


# =========================================================================
# 10. Normal Approval Gate Cannot Be Bypassed with force=True
# =========================================================================

def test_force_flag_does_not_bypass_verification(disposable_repo):
    """Normal user/API approval must not silently bypass verification through force=True."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": False,
        "test_status": "failed",
    }
    cand["security_validation"] = {
        "security_status": "passed",
        "security_approved": True,
        "security_policy": "strict",
    }

    # Calling with force=True MUST still be blocked by the central gate
    ok_force, msg_force = disposable_repo["engine"].apply_patch(cand, force=True)
    assert ok_force is False
    assert "Approval rejected" in msg_force

    # Target file content must remain untouched
    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]


# =========================================================================
# 11. Entry Point Consistency: Saved Proposals & Backend API
# =========================================================================

def test_saved_proposal_approval_enforces_central_gate(disposable_repo):
    """Saved proposal approval via update_patch_status(status='applied') enforces the central gate."""
    cand = _make_base_candidate(disposable_repo)
    cand["sandbox_validation"] = {
        "verified": False,
        "test_status": "skipped",
    }
    patch_id = cand["patch_id"]

    # Insert into database as pending proposal
    db_manager.insert("generated_patches", cand)

    # Approve via update_patch_status (as done by CLI 'approve <id>')
    updated = disposable_repo["engine"].update_patch_status(patch_id, status="applied", user="cli_user")
    assert updated is not None
    assert updated.get("apply_result", {}).get("success") is False
    assert "skipped" in updated["apply_result"].get("message", "").lower()
    # Invariant: status must NOT be updated to 'applied' in DB
    assert updated.get("status") == "pending"

    stored = db_manager.find_one("generated_patches", {"patch_id": patch_id})
    assert stored["status"] == "pending"

    # Cleanup DB
    db_manager.delete("generated_patches", {"patch_id": patch_id})


def test_api_patch_approval_enforces_central_gate(disposable_repo):
    """REST API /api/patches/apply endpoint rejects unverified candidate with 400 Bad Request."""
    cand = _make_base_candidate(disposable_repo)
    cand["owner_id"] = "test_user_id"
    cand["repo_id"] = "test_repo_id"
    cand["sandbox_validation"] = {
        "verified": False,
        "test_status": "failed",
    }
    patch_id = cand["patch_id"]

    db_manager.insert("users", {
        "id": "test_user_id",
        "username": "tester",
        "email": "tester@example.com",
        "role": "developer",
    })
    db_manager.insert("generated_patches", cand)
    db_manager.insert("repositories", {
        "repo_id": "test_repo_id",
        "owner_id": "test_user_id",
        "repo_path": disposable_repo["tmp_dir"],
    })

    client = TestClient(app)
    from backend.auth import create_access_token, User
    user = User(id="test_user_id", username="tester", email="tester@example.com", role="developer")
    token = create_access_token(user)
    headers = {"Authorization": f"Bearer {token}"}

    with patch("backend.api.patches.get_repo_engine") as mock_get_engine:
        mock_get_engine.return_value = {
            "store": None,
            "embedder": None,
            "engine": MagicMock(llm=None),
            "graph": None,
            "meta": {"repo_path": disposable_repo["tmp_dir"]},
        }
        resp = client.post("/api/patches/apply", json={
            "patch_id": patch_id,
            "status": "applied",
        }, headers=headers)

    # Must reject with 400 Bad Request explaining verification failure
    assert resp.status_code == 400
    assert "Patch application failed" in resp.json()["detail"]
    assert "failed test verification" in resp.json()["detail"]

    # Target file must remain untouched
    with open(disposable_repo["target_abs"], "r", encoding="utf-8") as f:
        assert f.read() == disposable_repo["original_code"]

    # Clean up DB
    db_manager.delete("users", {"id": "test_user_id"})
    db_manager.delete("generated_patches", {"patch_id": patch_id})
    db_manager.delete("repositories", {"repo_id": "test_repo_id"})


def test_zero_test_sandbox_result_invariance_and_experience_rejection(disposable_repo):
    """
    Focused regression test verifying:
    1. Zero-test/skipped runs are strictly unverified (success=False, skipped=True, passed_count=0).
    2. Unverified candidates cannot become verified experiences in RepairExperienceBank.
    3. Strict security policy cannot silently become secrets_only.
    4. Tests and original repository files remain protected and immutable.
    """
    from core.sandbox_runner import SandboxRunner
    from core.patch_generator import PatchEngine, evaluate_patch_approval_gate
    from core.self_improving import RepairExperienceBank
    from core.vectorstore import FaissVectorStore
    from core.embedder import TfidfEmbedder
    import hashlib

    with tempfile.TemporaryDirectory(prefix="icx_zero_test_inv_") as tmp_dir:
        orphan_file = os.path.join(tmp_dir, "orphan_module.py")
        orig_code = "def compute():\n    return 42\n"
        with open(orphan_file, "w", encoding="utf-8") as f:
            f.write(orig_code)

        hash_before = hashlib.sha256(orig_code.encode("utf-8")).hexdigest()

        # 1. SandboxRunner contract on zero-test repository
        runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
        res = runner.run_tests_with_patch(
            repo_path=tmp_dir,
            target_file="orphan_module.py",
            patched_code="def compute():\n    return 100\n",
        )
        assert res.success is False, "Zero-test execution must return success=False"
        assert res.skipped is True, "Zero-test execution must return skipped=True"
        assert res.passed_count == 0, "Zero-test execution must report passed_count=0"

        # 2. PatchEngine integration and experience bank non-recording
        exp_bank_path = os.path.join(tmp_dir, "exp_bank.json")
        exp_bank = RepairExperienceBank(storage_path=exp_bank_path)
        engine = PatchEngine(
            store=FaissVectorStore(dim=64),
            embedder=TfidfEmbedder(),
            repo_path=tmp_dir,
            sandbox_runner=runner,
            experience_bank=exp_bank,
            is_admin=True,
        )

        record = engine.generate_and_verify_patch(
            repo_id="zero-test-repo",
            error_report="Test error on orphan module",
            target_file="orphan_module.py",
            max_iterations=1,
        )

        # Invariant: Must not be marked verified
        assert record["status"] != "verified", f"Zero-test repair must not be marked verified: {record['status']}"
        assert record["sandbox_validation"]["verified"] is False
        recorded_new = [e for e in exp_bank.experiences.values() if e.repo_id == "zero-test-repo"]
        assert len(recorded_new) == 0, "Unverified candidate was incorrectly recorded in experience bank"

        # 3. Central Approval Gate rejects candidate
        allowed, reason = evaluate_patch_approval_gate(record, security_policy="strict")
        assert not allowed, "Approval gate must reject unverified zero-test candidate"
        assert "skipped" in reason.lower() or "unverified" in reason.lower() or "passed" in reason.lower()

        # Strict security policy cannot silently become secrets_only
        assert record["security_validation"]["security_policy"] == "strict"
        bad_policy_record = dict(record)
        bad_policy_record["security_validation"] = dict(record["security_validation"])
        bad_policy_record["security_validation"]["security_policy"] = "secrets_only"
        bad_policy_record["sandbox_validation"] = {
            "verified": True,
            "test_status": "passed",
            "test_result": {"success": True, "exit_code": 0, "passed_count": 1, "failed_count": 0, "skipped": False},
        }
        # Gate under strict policy rejects secrets_only provenance
        allowed_strict, reason_strict = evaluate_patch_approval_gate(bad_policy_record, security_policy="strict")
        assert not allowed_strict
        assert "secrets_only" in reason_strict or "strict" in reason_strict

        # 4. Host files remain protected and immutable
        applied, apply_msg = engine.apply_patch(record, force=True)
        assert applied is False, "apply_patch must reject unverified patch even with force=True"
        assert "skipped" in apply_msg.lower() or "unverified" in apply_msg.lower()

        with open(orphan_file, "r", encoding="utf-8") as f:
            current_code = f.read()
        hash_after = hashlib.sha256(current_code.encode("utf-8")).hexdigest()
        assert hash_before == hash_after, "Host repository file was mutated by unverified patch application"

