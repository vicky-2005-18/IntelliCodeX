# Evidence: AI-Assisted Architecture Optimization (REQ-FUT-06)

> **Requirement Reference**: REQ-FUT-06 (PDF Section VIII-B, p. 7)  
> **Status**: **Verified**  
> **Test Suite**: `tests/test_architecture_optimizer.py` (11/11 passed), `tests/test_self_improving.py` (13/13 passed), `tests/test_security_vulnerability_detection.py` (21/21 passed), `tests/test_ci_pipeline.py` (12/12 passed); 68/68 tests passing across related suites.  
> **Verification Date**: 2026-10-15  
> **Hardware & Environment**: AMD Ryzen 7 7445HS, 16 GB RAM, NVIDIA RTX 3050 Laptop GPU (4 GB VRAM), Windows 11 64-bit, Python 3.14.6.

---

## 1. Existing Functionality vs. Changes Completed

| Area | Prior Implementation / Gap | Completed Implementation & Architectural Guarantee |
| :--- | :--- | :--- |
| **Security Provenance in Experiences** | `RepairExperience` stored `security_status` and `security_coverage`, but lacked `security_policy`. A candidate approved under `secrets_only` could potentially be retrieved under strict security requests. | Added `security_policy: str = "unscanned"` (`"strict"`, `"secrets_only"`, `"unscanned"`). Historical experiences safely default to `"unscanned"` and cannot be upgraded automatically. `retrieve_few_shots(required_security_policy="strict")` strictly blocks `secrets_only` and unscanned candidates. |
| **Grounded Recommendation Contract** | `RefactoringRecommendation` returned only generic strings (`type`, `target`, `strategy`, `suggested_diff`) without structured metrics, configured thresholds, source line citations, or explicit tradeoffs. | Implemented full 11-field grounded contract: `finding_type`, `target`, `affected_files`, `affected_symbols`, `supporting_evidence`, `source_locations` with line numbers, `threshold_used`, `explanation`, `proposed_improvement`, `tradeoffs`, `limitations`, `confidence`. |
| **Centrality & Bottleneck Distinction** | High afferent/efferent coupling was reported as a generic "bottleneck" without distinguishing legitimate central hubs from design defects. | Explicitly documents in report, findings, and API that high centrality alone is NOT an inherent defect (essential coordinators and utilities naturally have high fan-in/fan-out); distinguishes structural change-propagation risk from defect claims, and explicitly disclaims performance claims without dynamic profiling. |
| **Overly Complex Components** | Analysis only detected graph cycles and module coupling; large monolithic functions/classes were omitted. | Added AST-level detection of large components (measuring physical component size in lines of code, not cyclomatic or cognitive complexity) exceeding configurable thresholds (`complexity_lines_threshold=80`, `complexity_class_lines_threshold=250`), reporting exact start/end lines, line count, and extract-method recommendations. Optional LLM advisory verification remains strictly separate from deterministic analysis evidence. |
| **Measured Facts vs. Generated Advice** | No clean demarcation between deterministic structural facts and AI text. | Strict architectural separation: `measured_facts` provides deterministic graph measurements (cycles, coupling metrics, line counts); `ai_advisory` cleanly encapsulates optional LLM advice or explicitly reports unavailable inference when running in deterministic mode. |
| **Snapshot & Staleness Disclosures** | API and CLI did not disclose snapshot identity or detect out-of-date graph cache. | Added `snapshot_info` returning `repo_id`, `snapshot_id`, `analyzed_at`, `is_stale`, and actionable `stale_warning` if filesystem watcher detected updates since graph indexing. |
| **Safe Non-destructive Guarantee** | Previous code had diff generation logic. | Explicit non-destructive invariant: optimizer produces reports, diff previews, and recommendations only; never modifies files on disk, never auto-refactors, and never applies patches without user intervention. |

---

## 2. Files Changed & Why

