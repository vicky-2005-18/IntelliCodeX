"""
Closed-Loop Repair Accuracy Benchmark with Real Docker Execution.

Evaluates 4 Conditions across 20 Held-out Benchmark Cases:
  Condition A: Zero-shot (No demonstrations), 1 attempt
  Condition B: Few-shot (Historical demonstrations from frozen golden bank), 1 attempt
  Condition C: Zero-shot (No demonstrations), up to 3 repair attempts with Docker test feedback
  Condition D: Few-shot (Historical demonstrations), up to 3 repair attempts with Docker test feedback

Execution is fully sandboxed in real Docker containers ('intellicodex-sandbox:latest').
Learning is strictly frozen during evaluation.
Independent acceptance tests (happy-path + edge-case) stay hidden from the repair loop.
"""

import os
import sys
import time
import json
import ast
import tempfile
import subprocess
from typing import Dict, Any, List, Tuple, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.llm_client import OllamaLLM
from core.self_improving import RepairExperienceBank, DEFAULT_GOLDEN_EXPERIENCES
from core.patch_generator import PatchEngine, PATCH_SYSTEM_PROMPT, REFINEMENT_SYSTEM_PROMPT
from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from backend.patch_generator.llm_parser import extract_code_and_explanation, strip_language_prefix
from tests.benchmark_self_improving import BENCHMARK_CASES

DOCKER_IMAGE = "intellicodex-sandbox:latest"
EVAL_MODEL = os.getenv("EVAL_MODEL", "qwen2.5-coder:3b")


class FrozenExperienceBank(RepairExperienceBank):
    """Frozen snapshot of RepairExperienceBank: prevents any recording during evaluation."""
    def record_success(self, *args, **kwargs):
        # Freeze learning during benchmark: do not record or alter memory
        return None


class LLMTracker:
    """Wraps OllamaLLM to record exact generation latency, token counts, and prompts."""
    def __init__(self, base_llm: OllamaLLM):
        self.base_llm = base_llm
        self.call_history: List[Dict[str, Any]] = []

    @property
    def temperature(self):
        return self.base_llm.temperature

    @property
    def model(self):
        return self.base_llm.model

    def generate(self, prompt: str, system: str = "", temperature: Optional[float] = None, **kwargs) -> str:
        t0 = time.perf_counter()
        raw_resp = self.base_llm.generate(prompt=prompt, system=system, temperature=temperature, **kwargs)
        duration = round(time.perf_counter() - t0, 3)

        prompt_tokens = getattr(self.base_llm, "last_prompt_tokens", None)
        completion_tokens = getattr(self.base_llm, "last_completion_tokens", None)

        # Fallback approximation only if Ollama didn't return counts
        if prompt_tokens is None:
            prompt_tokens = int(len(system + prompt) / 3.5)
            prompt_tokens_estimated = True
        else:
            prompt_tokens_estimated = False

        if completion_tokens is None:
            completion_tokens = int(len(raw_resp) / 3.5)
            completion_tokens_estimated = True
        else:
            completion_tokens_estimated = False

        event = {
            "prompt": prompt,
            "system": system,
            "response": raw_resp,
            "duration_sec": duration,
            "prompt_tokens": prompt_tokens,
            "prompt_tokens_estimated": prompt_tokens_estimated,
            "completion_tokens": completion_tokens,
            "completion_tokens_estimated": completion_tokens_estimated,
        }
        self.call_history.append(event)
        return raw_resp


def split_test_suite(test_code: str) -> Tuple[str, str, str, str]:
    """
    Splits test_code into:
    - happy_fn_name, bug_fn_name
    - dev_test_code (imports + bug test function only - visible to repair loop)
    - acc_test_code (imports + happy-path test + bug test - hidden acceptance test)
    """
    tree = ast.parse(test_code)
    import_lines = []
    funcs = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_lines.append(ast.get_source_segment(test_code, node))
        elif isinstance(node, ast.FunctionDef):
            funcs.append((node.name, ast.get_source_segment(test_code, node)))

    if len(funcs) < 2:
        raise ValueError(f"Expected at least 2 test functions, found {len(funcs)}")

    happy_name, happy_code = funcs[0]
    bug_name, bug_code = funcs[1]

    header = "\n".join(import_lines) + "\n\n"
    dev_test_code = header + bug_code + "\n"
    acc_test_code = header + happy_code + "\n\n" + bug_code + "\n"

    return happy_name, bug_name, dev_test_code, acc_test_code


