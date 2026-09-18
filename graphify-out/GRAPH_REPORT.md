# Graph Report - intellicodex  (2026-09-18)

## Corpus Check
- 115 files · ~51,542 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 8 file(s) not represented in the graph (top: (none) 3, .bat 3, .1789749828 1)

## Summary
- 1145 nodes · 2516 edges · 71 communities (56 shown, 7 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 101 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `49cfb141`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- PatchEngine
- test_week4_verification.py
- cli.py
- CodeChunk
- AdvancedBugLocalizer
- OllamaLLM
- 2. Current Implementation Status ("What is Done")
- test_full_system_integration.py
- test_week3_verification.py
- tree_sitter_chunker.py
- LocalDiskStore
- call_graph.py
- SandboxRunner
- 3. Functional Requirements (FR)
- api/auth.py
- Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)
- Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)
- IntelliCodeX — Architecture, LLM Pipeline & File Modification Guide
- get_repo_engine
- TfidfEmbedder
- QueryEngine
- AssistantEngine
- test_full_system_end_to_end_pipeline
- get_db_connection
- RepositoryWatcher
- SourceFile
- EnhancedDependencyGraph
- incremental_indexer.py
- pkg/auth.py
- test_graph_context_expansion.py
- test_faiss_sqlite_persistence.py
- IntelliCodeX — System Architecture & Technical Design
- IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine
- review.py
- 3. Verified Test Scenarios & Acceptance Criteria
- patches.py
- repos.py
- RepositoryEventHandler
- walk_repository
- IntelliCodeX — Project Engineering Roadmap
- multi_parser.py
- User
- docs.py
- DocumentationGenerator
- test_call_graph.py
- ADR-0001: Dual Embedding Strategy with Offline Fallback (Ollama + TF-IDF SVD)
- ADR-0002: Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors)
- ADR-0003: Multi-Language Semantic AST Chunking via Tree-Sitter Grammars
- ADR-0004: Spectrum Fault Localization (Ochiai) & Defensive Patch Generation with Backups
- ADR-0005: Modular Enterprise FastAPI Architecture with Legacy API Bridge
- metrics.py
- get_current_user
- .add
- Architecture Decision Records (ADRs)
- service.py
- IntelliCodeX — Project Implementation & Verification Status
- .sync_repository
- app.js
- math_utils.py
- .clone_repository
- .start
- test_repository_event_handler_debouncing
- backend/__init__.py

## God Nodes (most connected - your core abstractions)
1. `SourceFile` - 76 edges
2. `CodeChunk` - 74 edges
3. `FaissVectorStore` - 68 edges
4. `TfidfEmbedder` - 56 edges
5. `main()` - 39 edges
6. `ingest_repository()` - 37 edges
7. `User` - 34 edges
8. `BaseEmbedder` - 34 edges
9. `PatchEngine` - 34 edges
10. `PatchEngine` - 29 edges

## Surprising Connections (you probably didn't know these)
- `RepositoryAnalyticsEngine` --uses--> `CodeChunk`  [INFERRED]
  backend/analytics/metrics.py → core/chunker.py
- `RepositoryAnalyticsEngine` --uses--> `SourceFile`  [INFERRED]
  backend/analytics/metrics.py → core/parser.py
- `generate_patch()` --uses--> `PatchEngine`  [INFERRED]
  backend/api/patches.py → core/patch_generator.py
- `approve_patch()` --uses--> `PatchEngine`  [INFERRED]
  backend/api/patches.py → core/patch_generator.py
- `ingest_repo()` --uses--> `QueryEngine`  [INFERRED]
  backend/api/repos.py → rag/query_engine.py

## Import Cycles
- None detected.

## Communities (71 total, 7 thin omitted)

### Community 0 - "PatchEngine"
Cohesion: 0.05
Nodes (63): Patch Generator Package (Phase 1), extract_code_and_explanation(), _looks_like_code(), LLM Response Parser Extracts code blocks and explanation text from unstructured…, Parse an LLM response into (code, explanation). Handles responses with one or…, Heuristic: response is likely source code rather than prose., Remove accidental language tag left on the first line of extracted code., strip_language_prefix() (+55 more)

### Community 1 - "test_week4_verification.py"
Cohesion: 0.09
Nodes (25): Advanced Bug Localization Package, BugLocalizer, calculate_ochiai_score(), calculate_ochiai_spectrum(), CoverageRecord, ParsedStackTrace, Any, DiGraph (+17 more)

