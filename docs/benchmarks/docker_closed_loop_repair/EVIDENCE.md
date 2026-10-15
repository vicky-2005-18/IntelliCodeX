# IntelliCodeX Closed-Loop Repair Accuracy Benchmark Evidence Package
## Real Docker Container Execution Evaluation (Reconciled Baseline)

> **Document Status**: Final Reconciled Evidence Package  
> **Source Execution Baseline**: 20 held-out cases evaluated across conditions A, B, C, D using local model `qwen2.5-coder:3b` and Docker image `intellicodex-sandbox:latest`.  
> **Data Sources**: [`.storage/docker_benchmark_evaluation_results.json`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/.storage/docker_benchmark_evaluation_results.json), [`docs/benchmarks/docker_closed_loop_repair/per_case_results.json`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/docs/benchmarks/docker_closed_loop_repair/per_case_results.json).

---

## 1. Evaluation Configuration & Cryptographic Hashes

- **Git Commit Baseline**: `5f7143f933d68bfd427b3a0ac31fb6b873f17797`
- **Model Identifier**: `qwen2.5-coder:3b` (Ollama Digest: `f72c60cabf62`)
- **Model Parameters**: 3.1B parameters, `Q4_K_M` quantization, architecture: `qwen2`
- **Inference Parameters**: `temperature = 0.0` (greedy decoding), `num_ctx = 8192`, `num_predict = 800`, `repeat_penalty = 1.1`
- **Docker Image Tag & Digest**: `intellicodex-sandbox:latest` (`sha256:94593d0182348d7d5c578f91badc9dbab1488b41e69b56c3fa14ac28a4d4bf53`)
- **Docker Engine**: Docker Desktop Linux Engine 29.8.0, WSL2 Kernel `6.18.33.2-microsoft-standard-WSL2`
- **Benchmark Version**: 20 held-out cases across 5 error categories in [`tests/benchmark_self_improving.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/tests/benchmark_self_improving.py)
  - `KeyError` (4 cases): `bench_keyerror_nested_prefs`, `bench_keyerror_query_param`, `bench_keyerror_webhook_signature`, `bench_keyerror_cache_lookup`
  - `IndexError` (4 cases): `bench_indexerror_first_token`, `bench_indexerror_coordinate_pair`, `bench_indexerror_split_field`, `bench_indexerror_last_history`
  - `ZeroDivisionError` (4 cases): `bench_zerodiv_average_rating`, `bench_zerodiv_progress_pct`, `bench_zerodiv_aspect_ratio`, `bench_zerodiv_slope`
  - `TypeError` (4 cases): `bench_typeerror_string_concat`, `bench_typeerror_list_iteration`, `bench_typeerror_length_check`, `bench_typeerror_number_addition`
  - `AttributeError` (4 cases): `bench_attrerror_strip_none`, `bench_attrerror_object_name`, `bench_attrerror_lowercase`, `bench_attrerror_status_code`

### Cryptographic Hashes for Strict Reproduction
| Artifact | Path / Description | SHA-256 Hash |
| :--- | :--- | :--- |
| **Benchmark Suite** | `tests/benchmark_self_improving.py` | `582fae21f6b45ba98818b8706e92e89848794fb78c5c660c621b780355ea7980` |
| **Benchmark Runner** | `scripts/benchmark_docker_closed_loop.py` | `5980b8e9a5ea47f15dca826e72be13f37db8d7725ab887072302ccd97dd03b5a` |
| **Frozen Experiences** | `DEFAULT_GOLDEN_EXPERIENCES` (canonical JSON) | `b188e483b401f9fa0b24410a46a9c26d2dc25cf820d02a32e87698b3392e0cd5` |
| **Docker Sandbox Image** | `intellicodex-sandbox:latest` ID | `94593d0182348d7d5c578f91badc9dbab1488b41e69b56c3fa14ac28a4d4bf53` |

---

## 2. Benchmark Validity Pre-Flight Verification

Before evaluating any condition, every benchmark case was executed inside an isolated Docker container against the original buggy code:
- **Buggy Test (Dev Test)**: 20/20 cases (100%) **failed** on original code.
- **Happy-Path Test**: 20/20 cases (100%) **passed** on original code.
- **Sanity Result**: Zero false positives on initial code. Solutions remained strictly quarantined from prompts and experience memory.

---

## 3. Reconciled Comparison Table (Mutually Exclusive Outcomes)

### Explicit Outcome Model Definitions:
1. **Solved (`passed`)**: Candidate patch passes both the bug test AND the independent happy-path acceptance test.
2. **Unresolved without Regression (`unresolved_bug`)**: Candidate patch fails the bug test, but does NOT break existing happy-path tests.
3. **Regression Introduced (`regression`)**: Candidate patch satisfies the bug test, but **breaks** the happy-path test.
4. **Regression & Unresolved (`regression_and_unresolved`)**: Candidate patch fails the bug test AND breaks the happy-path test.
5. **Invalid Patch (`invalid_patch`)**: Patch cannot be parsed by `ast.parse` or cannot be applied.
6. **Infrastructure Failure (`infrastructure_error`)**: Container timeout, Docker daemon disconnect, or resource exhaustion.

### Overlapping Diagnostic Flags:
- **Any Regression Flag**: Total cases where happy-path tests broke (`regression` + `regression_and_unresolved`).
- **Any Unresolved Flag**: Total cases where the original bug was not fixed (`unresolved_bug` + `regression_and_unresolved`).

*(In the initial summary table, summing `unresolved_bugs` and `new_regressions` produced 8 + 12 + 1 = 21 for Condition B and 11 + 9 + 2 = 22 for Condition C because `regression_and_unresolved` cases were counted under both flags. The reconciled table below enforces mutual exclusivity so every row sums to exactly 20 cases).*

### Performance Across Conditions A, B, C, D (20 Cases Each)

| Metric | Condition A (0-shot, 1 att) | Condition B (Few-shot, 1 att) | Condition C (0-shot, 3 att Docker) | Condition D (Few-shot, 3 att Docker) |
| :--- | :---: | :---: | :---: | :---: |
| **Solved / Pass Rate** | **5 / 20 (25.0%)** | **8 / 20 (40.0%)** | **11 / 20 (55.0%)** | **13 / 20 (65.0%)** |
| **Unresolved (No Regression)** | 15 | 11 | 7 | 6 |
| **Regression (Bug Solved, Happy Broke)** | 0 | 0 | 0 | 1 |
| **Regression & Unresolved (Both Broke)** | 0 | 1 | 2 | 0 |
| **Invalid Patches** | 0 | 0 | 0 | 0 |
| **Infrastructure Errors** | 0 | 0 | 0 | 0 |
| **Total Cases Accounted** | **20 / 20** | **20 / 20** | **20 / 20** | **20 / 20** |
| *Diagnostic: Any Regression Flag* | *0* | *1* | *2* | *1* |
| *Diagnostic: Any Unresolved Flag* | *15* | *12* | *9* | *6* |
| **Total Attempts Across Suite** | 20 | 20 | 44 | 40 |
| **Average Attempts per Case** | 1.00 | 1.00 | 2.20 | 2.00 |
| **Total Elapsed Time** | 167.56s | 154.94s | 352.29s | 301.89s |
| **Average Total Time per Case** | 8.38s | 7.75s | 17.61s | 15.09s |
| &nbsp;&nbsp;&bull; *Avg LLM Generation Time* | 5.25s | 4.80s | 13.51s | 11.28s |
| &nbsp;&nbsp;&bull; *Avg Docker Execution Time* | 3.13s | 2.94s | 4.10s | 3.81s |

---

## 4. Token Accounting Reconciliation

Token counts are captured directly from the Ollama HTTP API (`prompt_eval_count` and `eval_count`) across all **124 individual generation attempts** (20 in A, 20 in B, 44 in C, 40 in D).

### Two Accounting Perspectives:
1. **Per-Case Average (Summed across attempts per case, then averaged over 20 cases)**:
   - Reflects the total token budget consumed to solve or exhaust attempts on a bug.
   - **Condition A**: 163.2 prompt tokens / case; 195.3 completion tokens / case.
   - **Condition B**: 327.4 prompt tokens / case; 170.8 completion tokens / case.
   - **Condition C**: 664.6 prompt tokens / case; 568.5 completion tokens / case.
   - **Condition D**: 711.0 prompt tokens / case; 465.9 completion tokens / case.
2. **Per-Generation Average (Total tokens across suite divided by total generation calls)**:
   - Reflects the average prompt length and generation size sent to/from the model per call.
   - **Condition A (20 calls)**: 163.2 prompt / 195.3 output tokens per generation.
   - **Condition B (20 calls)**: 327.4 prompt / 170.8 output tokens per generation.
   - **Condition C (44 calls)**: 302.1 prompt / 258.4 output tokens per generation.
   - **Condition D (40 calls)**: 355.5 prompt / 232.9 output tokens per generation.

*(Note: In conditions C and D, per-generation prompt tokens are higher on turns 2 and 3 because the refinement prompt incorporates the test traceback, assertion failure output, and previous candidate code).*

---

## 5. Development-Test Success vs. Independent Acceptance-Test Success

### Loop Termination vs. Acceptance Evaluation
- **During the Repair Loop**: The agent only has access to the **development test** (`test_dev_<file>.py`), which reproduces the bug.
  - If the candidate patch passes the development test inside Docker, the repair loop terminates immediately (`attempts_used = turn`).
  - If the development test fails and attempts remain, the execution failure is fed back into `_refine_fix`.
- **After Loop Termination**: The candidate patch is independently evaluated in Docker against `test_acc_<file>.py`, which contains:
  1. The **happy-path test** (verifying baseline functionality).
  2. The **bug test** (verifying resolution).

### Critical Case Study: `bench_typeerror_list_iteration` in Condition D
- On Turn 1, the model generated an over-defensive patch that failed the bug test.
- On Turn 2, the model refined the patch based on test feedback. The new patch passed the development test (`test_count_none`).
- Because the dev test passed, the repair loop stopped (`attempts_used = 2`, `dev_passed = True`).
- However, when evaluated against the independent acceptance test:
  - `test_count_none` passed.
  - `test_count_list` (`assert count_valid_items([1, 0, 2, None]) == 2`) **failed** with an `AssertionError`.
- **Classification**: Because the final solved status strictly enforces the independent acceptance criteria, this case was classified as `regression` (Outcome: `regression`, `resolved = False`).
- This proves that development-test pass rate (70.0% in D) overestimates true functional repair accuracy, and that independent acceptance tests are mandatory to detect newly introduced regressions.

---

## 6. Pass/Fail Transitions

- **A &rarr; B (Effect of Frozen Golden Demonstrations on Turn 1)**:
  - Pass rate: 25.0% &rarr; 40.0% (+15.0 percentage points).
  - Helped (4): `bench_keyerror_cache_lookup`, `bench_indexerror_first_token`, `bench_indexerror_last_history`, `bench_zerodiv_aspect_ratio`.
  - Harmed (1): `bench_typeerror_list_iteration` (demonstration introduced defensive cast).
- **A &rarr; C (Effect of Docker Test-Guided Iteration on Zero-Shot)**:
  - Pass rate: 25.0% &rarr; 55.0% (+30.0 percentage points).
  - Recovered (6): `bench_indexerror_first_token`, `bench_indexerror_coordinate_pair`, `bench_indexerror_last_history`, `bench_zerodiv_aspect_ratio`, `bench_typeerror_string_concat`, `bench_typeerror_number_addition`.
- **B &rarr; D (Effect of Docker Test-Guided Iteration on Few-Shot)**:
  - Pass rate: 40.0% &rarr; 65.0% (+25.0 percentage points).
  - Recovered (5): `bench_keyerror_nested_prefs`, `bench_indexerror_split_field`, `bench_typeerror_length_check`, `bench_typeerror_number_addition`, `bench_attrerror_lowercase`.
- **C &rarr; D (Demonstrations + Docker Feedback vs Zero-Shot Docker Feedback)**:
  - Pass rate: 55.0% &rarr; 65.0% (+10.0 percentage points).
  - Condition D achieved higher accuracy (13 vs 11) in fewer total attempts (40 vs 44) and less average time per case (15.09s vs 17.61s) because demonstrations helped 8 cases succeed on Turn 1.

---

## 7. Clarifications & Correction of Unsupported Claims

1. **Attempt Limits**:
   - The evaluation tested $N \le 3$ attempts. No tests were executed with 4 or more attempts.
   - *Correction*: We do not claim general "diminishing returns beyond 3 attempts"; we state that within this 3-attempt ceiling, 100% of recoveries occurred in turns 1 (8 cases), 2 (4 cases), or 3 (1 case).
2. **Latency Observations**:
   - The observed elapsed times (8.38s for A, 7.75s for B, 17.61s for C, 15.09s for D) are specific measurements from this run on AMD Ryzen 7 7445HS / RTX 3050.
   - *Correction*: Latency numbers must be reported as empirical run observations, not invariant system guarantees.
3. **Execution Order and Warm-Up**:
   - Conditions ran sequentially: A &rarr; B &rarr; C &rarr; D. Within each condition, cases 1 through 20 ran in list order.
   - The Docker daemon was exercised by 40 container runs during pre-flight checks, but no formal token generation warm-up was performed prior to Condition A.
4. **Nature of Demonstrations**:
   - This benchmark evaluated in-context few-shot prompting using a **frozen snapshot of 5 curated golden demonstrations**, not a longitudinal evaluation of dynamically accumulated, continuous self-improvement experiences.
5. **Generalizability Scope**:
   - All findings and percentage-point deltas are strictly limited to these **20 specific held-out cases** using `qwen2.5-coder:3b`. They cannot be extrapolated to all bug types or different model families.

---

## 8. Heuristic Fallback Policy vs. Benchmark Purity

- In [`core/patch_generator.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/core/patch_generator.py), `PatchEngine` previously contained a regex fallback (`_heuristic_fix`) that executed when the LLM returned code identical to the input or threw an exception.
- **Product Policy Preserved**: The default product behavior retains `allow_heuristic_fallback = True` so production users receive graceful degradation if Ollama is unreachable. All heuristic patches are explicitly stamped with `"llm_generated": False`.
- **Benchmark Evaluation Mode**: In evaluation mode, `allow_heuristic_fallback = False` is set, ensuring that any model failure is reported as a model failure rather than masked by a regex heuristic.

---

## 9. Reproduction Command

To reproduce this benchmark end-to-end:
```bash
python scripts/benchmark_docker_closed_loop.py
```
*(Requires Docker Desktop active with `intellicodex-sandbox:latest` and Ollama running with `qwen2.5-coder:3b`).*