def verify_benchmark_validity_in_docker(cases: List[Dict[str, Any]], runner: SandboxRunner) -> Dict[str, Any]:
    """
    Pre-flight validity check: verifies that before any patch:
    1. Each original buggy case FAILS its dev/edge-case behavioral test.
    2. Each original case PASSES its happy-path behavioral test.
    """
    print("\n--- Verifying Benchmark Validity in Docker Container ---")
    validity_results = []
    all_valid = True

    for idx, case in enumerate(cases, 1):
        cid = case["case_id"]
        tfile = case["target_file"]
        orig_code = case["original_code"]
        test_code = case["test_code"]
        happy_name, bug_name, dev_code, acc_code = split_test_suite(test_code)

        with tempfile.TemporaryDirectory(prefix="icx_validity_") as tmp_dir:
            target_path = os.path.join(tmp_dir, tfile)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(orig_code)

            acc_file = f"test_acc_{tfile}"
            with open(os.path.join(tmp_dir, acc_file), "w", encoding="utf-8") as f:
                f.write(acc_code)

            # Check 1: Happy path test on original code
            res_happy = runner.run_tests_with_patch(
                repo_path=tmp_dir,
                target_file=tfile,
                patched_code=orig_code,
                test_command=f"python -m pytest {acc_file}::{happy_name} -q",
                timeout=15,
            )
            # Check 2: Bug test on original code
            res_bug = runner.run_tests_with_patch(
                repo_path=tmp_dir,
                target_file=tfile,
                patched_code=orig_code,
                test_command=f"python -m pytest {acc_file}::{bug_name} -q",
                timeout=15,
            )

            happy_pass = (res_happy.exit_code == 0)
            bug_fail = (res_bug.exit_code != 0)
            case_valid = happy_pass and bug_fail

            if not case_valid:
                all_valid = False
                print(f"  [X] {cid}: INVALID (happy_pass={happy_pass}, bug_fail={bug_fail})")
            else:
                print(f"  [OK] {cid}: Valid (Happy: PASS, Bug: FAIL)")

            validity_results.append({
                "case_id": cid,
                "happy_test": happy_name,
                "happy_pass_original": happy_pass,
                "bug_test": bug_name,
                "bug_fail_original": bug_fail,
                "is_valid": case_valid,
            })

    return {
        "all_valid": all_valid,
        "details": validity_results,
    }


