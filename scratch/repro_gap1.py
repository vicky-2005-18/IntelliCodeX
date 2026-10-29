"""
Reproduction script for Gap 1:
Demonstrates a smoke assertion with a behavioral-looking test name (e.g. test_process_payment)
upgrading smoke check into behavioral verification when requirement metadata is missing.
"""
from core.patch_generator import evaluate_patch_approval_gate

def test_gap1_demonstration():
    # A creation proposal where test is actually just a smoke check, but named 'test_process_payment'
    # requirement_tests_passed_count is absent, requirements_status was 'interface_smoke_only'
    smoke_proposal = {
        "target_file": "payment.py",
        "suggested_patch": "def process_payment(amount):\n    return True\n",
        "is_new_file": True,
        "contract_type": "ai_generated_candidate_contract",
        "requirements_status": "interface_smoke_only",
        "repo_id": "repo_12345678",
        "sandbox_validation": {
            "verified": True,
            "test_status": "passed",
            "passed_count": 1,
            "failed_count": 0,
            "total_count": 1,
            # Behavioral-looking name for a smoke assertion!
            "passed_tests": ["test_process_payment"],
            "test_result": {
                "success": True,
                "exit_code": 0,
                "passed_count": 1,
                "passed_tests": ["test_process_payment"],
            },
        },
        "security_validation": {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
        },
    }

    ok_gate, gate_msg = evaluate_patch_approval_gate(smoke_proposal, target_repo_id="repo_12345678")
    print(f"Gate outcome: ok_gate={ok_gate}, gate_msg='{gate_msg}'")
    if ok_gate is True:
        print("DEFECT DEMONSTRATED: test_process_payment name heuristic upgraded smoke assertion into behavioral approval!")
    else:
        print("Gate correctly rejected.")

if __name__ == "__main__":
    test_gap1_demonstration()
