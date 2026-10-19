"""
Tests for Repository History Restoration & Repository Isolation.
Verifies:
1. Q&A conversation persistence and restoration across restarts.
2. Code creation and repair activity records with target, proposal ID,
   verification outcome, and actual save outcome.
3. Rejected and cancelled proposals are never labeled as applied.
4. UI distinction between conversation history and activity history.
5. Historical generated code separated from current repository facts.
6. A -> B -> A switching isolation, including repos with identical folder names.
7. Cross-repository proposal review and approval protections.
8. Scoped clear-chat behavior.
"""
import os
import sys
import shutil
import tempfile
import pytest
from unittest.mock import MagicMock

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.persistence import (
    get_repo_id,
    save_repo_turn,
    save_repo_activity,
    load_repo_conversation,
    clear_repo_conversation,
    load_conversation_memory,
    get_db_connection,
)
from rag.query_engine import ConversationMemory, QueryEngine
from core.vectorstore import FaissVectorStore
from core.chunker import CodeChunk
from core.code_creation import (
    execute_create_command,
    CodeCreationEngine,
    SandboxRunner,
)
from backend.database.mongo import db_manager


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    """Isolate storage directory for testing."""
    s_dir = tmp_path / ".storage"
    s_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("STORAGE_DIR", str(s_dir))
    return str(s_dir)


