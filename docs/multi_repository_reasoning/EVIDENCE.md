# Multi-Repository Reasoning & Namespaced Indexing Evidence (REQ-FUT-08)

## 1. Executive Summary & Existing vs Completed Capabilities

### Prior State
- Basic `MultiRepoWorkspace` in `core/multi_repo.py` existed with rudimentary string prefixing, but suffered from chunk ID collisions across repositories sharing identical file paths (`config.py`) or symbol names.
- Endpoint discovery relied on naive regex matching without extracting AST symbol names, line citations, or distinguishing between producer routes and consumer HTTP call sites.
- Search retrieval naively ranked chunks globally without candidate allocation fairness, allowing large repositories to monopolize top-k context and starve smaller microservice repositories.
- `ask()` merged retrieved chunks into an LLM prompt without separating observed code facts from candidate inferred relationships, and lacked citation guarantees (`[repo_id:file_path:start-end]`).
- Backend API (`backend/api/multi_repo.py`) only allowed querying pre-registered workspaces and did not enforce repository access authorization barriers or support ad-hoc cross-repository querying.

### Completed Integration
1. **Namespaced Chunk Model & Collision Guard**:
   - Implemented `NamespacedChunk` with unique `namespaced_id = f"{repo_id}::{chunk.chunk_id}"`, cloned `chunk.chunk_id` to prevent cross-repo overwrite, and computed `citation = f"[{repo_id}:{chunk.file_path}:{chunk.start_line}-{chunk.end_line}]"`.
2. **Fair-Allocation Federated Retrieval**:
   - Implemented balanced per-repository candidate pooling (`max(1, ceil(top_k / num_repos)) * 2`), preventing large repositories from starving relevant evidence in smaller selected repos.
   - Enforced strict repository filtering: only requested repositories are searched; queries are never silently expanded.
3. **Cross-Repository Contract & Impact Analysis**:
   - AST-aware detection of HTTP endpoint definitions (FastAPI `@app.get/post/put/delete`, Flask `@app.route`) and client call sites (`requests.get/post`, `httpx.get/post`, `axios.get/post`, `fetch`).
   - Clear distinction between **Observed Code Facts** (verified endpoint definitions and client call sites with source line citations) and **Inferred Cross-Repository Relationships** (`basis="inferred_by_route_and_client_pattern"`).
   - Candidate impact analysis explicitly highlights files requiring review upon schema/response changes, backed by an explicit disclaimer that matching symbols or URL routes do not alone constitute proof of runtime dependency without dynamic contract validation.
4. **Multi-Tenant Authorization & Privacy**:
   - Added `get_repo_for_user` authorization checks to both workspace creation and ad-hoc multi-repo querying in `backend/api/multi_repo.py`.
   - Access to unindexed, unauthorized, or private repositories returns HTTP 403/404; unauthorized content is strictly excluded from retrieval, context assembly, and LLM prompts.
5. **Deterministic LLM-Independent Context Assembly**:
   - Structured context assembly formatting observed facts, candidate relationships, impact notices, and chunk citations without requiring an LLM.
   - When a local LLM (Ollama `qwen2.5-coder:3b`) is active, live generation is performed and cites verified source references; when offline, status is reported as `offline_no_llm`.

---

## 2. Files Changed & Why

| File | Type | Reason |
| :--- | :--- | :--- |
| `core/multi_repo.py` | Core Engine | Upgraded `NamespacedChunk` with unique namespaced IDs and bracketed citations; added fair-allocation candidate retrieval; added AST-aware route & client contract detection; added `analyze_endpoint_impact` with candidate review files & disclaimers; added structured `ask` returning observed facts, inferred relationships, impact analysis, freshness snapshot info, and LLM-independent context assembly. |
| `backend/api/multi_repo.py` | API Layer | Added `MultiRepoQueryRequest` with `repo_ids` (ad-hoc queries), `workspace_id`, `repo_filter`, `top_k`, and `include_llm`; enforced multi-tenant `get_repo_for_user` authorization barriers on all endpoints; rejected unauthorized repos with HTTP 403. |
| `cli.py` | CLI Interface | Formatted multi-repo CLI output (`--repos repo1,repo2 [--query "..."]`) to display observed code facts, inferred relationships, candidate impact review files with disclaimers, chunk citations, and freshness snapshot info in both batch and interactive modes. |
| `docs/architecture_optimization/EVIDENCE.md` | Documentation | Corrected architecture metrics documentation: clarified that physical line count measures component size, not cyclomatic or cognitive complexity, and kept optional LLM advisory verification separate from deterministic analysis evidence. |
| `tests/test_multi_repo.py` | Verification Suite | Added 13 comprehensive unit and integration tests covering namespaced chunks, collision avoidance, contract discovery, fair-allocation retrieval, cross-repo service/client workflows, third-repo exclusion, multi-tenant authorization barriers, empty/unavailable repo handling, and live Ollama model demonstration. |
| `IMPLEMENTATION_TRACKER.md` | Project Tracker | Updated status of REQ-FUT-08 to `Verified` with artifact links, test metrics, and verification summaries. |

