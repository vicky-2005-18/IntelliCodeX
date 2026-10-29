"""
Evaluates IntelliCodeX contract propagation and repair pipeline across:
1. Explicit return-value and boundary condition contracts.
2. Specific exception contracts (e.g. KeyError / ZeroDivisionError).
3. Cross-file repair cases (callee repaired to satisfy caller integration tests).

Uses the live model (qwen2.5-coder:7b) and Docker sandbox (intellicodex-sandbox:latest).
"""
import os
import sys
import tempfile
import time
import json
import pytest

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.llm_client import OllamaLLM
from core.sandbox_runner import SandboxRunner
from core.patch_generator import PatchEngine
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.persistence import get_repo_id

import numpy as np

class DummyEmbedder(BaseEmbedder):
    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, texts):
        return np.zeros((len(texts), self.dim), dtype="float32")

def run_case_boundary_and_return_value():
    print("\n" + "="*70)
    print("RUNNING CASE 1: Boundary & Return-Value Contract")
    print("="*70)
    with tempfile.TemporaryDirectory(prefix="icx_eval_boundary_") as tmp_dir:
        target_code = (
            "def clamp_value(val, low, high, fallback=-1):\n"
            "    \"\"\"Clamps val between low and high. If val is None, returns fallback.\"\"\"\n"
            "    if val is None:\n"
            "        return 0  # BUG: returns 0 instead of fallback\n"
            "    if val < low:\n"
            "        return high  # BUG: returns high instead of low\n"
            "    if val > high:\n"
            "        return high\n"
            "    return val\n"
        )
        target_file = "validator.py"
        with open(os.path.join(tmp_dir, target_file), "w", encoding="utf-8") as f:
            f.write(target_code)

        test_code = (
            "import pytest\n"
            "from validator import clamp_value\n\n"
            "def test_clamp_fallback():\n"
            "    # Grounded in: fallback specification\n"
            "    assert clamp_value(None, 0, 10, fallback=999) == 999\n\n"
            "def test_clamp_low_boundary():\n"
            "    # Grounded in: lower boundary clamping\n"
            "    assert clamp_value(-5, 0, 10) == 0\n\n"
            "def test_clamp_normal():\n"
            "    assert clamp_value(5, 0, 10) == 5\n"
        )
        extra_files = {"test_validator.py": test_code}

        llm = OllamaLLM(model="qwen2.5-coder:7b", temperature=0.0)
        sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
        store = FaissVectorStore(dim=384)
        engine = PatchEngine(
            store=store,
            embedder=DummyEmbedder(),
            llm=llm,
            repo_path=tmp_dir,
            sandbox_runner=sb,
            is_admin=True,
            allow_local_sandbox=True,
        )

        user_contract = (
            "Contract: clamp_value(val, low, high, fallback=-1)\n"
            "- If val is None, must return the exact fallback value parameter.\n"
            "- If val < low, must return low.\n"
            "- If val > high, must return high.\n"
            "- Otherwise return val."
        )

        error_report = (
            "[ACCEPTED CONTRACT SPECIFICATION (MANDATORY REQUIREMENT)]:\n"
            f"{user_contract}\n\n"
            "Baseline test failures:\n"
            "- test_clamp_fallback (expected 999, got 0)\n"
            "- test_clamp_low_boundary (expected 0, got 10)\n"
        )

        patch_rec = engine.generate_patch(
            repo_id=get_repo_id(tmp_dir),
            error_report=error_report,
            target_file=target_file,
            verify_in_sandbox=True,
            max_iterations=3,
            extra_files=extra_files,
            user_contract=user_contract,
        )

        status = patch_rec.get("status")
        verified = patch_rec.get("sandbox_validation", {}).get("verified", False)
        print(f"Outcome: status={status}, verified={verified}")
        print(f"Diff:\n{patch_rec.get('git_diff')}")
        return {
            "case": "Boundary & Return-Value Contract",
            "status": "autonomously repaired" if verified else "safely unresolved",
            "verified": verified,
            "diff": patch_rec.get("git_diff"),
        }

def run_case_specific_exception():
    print("\n" + "="*70)
    print("RUNNING CASE 2: Specific Exception Type Contract (KeyError on missing required key)")
    print("="*70)
    with tempfile.TemporaryDirectory(prefix="icx_eval_exception_") as tmp_dir:
        target_code = (
            "def parse_user_config(config_dict):\n"
            "    \"\"\"Parses user config. Raises KeyError if 'username' is missing.\"\"\"\n"
            "    if not isinstance(config_dict, dict):\n"
            "        raise TypeError('Expected dict')\n"
            "    if 'username' not in config_dict:\n"
            "        raise ValueError('Missing username')  # BUG: raises ValueError instead of KeyError\n"
            "    return config_dict['username'].strip().lower()\n"
        )
        target_file = "config_parser.py"
        with open(os.path.join(tmp_dir, target_file), "w", encoding="utf-8") as f:
            f.write(target_code)

        test_code = (
            "import pytest\n"
            "from config_parser import parse_user_config\n\n"
            "def test_parse_success():\n"
            "    assert parse_user_config({'username': ' Alice '}) == 'alice'\n\n"
            "def test_missing_username_raises_keyerror():\n"
            "    # Grounded in: contract requiring KeyError for missing dictionary key\n"
            "    with pytest.raises(KeyError):\n"
            "        parse_user_config({'email': 'alice@example.com'})\n"
        )
        extra_files = {"test_config_parser.py": test_code}

        llm = OllamaLLM(model="qwen2.5-coder:7b", temperature=0.0)
        sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
        store = FaissVectorStore(dim=384)
        engine = PatchEngine(
            store=store,
            embedder=DummyEmbedder(),
            llm=llm,
            repo_path=tmp_dir,
            sandbox_runner=sb,
            is_admin=True,
            allow_local_sandbox=True,
        )

        user_contract = (
            "Contract: parse_user_config(config_dict)\n"
            "- When 'username' is missing, MUST raise KeyError('username'). "
            "DO NOT raise ValueError or generic Exception."
        )

        error_report = (
            "[ACCEPTED CONTRACT SPECIFICATION (MANDATORY REQUIREMENT)]:\n"
            f"{user_contract}\n\n"
            "Baseline test failure:\n"
            "- test_missing_username_raises_keyerror (expected KeyError, actual ValueError: Missing username)\n"
        )

        patch_rec = engine.generate_patch(
            repo_id=get_repo_id(tmp_dir),
            error_report=error_report,
            target_file=target_file,
            verify_in_sandbox=True,
            max_iterations=3,
            extra_files=extra_files,
            user_contract=user_contract,
        )

        status = patch_rec.get("status")
        verified = patch_rec.get("sandbox_validation", {}).get("verified", False)
        print(f"Outcome: status={status}, verified={verified}")
        print(f"Diff:\n{patch_rec.get('git_diff')}")
        return {
            "case": "Specific Exception Contract (KeyError)",
            "status": "autonomously repaired" if verified else "safely unresolved",
            "verified": verified,
            "diff": patch_rec.get("git_diff"),
        }