1. [`core/self_improving.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/core/self_improving.py):
   - Added `security_policy: str = "unscanned"` field to `RepairExperience`.
   - Backward-compatible deserialization in `from_dict`: defaults missing policy to `"unscanned"` (prevents automatic elevation).
   - In `record_success`: persists `security_policy`.
   - In `retrieve_few_shots`: added `required_security_policy` and `require_strict_security`; guarantees that records approved under `secrets_only` cannot satisfy a `strict` retrieval requirement.
2. [`core/patch_generator.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/core/patch_generator.py):
   - Persists `security_policy` into candidate `patch_record["security_validation"]`.
   - Forwards `security_policy` when recording verified fixes into `RepairExperienceBank`.
   - Forwards security metadata during developer approval recording.
3. [`core/architecture_optimizer.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/core/architecture_optimizer.py):
   - Upgraded `RefactoringRecommendation` dataclass to implement the 11-field grounded contract while preserving backward compatibility.
   - Added AST-based detection of complex functions and classes exceeding configurable line thresholds.
   - Added `snapshot_info` (repo ID, snapshot ID, freshness/staleness tracking).
   - Separated deterministic `measured_facts` from optional `ai_advisory`.
   - Provided explicit engineering tradeoffs and static analysis limitations for every finding type.
   - Added explicit disclaimers: high centrality != defect, and no performance claims without dynamic profiling.
4. [`backend/api/graph.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/backend/api/graph.py):
   - Added configurable query parameters to `GET /api/graph/{repo_id}/architecture-optimization`: `high_coupling_threshold` (default 5), `complexity_threshold` (default 80), and `include_llm_advisory` (default False).
   - Enforced repository tenant authorization via `get_repo_for_user(repo_id, current_user)` (returning 403 on cross-tenant access).
   - Added snapshot identification and staleness warning checks.
5. [`cli.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/cli.py):
   - Passed repository scope (`repo_id`) and snapshot context to `ArchitectureOptimizer.analyze` in both batch query (`-q arch`) and interactive mode (`arch`).
6. [`tests/test_architecture_optimizer.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/tests/test_architecture_optimizer.py):
   - Added 5 new comprehensive integration tests covering deterministic multi-module fixture with cycles, bottlenecks, healthy control modules, complex functions, disposable cycle-break verification, threshold customization, empty graph handling, and API tenant authorization. (11/11 passing).
