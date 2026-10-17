# IntelliCodeX — Presentation Slide Deck Outline

**Presentation Date**: October 23, 2026  
**Project**: IntelliCodeX — AI-Powered Software Repository Intelligence & Automated Repair Engine  
**Presenter**: Vikii  

---

## Slide 1: Title & Overview
- **Title**: IntelliCodeX: Local & Privacy-Preserving Code Intelligence and Verified Automated Repair
- **Subtitle**: Combining Tree-Sitter AST Chunking, Graph-Augmented RAG, and Closed-Loop Sandbox Validation
- **Key Proposition**: Empowering developers to query, diagnose, and repair complex multi-language repositories without transmitting proprietary code to third-party cloud services.
- **Presenter**: Vikii

---

## Slide 2: The Core Problem
- **Context Window Fragility**: Naive RAG dumps raw file slices into prompts, losing call hierarchies, caller-callee scopes, and architectural structure.
- **Unvalidated Patch Hallucination**: Current LLM assistants propose syntactically invalid or regression-introducing fixes that break adjacent modules.
- **Cloud Privacy Barriers**: Proprietary codebases cannot be uploaded to hosted cloud LLMs (OpenAI, Anthropic) due to compliance and security constraints.
- **The Solution**: A 100% locally-executable engine integrating high-precision symbol graphs, BM25 + dense FAISS retrieval, Ochiai fault localization, and Docker test-driven validation before developer approval.

---

## Slide 3: System Architecture
- **Layer 1: Parsing & Chunking**: Tree-Sitter concrete syntax trees across 9 languages (Python, JS, TS, Java, C, C++, Go, Rust) with disambiguated line-bound symbol IDs.
- **Layer 2: Dual Embeddings & Graphs**:
  - Dense local embeddings via Ollama (`nomic-embed-text`) with automatic Scikit-Learn TF-IDF/SVD fallback.
  - NetworkX directed dependency & high-precision call graphs with Python scope resolution (`self`/`cls`), deduplication, and 3-candidate fan-out capping.
- **Layer 3: Retrieval & Context Synthesis**:
  - BM25Okapi lexical matching fused with FAISS dense vector search via Reciprocal Rank Fusion (RRF).
  - Dynamic graph expansion traversing callers, callees, and imported modules under a strict token budget.
- **Layer 4: Closed-Loop Repair & Verification**:
  - Spectrum-based fault localization (SBFL) ranking root-cause candidates.
  - Multi-turn refinement loop inside isolated Docker containers (`--network none`).
  - Central Approval Gate enforcing test verification and security policies before disk application.

---

## Slide 4: Literature Mapping & Theoretical Foundation (25 Papers)
*Organized into five core research themes (Taxonomy adapted from recent automated program repair surveys):*

1. **Repository Graphs & Retrieval (Theme A)**:
   - *CodexGraph, RepoGraph, LocAgent, RepoHYPER*: Demonstrated that graph-augmented symbol traversal improves multi-hop code reasoning over flat text chunks.
   - *IntelliCodeX Implementation*: Scope-aware AST call graphs with caller/callee traversal and RRF fusion.
2. **Agent-Style Repair Workflows (Theme B)**:
   - *RepairAgent, MarsCode Agent, RePair*: Highlighted finite-state machines separating localize, generate, execute, and validate.
   - *IntelliCodeX Implementation*: Closed-loop sandbox testing with iterative self-correction prompting (up to 3 turns).
3. **Patch Validation & Correctness (Theme C)**:
   - *LLM4PatchCorrect, RePaCA, APPATCH*: Emphasized that LLM generated patches must pass concrete static & behavioral checks to avoid plausibility-correctness traps.
   - *IntelliCodeX Implementation*: AST syntax checks, container test execution, and honest "NOT VERIFIED" reporting.
4. **Candidate Generation & Context Editing (Theme D)**:
   - *RepairLLaMA, Search-Generate-Modify, D4C*: Focused on inference-time grounding and prompt construction.
   - *IntelliCodeX Implementation*: Experience bank few-shot examples and grounded context chunk citations.