### Community 2 - "cli.py"
Cohesion: 0.09
Nodes (38): check_ollama_available(), create_components(), format_time_consumed(), get_available_repos(), main(), on_auto_reindex(), print_banner(), print_help() (+30 more)

### Community 3 - "CodeChunk"
Cohesion: 0.10
Nodes (27): get_index_paths(), load_vector_store(), FAISS Vector Store Persistence Module (Phase 7) Handles disk serialization and…, Serialize FAISS index and chunk metadata to disk., Load FAISS index and chunk metadata from disk if available., save_vector_store(), CodeChunk, What actually gets embedded — code + surrounding context. (+19 more)

### Community 4 - "AdvancedBugLocalizer"
Cohesion: 0.12
Nodes (13): AdvancedBugLocalizer, ParsedStackTrace, Any, DiGraph, Advanced Bug Localization Engine (Phase 2) Combines stack trace parsing, error…, Pinpoints bug locations by combining: - Stack trace frame matching - Semantic…, Single frame extracted from a stack trace., Collect dependency graph signals for a candidate file. (+5 more)

### Community 5 - "OllamaLLM"
Cohesion: 0.07
Nodes (17): DiGraph, Code Review Assistant & Commit Message Generator (Phases 14 & 15) Performs…, OllamaLLM, Dynamically switches active Ollama LLM model., Yields response text tokens in real-time streaming chunks., DiGraph, ConversationMemory, Manages multi-turn conversation dialogue history for RAG queries. (+9 more)

### Community 6 - "2. Current Implementation Status ("What is Done")"
Cohesion: 0.06
Nodes (30): 1. Executive Summary, 2.1 Core Code Ingestion & AST Parsing, 2.2 Graph Dependency & Call-Graph Engine, 2.3 Vector Database & Persistence, 2.4 RAG Engine & Persona System, 2.5 Fault Localization (SBFL / Ochiai) & Patch Generator, 2.6 Enterprise Backend API (FastAPI), 2.7 Modern Web Frontend (React + Vite + Tailwind) (+22 more)

### Community 7 - "test_full_system_integration.py"
Cohesion: 0.11
Nodes (21): ABC, create_embedder(), LLM & Embedder Factory Centralizes creation of Ollama clients using enterprise…, Create an embedder instance based on backend preference., BenchmarkReport, Benchmarking Engine for IntelliCodeX Repository Parsing & Ingestion Measures…, Runs performance benchmarking measuring fresh vs cached ingestion speed, query…, run_benchmark() (+13 more)

### Community 8 - "test_week3_verification.py"
Cohesion: 0.13
Nodes (21): Repository Parser Module - Walks a repository directory recursively - Detects…, delete_files_from_db(), detect_repository_changes(), get_repo_id(), Index Persistence & Metadata Database Manager Uses SQLite…, Generates a canonical, filesystem-friendly repository ID from a local path or…, Unified high-level save function: 1. Saves repository metadata, file hashes,…, Compares current repository source files against stored SHA-256 hashes in… (+13 more)

### Community 9 - "tree_sitter_chunker.py"
Cohesion: 0.14
Nodes (25): _extract_c_cpp_chunks(), walk(), _extract_go_chunks(), _extract_java_chunks(), walk(), _extract_js_ts_chunks(), walk(), _extract_node_name() (+17 more)

### Community 10 - "LocalDiskStore"
Cohesion: 0.11
Nodes (12): BaseModel, IntelliCodeX Enterprise Configuration Module Centralized settings management…, Settings, DatabaseManager, LocalDiskStore, Any, Database & Persistent Storage Module (Phase 7) Provides MongoDB document…, File-backed fallback database when MongoDB is offline. (+4 more)

### Community 11 - "call_graph.py"
Cohesion: 0.14
Nodes (22): calculate_symbol_centrality(), CallSite, find_callees_of_chunk(), get_top_central_symbols(), DiGraph, Fine-Grained Symbol Call Graph Engine - Extracts caller/callee function…, Returns a list of target chunk IDs called by chunk_id., Computes PageRank centrality scores for all function chunks in the call graph.… (+14 more)

### Community 12 - "SandboxRunner"
Cohesion: 0.12
Nodes (16): Any, Copies repo to an isolated temporary sandbox, applies patched_code to…, Copies source files into sandbox directory ignoring heavy/cache artifacts., Extracts passed/failed counts, assertion messages, and traceback highlights…, Fallback parser for generic test runners., Manages isolated temporary directory sandboxes to safely apply patches and…, Detects test framework available in the target repository., SandboxRunner (+8 more)