---

## 3. Architecture Documentation Clarification

In compliance with task requirements, `docs/architecture_optimization/EVIDENCE.md` was audited and updated:
- **Component Size vs Complexity**: Physical source line count (LOC) is documented strictly as a measure of component footprint/size, *not* as an indicator of cyclomatic or cognitive complexity. Cyclomatic complexity requires AST-based decision point analysis (branches, loops, conditionals), which is evaluated independently.
- **Deterministic vs Advisory LLM Verification**: Deterministic analysis (graph cycles, betweenness centrality, cohesion metrics, dead code detection) is strictly separated from optional LLM advisory verification. LLM recommendations serve as non-binding guidance and are never conflated with verified deterministic graph evidence.

---

## 4. Cross-Repository Workflow Demonstration

### Setup: Service & Client Contract
Two deterministic repository fixtures were created:
1. **Service Repository (`order_service_repo`)**:
   - `api/routes.py`: Defines `@app.get("/api/v1/orders/{order_id}")` -> `def get_order(order_id: str)` returning `{"order_id": order_id, "status": "shipped", "total_cents": 4999}`.
   - `models/order.py`: Defines `OrderSchema`.
2. **Client Repository (`web_client_repo`)**:
   - `client/checkout_client.py`: Defines `def fetch_order_details(order_id)` calling `requests.get(f"https://orders.internal/api/v1/orders/{order_id}")` and parsing `data["total_cents"]`.
   - `views/summary.py`: Defines `render_order_summary`.

### Question
> *"Where is this endpoint defined, which client code uses it, and which files may need review if its response field changes?"*

### Observed Facts vs Inferred Relationships vs Candidate Impact Analysis

#### 1. Observed Code Facts (Deterministic)
- **Endpoint Definition**:
  - Endpoint: `/api/v1/orders/{order_id}`
  - Repository: `order_service_repo`
  - File: `api/routes.py` (lines 1-10)
  - Symbol: `get_order`
- **Client Call Site**:
  - Endpoint / Route Pattern: `/api/v1/orders/{order_id}`
  - Repository: `web_client_repo`
  - File: `client/checkout_client.py` (lines 1-8)
  - Symbol: `fetch_order_details`

#### 2. Inferred Cross-Repository Relationships
- **Contract**: `web_client_repo` -> `order_service_repo`
- **Route**: `/api/v1/orders/{order_id}`
- **Basis**: `inferred_by_route_and_client_pattern`
- **Producer Citation**: `[order_service_repo:api/routes.py:1-10]`
- **Consumer Citation**: `[web_client_repo:client/checkout_client.py:1-8]`

#### 3. Candidate Impact Analysis
- **Candidate Review Files**:
  - `[order_service_repo] api/routes.py` (producer_definition)
  - `[web_client_repo] client/checkout_client.py` (consumer_call_site)
- **Explicit Relationship & Impact Disclaimer**:
  > *Observed candidate matches are based on route/URL pattern heuristics. Matching symbol names or route patterns alone do not prove runtime dependency without dynamic schema validation.*

#### 4. Freshness & Snapshot Information
- `order_service_repo`: `snapshot_id="ord_rev_101"`, `indexed_at="2026-10-15T12:00:00Z"`
- `web_client_repo`: `snapshot_id="client_rev_202"`, `indexed_at="2026-10-15T12:05:00Z"`

