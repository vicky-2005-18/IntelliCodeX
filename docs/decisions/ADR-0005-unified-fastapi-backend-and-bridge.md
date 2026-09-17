# ADR-0005: Modular Enterprise FastAPI Architecture with Legacy API Bridge

* **Status**: Accepted
* **Date**: 2026-09-17
* **Deciders**: IntelliCodeX Core Team
* **Technical Area**: Backend Architecture / API Routing

## Context & Problem Statement
Early prototypes exposed single-file endpoints (`/ingest`, `/query`, `/localize_bug`, `/dependencies`). As the system grew to support JWT authentication, multi-repository workspaces, Cytoscape graph visualization, analytics metrics, automated documentation export, and code review, maintaining all endpoints in a monolithic script became unmaintainable. However, existing test scripts and simple integration clients rely on the legacy root paths.

## Decision Drivers
- Modular domain-driven REST API design separating authentication, repositories, chat, bugs, patches, graph, analytics, docs, and review.
- Support for token-based JWT authentication (`/api/auth`) while preserving backward compatibility for unauthenticated local development scripts.
- Single unified backend entry point running on port 8000.

## Considered Options
1. **Monolithic API File**: Keep expanding `server/api.py`; results in high merge conflicts and poor separation of concerns.
2. **Hard Breaking Change**: Delete legacy root paths and force all callers to use `/api/*` with mandatory JWT headers; breaks legacy scripts and tests.
3. **Modular Enterprise Backend (`backend/api/*`) with Legacy Bridge (`server/api.py`)**: Implement full modular router architecture mounted under `/api` in `backend/main.py`, and have `server/api.py` import and wrap `backend.main.app` while maintaining legacy root aliases (`/ingest`, `/query`, `/localize_bug`, `/dependencies`).

## Decision Outcome
Chosen Option: **Modular Enterprise Backend with Legacy Bridge**.

### Consequences
* **Positive**:
  - Clear modularity across 9 distinct router files under `backend/api/`.
  - Automatic OpenAPI / Swagger UI documentation generated at `/docs`.
  - Full backward compatibility for Phase 1 legacy endpoints.
* **Negative / Trade-offs**:
  - Two server entry points exist (`backend.main:app` and `server.api:app`), though `server.api:app` is a direct bridge to `backend.main:app`.

## Implementation References
- File: [`backend/main.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/backend/main.py)
- File: [`server/api.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/server/api.py)
- Symbols: `backend.main.app`, `server.api.legacy_ingest`, `server.api.legacy_query`
- Verification Tests: [`tests/test_full_system_integration.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_full_system_integration.py)
