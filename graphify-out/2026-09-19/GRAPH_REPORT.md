# Graph Report - intellicodex  (2026-09-18)

## Corpus Check
- 117 files · ~53,618 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 8 file(s) not represented in the graph (top: (none) 3, .bat 3, .1789749828 1)

## Summary
- 1176 nodes · 2599 edges · 71 communities (58 shown, 5 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 105 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `06efb84d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- patch_engine.py
- test_week4_verification.py
- cli.py
- CodeChunk
- AdvancedBugLocalizer
- test_hybrid_search.py
- 2. Current Implementation Status ("What is Done")
- OllamaLLM
- RepositoryDelta
- tree_sitter_chunker.py
- LocalDiskStore
- call_graph.py
- patch_generator.py
- 3. Functional Requirements (FR)
- get_current_user
- Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)
- Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)
- IntelliCodeX — Architecture, LLM Pipeline & File Modification Guide
- api.py
- TfidfEmbedder
- QueryEngine
- AssistantEngine
- test_full_system_end_to_end_pipeline
- test_week3_verification.py
- RepositoryWatcher
- SourceFile
- EnhancedDependencyGraph
- BaseEmbedder
- pkg/auth.py
- PatchEngine
- PatchEngine
- IntelliCodeX — System Architecture & Technical Design
- IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine
- User
- 3. Verified Test Scenarios & Acceptance Criteria
- patches.py
- repos.py
- RepositoryEventHandler
- parser.py
- IntelliCodeX — Project Engineering Roadmap
- test_file_watcher.py
- save_vector_store
- get_repo_engine
- DocumentationGenerator
- backend/config.py
- ADR-0001: Dual Embedding Strategy with Offline Fallback (Ollama + TF-IDF SVD)
- ADR-0002: Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors)
- ADR-0003: Multi-Language Semantic AST Chunking via Tree-Sitter Grammars
- ADR-0004: Spectrum Fault Localization (Ochiai) & Defensive Patch Generation with Backups
- ADR-0005: Modular Enterprise FastAPI Architecture with Legacy API Bridge
- metrics.py
- CodeReviewAssistant
- run_benchmark
- Architecture Decision Records (ADRs)
- service.py
- IntelliCodeX — Project Implementation & Verification Status
- SandboxTestResult
- app.js
- math_utils.py
- .clone_repository
- apply_patch_to_file
- _format_time
- backend/__init__.py

## God Nodes (most connected - your core abstractions)
1. `CodeChunk` - 85 edges
2. `SourceFile` - 76 edges
3. `FaissVectorStore` - 69 edges
4. `TfidfEmbedder` - 59 edges
5. `main()` - 41 edges
6. `ingest_repository()` - 41 edges
7. `QueryEngine` - 36 edges
8. `User` - 34 edges
9. `BaseEmbedder` - 34 edges
10. `PatchEngine` - 34 edges

## Surprising Connections (you probably didn't know these)
- `RepositoryAnalyticsEngine` --uses--> `CodeChunk`  [INFERRED]
  backend/analytics/metrics.py → core/chunker.py
- `RepositoryAnalyticsEngine` --uses--> `SourceFile`  [INFERRED]
  backend/analytics/metrics.py → core/parser.py
- `legacy_generate_patch()` --uses--> `GeneratePatchRequest`  [INFERRED]
  server/api.py → backend/api/patches.py
- `generate_patch()` --uses--> `PatchEngine`  [INFERRED]
  backend/api/patches.py → core/patch_generator.py
- `approve_patch()` --uses--> `PatchEngine`  [INFERRED]
  backend/api/patches.py → core/patch_generator.py

## Import Cycles
- None detected.

## Communities (71 total, 5 thin omitted)

### Community 0 - "patch_engine.py"
Cohesion: 0.11
Nodes (30): Patch Generator Package (Phase 1), extract_code_and_explanation(), _looks_like_code(), LLM Response Parser Extracts code blocks and explanation text from unstructured…, Parse an LLM response into (code, explanation). Handles responses with one or…, Heuristic: response is likely source code rather than prose., merge_snippet_into_file(), Replace a snippet region inside a full file with the patched version. First… (+22 more)

### Community 1 - "test_week4_verification.py"
Cohesion: 0.09
Nodes (25): Advanced Bug Localization Package, BugLocalizer, calculate_ochiai_score(), calculate_ochiai_spectrum(), CoverageRecord, ParsedStackTrace, Any, DiGraph (+17 more)

### Community 2 - "cli.py"
Cohesion: 0.11
Nodes (31): check_ollama_available(), format_time_consumed(), get_available_repos(), main(), on_auto_reindex(), print_banner(), print_help(), print_ingestion_summary() (+23 more)

### Community 3 - "CodeChunk"
Cohesion: 0.08
Nodes (29): Repository AI Assistant Engine (Phase 3) Enhances RAG chat with query intent…, make_chunk(), CodeChunk, What actually gets embedded — code + surrounding context., FaissVectorStore, ndarray, Vector Database Layer — FAISS-backed similarity search over CodeChunks., Promote the flat index to an IVFFlat approximate index for faster large-repo… (+21 more)

### Community 4 - "AdvancedBugLocalizer"
Cohesion: 0.12
Nodes (13): AdvancedBugLocalizer, ParsedStackTrace, Any, DiGraph, Advanced Bug Localization Engine (Phase 2) Combines stack trace parsing, error…, Pinpoints bug locations by combining: - Stack trace frame matching - Semantic…, Single frame extracted from a stack trace., Collect dependency graph signals for a candidate file. (+5 more)

### Community 5 - "test_hybrid_search.py"
Cohesion: 0.05
Nodes (31): BM25Index, BM25 Lexical Indexer for Software Repositories (Milestone 3) Provides inverted…, Computes Okapi IDF with smoothing to ensure non-negative values: IDF(q) = ln(1…, Searches the inverted index with BM25 Okapi scoring. Returns top-K matching…, Code-aware tokenizer: 1. Splits text into raw identifier and literal tokens. 2.…, Inverted index implementation using the BM25 Okapi probabilistic ranking model.…, Builds the BM25 inverted index from a list of code chunks., tokenize_code() (+23 more)

### Community 6 - "2. Current Implementation Status ("What is Done")"
Cohesion: 0.06
Nodes (30): 1. Executive Summary, 2.1 Core Code Ingestion & AST Parsing, 2.2 Graph Dependency & Call-Graph Engine, 2.3 Vector Database & Persistence, 2.4 RAG Engine & Persona System, 2.5 Fault Localization (SBFL / Ochiai) & Patch Generator, 2.6 Enterprise Backend API (FastAPI), 2.7 Modern Web Frontend (React + Vite + Tailwind) (+22 more)

### Community 7 - "OllamaLLM"
Cohesion: 0.11
Nodes (17): create_embedder(), create_llm(), LLM & Embedder Factory Centralizes creation of Ollama clients using enterprise…, Create an embedder instance based on backend preference., Create an LLM client when Ollama backend is active; otherwise None., create_components(), Factory helper to instantiate embedder and LLM with automatic fallback., _get_embedding_cache() (+9 more)

### Community 9 - "tree_sitter_chunker.py"
Cohesion: 0.14
Nodes (25): _extract_c_cpp_chunks(), walk(), _extract_go_chunks(), _extract_java_chunks(), walk(), _extract_js_ts_chunks(), walk(), _extract_node_name() (+17 more)

### Community 10 - "LocalDiskStore"
Cohesion: 0.20
Nodes (5): DatabaseManager, LocalDiskStore, Any, Database & Persistent Storage Module (Phase 7) Provides MongoDB document…, File-backed fallback database when MongoDB is offline.

### Community 11 - "call_graph.py"
Cohesion: 0.08
Nodes (46): build_call_graph(), calculate_symbol_centrality(), CallSite, extract_function_calls(), _extract_python_calls(), _extract_tree_sitter_calls(), walk(), find_callees_of_chunk() (+38 more)

### Community 12 - "patch_generator.py"
Cohesion: 0.09
Nodes (20): DiGraph, DiGraph, Multi-File Context-Aware Code Patch Generator Engine (Milestone 1) Extracts…, Any, Isolated Sandbox Test Execution Runner for IntelliCodeX (Milestone 1) Executes…, Copies repo to an isolated temporary sandbox, applies patched_code to…, Copies source files into sandbox directory ignoring heavy/cache artifacts., Extracts passed/failed counts, assertion messages, and traceback highlights… (+12 more)

### Community 13 - "3. Functional Requirements (FR)"
Cohesion: 0.08
Nodes (23): 1.1 Problem Statement, 1.2 Objectives, 1.3 System Scope, 1. Problem Statement & Objectives, 2. Requirements Classification, 3. Functional Requirements (FR), 4. Inferred Requirements (IR), 5. Non-Functional Requirements (NFR) (+15 more)

### Community 14 - "get_current_user"
Cohesion: 0.14
Nodes (23): login(), post, Auth API Router (Phase 11) Endpoints for user registration, authentication,…, register(), Authentication Package, create_access_token(), decode_access_token(), get_current_user() (+15 more)

### Community 15 - "Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)"
Cohesion: 0.09
Nodes (21): Executive Summary, High-Level Semester 2 Timeline (10 Weeks Preview), Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next), Manual Verification of Plan, PHASE 1: Core Engine & Multi-Language Parsing (Weeks 1 – 3), PHASE 2: Intelligent Retrieval, RAG & Automated Patch Generation (Weeks 4 – 6), PHASE 3: Rich Terminal UI (TUI), UX & CLI Packaging (Weeks 7 – 8), PHASE 4: Benchmarking, Testing & Semester Final Demo (Weeks 9 – 10) (+13 more)

### Community 16 - "Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)"
Cohesion: 0.09
Nodes (21): Executive Summary, High-Level Semester 2 Timeline (10 Weeks Preview), Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next), Manual Verification of Plan, PHASE 1: Core Engine & Multi-Language Parsing (Weeks 1 – 3), PHASE 2: Intelligent Retrieval, RAG & Automated Patch Generation (Weeks 4 – 6), PHASE 3: Rich Terminal UI (TUI), UX & CLI Packaging (Weeks 7 – 8), PHASE 4: Benchmarking, Testing & Semester Final Demo (Weeks 9 – 10) (+13 more)

### Community 17 - "IntelliCodeX — Architecture, LLM Pipeline & File Modification Guide"
Cohesion: 0.09
Nodes (21): 1. Multi-Language AST Parsing via Tree-Sitter, 1. Project Overview & Architecture, 2. Models & Generation Parameters, 2. Multi-turn Agentic Tool Calling & Iterative Fixes, 3. High-Quality Code Model Selection & Fine-Tuning, 3. How the LLM Generates Code & Modifies Files, 4. Codebase-wide Persistence & Incremental Re-indexing, 4. Feature Index & Code Mapping (+13 more)

### Community 18 - "api.py"
Cohesion: 0.18
Nodes (16): BugReportRequest, localize_bug(), BaseModel, post, Bug Localization API Router (Phase 2) Submits stack traces or error logs to…, ask_assistant(), BaseModel, post (+8 more)

### Community 19 - "TfidfEmbedder"
Cohesion: 0.13
Nodes (22): Benchmarking Engine for IntelliCodeX Repository Parsing & Ingestion Measures…, Embedding Generation Module Two backends: - OllamaEmbedder: calls a local…, Local, dependency-light fallback. Fit once on the corpus, then transform., TfidfEmbedder, ingest_repository(), IngestedRepository, Ingests a repository directory with incremental re-indexing & disk caching…, Full System Cross-Module Integration & Stress Testing Suite (Week 6 Day 5)… (+14 more)

### Community 20 - "QueryEngine"
Cohesion: 0.13
Nodes (13): QueryEngine, Multi-Turn Repository-Aware Query Engine with Hybrid RRF Search., Toggles or explicitly sets the active hybrid search state., Sets the active AI persona and system prompt., Switches the active LLM model if supported., Clears current conversation history., Week 5 Comprehensive Milestone Verification Suite Tests ConversationMemory…, 5. Verifies dynamic model switching on OllamaLLM and QueryEngine. (+5 more)

### Community 21 - "AssistantEngine"
Cohesion: 0.20
Nodes (7): AssistantEngine, Any, DiGraph, QueryIntent, Enterprise repository assistant that combines: - Intent-aware retrieval…, Enum, str

### Community 22 - "test_full_system_end_to_end_pipeline"
Cohesion: 0.18
Nodes (18): check_git_hooks_status(), find_git_dir(), install_git_hooks(), Git Hook Generator & Installer Module Installs post-commit and post-merge hooks…, Removes IntelliCodeX hook sections from post-commit and post-merge files.…, Returns a dict mapping hook names (post-commit, post-merge) -> boolean…, Locates the .git directory inside repo_path (supports regular git repos and git…, Installs post-commit and post-merge hooks into <repo_path>/.git/hooks/. Returns… (+10 more)

### Community 23 - "test_week3_verification.py"
Cohesion: 0.10
Nodes (46): compute_file_hash(), delete_files_from_db(), detect_repository_changes(), get_db_connection(), get_faiss_index_path(), get_repo_id(), init_schema(), load_faiss_index() (+38 more)

### Community 24 - "RepositoryWatcher"
Cohesion: 0.16
Nodes (7): Any, Real-Time Filesystem Watcher Daemon for active repository directories. Runs a…, Starts the background filesystem observer thread., Stops the background filesystem observer thread gracefully., Returns True if the background watcher thread is actively monitoring., Executes thread-safe incremental re-indexing of the repository. Updates…, RepositoryWatcher

### Community 25 - "SourceFile"
Cohesion: 0.20
Nodes (21): chunk_file(), _chunk_markdown_file(), chunk_python_file(), chunk_repository(), _extract_imports(), Semantic Chunking Engine - Python: AST-based extraction of functions/classes…, Chunks markdown documents by section headings (# Heading)., Chunks non-AST or unparsable files into overlapping line windows. (+13 more)

### Community 26 - "EnhancedDependencyGraph"
Cohesion: 0.14
Nodes (9): EnhancedDependencyGraph, Any, DiGraph, Enhanced Dependency Graph Engine (Phase 4) Supports file imports, class…, Finds circular dependency cycles in file imports., Exports graph in Cytoscape.js format for interactive UI rendering., Enhanced Dependency Graph Package, Unit Tests for Enhanced Dependency Graph (Phase 4) (+1 more)

### Community 27 - "BaseEmbedder"
Cohesion: 0.15
Nodes (12): ABC, GitService, Git Integration Service (Phase 9) Clones remote GitHub/GitLab repositories,…, Retrieves recent commit log history., Lists repository branches., Gets list of modified or untracked files., compute_file_hash(), IncrementalIndexer (+4 more)

### Community 28 - "pkg/auth.py"
Cohesion: 0.13
Nodes (13): authenticate(), hash_password(), Authentication utilities for the sample application., Check a username/password pair against stored credentials., Tracks active user sessions in memory., Returns True if token exists in active sessions., Hash a plaintext password with a salt using SHA-256., SessionManager (+5 more)

### Community 29 - "PatchEngine"
Cohesion: 0.19
Nodes (10): PatchEngine, Any, Closed-Loop Agentic Test-Driven Repair (Milestone 1)., Update approval status. When status is 'applied', writes the patch to disk., Context-aware patch generation engine with closed-loop sandbox test…, Generate a patch recommendation based on error report and repository context., format_context(), Formats expanded code chunks into markdown code blocks with dynamic token… (+2 more)

### Community 30 - "PatchEngine"
Cohesion: 0.23
Nodes (9): generate_git_diff(), PatchEngine, Any, Closed-Loop Agentic Test-Driven Repair (Milestone 1). Generates patch, tests…, Generates standard unified git diff format., Applies suggested patch directly to physical file on disk., Helper to merge snippet into full file or return snippet directly., Context-aware multi-file patch generation engine with closed-loop sandbox test… (+1 more)

### Community 31 - "IntelliCodeX — System Architecture & Technical Design"
Cohesion: 0.12
Nodes (16): 1. Architectural Overview & System Decomposition, 2.1 Technology Stack Matrix, 2.2 Application Entry Points, 2. Technology Stack & Entry Points, 3.1 Code Ingestion & Multi-Language Parsing (`core/parser.py`, `core/ts_loader.py`, `core/tree_sitter_chunker.py`), 3.2 Graph Analysis Subsystem (`core/dependency_graph.py`, `core/call_graph.py`), 3.3 Dual Embedding & Vector Indexing (`core/embedder.py`, `core/vectorstore.py`), 3.4 Hybrid Persistence Subsystem (`core/persistence.py`, `backend/database/mongo.py`) (+8 more)

### Community 32 - "IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine"
Cohesion: 0.12
Nodes (16): 1. Project Purpose & Target Users, 2. Current Capabilities & Important Limitations, 3. Prerequisites & Environment Configuration, 4.1 Clone Repository & Setup Virtual Environment `[TESTED]`, 4.2 Run IntelliCodeX Interactive CLI `[TESTED]`, 4.3 Start Local Backend API Server (Optional) `[TESTED]`, 4. Installation & Startup Instructions, 5. Minimal Usage Example (CLI) (+8 more)

### Community 33 - "User"
Cohesion: 0.19
Nodes (14): get_me(), get, get_bug_reports(), get, get_chat_history(), get, analyze_code(), CommitMsgRequest (+6 more)

### Community 34 - "3. Verified Test Scenarios & Acceptance Criteria"
Cohesion: 0.13
Nodes (14): 1.1 Test Directory Structure, 1. Test Suite Organization & Execution Commands, 2.1 Complete Automated Test Suite, 2.2 Performance Benchmarking Command, 2. Test Execution Commands, 3.1 Core Ingestion & AST Parsing Scenarios, 3.2 Graph Analysis & Centrality Scenarios, 3.3 Persistence & Incremental Re-Indexing Scenarios (+6 more)

### Community 35 - "patches.py"
Cohesion: 0.21
Nodes (12): approve_patch(), generate_patch(), GeneratePatchRequest, list_patches(), PatchApprovalRequest, BaseModel, get, post (+4 more)

### Community 36 - "repos.py"
Cohesion: 0.31
Nodes (10): clone_repo(), GitCloneRequest, ingest_repo(), IngestRequest, list_repos(), BaseModel, get, post (+2 more)

### Community 37 - "RepositoryEventHandler"
Cohesion: 0.19
Nodes (5): Watchdog event handler that debounces file system events on active repository…, Cancels any pending timer and flushes state., RepositoryEventHandler, FileSystemEventHandler, test_repository_event_handler_debouncing()

### Community 38 - "parser.py"
Cohesion: 0.13
Nodes (22): Multi-Language Parser Package, parse_and_chunk_file(), parse_generic_file(), parse_repository_files(), Multi-Language Repository Parser Engine (Phase 10) Supports Python, JavaScript,…, Walk repository and detect all multi-language files., Pattern-based structure extractor for non-Python languages (JS, TS, Java, Go,…, Synchronizes changed files against previous file hashes. Re-embeds only… (+14 more)

### Community 39 - "IntelliCodeX — Project Engineering Roadmap"
Cohesion: 0.14
Nodes (13): 1. Prioritized Milestones & Dependency Flow, 2. Milestone 1: Closed-Loop Agentic Test-Driven Repair (Self-Healing Code) `[ESSENTIAL - SEMESTER 1]`, 3. Milestone 2: Real-Time Filesystem Watcher Daemon `[CORE PERFORMANCE - SEMESTER 1]`, 4. Milestone 3: Hybrid BM25 & Dense Reciprocal Rank Fusion (RRF) `[RETRIEVAL OPTIMIZATION - SEMESTER 1]`, 5. Milestone 4: Advanced Terminal TUI & CLI Packaging `[CLI EXPERIENCE - SEMESTER 1]`, 6. Milestone 5: Full Web Application Workspace `[FUTURE PHASE - SEMESTER 2]`, 7. Milestone 6: Distributed Vector Storage & Enterprise CI/CD `[FUTURE PHASE - SEMESTER 2]`, IntelliCodeX — Project Engineering Roadmap (+5 more)

### Community 40 - "test_file_watcher.py"
Cohesion: 0.19
Nodes (10): is_ignored_path(), Checks if a filesystem path should be ignored by the watcher. Ignores hidden…, skipif, Unit & Integration Tests for Milestone 2: Real-Time Filesystem Watcher Daemon…, test_is_ignored_path(), test_repository_event_handler_filtering(), test_repository_watcher_lifecycle(), test_repository_watcher_live_incremental_reindex() (+2 more)

### Community 41 - "save_vector_store"
Cohesion: 0.27
Nodes (8): get_index_paths(), load_vector_store(), FAISS Vector Store Persistence Module (Phase 7) Handles disk serialization and…, Serialize FAISS index and chunk metadata to disk., Load FAISS index and chunk metadata from disk if available., save_vector_store(), Unit Tests for FAISS Vector Store Disk Serialization and Database Manager…, test_faiss_persistence()

### Community 42 - "get_repo_engine"
Cohesion: 0.14
Nodes (16): get_analytics(), get, Repository Analytics API Router (Phase 5) Provides high-level stats, language…, DocGenRequest, generate_documentation(), BaseModel, post, Documentation Generator API Router (Phase 6) Auto-generates Markdown READMEs,… (+8 more)

### Community 43 - "DocumentationGenerator"
Cohesion: 0.25
Nodes (4): DocumentationGenerator, Automated Documentation Generator Engine (Phase 6) Generates READMEs, API…, Converts markdown content to printable HTML/PDF styled document., Documentation Generator Package

### Community 44 - "backend/config.py"
Cohesion: 0.25
Nodes (7): BaseModel, IntelliCodeX Enterprise Configuration Module Centralized settings management…, Settings, health(), get, IntelliCodeX Enterprise FastAPI Backend Application Entry Point, root()

### Community 45 - "ADR-0001: Dual Embedding Strategy with Offline Fallback (Ollama + TF-IDF SVD)"
Cohesion: 0.25
Nodes (7): ADR-0001: Dual Embedding Strategy with Offline Fallback (Ollama + TF-IDF SVD), Consequences, Considered Options, Context & Problem Statement, Decision Drivers, Decision Outcome, Implementation References

### Community 46 - "ADR-0002: Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors)"
Cohesion: 0.25
Nodes (7): ADR-0002: Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors), Consequences, Considered Options, Context & Problem Statement, Decision Drivers, Decision Outcome, Implementation References

### Community 47 - "ADR-0003: Multi-Language Semantic AST Chunking via Tree-Sitter Grammars"
Cohesion: 0.25
Nodes (7): ADR-0003: Multi-Language Semantic AST Chunking via Tree-Sitter Grammars, Consequences, Considered Options, Context & Problem Statement, Decision Drivers, Decision Outcome, Implementation References

### Community 48 - "ADR-0004: Spectrum Fault Localization (Ochiai) & Defensive Patch Generation with Backups"
Cohesion: 0.25
Nodes (7): ADR-0004: Spectrum Fault Localization (Ochiai) & Defensive Patch Generation with Backups, Consequences, Considered Options, Context & Problem Statement, Decision Drivers, Decision Outcome, Implementation References

### Community 49 - "ADR-0005: Modular Enterprise FastAPI Architecture with Legacy API Bridge"
Cohesion: 0.25
Nodes (7): ADR-0005: Modular Enterprise FastAPI Architecture with Legacy API Bridge, Consequences, Considered Options, Context & Problem Statement, Decision Drivers, Decision Outcome, Implementation References

### Community 50 - "metrics.py"
Cohesion: 0.33
Nodes (4): Any, DiGraph, Repository Analytics Dashboard Engine (Phase 5) Computes repository structure…, RepositoryAnalyticsEngine

### Community 51 - "CodeReviewAssistant"
Cohesion: 0.22
Nodes (5): CodeReviewAssistant, Any, Code Review Assistant & Commit Message Generator (Phases 14 & 15) Performs…, Scans source code for potential bugs, smells, complexity, naming & security…, Generates AI commit message from git diff.

### Community 52 - "run_benchmark"
Cohesion: 0.36
Nodes (7): BenchmarkReport, Runs performance benchmarking measuring fresh vs cached ingestion speed, query…, run_benchmark(), Tests for Benchmarking Engine, test_benchmarking_sample_repo(), 6. Verifies zero-latency startup benchmarking on sample_repo., test_week3_benchmark_performance_verification()

### Community 53 - "Architecture Decision Records (ADRs)"
Cohesion: 0.33
Nodes (5): ADR Template, Architecture Decision Records (ADRs), Log of Decisions, What is an ADR?, When to Record an ADR

### Community 54 - "service.py"
Cohesion: 0.60
Nodes (3): connect_db(), main_run(), process_data()

### Community 55 - "IntelliCodeX — Project Implementation & Verification Status"
Cohesion: 0.40
Nodes (4): 1. Status Classification Guidelines, 2. Feature-Level Verification Matrix, 3. Discrepancy & Gap Analysis, IntelliCodeX — Project Implementation & Verification Status

### Community 56 - "SandboxTestResult"
Cohesion: 0.33
Nodes (5): Remove accidental language tag left on the first line of extracted code., strip_language_prefix(), Prompts LLM to self-correct patch based on failed sandbox test outputs., Encapsulates the execution results of a sandboxed test run., SandboxTestResult

### Community 60 - "apply_patch_to_file"
Cohesion: 0.33
Nodes (6): apply_patch_to_file(), apply_unified_diff(), Any, Patch Application Module Safely applies approved patches to the repository…, Write patched content to the target file within the repository. Creates a .bak…, Apply a unified diff using git apply when available. Falls back to manual…

### Community 61 - "_format_time"
Cohesion: 0.40
Nodes (3): _format_time(), ndarray, Formats duration in human-readable format.

## Knowledge Gaps
- **158 isolated node(s):** `CallSite`, `Target Users:`, `Implemented Capabilities (Tested & Verified)`, `Important Limitations`, `Prerequisites` (+153 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 526 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodeChunk` connect `CodeChunk` to `patch_engine.py`, `test_week4_verification.py`, `test_hybrid_search.py`, `parser.py`, `save_vector_store`, `DocumentationGenerator`, `call_graph.py`, `patch_generator.py`, `metrics.py`, `TfidfEmbedder`, `QueryEngine`, `AssistantEngine`, `test_week3_verification.py`, `SourceFile`, `BaseEmbedder`, `PatchEngine`?**
  _High betweenness centrality (0.103) - this node is a cross-community bridge._
- **Why does `FaissVectorStore` connect `CodeChunk` to `patch_engine.py`, `test_week4_verification.py`, `AdvancedBugLocalizer`, `test_hybrid_search.py`, `parser.py`, `save_vector_store`, `patch_generator.py`, `TfidfEmbedder`, `QueryEngine`, `AssistantEngine`, `test_week3_verification.py`, `SourceFile`, `BaseEmbedder`, `PatchEngine`, `PatchEngine`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `PatchEngine` connect `PatchEngine` to `test_week4_verification.py`, `cli.py`, `patches.py`, `CodeChunk`, `OllamaLLM`, `patch_generator.py`, `TfidfEmbedder`, `test_full_system_end_to_end_pipeline`, `SandboxTestResult`, `BaseEmbedder`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `CodeChunk` (e.g. with `RepositoryAnalyticsEngine` and `DocumentationGenerator`) actually correct?**
  _`CodeChunk` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `SourceFile` (e.g. with `RepositoryAnalyticsEngine` and `EnhancedDependencyGraph`) actually correct?**
  _`SourceFile` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `FaissVectorStore` (e.g. with `AdvancedBugLocalizer` and `save_vector_store()`) actually correct?**
  _`FaissVectorStore` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `TfidfEmbedder` (e.g. with `test_create_components_ollama_fallback()` and `test_create_components_tfidf()`) actually correct?**
  _`TfidfEmbedder` has 4 INFERRED edges - model-reasoned connections that need verification._