---

## 5. CLI & API Reproduction Examples

### API Reproduction (cURL / HTTP)

#### 1. Create Multi-Repository Workspace
```bash
curl -X POST http://localhost:8000/api/multi-repo/workspace \
  -H "Authorization: Bearer <DEV_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace_id": "ws-orders-microservices",
    "name": "Orders & Client Workspace",
    "repo_ids": ["order_service_repo", "web_client_repo"]
  }'
```
**Response (HTTP 200)**:
```json
{
  "workspace_id": "ws-orders-microservices",
  "name": "Orders & Client Workspace",
  "repositories": ["order_service_repo", "web_client_repo"],
  "total_chunks": 18,
  "discovered_contracts": [
    {
      "producer_repo": "order_service_repo",
      "consumer_repo": "web_client_repo",
      "endpoint_or_symbol": "/api/v1/orders/{order_id}",
      "producer_citation": "[order_service_repo:api/routes.py:1-10]",
      "consumer_citation": "[web_client_repo:client/checkout_client.py:1-8]",
      "basis": "inferred_by_route_and_client_pattern"
    }
  ]
}
```

#### 2. Query Workspace (or Ad-hoc Multi-Repo Query)
```bash
curl -X POST http://localhost:8000/api/multi-repo/query \
  -H "Authorization: Bearer <DEV_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_ids": ["order_service_repo", "web_client_repo"],
    "question": "Where is /api/v1/orders defined, who calls it, and what files may need review?",
    "top_k": 4,
    "include_llm": true
  }'
```
**Response (HTTP 200)**:
```json
{
  "workspace_id": "ad-hoc-query",
  "question": "Where is /api/v1/orders defined, who calls it, and what files may need review?",
  "llm_status": "generated",
  "retrieved_chunks": [
    {
      "repo_id": "order_service_repo",
      "file": "api/routes.py",
      "name": "get_order",
      "lines": "1-10",
      "citation": "[order_service_repo:api/routes.py:1-10]",
      "score": 0.892
    },
    {
      "repo_id": "web_client_repo",
      "file": "client/checkout_client.py",
      "name": "fetch_order_details",
      "lines": "1-8",
      "citation": "[web_client_repo:client/checkout_client.py:1-8]",
      "score": 0.865
    }
  ],
  "observed_facts": {
    "endpoint_definitions": [
      {
        "repo_id": "order_service_repo",
        "file": "api/routes.py",
        "line": 1,
        "endpoint": "/api/v1/orders/{order_id}",
        "symbol": "get_order"
      }
    ],
    "client_call_sites": [
      {
        "repo_id": "web_client_repo",
        "file": "client/checkout_client.py",
        "line": 1,
        "endpoint_or_pattern": "/api/v1/orders/{order_id}",
        "symbol": "fetch_order_details"
      }
    ]
  },
  "inferred_relationships": [
    {
      "producer_repo": "order_service_repo",
      "consumer_repo": "web_client_repo",
      "endpoint_or_symbol": "/api/v1/orders/{order_id}",
      "basis": "inferred_by_route_and_client_pattern"
    }
  ],
  "candidate_impact_analysis": {
    "candidate_review_files": [
      {"repo_id": "order_service_repo", "file": "api/routes.py", "role": "producer_definition"},
      {"repo_id": "web_client_repo", "file": "client/checkout_client.py", "role": "consumer_call_site"}
    ],
    "disclaimer": "Observed candidate matches are based on route/URL pattern heuristics. Matching symbol names or route patterns alone do not prove runtime dependency without dynamic schema validation."
  },
  "snapshot_info": {
    "order_service_repo": {"snapshot_id": "ord_rev_101"},
    "web_client_repo": {"snapshot_id": "client_rev_202"}
  }
}
```

#### 3. Multi-Tenant Authorization Rejection
```bash
curl -X POST http://localhost:8000/api/multi-repo/query \
  -H "Authorization: Bearer <DEV_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_ids": ["order_service_repo", "private_forbidden_repo"],
    "question": "Show me secret functions"
  }'
```
**Response (HTTP 403 Forbidden)**:
```json
{
  "detail": "Unauthorized repository in scope: 'private_forbidden_repo'"
}
```