### Community 13 - "3. Functional Requirements (FR)"
Cohesion: 0.08
Nodes (23): 1.1 Problem Statement, 1.2 Objectives, 1.3 System Scope, 1. Problem Statement & Objectives, 2. Requirements Classification, 3. Functional Requirements (FR), 4. Inferred Requirements (IR), 5. Non-Functional Requirements (NFR) (+15 more)

### Community 14 - "api/auth.py"
Cohesion: 0.19
Nodes (17): login(), post, Auth API Router (Phase 11) Endpoints for user registration, authentication,…, register(), Authentication Package, create_access_token(), hash_password(), BaseModel (+9 more)

### Community 15 - "Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)"
Cohesion: 0.09
Nodes (21): Executive Summary, High-Level Semester 2 Timeline (10 Weeks Preview), Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next), Manual Verification of Plan, PHASE 1: Core Engine & Multi-Language Parsing (Weeks 1 – 3), PHASE 2: Intelligent Retrieval, RAG & Automated Patch Generation (Weeks 4 – 6), PHASE 3: Rich Terminal UI (TUI), UX & CLI Packaging (Weeks 7 – 8), PHASE 4: Benchmarking, Testing & Semester Final Demo (Weeks 9 – 10) (+13 more)

### Community 16 - "Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)"
Cohesion: 0.09
Nodes (21): Executive Summary, High-Level Semester 2 Timeline (10 Weeks Preview), Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next), Manual Verification of Plan, PHASE 1: Core Engine & Multi-Language Parsing (Weeks 1 – 3), PHASE 2: Intelligent Retrieval, RAG & Automated Patch Generation (Weeks 4 – 6), PHASE 3: Rich Terminal UI (TUI), UX & CLI Packaging (Weeks 7 – 8), PHASE 4: Benchmarking, Testing & Semester Final Demo (Weeks 9 – 10) (+13 more)

### Community 17 - "IntelliCodeX — Architecture, LLM Pipeline & File Modification Guide"
Cohesion: 0.09
Nodes (21): 1. Multi-Language AST Parsing via Tree-Sitter, 1. Project Overview & Architecture, 2. Models & Generation Parameters, 2. Multi-turn Agentic Tool Calling & Iterative Fixes, 3. High-Quality Code Model Selection & Fine-Tuning, 3. How the LLM Generates Code & Modifies Files, 4. Codebase-wide Persistence & Incremental Re-indexing, 4. Feature Index & Code Mapping (+13 more)

### Community 18 - "get_repo_engine"
Cohesion: 0.17
Nodes (18): BugReportRequest, localize_bug(), BaseModel, post, Bug Localization API Router (Phase 2) Submits stack traces or error logs to…, ask_assistant(), BaseModel, post (+10 more)

