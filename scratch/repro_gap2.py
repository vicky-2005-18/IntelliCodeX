"""
Reproduction script for Gap 2:
Multiple explicit requirements: one passes, but another requirement is ambiguous/unbound/missing.
Does creation incorrectly receive overall verification and approval?
"""
import tempfile
import os
from core.code_creation import CodeCreationEngine
from core.patch_generator import evaluate_patch_approval_gate

def test_gap2_demonstration():
    with tempfile.TemporaryDirectory() as tmp_dir:
        engine = CodeCreationEngine(repo_path=tmp_dir)
        
        # Req 1: calculate_discount(100, 0.2) returns 80.0 (passes!)
        # Req 2: extra_feature(5) returns 10 (unbound: extra_feature not defined in candidate code!)
        inst = (
            'create: calculate_discount(price, rate). Given (100, 0.2) returns 80.0. '
            'Also extra_feature(x). Given (5) returns 10. Target: "multi_req.py"'
        )
        code = (
            'def calculate_discount(price, rate):\n'
            '    return price * (1.0 - rate)\n'
        )
        
        proposal = engine.propose_creation(inst, generate_tests=True, candidate_code=code)
        
        print("Proposal status:", proposal.get("status"))
        print("Proposal requirements_status:", proposal.get("requirements_status"))
        print("Proposal missing_coverage:", proposal.get("missing_coverage"))
        print("Proposal sandbox verified:", proposal.get("sandbox_validation", {}).get("verified"))
        print("Limitations noted:", proposal.get("requirements_evaluation", {}).get("limitations_noted"))
        
        ok_gate, gate_msg = evaluate_patch_approval_gate(proposal, target_repo_path=tmp_dir)
        print(f"Gate outcome: ok_gate={ok_gate}, gate_msg='{gate_msg}'")
        
        if ok_gate is True or proposal.get("status") == "verified":
            print("DEFECT DEMONSTRATED: Creation received status='verified' and approval despite KNOWN missing/ambiguous requirement coverage!")
        else:
            print("Gate correctly blocked partial requirement coverage.")

if __name__ == "__main__":
    test_gap2_demonstration()