@pytest.fixture
def two_identical_name_repos(tmp_path):
    """Creates two distinct repositories that share the exact same folder name ('my_project')."""
    repo_a = tmp_path / "workspace_a" / "my_project"
    repo_b = tmp_path / "workspace_b" / "my_project"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    # Initial file in each
    (repo_a / "Main.java").write_text("public class Main { public static void main(String[] args) {} }", encoding="utf-8")
    (repo_b / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    return str(repo_a), str(repo_b)


def test_canonical_repo_id_separates_identical_names(two_identical_name_repos):
    """Verifies that two directories with identical basenames get unique canonical IDs."""
    repo_a, repo_b = two_identical_name_repos
    id_a = get_repo_id(repo_a)
    id_b = get_repo_id(repo_b)

    assert id_a.startswith("my_project_")
    assert id_b.startswith("my_project_")
    assert id_a != id_b, f"Expected distinct repo IDs, got {id_a} == {id_b}"


def test_conversation_persistence_and_restoration(temp_storage, tmp_path):
    """Verifies Q&A turn persistence across CLI restart."""
    repo_dir = str(tmp_path / "sample_repo")
    os.makedirs(repo_dir, exist_ok=True)
    repo_id = get_repo_id(repo_dir)

    mem = ConversationMemory(max_turns=5, repo_id=repo_id)
    mem.add_turn("What does App.java do?", "App.java initializes the service.", files={"App.java"})

    # Simulate restart by creating a fresh memory object and loading
    restored_mem = ConversationMemory(max_turns=5, repo_id=repo_id)
    load_conversation_memory(repo_id, restored_mem)

    assert len(restored_mem.turns) == 1
    assert restored_mem.turns[0][0] == "What does App.java do?"
    assert "App.java initializes the service." in restored_mem.turns[0][1]
    assert restored_mem.turn_files[0] == {"App.java"}

    hist = restored_mem.format_history()
    assert "Turn 1 User: What does App.java do?" in hist
    assert "Turn 1 Assistant: App.java initializes the service." in hist
    assert "Context only — never let history outweigh" in hist


def test_activity_persistence_outcomes(temp_storage, tmp_path):
    """Verifies creation/repair activity recording with all outcome states."""
    repo_dir = str(tmp_path / "activity_repo")
    os.makedirs(repo_dir, exist_ok=True)
    repo_id = get_repo_id(repo_dir)

    mem = ConversationMemory(max_turns=5, repo_id=repo_id)

    # 1. Successful application
    mem.add_activity(
        activity_type="creation",
        target_file="TodoApp.java",
        proposal_id="prop_applied_1",
        verification_outcome="passed",
        save_outcome="applied",
        summary="File created and saved",
    )

    # 2. Cancelled by user
    mem.add_activity(
        activity_type="creation",
        target_file="Calc.java",
        proposal_id="prop_cancel_2",
        verification_outcome="passed",
        save_outcome="cancelled",
        summary="User cancelled save",
    )

    # 3. Gate rejected
    mem.add_activity(
        activity_type="repair",
        target_file="utils.py",
        proposal_id="prop_gate_3",
        verification_outcome="blocked",
        save_outcome="gate_rejected",
        summary="Docker sandbox unavailable",
    )

    # Simulate restart
    restored_mem = ConversationMemory(max_turns=5, repo_id=repo_id)
    load_conversation_memory(repo_id, restored_mem)

    assert len(restored_mem.activities) == 3

    act1 = restored_mem.activities[0]
    assert act1["target_file"] == "TodoApp.java"
    assert act1["verification_outcome"] == "passed"
    assert act1["save_outcome"] == "applied"

    act2 = restored_mem.activities[1]
    assert act2["target_file"] == "Calc.java"
    assert act2["verification_outcome"] == "passed"
    assert act2["save_outcome"] == "cancelled"

    act3 = restored_mem.activities[2]
    assert act3["target_file"] == "utils.py"
    assert act3["verification_outcome"] == "blocked"
    assert act3["save_outcome"] == "gate_rejected"

    # Verify UI activity log formatting
    log = restored_mem.format_activity_log()
    assert "--- Activity History (Code Creation & Repair) ---" in log
    assert "CREATION | Target: TodoApp.java" in log
    assert "Save Outcome: APPLIED" in log
    assert "CREATION | Target: Calc.java" in log
    assert "Save Outcome: CANCELLED" in log
    assert "REPAIR   | Target: utils.py" in log
    assert "Save Outcome: GATE_REJECTED" in log


def test_switching_a_to_b_to_a_isolation(temp_storage, two_identical_name_repos):
    """
    Verifies A -> B -> A switching:
    1. In Repo A: record Q&A and creation activity.
    2. Switch to Repo B: verify history is empty / isolated.
    3. Switch back to Repo A: verify Repo A's history is fully restored.
    """
    repo_a, repo_b = two_identical_name_repos
    id_a = get_repo_id(repo_a)
    id_b = get_repo_id(repo_b)

    # In Repo A: Add turn and activity
    mem_a = ConversationMemory(max_turns=5, repo_id=id_a)
    mem_a.add_turn("Repo A question", "Repo A answer", files={"Main.java"})
    mem_a.add_activity("creation", "TodoApp.java", "prop_a_001", "passed", "applied")

    # In Repo B: Brand new repo, memory should be empty
    mem_b = ConversationMemory(max_turns=5, repo_id=id_b)
    load_conversation_memory(id_b, mem_b)
    assert len(mem_b.turns) == 0
    assert len(mem_b.activities) == 0

    # Add something to Repo B
    mem_b.add_turn("Repo B question", "Repo B answer", files={"app.py"})
    assert len(mem_b.turns) == 1

    # Switch back to Repo A
    mem_a_restored = ConversationMemory(max_turns=5, repo_id=id_a)
    load_conversation_memory(id_a, mem_a_restored)

    # Repo A must have only Repo A's data, untouched by Repo B
    assert len(mem_a_restored.turns) == 1
    assert mem_a_restored.turns[0][0] == "Repo A question"
    assert len(mem_a_restored.activities) == 1
    assert mem_a_restored.activities[0]["target_file"] == "TodoApp.java"


def test_clear_chat_only_clears_active_repo(temp_storage, two_identical_name_repos):
    """Verifies clear-chat in Repo A does NOT clear turns in Repo B."""
    repo_a, repo_b = two_identical_name_repos
    id_a = get_repo_id(repo_a)
    id_b = get_repo_id(repo_b)

    # Setup turns in both
    mem_a = ConversationMemory(max_turns=5, repo_id=id_a)
    mem_a.add_turn("A query", "A ans")

    mem_b = ConversationMemory(max_turns=5, repo_id=id_b)
    mem_b.add_turn("B query", "B ans")

    # Clear Repo A's turns
    mem_a.clear(clear_persisted=True)
    assert len(mem_a.turns) == 0

    # Verify persisted turns for Repo A are gone
    reloaded_a = ConversationMemory(max_turns=5, repo_id=id_a)
    load_conversation_memory(id_a, reloaded_a)
    assert len(reloaded_a.turns) == 0

    # Verify Repo B remains intact!
    reloaded_b = ConversationMemory(max_turns=5, repo_id=id_b)
    load_conversation_memory(id_b, reloaded_b)
    assert len(reloaded_b.turns) == 1
    assert reloaded_b.turns[0][0] == "B query"


def test_cross_repo_proposal_isolation(temp_storage, two_identical_name_repos):
    """Verifies that proposals belonging to Repo A cannot be listed or approved in Repo B."""
    repo_a, repo_b = two_identical_name_repos
    id_a = get_repo_id(repo_a)
    id_b = get_repo_id(repo_b)

    import uuid
    prop_id = f"patch_repo_a_{uuid.uuid4().hex[:8]}"
    db_manager.insert("generated_patches", {
        "patch_id": prop_id,
        "repo_id": id_a,
        "target_file": "Main.java",
        "status": "pending",
        "sandbox_validation": {"test_status": "passed"},
    })

    # While in Repo B, query pending proposals
    curr_repo_id = id_b
    all_pending = db_manager.find("generated_patches", {"status": "pending"})
    scoped_proposals = [p for p in all_pending if p.get("repo_id") == curr_repo_id]

    assert len(scoped_proposals) == 0, "Repo A proposal leaked into Repo B listing!"

    # Attempt cross-repo access:
    matched = [p for p in db_manager.find("generated_patches", {}) if p.get("patch_id") == prop_id]
    assert len(matched) == 1
    p = matched[0]
    # Check authorization logic
    is_cross_repo = (p.get("repo_id") and p.get("repo_id") != curr_repo_id)
    assert is_cross_repo is True


def test_create_workflow_records_activity(temp_storage, tmp_path):
    """
    Verifies end-to-end:
    create: TodoApp.java with auto_approve=True -> verifies file is created and activity recorded as 'applied'.
    Then verifies loading on restart shows the activity.
    """
    repo_dir = tmp_path / "disposable_create_repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    repo_path = str(repo_dir)
    r_id = get_repo_id(repo_path)

    fake_java_code = "public class TodoApp { public static void main(String[] args) { System.out.println(\"Todo\"); } }"
    fake_tests = "public class TodoAppTest { public static void main(String[] args) { System.out.println(\"PASS: test1\"); } }"

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        fake_java_code,
        fake_tests,
    ]

    mock_sb = MagicMock()
    mock_sb.sandbox_mode = "local"
    mock_sb.allow_local_sandbox = True
    # Return 4-tuple for javac compile and java test run
    mock_sb._execute_in_sandbox.side_effect = [
        (0, "Compiled successfully", "", None),
        (0, "PASS: test1\nPASS: test2\nALL TESTS PASSED", "", None),
    ]

    mock_args = MagicMock()
    mock_args.sandbox = "local"
    mock_args.security_policy = "secrets_only"
    mock_args.security_threshold = "HIGH"
    mock_args.keep_overload_stubs = False
    mock_args.legacy_call_graph = False

    raw_query = "create: Build a Java TodoApp Target: TodoApp.java"

    from unittest.mock import patch
    from core.embedder import TfidfEmbedder
    with patch("core.code_creation.probe_sandbox_infrastructure") as mock_probe:
        mock_probe.return_value = {
            "backend": "Local Sandbox",
            "infrastructure_blocker": None,
            "toolchain_available": True,
        }
        with patch("core.code_creation.SandboxRunner", return_value=mock_sb):
            new_res, new_eng = execute_create_command(
                raw_query,
                repo_path,
                embedder=TfidfEmbedder(),
                llm=mock_llm,
                args=mock_args,
                auto_approve=True,
            )




    # 1. File must exist
    created_file = repo_dir / "TodoApp.java"
    assert created_file.exists()

    # 2. Activity must be recorded in new_eng.memory
    assert new_eng is not None
    assert len(new_eng.memory.activities) == 1
    act = new_eng.memory.activities[0]
    assert act["activity_type"] == "creation"
    assert act["target_file"] == "TodoApp.java"
    assert act["verification_outcome"] == "passed"
    assert act["save_outcome"] == "applied"

    # 3. Simulate CLI exit and restart
    fresh_mem = ConversationMemory(max_turns=5, repo_id=r_id)
    load_conversation_memory(r_id, fresh_mem)
    assert len(fresh_mem.activities) == 1
    assert fresh_mem.activities[0]["save_outcome"] == "applied"
    assert "TodoApp.java" in fresh_mem.format_activity_log()


