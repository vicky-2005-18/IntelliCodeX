# Architecture Decision Records (ADRs)

This directory maintains the Architecture Decision Records for the IntelliCodeX project.

## What is an ADR?

An Architecture Decision Record (ADR) captures a significant architectural or technical decision along with its context, options considered, decision rationale, and consequences.

## When to Record an ADR

Record an ADR when:
- Selecting or swapping a major dependency or library (e.g., Tree-Sitter vs Regex, FAISS vs ChromaDB).
- Establishing a data persistence or storage schema (e.g., SQLite metadata + FAISS binary vector indices).
- Designing a core workflow or subsystem boundary (e.g., Dual Embedder Fallback, Ochiai SBFL calculation).
- Changing security, authentication, or communication protocols (e.g., JWT auth, FastAPI route modularization).
- Introducing breaking changes or deprecating legacy APIs.

## ADR Template

```markdown
# ADR-XXXX: [Short Title of Decision]

* **Status**: [Proposed | Accepted | Superseded | Deprecated]
* **Date**: YYYY-MM-DD
* **Deciders**: [List of engineers/leads]
* **Technical Area**: [Backend | Core Engine | RAG | Database | UI | CLI]

## Context & Problem Statement
[Describe the context, problem, requirements, and constraints that motivated this decision.]

## Decision Drivers
- [Driver 1, e.g., Offline zero-dependency requirement]
- [Driver 2, e.g., Multi-language grammar accuracy]
- [Driver 3, e.g., Execution speed & memory constraints]

## Considered Options
1. **Option 1**: [Description]
2. **Option 2**: [Description]
3. **Option 3**: [Description]

## Decision Outcome
Chosen Option: **[Option Name]** because [primary rationale].

### Consequences
* **Positive**:
  - [Benefit 1]
  - [Benefit 2]
* **Negative / Trade-offs**:
  - [Trade-off 1]
  - [Mitigation]

## Implementation References
- File: [`core/module.py`](../../core/module.py)
- Symbols: `ClassOrFunction`
```

---

## Log of Decisions

| ID | Title | Status | Date | Primary Implementation File |
| :--- | :--- | :--- | :--- | :--- |
| [ADR-0001](ADR-0001-dual-embedding-strategy.md) | Dual Embedding Engine with Offline Fallback (Ollama + TF-IDF SVD) | Accepted | 2026-09-17 | [`core/embedder.py`](../../core/embedder.py) |
| [ADR-0002](ADR-0002-hybrid-persistence-sqlite-faiss.md) | Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors) | Accepted | 2026-09-17 | [`core/persistence.py`](../../core/persistence.py) |
| [ADR-0003](ADR-0003-tree-sitter-semantic-ast-chunking.md) | Multi-Language Semantic AST Chunking via Tree-Sitter Grammars | Accepted | 2026-09-17 | [`core/tree_sitter_chunker.py`](../../core/tree_sitter_chunker.py) |
| [ADR-0004](ADR-0004-spectrum-fault-localization-and-patch-safeguards.md) | Ochiai SBFL Bug Localization and Defensive Code Patching with Backup | Accepted | 2026-09-17 | [`core/bug_localizer.py`](../../core/bug_localizer.py) |
| [ADR-0005](ADR-0005-unified-fastapi-backend-and-bridge.md) | Modular Enterprise FastAPI Routing with Backward-Compatible Legacy Bridge | Superseded by ADR-0006 | 2026-09-17 | [`backend/main.py`](../../backend/main.py) |
| [ADR-0006](ADR-0006-removal-of-legacy-api-bridge.md) | Removal of Legacy Server Bridge and Enforcing Unified Authentication | Accepted | 2026-10-04 | [`backend/main.py`](../../backend/main.py) |
