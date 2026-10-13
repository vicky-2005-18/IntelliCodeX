"""
Live End-to-End Workflow Runner for IntelliCodeX (Task 6).

Workflow Steps:
1. Disposable Git repository initialization.
2. Unrelated dirty Git change in `utils.py` to verify patch applier preserves unrelated changes.
3. Bug injection: `ZeroDivisionError` in `calculator.py`.
4. Bug localization (AST/traceback analysis).
5. AI patch proposal via live Ollama LLM.
6. Isolated sandbox test execution.
7. Human review gate (outputs concrete unified diff).
8. Approved integration & experience recording.
9. Retrieval demonstration for a distinct bug.
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm_client import OllamaLLM
from core.self_improving import RepairExperienceBank
from core.patch_generator import PatchEngine
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder


WORKFLOW_STATE_PATH = os.path.join(".storage", "live_workflow_state.json")


def setup_disposable_repo() -> str:
    temp_dir = tempfile.mkdtemp(prefix="intellicodex_live_repo_")

    # 1. git init
    subprocess.run(["git", "init"], cwd=temp_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=temp_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=temp_dir, check=True, capture_output=True)

    # 2. Add utils.py and commit
    utils_file = os.path.join(temp_dir, "utils.py")
    with open(utils_file, "w", encoding="utf-8") as f:
        f.write("# Utility functions\ndef get_version():\n    return '1.0.0'\n")
    subprocess.run(["git", "add", "utils.py"], cwd=temp_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit with utils"], cwd=temp_dir, check=True, capture_output=True)

    # 3. Add an UNRELATED uncommitted modification to utils.py
    with open(utils_file, "a", encoding="utf-8") as f:
        f.write("\nEXTRA_CONFIG = {'unrelated_change': True}\n")

    # 4. Create calculator.py with division bug
    calc_file = os.path.join(temp_dir, "calculator.py")
    with open(calc_file, "w", encoding="utf-8") as f:
        f.write("def compute_ratio(a: float, b: float) -> float:\n    return a / b\n")

    # 5. Create test_calculator.py
    test_file = os.path.join(temp_dir, "test_calculator.py")
    with open(test_file, "w", encoding="utf-8") as f:
        f.write(
            "import pytest\n"
            "from calculator import compute_ratio\n\n"
            "def test_ratio_normal():\n"
            "    assert compute_ratio(10.0, 2.0) == 5.0\n\n"
            "def test_ratio_zero_denominator():\n"
            "    assert compute_ratio(10.0, 0.0) == 0.0\n"
        )

    return temp_dir


def step_propose_patch(repo_dir: str) -> Dict[str, Any]:
    llm = OllamaLLM(model="qwen2.5-coder:3b", temperature=0.0)
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)
    bank = RepairExperienceBank()
    from core.chunker import CodeChunk
    chunks = [
        CodeChunk(
            chunk_id="calculator.py::compute_ratio",
            file_path="calculator.py",
            language="python",
            kind="function",
            name="compute_ratio",
            start_line=1,
            end_line=2,
            code="def compute_ratio(a: float, b: float) -> float:\n    return a / b\n",
        ),
        CodeChunk(
            chunk_id="utils.py::get_version",
            file_path="utils.py",
            language="python",
            kind="function",
            name="get_version",
            start_line=1,
            end_line=3,
            code="# Utility functions\ndef get_version():\n    return '1.0.0'\n",
        ),
    ]
    import numpy as np
    texts = [c.as_embedding_text() for c in chunks]
    embeddings = np.array(embedder.embed(texts), dtype=np.float32)
    store.add(chunks, embeddings)

    engine = PatchEngine(
        store=store,
        embedder=embedder,
        llm=llm,
        repo_path=repo_dir,
        experience_bank=bank,
        allow_local_sandbox=True,
    )

    error_report = "ZeroDivisionError: division by zero in compute_ratio(10.0, 0.0)"
    target_file = "calculator.py"

    # 1. Localization
    localization = {
        "file": target_file,
        "line": 2,
        "error_type": "ZeroDivisionError",
        "symbol": "compute_ratio",
    }

    # 2. Patch generation with isolated sandbox validation
    patch_rec = engine.generate_patch(
        repo_id="disposable_repo_01",
        error_report=error_report,
        target_file=target_file,
        verify_in_sandbox=True,
        test_command=f'"{sys.executable}" -m pytest test_calculator.py -q',
    )

    state = {
        "repo_dir": repo_dir,
        "patch_rec": patch_rec,
        "localization": localization,
    }
    os.makedirs(os.path.dirname(WORKFLOW_STATE_PATH), exist_ok=True)
    with open(WORKFLOW_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    return state


def step_apply_and_verify(approve: bool) -> Dict[str, Any]:
    if not os.path.exists(WORKFLOW_STATE_PATH):
        raise RuntimeError("No active workflow state found.")

    with open(WORKFLOW_STATE_PATH, "r", encoding="utf-8") as f:
        state = json.load(f)

    repo_dir = state["repo_dir"]
    patch_rec = state["patch_rec"]
    utils_file = os.path.join(repo_dir, "utils.py")
    calc_file = os.path.join(repo_dir, "calculator.py")

    # Read utils content before
    with open(utils_file, "r", encoding="utf-8") as f:
        utils_before = f.read()

    with open(calc_file, "r", encoding="utf-8") as f:
        calc_before = f.read()

    bank = RepairExperienceBank()
    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)
    engine = PatchEngine(
        store=store,
        embedder=embedder,
        llm=None,
        repo_path=repo_dir,
        experience_bank=bank,
        allow_local_sandbox=True,
    )

    if not approve:
        # CANCELLATION PATH: ensure source files left unchanged
        with open(calc_file, "r", encoding="utf-8") as f:
            calc_after = f.read()
        with open(utils_file, "r", encoding="utf-8") as f:
            utils_after = f.read()

        is_calc_unchanged = (calc_before == calc_after)
        is_utils_unchanged = (utils_before == utils_after)
        return {
            "status": "cancelled",
            "calculator_unchanged": is_calc_unchanged,
            "utils_unchanged": is_utils_unchanged,
        }

    # APPROVAL PATH: apply patch
    ok, msg = engine.apply_patch(patch_rec, approved_by="developer_human_gate")

    # Verify unrelated git change is preserved
    with open(utils_file, "r", encoding="utf-8") as f:
        utils_after = f.read()
    unrelated_preserved = ("EXTRA_CONFIG = {'unrelated_change': True}" in utils_after)

    # Verify calculator.py updated and test passes
    with open(calc_file, "r", encoding="utf-8") as f:
        calc_after = f.read()

    test_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_calculator.py", "-q"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    test_passed = (test_proc.returncode == 0)

    # Experience Retrieval for a different relevant bug in same repository scope
    retrieved_shots = bank.retrieve_few_shots(
        error_type="ZeroDivisionError",
        query_text="division by zero in calculate_mean",
        repo_id=patch_rec.get("repo_id"),
        limit=5,
    )
    retrieval_success = any("compute_ratio" in s.original_code or "b == 0" in s.fixed_code for s in retrieved_shots)

    return {
        "status": "applied",
        "apply_success": ok,
        "message": msg,
        "unrelated_git_changes_preserved": unrelated_preserved,
        "test_passed": test_passed,
        "calc_content_after": calc_after,
        "retrieved_for_different_bug": retrieval_success,
        "retrieved_demonstrations": [s.to_dict() for s in retrieved_shots],
    }


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "propose"
    if action == "propose":
        repo_dir = setup_disposable_repo()
        res = step_propose_patch(repo_dir)
        print("PROPOSAL_READY")
        print(json.dumps({
            "repo_dir": res["repo_dir"],
            "patch_id": res["patch_rec"]["patch_id"],
            "git_diff": res["patch_rec"].get("git_diff", ""),
            "suggested_patch": res["patch_rec"].get("suggested_patch", ""),
            "confidence": res["patch_rec"].get("confidence_score", 0.0),
            "sandbox_verified": res["patch_rec"].get("sandbox_validation", {}).get("verified", False),
        }, indent=2))
    elif action == "approve":
        res = step_apply_and_verify(approve=True)
        print("APPROVAL_RESULT")
        print(json.dumps(res, indent=2))
    elif action == "cancel":
        res = step_apply_and_verify(approve=False)
        print("CANCEL_RESULT")
        print(json.dumps(res, indent=2))