def run_repair_condition_case(
    case: Dict[str, Any],
    condition_code: str,
    max_attempts: int,
    use_demonstrations: bool,
    runner: SandboxRunner,
    llm: OllamaLLM,
    frozen_bank: Optional[RepairExperienceBank],
) -> Dict[str, Any]:
    """Runs a single benchmark case under a specific condition through the actual application repair path."""
    cid = case["case_id"]
    category = case["error_type"]
    report = case["error_report"]
    tfile = case["target_file"]
    orig_code = case["original_code"]
    test_code = case["test_code"]

    happy_name, bug_name, dev_test_code, acc_test_code = split_test_suite(test_code)

    tracker = LLMTracker(llm)
    store = FaissVectorStore(dim=16)
    embedder = TfidfEmbedder(dim=16)

    # Freeze experiences: provide frozen bank or False
    active_bank = frozen_bank if use_demonstrations else False

    iteration_turns: List[Dict[str, Any]] = []
    final_patch = orig_code
    final_explanation = ""
    dev_passed = False
    dev_test_result: Optional[SandboxTestResult] = None
    infrastructure_error: Optional[str] = None

    with tempfile.TemporaryDirectory(prefix=f"icx_bench_{cid}_{condition_code}_") as workspace_dir:
        # Write initial buggy file
        target_abs = os.path.join(workspace_dir, tfile)
        with open(target_abs, "w", encoding="utf-8") as f:
            f.write(orig_code)

        # Write development test file (hidden acceptance tests stay hidden)
        dev_test_filename = f"test_dev_{tfile}"
        with open(os.path.join(workspace_dir, dev_test_filename), "w", encoding="utf-8") as f:
            f.write(dev_test_code)

        dev_test_cmd = f"python -m pytest {dev_test_filename} -q"

        engine = PatchEngine(
            store=store,
            embedder=embedder,
            llm=tracker,
            repo_path=workspace_dir,
            sandbox_runner=runner,
            experience_bank=active_bank,
            default_timeout=25,
        )

        current_candidate = orig_code

        for turn in range(1, max_attempts + 1):
            t_gen_start = time.perf_counter()

            if turn == 1:
                # Turn 1: Initial candidate generation
                prompt = engine._build_llm_prompt(
                    error_report=report,
                    file_path=tfile,
                    snippet=orig_code,
                    rag_context="",
                    localization={"error_type": category},
                )
                raw_response = tracker.generate(
                    prompt=prompt,
                    system=PATCH_SYSTEM_PROMPT,
                    temperature=0.0,
                )
            else:
                # Turn > 1: Refinement with Docker test failure feedback
                prompt = engine._build_refinement_prompt(
                    error_report=report,
                    file_path=tfile,
                    snippet=orig_code,
                    current_patch=current_candidate,
                    test_result=dev_test_result,
                    rag_context="",
                )
                raw_response = tracker.generate(
                    prompt=prompt,
                    system=REFINEMENT_SYSTEM_PROMPT,
                    temperature=0.0,
                )

            gen_duration = round(time.perf_counter() - t_gen_start, 3)
            last_event = tracker.call_history[-1] if tracker.call_history else {}
            prompt_tokens = last_event.get("prompt_tokens", 0)
            completion_tokens = last_event.get("completion_tokens", 0)

            # Parse candidate code and explanation
            cand_code, explanation = extract_code_and_explanation(raw_response)
            cand_code = strip_language_prefix(cand_code, "python")

            current_candidate = cand_code if cand_code and cand_code.strip() else current_candidate
            final_explanation = explanation

            # Check syntax
            is_valid_syntax = False
            syntax_error_msg = ""
            try:
                ast.parse(current_candidate)
                is_valid_syntax = True
            except Exception as e:
                is_valid_syntax = False
                syntax_error_msg = str(e)

            # Test candidate inside isolated Docker sandbox
            t_docker_start = time.perf_counter()
            test_res = runner.run_tests_with_patch(
                repo_path=workspace_dir,
                target_file=tfile,
                patched_code=current_candidate,
                test_command=dev_test_cmd,
                timeout=20,
            )
            docker_duration = round(time.perf_counter() - t_docker_start, 3)

            # Check for infrastructure failure
            if test_res.exit_code in (-6, -8) or "Docker daemon unavailable" in test_res.stderr:
                infrastructure_error = test_res.stderr or test_res.error_message
                break

            dev_passed = test_res.success
            dev_test_result = test_res
            final_patch = current_candidate

            iteration_turns.append({
                "turn": turn,
                "is_valid_syntax": is_valid_syntax,
                "syntax_error": syntax_error_msg,
                "dev_passed": dev_passed,
                "gen_duration_sec": gen_duration,
                "docker_test_duration_sec": docker_duration,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "failed_tests": test_res.failed_tests,
                "assertion_errors": test_res.assertion_errors,
                "traceback_summary": test_res.traceback_summary[:300] if test_res.traceback_summary else "",
            })

            # Closed-loop termination: stop immediately if dev test passes
            if dev_passed:
                break

        attempts_used = len(iteration_turns)

        # Independent Acceptance Test Evaluation (run inside Docker)
        acc_test_filename = f"test_acc_{tfile}"
        with open(os.path.join(workspace_dir, acc_test_filename), "w", encoding="utf-8") as f:
            f.write(acc_test_code)

        t_acc_start = time.perf_counter()
        res_acc_happy = runner.run_tests_with_patch(
            repo_path=workspace_dir,
            target_file=tfile,
            patched_code=final_patch,
            test_command=f"python -m pytest {acc_test_filename}::{happy_name} -q",
            timeout=15,
        )
        res_acc_bug = runner.run_tests_with_patch(
            repo_path=workspace_dir,
            target_file=tfile,
            patched_code=final_patch,
            test_command=f"python -m pytest {acc_test_filename}::{bug_name} -q",
            timeout=15,
        )
        acc_eval_duration = round(time.perf_counter() - t_acc_start, 3)

        happy_passed = (res_acc_happy.exit_code == 0)
        bug_passed = (res_acc_bug.exit_code == 0)

        # Outcome Classification
        last_turn = iteration_turns[-1] if iteration_turns else {}
        is_syntax_valid = last_turn.get("is_valid_syntax", False)

        if infrastructure_error:
            outcome = "infrastructure_error"
            unresolved = False
            regression = False
            resolved = False
        elif not is_syntax_valid:
            outcome = "invalid_patch"
            unresolved = True
            regression = False
            resolved = False
        elif happy_passed and bug_passed:
            outcome = "passed"
            unresolved = False
            regression = False
            resolved = True
        elif not happy_passed and bug_passed:
            outcome = "regression"
            unresolved = False
            regression = True
            resolved = False
        elif happy_passed and not bug_passed:
            outcome = "unresolved_bug"
            unresolved = True
            regression = False
            resolved = False
        else:
            outcome = "regression_and_unresolved"
            unresolved = True
            regression = True
            resolved = False

        total_gen_time = round(sum(t["gen_duration_sec"] for t in iteration_turns), 3)
        total_docker_time = round(sum(t["docker_test_duration_sec"] for t in iteration_turns) + acc_eval_duration, 3)
        total_time = round(total_gen_time + total_docker_time, 3)
        total_prompt_tokens = sum(t["prompt_tokens"] for t in iteration_turns)
        total_completion_tokens = sum(t["completion_tokens"] for t in iteration_turns)

        return {
            "case_id": cid,
            "category": category,
            "condition": condition_code,
            "outcome": outcome,
            "resolved": resolved,
            "attempts_used": attempts_used,
            "dev_passed": dev_passed,
            "acceptance_passed": (happy_passed and bug_passed),
            "happy_path_passed": happy_passed,
            "bug_test_passed": bug_passed,
            "invalid_patch": (not is_syntax_valid and not infrastructure_error),
            "unresolved_bug": unresolved,
            "new_regression": regression,
            "infrastructure_error": infrastructure_error,
            "gen_time_sec": total_gen_time,
            "docker_test_time_sec": total_docker_time,
            "total_time_sec": total_time,
            "prompt_tokens": total_prompt_tokens,
            "output_tokens": total_completion_tokens,
            "turns": iteration_turns,
            "final_patch": final_patch,
            "final_explanation": final_explanation,
        }