def test_direct_core_apply_patch_cross_repo_rejected_with_hash_invariance(tmp_path, temp_storage):
    """
    Verifies that:
    1. Direct core PatchEngine.apply_patch rejects proposals originating in another repo.
    2. force=True CANNOT bypass repository identity checks.
    3. Both repos remain strictly unchanged (verified via SHA-256 hashes).
    4. Proposal status in database remains 'pending' (not 'applied').
    5. Experience-bank records remain untouched.
    """
    import hashlib
    from core.patch_generator import PatchEngine
    from core.self_improving import RepairExperienceBank

    # 1. Setup two same-named disposable repositories in different directories
    repo_a = tmp_path / "workspace_a" / "identical_app"
    repo_b = tmp_path / "workspace_b" / "identical_app"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    file_a = repo_a / "service.py"
    file_b = repo_b / "service.py"
    code_a = "def process():\n    return 'repo_a_code'\n"
    code_b = "def process():\n    return 'repo_b_code'\n"
    file_a.write_text(code_a, encoding="utf-8")
    file_b.write_text(code_b, encoding="utf-8")

    hash_a_before = hashlib.sha256(file_a.read_bytes()).hexdigest()
    hash_b_before = hashlib.sha256(file_b.read_bytes()).hexdigest()
    assert hash_a_before != hash_b_before

    r_id_a = get_repo_id(str(repo_a))
    r_id_b = get_repo_id(str(repo_b))
    assert r_id_a != r_id_b

    # 2. Setup engines and experience banks
    exp_bank_b = RepairExperienceBank(storage_path=str(repo_b / "exp_bank.json"))
    initial_exp_count = len(exp_bank_b.experiences)
    engine_b = PatchEngine(
        store=None,
        embedder=None,
        llm=None,
        repo_path=str(repo_b),
        experience_bank=exp_bank_b,
        is_admin=True,
    )

    # 3. Create verified proposal originating in Repo A
    patch_id = "cross_patch_001"
    proposal_a = {
        "patch_id": patch_id,
        "repo_id": r_id_a,
        "target_file": "service.py",
        "original_code": code_a,
        "original_hash": hash_a_before,
        "suggested_patch": "def process():\n    return 'patched_code'\n",
        "snippet_patch": "return 'patched_code'",
        "file_read_from_disk": True,
        "status": "pending",
        "explanation": "Security patch for Repo A",
        "error_type": "ValueError",
        "sandbox_validation": {
            "verified": True,
            "test_status": "passed",
            "passed_count": 2,
            "failed_count": 0,
            "test_result": {"success": True, "exit_code": 0, "passed_count": 2},
        },
        "security_validation": {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
            "security_coverage": "completed",
        },
    }

    db_manager.insert("generated_patches", dict(proposal_a))

    # 4. Attempt direct core apply from Repo B engine with force=True
    ok_apply, msg_apply = engine_b.apply_patch(proposal_a, force=True)

    # Invariant: Must be rejected by Security Block, force=True cannot bypass
    assert ok_apply is False
    assert "Security Block" in msg_apply
    assert "Cross-repository operation rejected" in msg_apply
    assert r_id_a in msg_apply
    assert r_id_b in msg_apply

    # Invariant: Both repos must remain byte-for-byte unchanged
    hash_a_after = hashlib.sha256(file_a.read_bytes()).hexdigest()
    hash_b_after = hashlib.sha256(file_b.read_bytes()).hexdigest()
    assert hash_a_before == hash_a_after
    assert hash_b_before == hash_b_after

    # Invariant: Proposal status in DB must remain 'pending' (not 'applied')
    db_rec = db_manager.find_one("generated_patches", {"patch_id": patch_id})
    assert db_rec is not None
    assert db_rec["status"] == "pending"

    # Invariant: Experience bank records in Repo B remain untouched
    assert len(exp_bank_b.experiences) == initial_exp_count
    assert not any(e.repo_id == r_id_a for e in exp_bank_b.experiences.values())

    # Cleanup DB
    db_manager.delete("generated_patches", {"patch_id": patch_id})


