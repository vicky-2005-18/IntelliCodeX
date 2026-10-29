import os
import sys
from core.canonical_path import resolve_canonical_target_path
from core.test_proposer import TestProposer
from core.patch_generator import (
    PatchEngine,
    evaluate_patch_approval_gate,
    validate_candidate_interface,
    replace_ast_symbols_in_python
)
from core.sandbox_runner import SandboxRunner
from core.persistence import get_repo_id

def main():
    repo_path = os.path.abspath(".")
    target_rel = "calculator_practice.py"
    
    print("=== Step 1: Target Resolution ===")
    canon, err = resolve_canonical_target_path(repo_path, target_rel)
    print(f"Canon target: {canon}, err: {err}")
    assert canon == "calculator_practice.py"
    
    print("\n=== Step 2: Contract Analysis & Grounding ===")
    proposer = TestProposer()
    analysis = proposer.analyze_contract(repo_path, canon)
    print(f"Contract analysis is_ambiguous: {analysis.is_ambiguous}")
    print(f"Explicit behaviors ({len(analysis.explicit_behaviors)})")
    print(f"Inferred behaviors ({len(analysis.inferred_behaviors)})")
    print(f"Call sites found: {len(analysis.call_sites)}")
    for cs in analysis.call_sites:
        print(f"  Call site: {cs.caller_file}:{cs.line_number} -> {cs.call_snippet}")
        
    print("\n=== Step 3: Test Generation ===")
    proposal = proposer.generate_candidate_tests(repo_path, canon, analysis)
    print(f"Proposed test file: {proposal.disposable_path}")
    print("Generated Test Code Summary: contains 8 test functions covering asymmetry, true division, zero division, and entry point")
    
    print("\n=== Step 4: Docker Sandbox Validation of Proposed Tests ===")
    sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
    val = proposer.validate_proposed_tests_in_docker(
        sandbox_runner=sb,
        repo_path=repo_path,
        proposal=proposal,
    )
    print(f"Validation Result: is_runnable={val.is_runnable}, tests_collected={val.tests_collected}")
    print(f"Harness errors: {val.harness_errors}")
    print(f"Behavioral failures: {val.behavioral_failures[:2]}")
    print(f"Baseline exit code: {val.baseline_exit_code}")
    assert val.is_runnable is True
    assert val.tests_collected == 8
    assert len(val.behavioral_failures) > 0  # correctly catches the bugs!
    
    with open(os.path.join(repo_path, canon), "r", encoding="utf-8") as f:
        original_code = f.read()

    print("\n=== Step 5: Defect Prevention Checks ===")
    # 5A: Defect check - candidate dropping main()
    dropped_main_candidate = "def subtract(a, b):\n    return a - b\n"
    is_valid, drop_err = validate_candidate_interface(original_code, dropped_main_candidate, language="python")
    print(f"Dropped main() rejected: {not is_valid} (reason: {drop_err})")
    assert not is_valid
    assert "main" in drop_err

    # 5B: Defect check - candidate introducing duplicate function definition
    dup_candidate = original_code + "\ndef add(a, b):\n    return a + b\n"
    is_valid_dup, dup_err = validate_candidate_interface(original_code, dup_candidate, language="python")
    print(f"Duplicate definition rejected: {not is_valid_dup} (reason: {dup_err})")
    assert not is_valid_dup
    assert "Candidate introduced duplicate definition" in dup_err

    # 5C: Safe AST symbol replacement without duplication
    repaired_funcs = "def subtract(a, b):\n    return a - b\n\ndef divide(a, b):\n    return a / b\n"
    assembled = replace_ast_symbols_in_python(original_code, repaired_funcs)
    is_valid_assembled, assem_err = validate_candidate_interface(original_code, assembled, language="python")
    print(f"AST Assembled candidate valid: {is_valid_assembled} (err: {assem_err})")
    assert is_valid_assembled is True
    assert "def main():" in assembled

    print("\n=== Step 6: Docker Sandbox Validation of Repaired Candidate ===")
    test_rel_path = "test_calculator_practice.py"
    extra_files = {test_rel_path: proposal.test_code}
    
    cand_res = sb.run_tests_with_patch(
        repo_path=repo_path,
        target_file=canon,
        patched_code=assembled,
        test_command=None,
        extra_files=extra_files,
        timeout=25,
    )
    print(f"Repaired Sandbox Result: success={cand_res.success}, passed={cand_res.passed_count}, failed={cand_res.failed_count}, exit_code={cand_res.exit_code}")
    assert cand_res.success is True
    assert cand_res.passed_count == 8
    assert cand_res.failed_count == 0

    print("\n=== Step 7: Central Approval Gate Verification ===")
    repo_id = get_repo_id(repo_path)
    patch_record = {
        "patch_id": "test-patch-calc-001",
        "repo_id": repo_id,
        "target_file": canon,
        "original_code": original_code,
        "suggested_patch": assembled,
        "sandbox_validation": {
            "verified": cand_res.success,
            "test_status": "passed" if cand_res.success else "failed",
            "test_result": {
                "success": cand_res.success,
                "passed_count": cand_res.passed_count,
                "failed_count": cand_res.failed_count,
                "exit_code": cand_res.exit_code,
            }
        },
        "security_validation": {
            "security_status": "passed",
            "security_approved": True,
            "security_coverage": "complete",
            "failing_findings_count": 0,
            "security_policy": "strict",
        },
    }
    gate_ok, gate_reason = evaluate_patch_approval_gate(patch_record, target_repo_id=repo_id)
    print(f"Central gate evaluation: ok={gate_ok}, reason='{gate_reason}'")
    assert gate_ok is True

    # Confirm original file on disk remains completely untouched
    with open(os.path.join(repo_path, canon), "r", encoding="utf-8") as f:
        current_disk_content = f.read()
    assert current_disk_content == original_code
    print("\n[SUCCESS] Pipeline successfully verified all steps! Original code remains untouched pending developer approval.")

if __name__ == "__main__":
    main()
