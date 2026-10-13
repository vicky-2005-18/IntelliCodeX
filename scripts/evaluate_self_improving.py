"""
Reproducible Live Evaluation Runner for IntelliCodeX Self-Improving Repair (REQ-FUT-10).

Compares:
Condition A: Zero-shot (Without historical demonstrations, experience_bank=None).
Condition B: Few-shot (With historical demonstrations, experience_bank active & frozen).

Measures:
- First-attempt test-pass rate
- Invalid or non-applicable patches
- Regression failures
- Generation latency (seconds)
- Prompt token usage
"""

import os
import sys
import time
import json
import tempfile
import subprocess
from typing import Dict, Any, List, Tuple

# Add workspace root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.llm_client import OllamaLLM
from core.self_improving import RepairExperienceBank
from core.patch_generator import PatchEngine
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from backend.patch_generator.llm_parser import extract_code_and_explanation, strip_language_prefix
from tests.benchmark_self_improving import BENCHMARK_CASES


def run_isolated_test(repo_dir: str, target_file: str, test_file: str) -> Tuple[bool, str]:
    """Runs pytest inside the isolated test environment on target code and test code."""
    cmd = [sys.executable, "-m", "pytest", test_file, "-q"]
    try:
        proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=15)
        passed = (proc.returncode == 0)
        output = proc.stdout + proc.stderr
        return passed, output.strip()
    except Exception as e:
        return False, str(e)


def evaluate_condition(
    condition_name: str,
    cases: List[Dict[str, Any]],
    llm: OllamaLLM,
    use_experiences: bool,
    model_name: str,
) -> Dict[str, Any]:
    print(f"\n=======================================================")
    print(f"Running Evaluation Condition: {condition_name}")
    print(f"Model: {model_name} | Temperature: {llm.temperature} | Cases: {len(cases)}")
    print(f"=======================================================\n")

    results: List[Dict[str, Any]] = []

    # Experience bank: frozen instance for Condition B, False (disabled) for Condition A
    bank = RepairExperienceBank() if use_experiences else False

    embedder = TfidfEmbedder(dim=16)
    store = FaissVectorStore(dim=16)

    for idx, case in enumerate(cases, start=1):
        case_id = case["case_id"]
        error_type = case["error_type"]
        error_report = case["error_report"]
        target_file = case["target_file"]
        orig_code = case["original_code"]
        test_code = case["test_code"]

        print(f"[{idx:02d}/{len(cases):02d}] Evaluating {case_id} ({error_type})... ", end="", flush=True)

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_abs = os.path.join(tmp_dir, target_file)
            with open(file_abs, "w", encoding="utf-8") as f:
                f.write(orig_code)

            test_file_name = f"test_{target_file}"
            test_file_abs = os.path.join(tmp_dir, test_file_name)
            with open(test_file_abs, "w", encoding="utf-8") as f:
                f.write(test_code)

            # Sanity check: confirm original code FAILS test
            init_passed, _ = run_isolated_test(tmp_dir, target_file, test_file_name)
            if init_passed:
                print(f"SKIP (Original code unexpectedly passed)")
                continue

            engine = PatchEngine(
                store=store,
                embedder=embedder,
                llm=llm,
                repo_path=tmp_dir,
                experience_bank=bank,
                allow_local_sandbox=True,
            )

            # Build prompt and measure tokens
            prompt = engine._build_llm_prompt(
                error_report=error_report,
                file_path=target_file,
                snippet=orig_code,
                rag_context="",
                localization={"error_type": error_type},
            )
            prompt_tokens = int(len(prompt) / 3.5)

            # Measure generation latency
            t0 = time.time()
            try:
                from core.patch_generator import PATCH_SYSTEM_PROMPT
                raw_response = llm.generate(prompt, system=PATCH_SYSTEM_PROMPT, temperature=0.0)
                gen_latency = round(time.time() - t0, 2)
            except Exception as e:
                gen_latency = round(time.time() - t0, 2)
                print(f"LLM ERROR ({e})")
                results.append({
                    "case_id": case_id,
                    "error_type": error_type,
                    "status": "llm_error",
                    "latency": gen_latency,
                    "prompt_tokens": prompt_tokens,
                    "first_attempt_pass": False,
                    "invalid_patch": True,
                    "regression_failure": False,
                })
                continue

            suggested_code, explanation = extract_code_and_explanation(raw_response)
            suggested_code = strip_language_prefix(suggested_code)

            # Validation: Syntax & applicability
            import ast
            is_valid_syntax = False
            try:
                ast.parse(suggested_code)
                is_valid_syntax = True
            except Exception:
                is_valid_syntax = False

            if not is_valid_syntax or not suggested_code.strip():
                print(f"INVALID SYNTAX (in {gen_latency}s)")
                results.append({
                    "case_id": case_id,
                    "error_type": error_type,
                    "status": "invalid_syntax",
                    "latency": gen_latency,
                    "prompt_tokens": prompt_tokens,
                    "first_attempt_pass": False,
                    "invalid_patch": True,
                    "regression_failure": False,
                })
                continue

            # Apply patch to target file
            with open(file_abs, "w", encoding="utf-8") as f:
                f.write(suggested_code)

            # Run regression test
            test_passed, test_output = run_isolated_test(tmp_dir, target_file, test_file_name)
            if test_passed:
                print(f"PASSED (in {gen_latency}s, {prompt_tokens} tokens)")
                results.append({
                    "case_id": case_id,
                    "error_type": error_type,
                    "status": "passed",
                    "latency": gen_latency,
                    "prompt_tokens": prompt_tokens,
                    "first_attempt_pass": True,
                    "invalid_patch": False,
                    "regression_failure": False,
                })
            else:
                # Distinguish regression failure (test assertion failure) from crash
                is_regression = ("AssertionError" in test_output or "FAILED" in test_output)
                print(f"FAILED (Regression: {is_regression}, in {gen_latency}s)")
                results.append({
                    "case_id": case_id,
                    "error_type": error_type,
                    "status": "test_failure",
                    "latency": gen_latency,
                    "prompt_tokens": prompt_tokens,
                    "first_attempt_pass": False,
                    "invalid_patch": False,
                    "regression_failure": is_regression,
                })

    # Summary metrics
    total = len(results)
    passed_count = sum(1 for r in results if r["first_attempt_pass"])
    invalid_count = sum(1 for r in results if r["invalid_patch"])
    regression_count = sum(1 for r in results if r["regression_failure"])
    avg_latency = round(sum(r["latency"] for r in results) / total, 2) if total else 0.0
    avg_tokens = round(sum(r["prompt_tokens"] for r in results) / total, 1) if total else 0.0

    summary = {
        "condition": condition_name,
        "total_cases": total,
        "passed_count": passed_count,
        "pass_rate_pct": round((passed_count / total) * 100, 1) if total else 0.0,
        "invalid_patches": invalid_count,
        "regression_failures": regression_count,
        "avg_latency_sec": avg_latency,
        "avg_prompt_tokens": avg_tokens,
        "case_details": results,
    }
    return summary