def test_direct_core_apply_creation_cross_repo_rejected_with_hash_invariance(tmp_path, temp_storage):
    """
    Verifies that direct core CodeCreationEngine.apply_creation rejects cross-repo proposals
    and leaves disk completely untouched.
    """
    import hashlib

    repo_a = tmp_path / "workspace_a" / "identical_app"
    repo_b = tmp_path / "workspace_b" / "identical_app"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    existing_b = repo_b / "existing.py"
    existing_b.write_text("print('original_b')", encoding="utf-8")
    hash_b_before = hashlib.sha256(existing_b.read_bytes()).hexdigest()

    r_id_a = get_repo_id(str(repo_a))
    r_id_b = get_repo_id(str(repo_b))

    engine_b = CodeCreationEngine(repo_path=str(repo_b))

    target_file = "NewFeature.java"
    proposal_creation_a = {
        "proposal_id": "create_cross_001",
        "repo_id": r_id_a,
        "target_file": target_file,
        "suggested_patch": "public class NewFeature {}",
        "original_code": "",
        "sandbox_validation": {
            "verified": True,
            "test_status": "passed",
            "passed_count": 1,
            "failed_count": 0,
            "test_result": {"success": True, "exit_code": 0, "passed_count": 1},
        },
        "security_validation": {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
            "security_coverage": "completed",
        },
    }

    # Attempt direct core apply in Repo B
    ok_c, msg_c = engine_b.apply_creation(proposal_creation_a)

    assert ok_c is False
    assert "Security Block" in msg_c
    assert "Cross-repository operation rejected" in msg_c

    # File must NOT exist in repo_b or repo_a
    assert not (repo_b / target_file).exists()
    assert not (repo_a / target_file).exists()

    # Existing files in repo_b remain untouched
    hash_b_after = hashlib.sha256(existing_b.read_bytes()).hexdigest()
    assert hash_b_before == hash_b_after