### Community 19 - "TfidfEmbedder"
Cohesion: 0.17
Nodes (16): Local, dependency-light fallback. Fit once on the corpus, then transform., TfidfEmbedder, ingest_repository(), IngestedRepository, Ingests a repository directory with incremental re-indexing & disk caching…, Unit Tests for Incremental Re-Indexing Pipeline (core/pipeline.py - Week 3 Day…, Tests that a 100% unchanged repository loads instantly from cached disk index., Tests incremental re-indexing when files are modified, added, or removed. (+8 more)

### Community 20 - "QueryEngine"
Cohesion: 0.12
Nodes (12): expand_retrieved_context(), DiGraph, QueryEngine, Multi-Turn Repository-Aware Query Engine., Sets the active AI persona and system prompt., Switches the active LLM model if supported., Clears current conversation history., Retrieves top-K vector matches and applies graph-augmented context expansion. (+4 more)

### Community 21 - "AssistantEngine"
Cohesion: 0.18
Nodes (8): AssistantEngine, Any, DiGraph, QueryIntent, Repository AI Assistant Engine (Phase 3) Enhances RAG chat with query intent…, Enterprise repository assistant that combines: - Intent-aware retrieval…, Enum, str

### Community 22 - "test_full_system_end_to_end_pipeline"
Cohesion: 0.18
Nodes (18): check_git_hooks_status(), find_git_dir(), install_git_hooks(), Git Hook Generator & Installer Module Installs post-commit and post-merge hooks…, Removes IntelliCodeX hook sections from post-commit and post-merge files.…, Returns a dict mapping hook names (post-commit, post-merge) -> boolean…, Locates the .git directory inside repo_path (supports regular git repos and git…, Installs post-commit and post-merge hooks into <repo_path>/.git/hooks/. Returns… (+10 more)

### Community 23 - "get_db_connection"
Cohesion: 0.19
Nodes (19): compute_file_hash(), get_db_connection(), init_schema(), load_stored_chunks(), load_stored_file_hashes(), Connection, Returns a dict mapping rel_path -> file_hash for the specified repo_id., Loads all stored CodeChunk objects for the specified repo_id from SQLite. (+11 more)

### Community 24 - "RepositoryWatcher"
Cohesion: 0.15
Nodes (12): Any, Real-Time Filesystem Watcher Daemon for active repository directories. Runs a…, Stops the background filesystem observer thread gracefully., Returns True if the background watcher thread is actively monitoring., Executes thread-safe incremental re-indexing of the repository. Updates…, RepositoryWatcher, skipif, Unit & Integration Tests for Milestone 2: Real-Time Filesystem Watcher Daemon… (+4 more)

### Community 25 - "SourceFile"
Cohesion: 0.25
Nodes (17): chunk_file(), _chunk_markdown_file(), chunk_repository(), Semantic Chunking Engine - Python: AST-based extraction of functions/classes…, Chunks markdown documents by section headings (# Heading)., Chunks non-AST or unparsable files into overlapping line windows., Chunks a source file using AST (Python/Tree-Sitter), Sectioning (Markdown), or…, _windowed_chunks() (+9 more)

### Community 26 - "EnhancedDependencyGraph"
Cohesion: 0.14
Nodes (9): EnhancedDependencyGraph, Any, DiGraph, Enhanced Dependency Graph Engine (Phase 4) Supports file imports, class…, Finds circular dependency cycles in file imports., Exports graph in Cytoscape.js format for interactive UI rendering., Enhanced Dependency Graph Package, Unit Tests for Enhanced Dependency Graph (Phase 4) (+1 more)

### Community 27 - "incremental_indexer.py"
Cohesion: 0.16
Nodes (11): GitService, Git Integration Service (Phase 9) Clones remote GitHub/GitLab repositories,…, Retrieves recent commit log history., Lists repository branches., Gets list of modified or untracked files., IncrementalIndexer, is_ignored_path(), Incremental Repository Indexing & Real-Time Filesystem Watcher Daemon… (+3 more)

### Community 28 - "pkg/auth.py"
Cohesion: 0.13
Nodes (13): authenticate(), hash_password(), Authentication utilities for the sample application., Check a username/password pair against stored credentials., Tracks active user sessions in memory., Returns True if token exists in active sessions., Hash a plaintext password with a salt using SHA-256., SessionManager (+5 more)

### Community 29 - "test_graph_context_expansion.py"
Cohesion: 0.18
Nodes (15): build_call_graph(), Builds a directed function-level Call Graph mapping caller chunks -> callee…, build_dependency_graph(), extract_file_imports(), Builds a directed dependency graph across all source files in the repository., Extracts raw import targets from a SourceFile across all supported languages., Resolves raw import string (relative path, package name, header name) to a…, resolve_import_to_file() (+7 more)

### Community 30 - "test_faiss_sqlite_persistence.py"
Cohesion: 0.15
Nodes (16): get_faiss_index_path(), load_faiss_index(), load_index(), load_repo_metadata(), Any, Loads top-level repository metadata from SQLite., Returns absolute file path for a repository's FAISS index…, Serializes the FAISS vector index to disk (.storage/<repo_id>.faiss). (+8 more)

### Community 31 - "IntelliCodeX — System Architecture & Technical Design"
Cohesion: 0.12
Nodes (16): 1. Architectural Overview & System Decomposition, 2.1 Technology Stack Matrix, 2.2 Application Entry Points, 2. Technology Stack & Entry Points, 3.1 Code Ingestion & Multi-Language Parsing (`core/parser.py`, `core/ts_loader.py`, `core/tree_sitter_chunker.py`), 3.2 Graph Analysis Subsystem (`core/dependency_graph.py`, `core/call_graph.py`), 3.3 Dual Embedding & Vector Indexing (`core/embedder.py`, `core/vectorstore.py`), 3.4 Hybrid Persistence Subsystem (`core/persistence.py`, `backend/database/mongo.py`) (+8 more)

### Community 32 - "IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine"
Cohesion: 0.12
Nodes (16): 1. Project Purpose & Target Users, 2. Current Capabilities & Important Limitations, 3. Prerequisites & Environment Configuration, 4.1 Clone Repository & Setup Virtual Environment `[TESTED]`, 4.2 Run IntelliCodeX Interactive CLI `[TESTED]`, 4.3 Start Local Backend API Server (Optional) `[TESTED]`, 4. Installation & Startup Instructions, 5. Minimal Usage Example (CLI) (+8 more)

### Community 33 - "review.py"
Cohesion: 0.19
Nodes (11): analyze_code(), CommitMsgRequest, FileReviewRequest, generate_commit_message(), BaseModel, post, Code Review & Commit Message API Router (Phases 14 & 15) Performs automated…, CodeReviewAssistant (+3 more)

### Community 34 - "3. Verified Test Scenarios & Acceptance Criteria"
Cohesion: 0.13
Nodes (14): 1.1 Test Directory Structure, 1. Test Suite Organization & Execution Commands, 2.1 Complete Automated Test Suite, 2.2 Performance Benchmarking Command, 2. Test Execution Commands, 3.1 Core Ingestion & AST Parsing Scenarios, 3.2 Graph Analysis & Centrality Scenarios, 3.3 Persistence & Incremental Re-Indexing Scenarios (+6 more)

### Community 35 - "patches.py"
Cohesion: 0.20
Nodes (13): approve_patch(), generate_patch(), GeneratePatchRequest, list_patches(), PatchApprovalRequest, BaseModel, get, post (+5 more)

### Community 36 - "repos.py"
Cohesion: 0.24
Nodes (13): clone_repo(), GitCloneRequest, ingest_repo(), IngestRequest, list_repos(), BaseModel, get, post (+5 more)

### Community 37 - "RepositoryEventHandler"
Cohesion: 0.19
Nodes (5): Watchdog event handler that debounces file system events on active repository…, Cancels any pending timer and flushes state., RepositoryEventHandler, FileSystemEventHandler, test_repository_event_handler_filtering()

### Community 38 - "walk_repository"
Cohesion: 0.22
Nodes (13): detect_language(), is_ignored_by_gitignore(), load_gitignore_patterns(), Checks if relative path matches any .gitignore pattern., Walks repo_root recursively and returns a list of all recognized, non-ignored…, Detects language identifier from filename extension., Parses .gitignore file in repo_root if present., walk_repository() (+5 more)

### Community 39 - "IntelliCodeX — Project Engineering Roadmap"
Cohesion: 0.14
Nodes (13): 1. Prioritized Milestones & Dependency Flow, 2. Milestone 1: Closed-Loop Agentic Test-Driven Repair (Self-Healing Code) `[ESSENTIAL - SEMESTER 1]`, 3. Milestone 2: Real-Time Filesystem Watcher Daemon `[CORE PERFORMANCE - SEMESTER 1]`, 4. Milestone 3: Hybrid BM25 & Dense Reciprocal Rank Fusion (RRF) `[RETRIEVAL OPTIMIZATION - SEMESTER 1]`, 5. Milestone 4: Advanced Terminal TUI & CLI Packaging `[CLI EXPERIENCE - SEMESTER 1]`, 6. Milestone 5: Full Web Application Workspace `[FUTURE PHASE - SEMESTER 2]`, 7. Milestone 6: Distributed Vector Storage & Enterprise CI/CD `[FUTURE PHASE - SEMESTER 2]`, IntelliCodeX — Project Engineering Roadmap (+5 more)

### Community 40 - "multi_parser.py"
Cohesion: 0.22
Nodes (11): Multi-Language Parser Package, parse_and_chunk_file(), parse_generic_file(), parse_repository_files(), Multi-Language Repository Parser Engine (Phase 10) Supports Python, JavaScript,…, Walk repository and detect all multi-language files., Pattern-based structure extractor for non-Python languages (JS, TS, Java, Go,…, chunk_python_file() (+3 more)

### Community 41 - "User"
Cohesion: 0.21
Nodes (11): get_me(), get, get_bug_reports(), get, get_chat_history(), get, get_blast_radius(), get_graph() (+3 more)

### Community 42 - "docs.py"
Cohesion: 0.20
Nodes (8): get_analytics(), get, Repository Analytics API Router (Phase 5) Provides high-level stats, language…, DocGenRequest, generate_documentation(), BaseModel, post, Documentation Generator API Router (Phase 6) Auto-generates Markdown READMEs,…

### Community 43 - "DocumentationGenerator"
Cohesion: 0.25
Nodes (4): DocumentationGenerator, Automated Documentation Generator Engine (Phase 6) Generates READMEs, API…, Converts markdown content to printable HTML/PDF styled document., Documentation Generator Package

### Community 44 - "test_call_graph.py"
Cohesion: 0.31
Nodes (8): extract_function_calls(), _extract_python_calls(), _extract_tree_sitter_calls(), walk(), Extracts all function and method call sites from a SourceFile., Tests for Symbol Call Graph Engine, test_extract_function_calls_javascript(), test_extract_function_calls_python()

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

### Community 51 - "get_current_user"
Cohesion: 0.29
Nodes (6): decode_access_token(), get_current_user(), Any, Dependency to retrieve authenticated user from Bearer header., Decodes and validates JWT token., HTTPAuthorizationCredentials

### Community 53 - "Architecture Decision Records (ADRs)"
Cohesion: 0.33
Nodes (5): ADR Template, Architecture Decision Records (ADRs), Log of Decisions, What is an ADR?, When to Record an ADR

### Community 54 - "service.py"
Cohesion: 0.60
Nodes (3): connect_db(), main_run(), process_data()

### Community 55 - "IntelliCodeX — Project Implementation & Verification Status"
Cohesion: 0.40
Nodes (4): 1. Status Classification Guidelines, 2. Feature-Level Verification Matrix, 3. Discrepancy & Gap Analysis, IntelliCodeX — Project Implementation & Verification Status

### Community 56 - ".sync_repository"
Cohesion: 0.50
Nodes (3): compute_file_hash(), Computes MD5 hash of file content for fast equality checks., Synchronizes changed files against previous file hashes. Re-embeds only…

## Knowledge Gaps
- **158 isolated node(s):** `CallSite`, `Target Users:`, `Implemented Capabilities (Tested & Verified)`, `Important Limitations`, `Prerequisites` (+153 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 514 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodeChunk` connect `CodeChunk` to `PatchEngine`, `test_week4_verification.py`, `OllamaLLM`, `test_full_system_integration.py`, `multi_parser.py`, `test_week3_verification.py`, `DocumentationGenerator`, `call_graph.py`, `SandboxRunner`, `metrics.py`, `.add`, `AssistantEngine`, `QueryEngine`, `get_db_connection`, `SourceFile`, `incremental_indexer.py`, `test_graph_context_expansion.py`, `test_faiss_sqlite_persistence.py`?**
  _High betweenness centrality (0.092) - this node is a cross-community bridge._
- **Why does `SourceFile` connect `SourceFile` to `walk_repository`, `multi_parser.py`, `test_week3_verification.py`, `DocumentationGenerator`, `call_graph.py`, `test_call_graph.py`, `metrics.py`, `TfidfEmbedder`, `get_db_connection`, `EnhancedDependencyGraph`, `incremental_indexer.py`, `test_graph_context_expansion.py`, `test_faiss_sqlite_persistence.py`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `FaissVectorStore` connect `CodeChunk` to `PatchEngine`, `test_week4_verification.py`, `AdvancedBugLocalizer`, `OllamaLLM`, `test_full_system_integration.py`, `test_week3_verification.py`, `SandboxRunner`, `TfidfEmbedder`, `.add`, `AssistantEngine`, `QueryEngine`, `.sync_repository`, `incremental_indexer.py`, `test_graph_context_expansion.py`, `test_faiss_sqlite_persistence.py`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `SourceFile` (e.g. with `RepositoryAnalyticsEngine` and `EnhancedDependencyGraph`) actually correct?**
  _`SourceFile` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `CodeChunk` (e.g. with `RepositoryAnalyticsEngine` and `DocumentationGenerator`) actually correct?**
  _`CodeChunk` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `FaissVectorStore` (e.g. with `AdvancedBugLocalizer` and `save_vector_store()`) actually correct?**
  _`FaissVectorStore` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `TfidfEmbedder` (e.g. with `test_create_components_ollama_fallback()` and `test_create_components_tfidf()`) actually correct?**
  _`TfidfEmbedder` has 4 INFERRED edges - model-reasoned connections that need verification._