def run_case_cross_file_repair():
    print("\n" + "="*70)
    print("RUNNING CASE 3: Cross-File Repair (Callee repaired to satisfy Caller integration test)")
    print("="*70)
    with tempfile.TemporaryDirectory(prefix="icx_eval_crossfile_") as tmp_dir:
        # Callee file to repair
        os.makedirs(os.path.join(tmp_dir, "utils"), exist_ok=True)
        os.makedirs(os.path.join(tmp_dir, "services"), exist_ok=True)
        os.makedirs(os.path.join(tmp_dir, "tests"), exist_ok=True)

        callee_file = "utils/formatter.py"
        callee_code = (
            "def format_records(items, delimiter=','):\n"
            "    \"\"\"Joins items using delimiter. Strips whitespace from each item.\"\"\"\n"
            "    # BUG: joins with hardcoded space instead of delimiter, misses item stripping\n"
            "    return ' '.join(str(x) for x in items)\n"
        )
        with open(os.path.join(tmp_dir, callee_file), "w", encoding="utf-8") as f:
            f.write(callee_code)

        # Caller file
        caller_file = "services/export_service.py"
        caller_code = (
            "from utils.formatter import format_records\n\n"
            "def export_csv_row(columns):\n"
            "    return format_records(columns, delimiter=',')\n"
        )
        with open(os.path.join(tmp_dir, caller_file), "w", encoding="utf-8") as f:
            f.write(caller_code)

        # Integration test in tests/
        test_file = "tests/test_export_service.py"
        test_code = (
            "import pytest\n"
            "from services.export_service import export_csv_row\n\n"
            "def test_export_csv_row_formatting():\n"
            "    # Grounded in: export_service calling format_records with delimiter=','\n"
            "    res = export_csv_row(['alpha ', ' beta', 'gamma'])\n"
            "    assert res == 'alpha,beta,gamma'\n"
        )
        with open(os.path.join(tmp_dir, test_file), "w", encoding="utf-8") as f:
            f.write(test_code)

        llm = OllamaLLM(model="qwen2.5-coder:7b", temperature=0.0)
        sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
        store = FaissVectorStore(dim=384)
        engine = PatchEngine(
            store=store,
            embedder=DummyEmbedder(),
            llm=llm,
            repo_path=tmp_dir,
            sandbox_runner=sb,
            is_admin=True,
            allow_local_sandbox=True,
        )

        user_contract = (
            "Contract: format_records(items, delimiter=',')\n"
            "- Strips leading and trailing whitespace from each string item.\n"
            "- Joins the stripped items using the given delimiter string."
        )

        error_report = (
            "[ACCEPTED CONTRACT SPECIFICATION (MANDATORY REQUIREMENT)]:\n"
            f"{user_contract}\n\n"
            f"Cross-file caller test failure in '{test_file}':\n"
            "- test_export_csv_row_formatting: assert 'alpha  beta gamma' == 'alpha,beta,gamma'\n"
        )

        patch_rec = engine.generate_patch(
            repo_id=get_repo_id(tmp_dir),
            error_report=error_report,
            target_file=callee_file,
            verify_in_sandbox=True,
            max_iterations=3,
            user_contract=user_contract,
        )

        status = patch_rec.get("status")
        verified = patch_rec.get("sandbox_validation", {}).get("verified", False)
        print(f"Outcome: status={status}, verified={verified}")
        print(f"Diff:\n{patch_rec.get('git_diff')}")
        return {
            "case": "Cross-File Repair (format_records for export_service)",
            "status": "autonomously repaired" if verified else "safely unresolved",
            "verified": verified,
            "diff": patch_rec.get("git_diff"),
        }

if __name__ == "__main__":
    results = []
    results.append(run_case_boundary_and_return_value())
    results.append(run_case_specific_exception())
    results.append(run_case_cross_file_repair())

    with open("scratch/contract_repair_suite_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\n" + "="*70)
    print("ALL 3 CONTRACT REPAIR CASES COMPLETED")
    for r in results:
        print(f"  - {r['case']}: {r['status']}")