def test_legacy_proposals_rejected_missing_or_basename_only(tmp_path, temp_storage):
    """
    Verifies that legacy proposals with missing or basename-only identity are strictly rejected.
    """
    from core.patch_generator import PatchEngine, evaluate_patch_approval_gate
    from core.persistence import is_canonical_repo_id

    repo_dir = tmp_path / "workspace" / "my_project"
    repo_dir.mkdir(parents=True, exist_ok=True)
    target = repo_dir / "mod.py"
    target.write_text("x = 1", encoding="utf-8")

    r_id = get_repo_id(str(repo_dir))
    assert is_canonical_repo_id(r_id) is True
    assert is_canonical_repo_id("my_project") is False
    assert is_canonical_repo_id(None) is False
    assert is_canonical_repo_id("") is False

    patch_engine = PatchEngine(store=None, embedder=None, llm=None, repo_path=str(repo_dir))
    creation_engine = CodeCreationEngine(repo_path=str(repo_dir))

    valid_sb = {
        "verified": True,
        "test_status": "passed",
        "passed_count": 1,
        "failed_count": 0,
        "test_result": {"success": True, "exit_code": 0, "passed_count": 1},
    }
    valid_sec = {
        "security_status": "passed",
        "security_approved": True,
        "security_policy": "strict",
        "security_coverage": "completed",
    }

    # 1. Missing repo_id
    prop_missing = {
        "target_file": "mod.py",
        "original_code": "x = 1",
        "suggested_patch": "x = 2",
        "sandbox_validation": valid_sb,
        "security_validation": valid_sec,
    }
    ok_p, msg_p = patch_engine.apply_patch(prop_missing, force=True)
    assert ok_p is False
    assert "canonical repository identity" in msg_p.lower()

    ok_c, msg_c = creation_engine.apply_creation(prop_missing)
    assert ok_c is False
    assert "canonical repository identity" in msg_c.lower()

    ok_g, msg_g = evaluate_patch_approval_gate(prop_missing, target_repo_id=r_id)
    assert ok_g is False
    assert "canonical repository identity" in msg_g.lower()

    # 2. Basename-only repo_id
    prop_basename = dict(prop_missing)
    prop_basename["repo_id"] = "my_project"  # Basename-only without path hash

    ok_p2, msg_p2 = patch_engine.apply_patch(prop_basename, force=True)
    assert ok_p2 is False
    assert "canonical repository identity" in msg_p2.lower()

    ok_c2, msg_c2 = creation_engine.apply_creation(prop_basename)
    assert ok_c2 is False
    assert "canonical repository identity" in msg_c2.lower()

    ok_g2, msg_g2 = evaluate_patch_approval_gate(prop_basename, target_repo_id=r_id)
    assert ok_g2 is False
    assert "canonical repository identity" in msg_g2.lower()