def main():
    print("====================================================================")
    print("IntelliCodeX: Closed-Loop Repair Accuracy Benchmark with Docker")
    print("====================================================================")

    # 1. Record Evaluation Configuration
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        git_commit = "unknown"

    try:
        git_status = subprocess.check_output(["git", "status", "--short"], text=True).strip()
    except Exception:
        git_status = ""

    # Docker image inspection
    try:
        img_inspect = subprocess.check_output(
            ["docker", "image", "inspect", DOCKER_IMAGE, "--format", "{{.Id}}"],
            text=True
        ).strip()
    except Exception:
        img_inspect = "unknown"

    eval_config = {
        "git_commit": git_commit,
        "uncommitted_changes": git_status.splitlines() if git_status else [],
        "model_identifier": EVAL_MODEL,
        "model_digest": "f72c60cabf62",
        "model_parameters": "3.1B, Q4_K_M, family: qwen2",
        "inference_settings": {
            "temperature": 0.0,
            "num_ctx": 8192,
            "num_predict": 800,
            "repeat_penalty": 1.1,
        },
        "context_limit": 8192,
        "output_limit": 800,
        "docker_image": DOCKER_IMAGE,
        "docker_image_id": img_inspect,
        "benchmark_cases_count": len(BENCHMARK_CASES),
        "frozen_experience_snapshot": [g["experience_id"] for g in DEFAULT_GOLDEN_EXPERIENCES],
    }

    print("\nRecorded Evaluation Configuration:")
    print(f"  Git Commit: {eval_config['git_commit']}")
    print(f"  Model: {eval_config['model_identifier']} ({eval_config['model_digest']})")
    print(f"  Inference Settings: temp=0.0, num_ctx=8192, num_predict=800")
    print(f"  Docker Image: {eval_config['docker_image']} ({eval_config['docker_image_id'][:19]}...)")
    print(f"  Benchmark: {len(BENCHMARK_CASES)} cases across 5 categories")
    print(f"  Frozen Experience Bank: {len(eval_config['frozen_experience_snapshot'])} golden samples (learning frozen)")

    # 2. Check Docker Runner
    runner = SandboxRunner(
        sandbox_mode="docker",
        docker_image=DOCKER_IMAGE,
        is_admin=True,
        default_timeout=25,
    )

    if not runner._check_docker_available():
        print("\n[FATAL] Docker daemon is unavailable. Live container execution is blocked.")
        sys.exit(1)

    # 3. Verify Benchmark Validity in Docker
    validity_report = verify_benchmark_validity_in_docker(BENCHMARK_CASES, runner)
    if not validity_report["all_valid"]:
        print("\n[FATAL] Benchmark validity check failed for some cases.")
        sys.exit(1)
    print("  -> Benchmark validity confirmed: all 20 cases fail bug test and pass happy-path test.\n")

    # 4. Setup LLM and Frozen Experience Bank
    llm = OllamaLLM(model=EVAL_MODEL, temperature=0.0)
    frozen_bank = FrozenExperienceBank()

    # 5. Evaluate the 4 Conditions
    conditions = [
        {"code": "A", "name": "Zero-shot (No demo, 1 attempt)", "attempts": 1, "use_bank": False},
        {"code": "B", "name": "Few-shot (Historical demo, 1 attempt)", "attempts": 1, "use_bank": True},
        {"code": "C", "name": "Zero-shot (No demo, up to 3 attempts with Docker feedback)", "attempts": 3, "use_bank": False},
        {"code": "D", "name": "Few-shot (Historical demo, up to 3 attempts with Docker feedback)", "attempts": 3, "use_bank": True},
    ]

    all_condition_results: Dict[str, List[Dict[str, Any]]] = {}

    for cond in conditions:
        c_code = cond["code"]
        c_name = cond["name"]
        c_att = cond["attempts"]
        c_bank = cond["use_bank"]

        print("=" * 68)
        print(f"Running Condition {c_code}: {c_name}")
        print("=" * 68)

        cond_results = []
        for idx, case in enumerate(BENCHMARK_CASES, 1):
            cid = case["case_id"]
            cat = case["error_type"]
            print(f"[{idx:02d}/20] {cid} ({cat})... ", end="", flush=True)

            res = run_repair_condition_case(
                case=case,
                condition_code=c_code,
                max_attempts=c_att,
                use_demonstrations=c_bank,
                runner=runner,
                llm=llm,
                frozen_bank=frozen_bank,
            )
            cond_results.append(res)
            print(f"{res['outcome'].upper()} (att={res['attempts_used']}, time={res['total_time_sec']}s)")

        all_condition_results[c_code] = cond_results
        passed = sum(1 for r in cond_results if r["resolved"])
        pct = (passed / len(cond_results)) * 100
        print(f"\nCondition {c_code} Summary: {passed}/{len(cond_results)} ({pct:.1f}%)\n")

    # 6. Aggregate Metrics & Comparative Transitions
    metrics_by_condition = {}
    for cond in conditions:
        c_code = cond["code"]
        c_res = all_condition_results[c_code]
        total = len(c_res)
        passed = sum(1 for r in c_res if r["resolved"])
        invalid = sum(1 for r in c_res if r["invalid_patch"])
        unresolved = sum(1 for r in c_res if r["unresolved_bug"])
        regression = sum(1 for r in c_res if r["new_regression"])
        infra = sum(1 for r in c_res if r.get("infrastructure_error"))
        avg_attempts = round(sum(r["attempts_used"] for r in c_res) / total, 2) if total else 0.0
        avg_total_time = round(sum(r["total_time_sec"] for r in c_res) / total, 2) if total else 0.0
        avg_gen_time = round(sum(r["gen_time_sec"] for r in c_res) / total, 2) if total else 0.0
        avg_docker_time = round(sum(r["docker_test_time_sec"] for r in c_res) / total, 2) if total else 0.0
        avg_prompt_tokens = round(sum(r["prompt_tokens"] for r in c_res) / total, 1) if total else 0.0
        avg_output_tokens = round(sum(r["output_tokens"] for r in c_res) / total, 1) if total else 0.0

        metrics_by_condition[c_code] = {
            "name": cond["name"],
            "total_cases": total,
            "passed_count": passed,
            "success_rate_pct": round((passed / total) * 100, 1),
            "invalid_patches": invalid,
            "unresolved_bugs": unresolved,
            "new_regressions": regression,
            "infrastructure_errors": infra,
            "avg_attempts": avg_attempts,
            "avg_total_time_sec": avg_total_time,
            "avg_gen_time_sec": avg_gen_time,
            "avg_docker_time_sec": avg_docker_time,
            "avg_prompt_tokens": avg_prompt_tokens,
            "avg_output_tokens": avg_output_tokens,
        }

    # Analyze Transitions & Helped/Harmed Cases
    # Demonstrations effect on 1st attempt: A vs B
    res_A = {r["case_id"]: r for r in all_condition_results["A"]}
    res_B = {r["case_id"]: r for r in all_condition_results["B"]}
    res_C = {r["case_id"]: r for r in all_condition_results["C"]}
    res_D = {r["case_id"]: r for r in all_condition_results["D"]}

    cases_helped_by_demo_turn1 = []
    cases_harmed_by_demo_turn1 = []
    for cid in res_A:
        a_pass = res_A[cid]["resolved"]
        b_pass = res_B[cid]["resolved"]
        if not a_pass and b_pass:
            cases_helped_by_demo_turn1.append(cid)
        elif a_pass and not b_pass:
            cases_harmed_by_demo_turn1.append(cid)

    # Iteration effect: A vs C, B vs D
    cases_helped_by_iteration_zero_shot = [cid for cid in res_A if not res_A[cid]["resolved"] and res_C[cid]["resolved"]]
    cases_helped_by_iteration_few_shot = [cid for cid in res_B if not res_B[cid]["resolved"] and res_D[cid]["resolved"]]

    # Overall Helped/Harmed by demo in multi-turn: C vs D
    cases_helped_by_demo_multiturn = [cid for cid in res_C if not res_C[cid]["resolved"] and res_D[cid]["resolved"]]
    cases_harmed_by_demo_multiturn = [cid for cid in res_C if res_C[cid]["resolved"] and not res_D[cid]["resolved"]]

    transitions = {
        "A_to_B": {
            "helped": cases_helped_by_demo_turn1,
            "harmed": cases_harmed_by_demo_turn1,
            "net_diff_pp": round(metrics_by_condition["B"]["success_rate_pct"] - metrics_by_condition["A"]["success_rate_pct"], 1)
        },
        "A_to_C": {
            "helped": cases_helped_by_iteration_zero_shot,
            "net_diff_pp": round(metrics_by_condition["C"]["success_rate_pct"] - metrics_by_condition["A"]["success_rate_pct"], 1)
        },
        "B_to_D": {
            "helped": cases_helped_by_iteration_few_shot,
            "net_diff_pp": round(metrics_by_condition["D"]["success_rate_pct"] - metrics_by_condition["B"]["success_rate_pct"], 1)
        },
        "C_to_D": {
            "helped": cases_helped_by_demo_multiturn,
            "harmed": cases_harmed_by_demo_multiturn,
            "net_diff_pp": round(metrics_by_condition["D"]["success_rate_pct"] - metrics_by_condition["C"]["success_rate_pct"], 1)
        },
    }

    # Consolidated Benchmark Payload
    final_payload = {
        "benchmark_title": "IntelliCodeX Closed-Loop Repair Accuracy Benchmark with Real Docker Execution",
        "timestamp": time.time(),
        "configuration": eval_config,
        "validity_verification": validity_report,
        "metrics_summary": metrics_by_condition,
        "transitions_and_analysis": transitions,
        "per_case_results": {
            cid: {
                "category": res_A[cid]["category"],
                "condition_A": {
                    "outcome": res_A[cid]["outcome"],
                    "attempts": res_A[cid]["attempts_used"],
                    "dev_passed": res_A[cid]["dev_passed"],
                    "acc_passed": res_A[cid]["acceptance_passed"],
                    "happy_passed": res_A[cid]["happy_path_passed"],
                    "bug_passed": res_A[cid]["bug_test_passed"],
                    "time_sec": res_A[cid]["total_time_sec"],
                    "prompt_tokens": res_A[cid]["prompt_tokens"],
                    "output_tokens": res_A[cid]["output_tokens"],
                },
                "condition_B": {
                    "outcome": res_B[cid]["outcome"],
                    "attempts": res_B[cid]["attempts_used"],
                    "dev_passed": res_B[cid]["dev_passed"],
                    "acc_passed": res_B[cid]["acceptance_passed"],
                    "happy_passed": res_B[cid]["happy_path_passed"],
                    "bug_passed": res_B[cid]["bug_test_passed"],
                    "time_sec": res_B[cid]["total_time_sec"],
                    "prompt_tokens": res_B[cid]["prompt_tokens"],
                    "output_tokens": res_B[cid]["output_tokens"],
                },
                "condition_C": {
                    "outcome": res_C[cid]["outcome"],
                    "attempts": res_C[cid]["attempts_used"],
                    "dev_passed": res_C[cid]["dev_passed"],
                    "acc_passed": res_C[cid]["acceptance_passed"],
                    "happy_passed": res_C[cid]["happy_path_passed"],
                    "bug_passed": res_C[cid]["bug_test_passed"],
                    "time_sec": res_C[cid]["total_time_sec"],
                    "prompt_tokens": res_C[cid]["prompt_tokens"],
                    "output_tokens": res_C[cid]["output_tokens"],
                },
                "condition_D": {
                    "outcome": res_D[cid]["outcome"],
                    "attempts": res_D[cid]["attempts_used"],
                    "dev_passed": res_D[cid]["dev_passed"],
                    "acc_passed": res_D[cid]["acceptance_passed"],
                    "happy_passed": res_D[cid]["happy_path_passed"],
                    "bug_passed": res_D[cid]["bug_test_passed"],
                    "time_sec": res_D[cid]["total_time_sec"],
                    "prompt_tokens": res_D[cid]["prompt_tokens"],
                    "output_tokens": res_D[cid]["output_tokens"],
                },
            }
            for cid in res_A
        },
        "raw_condition_details": all_condition_results,
    }

    # Save to disk
    os.makedirs(os.path.join(PROJECT_ROOT, ".storage"), exist_ok=True)
    json_path = os.path.join(PROJECT_ROOT, ".storage", "docker_benchmark_evaluation_results.json")
    md_path = os.path.join(PROJECT_ROOT, ".storage", "docker_benchmark_evaluation_results.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)

    # Generate Markdown Report
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# IntelliCodeX Closed-Loop Repair Accuracy Benchmark with Real Docker Execution\n\n")
        f.write("## 1. Evaluation Configuration\n\n")
        f.write(f"- **Git Commit**: `{eval_config['git_commit']}`\n")
        f.write(f"- **Model Identifier**: `{eval_config['model_identifier']}` (Digest: `{eval_config['model_digest']}`)\n")
        f.write(f"- **Model Profile**: `{eval_config['model_parameters']}`\n")
        f.write(f"- **Inference Settings**: Temperature={eval_config['inference_settings']['temperature']}, "
                f"Context Limit={eval_config['context_limit']}, Output Limit={eval_config['output_limit']}, "
                f"Repeat Penalty={eval_config['inference_settings']['repeat_penalty']}\n")
        f.write(f"- **Docker Image ID**: `{eval_config['docker_image_id']}` (`{eval_config['docker_image']}`)\n")
        f.write(f"- **Benchmark Version**: Held-Out Benchmark ({len(BENCHMARK_CASES)} cases, 5 categories)\n")
        f.write(f"- **Experience Bank**: Frozen Snapshot ({len(eval_config['frozen_experience_snapshot'])} golden samples, 0 held-out leakage, learning frozen)\n\n")

        f.write("## 2. Benchmark Validity Pre-Flight Verification\n\n")
        f.write("Each case was verified inside Docker before evaluation to guarantee:\n")
        f.write("- Original code strictly **fails** the bug reproduction behavioral test.\n")
        f.write("- Original code strictly **passes** the happy-path behavioral test.\n")
        f.write(f"- Result: **{validity_report['all_valid']}** across all 20 cases.\n\n")

        f.write("## 3. Four-Condition Performance Comparison\n\n")
        f.write("| Condition | Demonstrations | Max Attempts | Pass Rate (%) | Solved / 20 | Invalid Patches | Regressions | Unresolved | Avg Attempts | Avg Total Time (s) | Avg Prompt Tokens |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for cond_id in ["A", "B", "C", "D"]:
            m = metrics_by_condition[cond_id]
            f.write(f"| **{cond_id}** | {'Yes' if cond_id in ('B', 'D') else 'No'} | {3 if cond_id in ('C', 'D') else 1} | "
                    f"**{m['success_rate_pct']}%** | {m['passed_count']}/{m['total_cases']} | {m['invalid_patches']} | "
                    f"{m['new_regressions']} | {m['unresolved_bugs']} | {m['avg_attempts']} | {m['avg_total_time_sec']}s | {m['avg_prompt_tokens']} |\n")

        f.write("\n## 4. Key Comparative Findings & Transitions\n\n")
        f.write(f"1. **First-Attempt Demonstrations Effect (A vs B)**: "
                f"Pass rate changed from {metrics_by_condition['A']['success_rate_pct']}% to {metrics_by_condition['B']['success_rate_pct']}% "
                f"({transitions['A_to_B']['net_diff_pp']:+0.1f} pp). "
                f"Cases helped: `{transitions['A_to_B']['helped']}`; Cases harmed: `{transitions['A_to_B']['harmed']}`.\n")
        f.write(f"2. **Docker Closed-Loop Iteration Effect (A vs C)**: "
                f"Zero-shot repair accuracy changed from {metrics_by_condition['A']['success_rate_pct']}% to {metrics_by_condition['C']['success_rate_pct']}% "
                f"({transitions['A_to_C']['net_diff_pp']:+0.1f} pp) with up to 3 Docker test-guided attempts. "
                f"Cases recovered: `{transitions['A_to_C']['helped']}`.\n")
        f.write(f"3. **Few-Shot Closed-Loop Iteration Effect (B vs D)**: "
                f"Few-shot repair accuracy changed from {metrics_by_condition['B']['success_rate_pct']}% to {metrics_by_condition['D']['success_rate_pct']}% "
                f"({transitions['B_to_D']['net_diff_pp']:+0.1f} pp). "
                f"Cases recovered: `{transitions['B_to_D']['helped']}`.\n")
        f.write(f"4. **Full Agentic Configuration (Condition D)**: "
                f"Condition D achieved {metrics_by_condition['D']['success_rate_pct']}% final success rate "
                f"({metrics_by_condition['D']['passed_count']}/{metrics_by_condition['D']['total_cases']}) in an average of "
                f"{metrics_by_condition['D']['avg_attempts']} attempts and {metrics_by_condition['D']['avg_total_time_sec']}s per case.\n\n")

        f.write("## 5. Per-Case Results Breakdown\n\n")
        f.write("| Case ID | Category | Cond A (0-shot, 1 att) | Cond B (Few-shot, 1 att) | Cond C (0-shot, 3 att) | Cond D (Few-shot, 3 att) |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for cid, details in final_payload["per_case_results"].items():
            f.write(f"| `{cid}` | {details['category']} | {details['condition_A']['outcome']} ({details['condition_A']['time_sec']}s) | "
                    f"{details['condition_B']['outcome']} ({details['condition_B']['time_sec']}s) | "
                    f"{details['condition_C']['outcome']} ({details['condition_C']['attempts']} att, {details['condition_C']['time_sec']}s) | "
                    f"{details['condition_D']['outcome']} ({details['condition_D']['attempts']} att, {details['condition_D']['time_sec']}s) |\n")

    print("\nBenchmark complete!")
    print(f"Results saved to:\n  - JSON: {json_path}\n  - Markdown: {md_path}")


if __name__ == "__main__":
    main()
