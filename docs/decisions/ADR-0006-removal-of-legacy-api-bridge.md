# ADR-0006: Removal of Legacy Server Bridge and Enforcing Unified Authentication

* **Status**: Accepted
* **Date**: 2026-10-04
* **Deciders**: IntelliCodeX Core Team
* **Technical Area**: Security / Backend Architecture / API Routing

## Context & Problem Statement
ADR-0005 introduced an interim bridge (`server/api.py`) exposing root endpoints (`/ingest`, `/query`, `/localize_bug`, `/dependencies`) that forwarded calls to underlying handlers with `current_user=None`. This design introduced a critical security vulnerability: any client could bypass authentication, rate limiting, and role-based access controls by invoking the unauthenticated legacy routes directly.

## Decision Drivers
- Zero-trust authentication across all repository operations, query engines, bug localizers, and patch appliers.
- Strict multi-tenant data isolation and preventing cross-user repository tampering.
- Eliminate duplicated server entry points and ensure all routes are documented in OpenAPI and protected by `Depends(get_current_user)`.

## Considered Options
1. **Add `Depends(get_current_user)` to `server/api.py`**: Keeps the duplicate server file and legacy alias routes.
2. **Remove `server/api.py` and Legacy Routes Entirely**: Delete `server/api.py`, standardize all clients and tests on `/api/*`, and require JWT authentication across all non-exempt endpoints.

## Decision Outcome
Chosen Option: **Remove `server/api.py` and Legacy Routes Entirely**.
- The `server/api.py` file was deleted.
- All application routes (except public allowlist: `/`, `/health`, `/docs`, `/openapi.json`, `/redoc`, and `/api/auth/*`) now strictly enforce `Depends(get_current_user)`.
- A programmatic route audit test iterates over every route in `app.openapi()` and `app.routes` to ensure no route can be exposed without authentication.

### Consequences
* **Positive**:
  - Eliminated auth bypass vector completely.
  - Consistent RBAC and repository ownership enforcement across all operational endpoints.
  - Simplified codebase with single backend entry point at `backend.main:app`.
* **Negative / Trade-offs**:
  - Unauthenticated legacy development scripts must be updated to register, authenticate, and call `/api/*`.

## Implementation References
- Deprecated File: `server/api.py` (Removed)
- Entry Point: [`backend/main.py`](../../backend/main.py)
- Verification Tests: [`tests/test_auth_and_rbac.py`](../../tests/test_auth_and_rbac.py)