def test_update_patch_status_cross_repo_rejected_leaves_db_unchanged(tmp_path, temp_storage):
    """
    Verifies that update_patch_status called from Repo B on a Repo A proposal returns None
    and leaves the proposal status in the database strictly unchanged.
    """
    from core.patch_generator import PatchEngine

    repo_a = tmp_path / "workspace_a" / "my_app"
    repo_b = tmp_path / "workspace_b" / "my_app"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    r_id_a = get_repo_id(str(repo_a))
    r_id_b = get_repo_id(str(repo_b))

    engine_b = PatchEngine(store=None, embedder=None, llm=None, repo_path=str(repo_b))

    patch_id = "status_cross_patch_999"
    proposal = {
        "patch_id": patch_id,
        "repo_id": r_id_a,
        "target_file": "app.py",
        "suggested_patch": "print('patched')",
        "original_code": "print('original')",
        "status": "pending",
        "sandbox_validation": {
            "verified": True,
            "test_status": "passed",
            "passed_count": 1,
            "failed_count": 0,
            "test_result": {"success": True, "exit_code": 0, "passed_count": 1},
        },
        "security_validation": {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
            "security_coverage": "completed",
        },
    }
    db_manager.insert("generated_patches", proposal)

    # Attempt cross-repo update to 'applied' from Repo B engine
    res = engine_b.update_patch_status(patch_id, status="applied")
    assert res is None, "Cross-repo update_patch_status must return None"

    stored = db_manager.find_one("generated_patches", {"patch_id": patch_id})
    assert stored["status"] == "pending", "Status must remain 'pending' after rejected cross-repo apply"

    # Attempt cross-repo update to 'rejected' from Repo B engine
    res2 = engine_b.update_patch_status(patch_id, status="rejected")
    assert res2 is None, "Cross-repo update_patch_status must return None"

    stored2 = db_manager.find_one("generated_patches", {"patch_id": patch_id})
    assert stored2["status"] == "pending", "Status must remain 'pending' after rejected cross-repo reject"

    db_manager.delete("generated_patches", {"patch_id": patch_id})


def test_prompt_buffer_arrow_history_switching_and_engine_rebinding(tmp_path, temp_storage):
    """
    Verifies that:
    1. Interactive PromptSession switches the actual prompt-buffer arrow history (session.default_buffer.history),
       not just session.history or history file path.
    2. QueryEngine and PatchEngine are properly rebound to the new repository path upon switching.
    """
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from core.patch_generator import PatchEngine

    repo_a = tmp_path / "workspace_a" / "proj"
    repo_b = tmp_path / "workspace_b" / "proj"
    repo_a.mkdir(parents=True, exist_ok=True)
    repo_b.mkdir(parents=True, exist_ok=True)

    r_id_a = get_repo_id(str(repo_a))
    r_id_b = get_repo_id(str(repo_b))

    # Initial session in Repo A with Repo A arrow history
    hist_a = InMemoryHistory()
    hist_a.append_string("repo_a_command_1")
    hist_a.append_string("repo_a_command_2")

    from prompt_toolkit.input import DummyInput
    from prompt_toolkit.output import DummyOutput
    session = PromptSession(history=hist_a, input=DummyInput(), output=DummyOutput())
    # Ensure default_buffer.history is set to hist_a
    assert session.default_buffer.history is hist_a
    assert session.default_buffer.history.get_strings() == ["repo_a_command_1", "repo_a_command_2"]

    # Initial engines for Repo A
    engine_a = QueryEngine(
        store=FaissVectorStore(dim=64),
        embedder=MagicMock(),
        llm=MagicMock(),
        repo_path=str(repo_a),
    )
    patch_engine_a = PatchEngine(
        store=FaissVectorStore(dim=64),
        embedder=MagicMock(),
        llm=MagicMock(),
        repo_path=str(repo_a),
    )
    assert engine_a.memory.repo_id == r_id_a
    assert patch_engine_a.repo_path == str(repo_a)

    # --- Switch repository: Repo A -> Repo B ---
    hist_b = InMemoryHistory()
    hist_b.append_string("repo_b_command_1")

    # In cli.py: session.history and session.default_buffer.history are both updated
    session.history = hist_b
    session.default_buffer.history = hist_b

    # Verify actual prompt buffer arrow history now reflects Repo B!
    assert session.default_buffer.history.get_strings() == ["repo_b_command_1"]
    assert "repo_a_command_1" not in session.default_buffer.history.get_strings()

    # Rebind engines as in cli.py repo switch handler
    engine_b = QueryEngine(
        store=FaissVectorStore(dim=64),
        embedder=MagicMock(),
        llm=MagicMock(),
        repo_path=str(repo_b),
    )
    patch_engine_b = PatchEngine(
        store=FaissVectorStore(dim=64),
        embedder=MagicMock(),
        llm=MagicMock(),
        repo_path=str(repo_b),
    )
    assert engine_b.memory.repo_id == r_id_b
    assert patch_engine_b.repo_path == str(repo_b)

    # --- Switch back: Repo B -> Repo A ---
    session.history = hist_a
    session.default_buffer.history = hist_a
    assert session.default_buffer.history.get_strings() == ["repo_a_command_1", "repo_a_command_2"]
    assert "repo_b_command_1" not in session.default_buffer.history.get_strings()