5. **Efficiency & Evaluation (Theme E)**:
   - Targeted test execution, token budgeting, and empirical trade-off analysis.

---

## Slide 5: Transparent RAG Inspection & Pipeline Provenance
- **Full Pipeline Transparency**: No black-box prompting.
- **Inspection Commands**:
  - `index-stats`: Instant totals of files, chunks, graph nodes, BM25 vocab, and FAISS vectors.
  - `chunks: <file>`: Explores chunk boundaries, token counts, and embedding previews.
  - `explain: <question>`: Exposes the exact augmented prompt seen by the model (instruction block, cited code chunks with line ranges, question).
  - `--compare`: Live side-by-side evaluation of Non-RAG baseline vs RAG-augmented generation.

---

## Slide 6: Agentic Repair & Docker Sandbox Validation
- **Closed-Loop Workflow**:
  ```text
  1. Capture Traceback -> 2. Ochiai Localization -> 3. Synthesize Candidate ->
  4. Execute Sandbox Tests -> 5. Self-Correct if Failed -> 6. Developer Approval Gate
  ```
- **Live Demo Bug (`invoice.py`)**:
  - Classic off-by-one bug in invoice total calculation.
  - Baseline execution fails 2 out of 3 tests.
  - IntelliCodeX localizes error, synthesizes fix, validates all 3 tests pass in Docker, and prints syntax-highlighted diff.
- **Developer Review Gate**:
  - Presents side-by-side / unified diff.
  - Allows developer to inspect, toggle view, or approve.
  - Strict immutability: Files on disk are NOT touched until human confirms.

---

## Slide 7: Central Patch Approval Gate & Guardrails
- **The Verification Invariant**: A patch that has not passed automated tests can NEVER be applied to source files.
- **Approval Gate Policies**:
  - Blocks candidates missing test results or having zero tests.
  - Blocks pre-flight syntax / interface rejections.
  - Evaluates security scanner status (`strict` vs `secrets_only`).
  - `force=True` cannot bypass behavioral or security requirements.
- **Rigorous Verification**: 17 dedicated tests in `tests/test_patch_approval_gate.py` asserting host file immutability.

---

## Slide 8: Empirical Verification & Test Suite Reality
- **Complete Test Suite Status**:
  - **572 passed, 4 skipped** across 576 collected test items.
  - Multi-language sandbox coverage: Python, Go, Rust, Java, C/C++.
  - Zero test regressions on working tree.
- **Claims to Safely Make (Backed by Empirical Evidence)**:
  - Local, privacy-preserving RAG across 9 languages using Tree-Sitter chunking.
  - Hybrid BM25 + dense retrieval with graph context expansion.
  - Spectrum-based fault localization with multi-language stack trace parsing.
  - Honest verification reporting ("NOT VERIFIED: NO TESTS RAN" when tests are skipped).
  - Central approval gate with file immutability prior to review.
- **Claims to Avoid**:
  - Avoid speculative accuracy percentages until Phase 1 measurement is complete.
  - Avoid calling single-node local server "distributed".
  - Avoid calling the system "autonomous" (human approval is a designed safety strength).

---

## Slide 9: Project Roadmap & Next Steps
- **Semester 1 Focus (Completed)**:
  - CLI First terminal assistant with auto-completion and TUI.
  - Offline TF-IDF + Local Ollama dual backend.
  - Automated bug localization and sandbox-verified repair loop.
  - Central Approval Gate & Headless CI/CD pipeline gate.
- **Phase 1: Measurement (Late October – November)**:
  - Benchmark on 15–25 bugs across multiple repositories (including held-out repos).
  - Measure localization top-1/top-3/top-5 accuracy and repair pass rates.
- **Semester 2 Product Work**:
  - React Web UI Dashboard on top of the FastAPI backend.
  - Multi-user authentication & team workspace management.
  - Pre-built multi-language Docker sandbox images.