def main():
    model_name = os.getenv("EVAL_MODEL", "qwen2.5-coder:3b")
    llm = OllamaLLM(model=model_name, temperature=0.0)

    print("====================================================================")
    print("IntelliCodeX Empirical Evaluation: Few-Shot vs Zero-Shot Repair")
    print("====================================================================")

    # 1. Condition A: Zero-shot (no historical demonstrations)
    res_a = evaluate_condition(
        condition_name="Condition A: Zero-Shot (No Demonstrations)",
        cases=BENCHMARK_CASES,
        llm=llm,
        use_experiences=False,
        model_name=model_name,
    )

    # 2. Condition B: Few-shot (with historical demonstrations)
    res_b = evaluate_condition(
        condition_name="Condition B: Few-Shot (With Demonstrations)",
        cases=BENCHMARK_CASES,
        llm=llm,
        use_experiences=True,
        model_name=model_name,
    )

    report = {
        "timestamp": time.time(),
        "model": model_name,
        "benchmark_cases_count": len(BENCHMARK_CASES),
        "condition_a_zero_shot": res_a,
        "condition_b_few_shot": res_b,
    }

    out_file = os.path.join(".storage", "benchmark_evaluation_results.json")
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n\n========================= FINAL COMPARISON =========================")
    print(f"{'Metric':<30} | {'Condition A (Zero-Shot)':<25} | {'Condition B (Few-Shot)':<25}")
    print("-" * 86)
    print(f"{'First-attempt Pass Rate':<30} | {res_a['passed_count']}/{res_a['total_cases']} ({res_a['pass_rate_pct']}%) | {res_b['passed_count']}/{res_b['total_cases']} ({res_b['pass_rate_pct']}%)")
    print(f"{'Invalid / Non-applicable':<30} | {res_a['invalid_patches']}/{res_a['total_cases']} | {res_b['invalid_patches']}/{res_b['total_cases']}")
    print(f"{'Regression Failures':<30} | {res_a['regression_failures']}/{res_a['total_cases']} | {res_b['regression_failures']}/{res_b['total_cases']}")
    print(f"{'Mean Generation Latency':<30} | {res_a['avg_latency_sec']}s | {res_b['avg_latency_sec']}s")
    print(f"{'Mean Prompt Tokens':<30} | {res_a['avg_prompt_tokens']} tokens | {res_b['avg_prompt_tokens']} tokens")
    print("====================================================================")
    print(f"Results persisted to: {out_file}\n")


if __name__ == "__main__":
    main()
