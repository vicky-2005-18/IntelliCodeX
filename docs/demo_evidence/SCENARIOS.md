# IntelliCodeX — Presentation Demo Scenarios & Rehearsal Guide

Prepared for Demo Presentation · October 23, 2026

This guide documents the 5 primary demonstration scenarios designed for live demonstration or recording. Each scenario has been empirically tested and verified against the current codebase.

---

## Scenario 1: Architecture Navigation & Transparent RAG Pipeline (sample_repo)

**Objective**: Demonstrate privacy-preserving local code indexing, AST parsing across functions/classes, and transparent RAG inspection.

### Execution Steps
```bash
# Launch interactive CLI in offline TF-IDF mode (zero external API/model dependencies)
python cli.py sample_repo --backend tfidf
```

### Demonstration Commands
1. **Repository Index Totals**:
   ```text
   >> index-stats
   ```
   *Shows files indexed, AST chunks extracted, dependency graph nodes, BM25 vocabulary size, and FAISS vector count.*

2. **Chunk & Vector Inspection**:
   ```text
   >> chunks: auth.py
   ```
   *Displays exact line boundaries (6–8, 11–20, 23–36), token estimates, embedding dimension (512), and vector preview.*

3. **Transparent Pipeline & Prompt Inspection**:
   ```text
   >> explain: how does user authentication work?
   ```
   *Displays the full augmented prompt (instruction block, retrieved context chunks with line numbers, and user question) alongside retrieved chunks, BM25 lexical vs FAISS dense match scores, and RRF fusion rank.*

4. **Comparative Analysis**:
   ```text
   >> explain: how does user authentication work? --compare
   ```
   *Displays side-by-side answer generation: Direct Model vs RAG-Augmented Model with latency benchmarking.*

---

## Scenario 2: Agentic Test-Driven Repair with Live Docker Sandbox Validation (demo_invoice_repo)

**Objective**: Demonstrate automated root cause localization, multi-turn repair loop that fails baseline tests first, verifies fix in Docker sandbox, and halts at the Developer Approval Gate.

### Target Bug
`IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py`:
```python
def invoice_total(prices):
    total = 0
    for index in range(len(prices) - 1):  # Off-by-one bug
        total += prices[index]
    return total
```
Test suite `test_invoice.py` has 3 tests:
- `test_multiple_prices([10, 20, 30]) == 60` -> **FAILS** (returns 30)
- `test_single_price([5]) == 5` -> **FAILS** (returns 0)
- `test_empty_list([]) == 0` -> **PASSES**

### Execution Steps
```bash
python cli.py scratch/demo_invoice_repo --backend tfidf
```

```text
>> fix: invoice.py fails AssertionError in test_invoice.py
```

### What the Audience Sees
1. **Baseline Failure Capture**: IntelliCodeX automatically discovers `test_invoice.py`, executes it inside Docker sandbox, and logs: `2 failed, 1 passed`.
2. **Bug Localization**: Spectrum-based fault localization flags line 3 of `invoice.py`.
3. **Turn 1 Generation & Live Test**: Generates patch replacing `range(len(prices) - 1)` with `range(len(prices))`, runs sandbox tests, and reports:
   - `Sandbox Verification: PASSED (3 passed, 0 failed — Exit Code 0, Iterations: 1)`
4. **Enhanced Patch Card**:
   - Displays Canonical Target, Confidence Score (99%), Refinement Iterations (1 attempt), Tests Passed (`test_multiple_prices, test_single_price, test_empty_list`), Grounded Chunks, and Model Advisory.
5. **Interactive Review Gate**:
   - Side-by-side or unified diff review screen.
   - Developer approval prompt: `Choose action ([a]pprove & commit, [c]ancel, [u] toggle view)`.
   - File on disk is NOT touched until approval.

---

## Scenario 3: Central Patch Approval Gate & Rejection Invariance

**Objective**: Prove that unverified or failing candidate patches can NEVER modify repository files on disk, even if an API or user requests approval.

### Execution Steps
```bash
python -m pytest tests/test_patch_approval_gate.py -v
```

### Key Verified Invariants
1. **Missing / Skipped Tests**: `evaluate_patch_approval_gate` rejects candidate with clear diagnostic.
2. **Collection Error / Timeout / Pre-flight Failure**: Immediately blocked from approval.
3. **Immutability Guarantee**: Target file SHA-256 hash before and after rejection remains identical. No partial edits, no orphaned backup files, no spurious git commits.
4. **Security Enforcement**: If strict security policy is enabled, candidate patches with unresolved security findings or unscanned status are blocked.

---

## Scenario 4: Headless CI/CD Automated Quality Gate

**Objective**: Demonstrate automated repository inspection, secret scanning, AST ratio check, and machine-readable JSON artifact export in headless pipelines.

### Execution Steps
```bash
python cli.py sample_repo --backend tfidf --ci --output-json docs/demo_evidence/ci-report-sample.json
```

### Output Summary
- Target Files Ingested: 3
- Chunks Extracted: 9 (8 AST chunks, 88.89% AST coverage)
- Static Security Scan: PASSED (1 Low finding B105 detected and safely redacted)
- Machine-Readable Report: `docs/demo_evidence/ci-report-sample.json` exported with full execution metadata.
- Standard Exit Code: `0` (Success).

---

## Scenario 5: Multi-Language Docker Sandbox Verification Gate

**Objective**: Prove that IntelliCodeX verifies candidate patches across multiple programming languages (Python, Go, Java, Rust, C/C++) inside isolated container environments.

### Execution Steps
```bash
python -m pytest tests/test_go_sandbox.py tests/test_rust_sandbox.py tests/test_java_sandbox.py -v
```

### What It Validates
1. Real compilation & execution: Go `go test`, Rust `cargo test`, Java `mvn test`.
2. Crash & Panic capture: Go runtime `SIGSEGV` / nil pointer dereference captured and reported as failure with panic stack trace.
3. Container cleanup: Subprocesses and containers killed cleanly upon timeout without orphaned processes.