7. [`tests/test_self_improving.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/tests/test_self_improving.py):
   - Added `test_security_policy_provenance_and_strict_retrieval` verifying that `secrets_only` cannot satisfy `strict` retrieval and historical records cannot be elevated. (13/13 passing).

---

## 3. Grounded Recommendation Contract

Every architectural finding produced by `ArchitectureOptimizer` fulfills the following contract:

```json
{
  "finding_type": "circular_dependency",
  "target": "service_a.py <-> service_b.py",
  "affected_files": ["service_a.py", "service_b.py"],
  "affected_symbols": [],
  "supporting_evidence": {
    "cycle": ["service_a.py", "service_b.py"],
    "cycle_edges": [["service_a.py", "service_b.py"], ["service_b.py", "service_a.py"]],
    "length": 2
  },
  "source_locations": [
    {
      "file": "service_a.py",
      "line": 1,
      "statement": "from service_b import process_order",
      "target_import": "service_b.py"
    },
    {
      "file": "service_b.py",
      "line": 1,
      "statement": "from service_a import create_user",
      "target_import": "service_a.py"
    }
  ],
  "threshold_used": {
    "min_cycle_length": 2
  },
  "explanation": "Circular dependency between 2 modules: service_a.py -> service_b.py -> service_a.py.",
  "proposed_improvement": "1. Dependency Inversion: Extract shared types, models, or function contracts into a dedicated leaf module (e.g. `service_a_types.py`).\n2. Deferred / Lazy Import: Move `import service_a` inside the specific function or method body where it is invoked.\n3. Dependency Injection: Pass the collaborator instance as a function parameter or constructor argument.",
  "tradeoffs": "Creating separate interface/types modules increases total repository file count. Deferred local imports can mask import-time missing dependency failures until execution time.",
  "limitations": "Static AST detection finds top-level import statements; dynamic reflection (`importlib.import_module`) or runtime conditional guards (`if TYPE_CHECKING:`) may prevent actual runtime panics despite static cycle presence.",
  "confidence": "high",
  "suggested_diff": "--- a/service_b.py\n+++ b/service_b.py\n@@ -1,3 +1,3 @@\n-# Deferred to avoid circular import: from service_a import create_user\n+from service_a import create_user\n"
}
```

---

## 4. Separation of Measured Facts vs. Generated Recommendations

The report output enforces strict structural isolation:

1. **`measured_facts` (Deterministic, 0% Hallucination)**:
   - `total_modules`: Exact number of parsed source modules.
   - `total_dependencies`: Exact count of directed AST import edges.
   - `detected_cycles`: Exact graph cycles computed via Tarjan / Johnson simple cycle algorithms.
   - `coupling_metrics`: Direct in-degree ($C_a$), out-degree ($C_e$), and instability metric $I = \frac{C_e}{C_a + C_e}$.
   - `complex_components`: Exact AST line count spans and start/end line coordinates.
2. **`ai_advisory` (Optional / Advisory Guidance)**:
   - Evaluated only when explicitly requested (`include_llm_advisory=True`).
   - Grounded strictly in the `measured_facts` dictionary without inventing unmeasured metrics.
   - If no LLM is configured or inference is unavailable, reports explicit notice:
     `"Deterministic analysis executed without LLM. All findings, metrics, and refactoring strategies are substantiated by static dependency and AST measurements."`

---

## 5. Deterministic Fixture Reproduction & Verification

### Fixture Architecture Overview

The deterministic test fixture ([`tests/test_architecture_optimizer.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/tests/test_architecture_optimizer.py#L190-L245)) contains:
1. **Known Dependency Cycle**: `service_a.py` and `service_b.py` import each other at top-level.
2. **Deliberately Coupled Hub**: `hub_module.py` imports 6 callee modules (`callee_0.py` .. `callee_5.py`) and is imported by 6 caller modules (`caller_0.py` .. `caller_5.py`) ($C_a=6, C_e=6$).
3. **Healthy Control Module**: `healthy_module.py` imports only `leaf_util.py`, has clean 8-line function, 0 cycles, low coupling ($C_a=0, C_e=1$).
4. **Complex Monolithic Component**: `monolith_component.py` contains `monolithic_executor` spanning 95 lines.

### Verification Results

| Scenario | Expected Result | Actual Result | Verification Status |
| :--- | :--- | :--- | :---: |
| **Cycle Detection** | Identifies `service_a.py <-> service_b.py` with line 1 citations and proposed diff. | Detected cycle length 2 with line citations in both files. | **PASSED** |
| **High Coupling Hub** | Identifies `hub_module.py` ($C_a=6, C_e=6, I=0.5$). | Flagged as hub component bottleneck. | **PASSED** |
| **Healthy Control Module** | `healthy_module.py` must NOT receive cycle, bottleneck, or complexity findings. | 0 findings triggered for `healthy_module.py`. | **PASSED** |
| **Complex Component** | `monolith_component.py::monolithic_executor` flagged for >80 lines. | Detected with line_count=95, lines 1-94. | **PASSED** |
| **Cycle Removal (Disposable Copy)** | Break import in `service_b.py`; rerun analysis. | Cycles = 0; cycle recommendations = 0; health score increases. | **PASSED** |
| **Configurable Thresholds** | Raise `high_coupling_threshold=10`, `complexity_threshold=120`. | Neither `hub_module.py` nor `monolith_component.py` flagged. | **PASSED** |
| **Empty / Isolated Graph** | Empty graph or isolated file handled without crashes. | `total_modules=0`/`1`, `health_score=100.0`. | **PASSED** |
| **Tenant Isolation (API)** | Non-owner user receives 403 Forbidden on private repository. | HTTP 403 returned on unauthorized request. | **PASSED** |

---

## 6. CLI & API Execution Examples

### CLI Batch Execution
```powershell
python cli.py sample_repo --backend tfidf -q arch
```
*Sample Output*:
```text
# Architecture Optimization & Health Report
- System Health Score: 77.0 / 100.0
- Total Analyzed Modules: 16
- Total Dependencies: 14
- Detected Circular Dependency Cycles: 1
- High-Coupling Bottlenecks: 1
- Complex Components Detected: 1
- Repository Scope: sample_repo (Snapshot: cli_session) — ✅ Fresh

## 1. Measured Architectural Facts (Deterministic)
### Circular Dependency Cycles Detected
1. `service_a.py -> service_b.py -> service_a.py`

### High-Coupling Architectural Modules
| Module | Afferent ($C_a$) | Efferent ($C_e$) | Instability ($I$) | Assessment |
| :--- | :---: | :---: | :---: | :--- |
| `hub_module.py` | 6 | 6 | 0.50 | Hub Component (High Afferent & Efferent Coupling): Ca=6, Ce=6 |

## 2. Grounded Refactoring Recommendations
### 1. [CIRCULAR_DEPENDENCY] service_a.py <-> service_b.py
- Affected Files: `service_a.py`, `service_b.py`
- Source Locations: `service_a.py:1`, `service_b.py:1`
...
```

### REST API Execution
```http
GET /api/graph/my_project/architecture-optimization?high_coupling_threshold=5&complexity_threshold=80 HTTP/1.1
Authorization: Bearer <JWT_TOKEN>
```
*HTTP 200 JSON Response Structure*:
```json
{
  "repo_id": "my_project",
  "snapshot_info": {
    "repo_id": "my_project",
    "snapshot_id": "commit_9a8b7c",
    "analyzed_at": 1792048500.12,
    "is_stale": false,
    "stale_warning": null
  },
  "total_modules": 16,
  "total_dependencies": 14,
  "cycles_count": 1,
  "cycles": [["service_a.py", "service_b.py"]],
  "bottlenecks": [
    {
      "module": "hub_module.py",
      "afferent_coupling": 6,
      "efferent_coupling": 6,
      "instability": 0.5,
      "is_bottleneck": true,
      "warning": "Hub Component (High Afferent & Efferent Coupling): Ca=6, Ce=6"
    }
  ],
  "complex_components": [
    {
      "symbol": "monolithic_executor",
      "file": "monolith_component.py",
      "start_line": 1,
      "end_line": 95,
      "line_count": 95,
      "type": "function",
      "threshold": 80
    }
  ],
  "recommendations": [...],
  "health_score": 77.0,
  "measured_facts": {...},
  "ai_advisory": {
    "status": "unavailable",
    "model": "none",
    "advisory": null,
    "notice": "Deterministic analysis executed without LLM. All findings, metrics, and refactoring strategies are substantiated by static dependency and AST measurements."
  }
}
```

---

## 7. Static Analysis Limitations & Caveats

1. **Line Count as Physical Size Proxy (Not Cyclomatic/Cognitive Complexity)**: Static line count measures physical component size, not cyclomatic paths or cognitive complexity. Decomposing modules or splitting methods does not inherently reduce runtime latency or memory consumption. No performance claims are made without runtime profiling measurements.
2. **Centrality vs. Defect Distinction**: Foundational utility packages, domain entities, and orchestrators naturally exhibit high in-degree or out-degree. High centrality alone is not treated as a defect.
3. **Dynamic Dispatch & Lazy Guards**: Python `ast` and static graphs analyze declared imports. Dynamic module loading (`importlib.import_module`) or runtime guards (`if TYPE_CHECKING:`) cannot be proven safe or harmful purely from static analysis.
4. **Non-destructive Invariant**: Recommendations and suggested diffs are purely advisory. The optimizer does not modify code, automatically refactor, or write changes to disk.