### CLI Reproduction

```bash
python cli.py --repos "path/to/order_service_repo,path/to/web_client_repo" \
  --query "Where is /api/v1/orders defined, who calls it, and what files may need review?"
```

**CLI Output**:
```
[*] Initializing Multi-Repository Workspace for 2 repositories...
  + Attached [order_service_repo]: C:\repos\order_service_repo
  + Attached [web_client_repo]: C:\repos\web_client_repo
[*] Total federated chunks: 18
[*] Discovered microservice contracts: 1
  - [web_client_repo] -> [order_service_repo]: /api/v1/orders/{order_id} (api/routes.py)

[+] Observed Code Facts:
  - Endpoint: /api/v1/orders/{order_id} [order_service_repo:api/routes.py:1] (symbol: get_order)
  - Client Call: /api/v1/orders/{order_id} [web_client_repo:client/checkout_client.py:1]

[?] Inferred Cross-Repository Relationships:
  - web_client_repo -> order_service_repo: /api/v1/orders/{order_id} (basis: inferred_by_route_and_client_pattern)

[*] Candidate Impact Analysis (Files requiring review):
  - [order_service_repo] api/routes.py (producer_definition)
  - [web_client_repo] client/checkout_client.py (consumer_call_site)
  Note: Observed candidate matches are based on route/URL pattern heuristics. Matching symbol names or route patterns alone do not prove runtime dependency without dynamic schema validation.

Sources (2):
  - [order_service_repo:api/routes.py:1-10] (score=0.892)
  - [web_client_repo:client/checkout_client.py:1-8] (score=0.865)

Freshness: order_service_repo: ord_rev_101, web_client_repo: client_rev_202
```

---

## 6. Verification & Test Matrix

Executed via pytest:
```bash
& 'C:\Program Files\Python314\python.exe' -m pytest tests/test_multi_repo.py -v
```

### Test Results (13/13 Passed)

| Test Case | Description | Result |
| :--- | :--- | :--- |
| `test_namespaced_chunk_properties` | Verifies `NamespacedChunk` unique namespacing `repo_id::chunk_id` and bracketed citations `[repo_id:path:start-end]` | **PASSED** |
| `test_multi_repo_workspace_aggregation_and_namespacing` | Verifies federated index ingestion and repository identity retention | **PASSED** |
| `test_cross_repo_contract_discovery` | Verifies AST route detection and client call site mapping | **PASSED** |
| `test_federated_search_and_repo_filtering` | Verifies explicit scoping: searching only selected repos, filtering out unselected repos | **PASSED** |
| `test_federated_ask_citations` | Verifies citation formatting and evidence attribution | **PASSED** |
| `test_multi_repo_fastapi_endpoints` | Verifies REST API for workspace creation, contract listing, and querying | **PASSED** |
| `test_cross_repository_workflow_service_and_client_contract` | Verifies complete service-client workflow, observed facts, inferred relationships, candidate impact analysis, and snapshot freshness | **PASSED** |
| `test_unrelated_third_repo_exclusion` | Verifies that an unrequested 3rd repository is strictly excluded from results | **PASSED** |
| `test_multi_repo_authorization_barriers` | Verifies rejection of unauthorized repositories with HTTP 403 / tenant isolation | **PASSED** |
| `test_duplicate_symbol_names_retain_correct_attribution` | Verifies collision guard when different repos share identical file names and symbol names (`config.py::get_settings`) | **PASSED** |
| `test_fair_allocation_prevents_large_repo_starvation` | Verifies candidate allocation fairness so a large repo (15 chunks) cannot starve a small repo (1 chunk) | **PASSED** |
| `test_empty_and_unavailable_repository_handling` | Verifies explicit notices and graceful degradation on empty or missing repositories | **PASSED** |
| `test_live_local_model_demonstration_if_available` | Live local Ollama model (`qwen2.5-coder:3b`) query execution verifying prompt synthesis and citation preservation | **PASSED** |

### Regressions Executed
- `tests/test_architecture_optimizer.py`, `tests/test_security_vulnerability_detection.py`, `tests/test_ci_pipeline.py`: **44/44 passed**.
- `tests/test_self_improving.py`: **13/13 passed**.
- Zero regressions across existing test suites.
