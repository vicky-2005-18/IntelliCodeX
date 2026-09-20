# Graph Report - intellicodex  (2026-09-19)

## Corpus Check
- 119 files · ~58,059 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 8 file(s) not represented in the graph (top: (none) 3, .bat 3, .1789749828 1)

## Summary
- 1258 nodes · 2752 edges · 83 communities (68 shown, 7 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 108 edges (avg confidence: 0.94)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `dd73893f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- patch_engine.py
- test_week4_verification.py
- test_cli.py
- CodeChunk
- AdvancedBugLocalizer
- QueryEngine
- 2. Current Implementation Status ("What is Done")
- format_time_consumed
- cli.py
- tree_sitter_chunker.py
- LocalDiskStore
- dependency_graph.py
- patch_generator.py
- 3. Functional Requirements (FR)
- api/auth.py
- Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)
- Implementation Plan: IntelliCodeX Semester Roadmap (CLI First, Web App Next)
- IntelliCodeX — Architecture, LLM Pipeline & File Modification Guide
- api.py
- ingest_repository
- expand_retrieved_context
- AssistantEngine
- main
- persistence.py
- test_file_watcher.py
- SourceFile
- EnhancedDependencyGraph
- OllamaLLM
- pkg/auth.py
- PatchEngine
- PatchEngine
- IntelliCodeX — System Architecture & Technical Design
- IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine
- User
- 3. Verified Test Scenarios & Acceptance Criteria
- patches.py
- repos.py
- test_tui_and_packaging.py
- parser.py
- IntelliCodeX — Project Engineering Roadmap
- call_graph.py
- save_vector_store
- get_current_user
- DocumentationGenerator
- multi_parser.py
- ADR-0001: Dual Embedding Strategy with Offline Fallback (Ollama + TF-IDF SVD)
- ADR-0002: Hybrid Local Persistence (SQLite Metadata + FAISS Binary Vectors)
- ADR-0003: Multi-Language Semantic AST Chunking via Tree-Sitter Grammars
- ADR-0004: Spectrum Fault Localization (Ochiai) & Defensive Patch Generation with Backups
- ADR-0005: Modular Enterprise FastAPI Architecture with Legacy API Bridge
- metrics.py
- ConversationMemory
- intellicodex
- Architecture Decision Records (ADRs)
- service.py
- IntelliCodeX — Project Implementation & Verification Status
- GitService
- app.js
- math_utils.py
- RepositoryEventHandler
- RepositoryWatcher
- BaseEmbedder
- backend/__init__.py
- backend/config.py
- extract_code_and_explanation
- apply_patch_to_file
- render_patch_card
- .__init__
- .sync_repository
- render_markdown_panel
- render_centrality_tables
- render_repos_table
- render_status_panel
- test_repository_event_handler_debouncing
- test_repo_id_generation

## God Nodes (most connected - your core abstractions)
1. `CodeChunk` - 85 edges
2. `SourceFile` - 76 edges
3. `FaissVectorStore` - 69 edges
4. `main()` - 61 edges
5. `TfidfEmbedder` - 59 edges
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
- `generate_patch()` --uses--> `PatchEngine`  [INFERRED]
  backend/api/patches.py → core/patch_generator.py
- `approve_patch()` --uses--> `PatchEngine`  [INFERRED]
  backend/api/patches.py → core/patch_generator.py
- `ingest_repo()` --uses--> `QueryEngine`  [INFERRED]
  backend/api/repos.py → rag/query_engine.py

## Import Cycles
- None detected.

## Communities (83 total, 7 thin omitted)

### Community 0 - "patch_engine.py"
Cohesion: 0.13
Nodes (24): Patch Generator Package (Phase 1), merge_snippet_into_file(), Replace a snippet region inside a full file with the patched version. First…, generate_git_diff(), AI-Powered Patch Generation Engine (Phase 1 & Milestone 1) Retrieves repository…, Generate standard unified git diff format., compute_patch_quality_score(), Any (+16 more)

### Community 1 - "test_week4_verification.py"
Cohesion: 0.09
Nodes (23): Advanced Bug Localization Package, BugLocalizer, calculate_ochiai_score(), calculate_ochiai_spectrum(), CoverageRecord, ParsedStackTrace, Any, DiGraph (+15 more)

### Community 2 - "test_cli.py"
Cohesion: 0.13
Nodes (22): check_ollama_available(), create_components(), Resolves local directory path or clones remote Git repository URL into .repos…, Factory helper to instantiate embedder and LLM with automatic fallback., Checks if local Ollama server is running and accessible., resolve_repo_path(), _get_embedding_cache(), OllamaEmbedder (+14 more)

### Community 3 - "CodeChunk"
Cohesion: 0.07
Nodes (37): Repository AI Assistant Engine (Phase 3) Enhances RAG chat with query intent…, CodeChunk, What actually gets embedded — code + surrounding context., Local, dependency-light fallback. Fit once on the corpus, then transform., TfidfEmbedder, BM25 Lexical Indexer for Software Repositories (Milestone 3) Provides inverted…, FaissVectorStore, ndarray (+29 more)

### Community 4 - "AdvancedBugLocalizer"
Cohesion: 0.12
Nodes (13): AdvancedBugLocalizer, ParsedStackTrace, Any, DiGraph, Advanced Bug Localization Engine (Phase 2) Combines stack trace parsing, error…, Pinpoints bug locations by combining: - Stack trace frame matching - Semantic…, Single frame extracted from a stack trace., Collect dependency graph signals for a candidate file. (+5 more)

### Community 5 - "QueryEngine"
Cohesion: 0.07
Nodes (25): BM25Index, Computes Okapi IDF with smoothing to ensure non-negative values: IDF(q) = ln(1…, Searches the inverted index with BM25 Okapi scoring. Returns top-K matching…, Code-aware tokenizer: 1. Splits text into raw identifier and literal tokens. 2.…, Inverted index implementation using the BM25 Okapi probabilistic ranking model.…, Builds the BM25 inverted index from a list of code chunks., tokenize_code(), QueryEngine (+17 more)

### Community 6 - "2. Current Implementation Status ("What is Done")"
Cohesion: 0.06
Nodes (30): 1. Executive Summary, 2.1 Core Code Ingestion & AST Parsing, 2.2 Graph Dependency & Call-Graph Engine, 2.3 Vector Database & Persistence, 2.4 RAG Engine & Persona System, 2.5 Fault Localization (SBFL / Ochiai) & Patch Generator, 2.6 Enterprise Backend API (FastAPI), 2.7 Modern Web Frontend (React + Vite + Tailwind) (+22 more)

### Community 7 - "format_time_consumed"
Cohesion: 0.11
Nodes (20): format_time_consumed(), on_auto_reindex(), print_ingestion_summary(), Renders repository ingestion results with rich panel styling., Renders dependency impact as a rich tree-style panel., Renders function callers as a rich tree-style panel., Renders fast retrieval-only results (no LLM) in a styled rich table., Formats seconds into human-readable duration with high precision. (+12 more)

### Community 8 - "cli.py"
Cohesion: 0.16
Nodes (14): print_banner(), print_help(), IntelliCodeX CLI — Ingest and query software repositories interactively. Usage:…, Renders interactive banner with rich styling if available., Renders indexed file list in a rich formatted table., Renders rich color-coded help table grouped by command category., render_banner(), render_files_table() (+6 more)

### Community 9 - "tree_sitter_chunker.py"
Cohesion: 0.14
Nodes (25): _extract_c_cpp_chunks(), walk(), _extract_go_chunks(), _extract_java_chunks(), walk(), _extract_js_ts_chunks(), walk(), _extract_node_name() (+17 more)

### Community 10 - "LocalDiskStore"
Cohesion: 0.20
Nodes (5): DatabaseManager, LocalDiskStore, Any, Database & Persistent Storage Module (Phase 7) Provides MongoDB document…, File-backed fallback database when MongoDB is offline.

### Community 11 - "dependency_graph.py"
Cohesion: 0.15
Nodes (22): build_dependency_graph(), calculate_file_centrality(), extract_file_imports(), files_likely_affected_by(), get_top_central_files(), DiGraph, Multi-Language Dependency Analysis Engine - Builds a file-level import and…, Builds a directed dependency graph across all source files in the repository. (+14 more)

### Community 12 - "patch_generator.py"
Cohesion: 0.10
Nodes (20): Multi-File Context-Aware Code Patch Generator Engine (Milestone 1) Extracts…, Any, Isolated Sandbox Test Execution Runner for IntelliCodeX (Milestone 1) Executes…, Copies repo to an isolated temporary sandbox, applies patched_code to…, Encapsulates the execution results of a sandboxed test run., Copies source files into sandbox directory ignoring heavy/cache artifacts., Extracts passed/failed counts, assertion messages, and traceback highlights…, Fallback parser for generic test runners. (+12 more)

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

### Community 18 - "api.py"
Cohesion: 0.17
Nodes (16): BugReportRequest, localize_bug(), BaseModel, post, Bug Localization API Router (Phase 2) Submits stack traces or error logs to…, ask_assistant(), BaseModel, post (+8 more)

### Community 19 - "ingest_repository"
Cohesion: 0.08
Nodes (44): BenchmarkReport, Benchmarking Engine for IntelliCodeX Repository Parsing & Ingestion Measures…, Runs performance benchmarking measuring fresh vs cached ingestion speed, query…, run_benchmark(), chunk_repository(), Embedding Generation Module Two backends: - OllamaEmbedder: calls a local…, check_git_hooks_status(), find_git_dir() (+36 more)

### Community 20 - "expand_retrieved_context"
Cohesion: 0.18
Nodes (8): expand_retrieved_context(), Any, DiGraph, Graph-Augmented Sub-Graph Expansion: Enriches top-K search results by expanding…, Retrieves top-K matches and applies graph-augmented context expansion., Performs RAG query answering with context expansion, conversation history, and…, Streams AI response tokens in real-time while updating conversation memory., Bug localization: treat error/stack trace as query and expand caller context…

### Community 21 - "AssistantEngine"
Cohesion: 0.20
Nodes (7): AssistantEngine, Any, DiGraph, QueryIntent, Enterprise repository assistant that combines: - Intent-aware retrieval…, Enum, str

### Community 22 - "main"
Cohesion: 0.10
Nodes (16): get_available_repos(), main(), Returns a list of (label, abs_path) tuples for all known local repositories.…, test_cli_main_files_ls(), test_cli_main_help_and_exit(), test_cli_main_keyboard_interrupt(), test_cli_main_prompt_stripping_and_query(), test_cli_main_repo_switch() (+8 more)

### Community 23 - "persistence.py"
Cohesion: 0.09
Nodes (46): compute_file_hash(), delete_files_from_db(), detect_repository_changes(), get_db_connection(), get_faiss_index_path(), init_schema(), load_faiss_index(), load_index() (+38 more)

### Community 24 - "test_file_watcher.py"
Cohesion: 0.19
Nodes (10): is_ignored_path(), Checks if a filesystem path should be ignored by the watcher. Ignores hidden…, skipif, Unit & Integration Tests for Milestone 2: Real-Time Filesystem Watcher Daemon…, test_is_ignored_path(), test_repository_event_handler_filtering(), test_repository_watcher_lifecycle(), test_repository_watcher_live_incremental_reindex() (+2 more)

### Community 25 - "SourceFile"
Cohesion: 0.18
Nodes (22): Incremental Repository Indexing & Real-Time Filesystem Watcher Daemon…, chunk_file(), _chunk_markdown_file(), chunk_python_file(), make_chunk(), _extract_imports(), Semantic Chunking Engine - Python: AST-based extraction of functions/classes…, Chunks markdown documents by section headings (# Heading). (+14 more)

### Community 26 - "EnhancedDependencyGraph"
Cohesion: 0.14
Nodes (9): EnhancedDependencyGraph, Any, DiGraph, Enhanced Dependency Graph Engine (Phase 4) Supports file imports, class…, Finds circular dependency cycles in file imports., Exports graph in Cytoscape.js format for interactive UI rendering., Enhanced Dependency Graph Package, Unit Tests for Enhanced Dependency Graph (Phase 4) (+1 more)

### Community 27 - "OllamaLLM"
Cohesion: 0.11
Nodes (15): analyze_code(), CommitMsgRequest, FileReviewRequest, generate_commit_message(), BaseModel, post, Code Review & Commit Message API Router (Phases 14 & 15) Performs automated…, CodeReviewAssistant (+7 more)

### Community 28 - "pkg/auth.py"
Cohesion: 0.13
Nodes (13): authenticate(), hash_password(), Authentication utilities for the sample application., Check a username/password pair against stored credentials., Tracks active user sessions in memory., Returns True if token exists in active sessions., Hash a plaintext password with a salt using SHA-256., SessionManager (+5 more)

### Community 29 - "PatchEngine"
Cohesion: 0.17
Nodes (11): Remove accidental language tag left on the first line of extracted code., strip_language_prefix(), PatchEngine, Any, DiGraph, Closed-Loop Agentic Test-Driven Repair (Milestone 1)., Update approval status. When status is 'applied', writes the patch to disk., Context-aware patch generation engine with closed-loop sandbox test… (+3 more)

### Community 30 - "PatchEngine"
Cohesion: 0.17
Nodes (11): generate_git_diff(), PatchEngine, Any, DiGraph, Closed-Loop Agentic Test-Driven Repair (Milestone 1). Generates patch, tests…, Generates standard unified git diff format., Applies suggested patch directly to physical file on disk., Helper to merge snippet into full file or return snippet directly. (+3 more)

### Community 31 - "IntelliCodeX — System Architecture & Technical Design"
Cohesion: 0.12
Nodes (16): 1. Architectural Overview & System Decomposition, 2.1 Technology Stack Matrix, 2.2 Application Entry Points, 2. Technology Stack & Entry Points, 3.1 Code Ingestion & Multi-Language Parsing (`core/parser.py`, `core/ts_loader.py`, `core/tree_sitter_chunker.py`), 3.2 Graph Analysis Subsystem (`core/dependency_graph.py`, `core/call_graph.py`), 3.3 Dual Embedding & Vector Indexing (`core/embedder.py`, `core/vectorstore.py`), 3.4 Hybrid Persistence Subsystem (`core/persistence.py`, `backend/database/mongo.py`) (+8 more)

### Community 32 - "IntelliCodeX — AI-Powered Software Repository Intelligence & Code Analysis Engine"
Cohesion: 0.12
Nodes (16): 1. Project Purpose & Target Users, 2. Current Capabilities & Important Limitations, 3. Prerequisites & Environment Configuration, 4.1 Clone Repository & Setup Virtual Environment `[TESTED]`, 4.2 Run IntelliCodeX Interactive CLI `[TESTED]`, 4.3 Start Local Backend API Server (Optional) `[TESTED]`, 4. Installation & Startup Instructions, 5. Minimal Usage Example (CLI) (+8 more)

### Community 33 - "User"
Cohesion: 0.13
Nodes (16): get_analytics(), get, Repository Analytics API Router (Phase 5) Provides high-level stats, language…, get_me(), get, get_bug_reports(), get, get_chat_history() (+8 more)

### Community 34 - "3. Verified Test Scenarios & Acceptance Criteria"
Cohesion: 0.13
Nodes (14): 1.1 Test Directory Structure, 1. Test Suite Organization & Execution Commands, 2.1 Complete Automated Test Suite, 2.2 Performance Benchmarking Command, 2. Test Execution Commands, 3.1 Core Ingestion & AST Parsing Scenarios, 3.2 Graph Analysis & Centrality Scenarios, 3.3 Persistence & Incremental Re-Indexing Scenarios (+6 more)

### Community 35 - "patches.py"
Cohesion: 0.20
Nodes (13): approve_patch(), generate_patch(), GeneratePatchRequest, list_patches(), PatchApprovalRequest, BaseModel, get, post (+5 more)

### Community 36 - "repos.py"
Cohesion: 0.21
Nodes (16): clone_repo(), get_repo_engine(), GitCloneRequest, ingest_repo(), IngestRequest, BaseModel, post, Repositories API Router (Phases 7, 8, 9) Ingests, clones, lists, auto-reloads,… (+8 more)

### Community 37 - "test_tui_and_packaging.py"
Cohesion: 0.09
Nodes (29): IntelliCodeXCompleter, Returns True if rich prompt_toolkit interactive session should be enabled., Renders Git hook status table., Renders real-time watcher status as a rich panel., Renders hybrid search status as a rich panel., Context-aware autocompleter for commands, files, symbols, and settings., render_hooks_table(), render_hybrid_panel() (+21 more)

### Community 38 - "parser.py"
Cohesion: 0.22
Nodes (14): detect_language(), is_ignored_by_gitignore(), load_gitignore_patterns(), Repository Parser Module - Walks a repository directory recursively - Detects…, Checks if relative path matches any .gitignore pattern., Walks repo_root recursively and returns a list of all recognized, non-ignored…, Detects language identifier from filename extension., Parses .gitignore file in repo_root if present. (+6 more)

### Community 39 - "IntelliCodeX — Project Engineering Roadmap"
Cohesion: 0.14
Nodes (13): 1. Prioritized Milestones & Dependency Flow, 2. Milestone 1: Closed-Loop Agentic Test-Driven Repair (Self-Healing Code) `[ESSENTIAL - SEMESTER 1]`, 3. Milestone 2: Real-Time Filesystem Watcher Daemon `[CORE PERFORMANCE - SEMESTER 1]`, 4. Milestone 3: Hybrid BM25 & Dense Reciprocal Rank Fusion (RRF) `[RETRIEVAL OPTIMIZATION - SEMESTER 1]`, 5. Milestone 4: Advanced Terminal TUI & CLI Packaging `[CLI EXPERIENCE - SEMESTER 1]`, 6. Milestone 5: Full Web Application Workspace `[FUTURE PHASE - SEMESTER 2]`, 7. Milestone 6: Distributed Vector Storage & Enterprise CI/CD `[FUTURE PHASE - SEMESTER 2]`, IntelliCodeX — Project Engineering Roadmap (+5 more)

### Community 40 - "call_graph.py"
Cohesion: 0.14
Nodes (24): build_call_graph(), calculate_symbol_centrality(), CallSite, extract_function_calls(), _extract_python_calls(), _extract_tree_sitter_calls(), walk(), find_callees_of_chunk() (+16 more)

### Community 41 - "save_vector_store"
Cohesion: 0.27
Nodes (8): get_index_paths(), load_vector_store(), FAISS Vector Store Persistence Module (Phase 7) Handles disk serialization and…, Serialize FAISS index and chunk metadata to disk., Load FAISS index and chunk metadata from disk if available., save_vector_store(), Unit Tests for FAISS Vector Store Disk Serialization and Database Manager…, test_faiss_persistence()

### Community 42 - "get_current_user"
Cohesion: 0.17
Nodes (11): DocGenRequest, generate_documentation(), BaseModel, post, Documentation Generator API Router (Phase 6) Auto-generates Markdown READMEs,…, decode_access_token(), get_current_user(), Any (+3 more)

### Community 43 - "DocumentationGenerator"
Cohesion: 0.25
Nodes (4): DocumentationGenerator, Automated Documentation Generator Engine (Phase 6) Generates READMEs, API…, Converts markdown content to printable HTML/PDF styled document., Documentation Generator Package

### Community 44 - "multi_parser.py"
Cohesion: 0.33
Nodes (7): Multi-Language Parser Package, parse_and_chunk_file(), parse_generic_file(), parse_repository_files(), Multi-Language Repository Parser Engine (Phase 10) Supports Python, JavaScript,…, Walk repository and detect all multi-language files., Pattern-based structure extractor for non-Python languages (JS, TS, Java, Go,…

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

### Community 51 - "ConversationMemory"
Cohesion: 0.22
Nodes (4): ConversationMemory, Manages multi-turn conversation dialogue history for RAG queries., 1. Verifies multi-turn dialogue memory retention, max turn truncation, and…, test_week5_conversation_memory()

### Community 53 - "Architecture Decision Records (ADRs)"
Cohesion: 0.33
Nodes (5): ADR Template, Architecture Decision Records (ADRs), Log of Decisions, What is an ADR?, When to Record an ADR

### Community 54 - "service.py"
Cohesion: 0.60
Nodes (3): connect_db(), main_run(), process_data()

### Community 55 - "IntelliCodeX — Project Implementation & Verification Status"
Cohesion: 0.40
Nodes (4): 1. Status Classification Guidelines, 2. Feature-Level Verification Matrix, 3. Discrepancy & Gap Analysis, IntelliCodeX — Project Implementation & Verification Status

### Community 56 - "GitService"
Cohesion: 0.17
Nodes (6): GitService, Git Integration Service (Phase 9) Clones remote GitHub/GitLab repositories,…, Clones a remote repository URL into local storage directory., Retrieves recent commit log history., Lists repository branches., Gets list of modified or untracked files.

### Community 59 - "RepositoryEventHandler"
Cohesion: 0.25
Nodes (4): Watchdog event handler that debounces file system events on active repository…, Cancels any pending timer and flushes state., RepositoryEventHandler, FileSystemEventHandler

### Community 60 - "RepositoryWatcher"
Cohesion: 0.24
Nodes (5): Real-Time Filesystem Watcher Daemon for active repository directories. Runs a…, Starts the background filesystem observer thread., Stops the background filesystem observer thread gracefully., Returns True if the background watcher thread is actively monitoring., RepositoryWatcher

### Community 61 - "BaseEmbedder"
Cohesion: 0.22
Nodes (7): ABC, IncrementalIndexer, Performs batch-level incremental synchronization between an existing vector…, BaseEmbedder, _format_time(), ndarray, Formats duration in human-readable format.

### Community 71 - "backend/config.py"
Cohesion: 0.25
Nodes (7): BaseModel, IntelliCodeX Enterprise Configuration Module Centralized settings management…, Settings, health(), get, IntelliCodeX Enterprise FastAPI Backend Application Entry Point, root()

### Community 72 - "extract_code_and_explanation"
Cohesion: 0.33
Nodes (6): extract_code_and_explanation(), _looks_like_code(), LLM Response Parser Extracts code blocks and explanation text from unstructured…, Parse an LLM response into (code, explanation). Handles responses with one or…, Heuristic: response is likely source code rather than prose., test_llm_parser_extracts_code_block()

### Community 73 - "apply_patch_to_file"
Cohesion: 0.33
Nodes (6): apply_patch_to_file(), apply_unified_diff(), Any, Patch Application Module Safely applies approved patches to the repository…, Write patched content to the target file within the repository. Creates a .bak…, Apply a unified diff using git apply when available. Falls back to manual…

### Community 74 - "render_patch_card"
Cohesion: 0.33
Nodes (6): Renders unified Git diff with syntax highlighting., Renders automated patch diagnosis and git diff., render_diff(), render_patch_card(), test_render_diff(), test_render_patch_card()

### Community 76 - ".sync_repository"
Cohesion: 0.50
Nodes (3): compute_file_hash(), Computes MD5 hash of file content for fast equality checks., Synchronizes changed files against previous file hashes. Re-embeds only…

### Community 77 - "render_markdown_panel"
Cohesion: 0.67
Nodes (3): Renders Markdown text inside a styled terminal panel., render_markdown_panel(), test_render_markdown_panel()

### Community 78 - "render_centrality_tables"
Cohesion: 0.67
Nodes (3): Renders PageRank centrality rankings in structured tables., render_centrality_tables(), test_render_centrality_tables()

### Community 79 - "render_repos_table"
Cohesion: 0.67
Nodes (3): Renders available repositories list in a formatted table., render_repos_table(), test_render_repos_table()

### Community 80 - "render_status_panel"
Cohesion: 0.67
Nodes (3): Renders at-a-glance master system status panel., render_status_panel(), test_render_status_panel()

## Knowledge Gaps
- **159 isolated node(s):** `CallSite`, `intellicodex`, `Target Users:`, `Implemented Capabilities (Tested & Verified)`, `Important Limitations` (+154 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 557 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CodeChunk` connect `CodeChunk` to `patch_engine.py`, `test_week4_verification.py`, `QueryEngine`, `call_graph.py`, `save_vector_store`, `DocumentationGenerator`, `multi_parser.py`, `patch_generator.py`, `metrics.py`, `ingest_repository`, `expand_retrieved_context`, `AssistantEngine`, `persistence.py`, `SourceFile`, `BaseEmbedder`?**
  _High betweenness centrality (0.095) - this node is a cross-community bridge._
- **Why does `FaissVectorStore` connect `CodeChunk` to `patch_engine.py`, `test_week4_verification.py`, `AdvancedBugLocalizer`, `QueryEngine`, `save_vector_store`, `.sync_repository`, `patch_generator.py`, `BaseEmbedder`, `ingest_repository`, `AssistantEngine`, `persistence.py`, `SourceFile`, `PatchEngine`, `PatchEngine`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **Why does `QueryEngine` connect `QueryEngine` to `CodeChunk`, `repos.py`, `format_time_consumed`, `cli.py`, `ingest_repository`, `expand_retrieved_context`, `main`, `SourceFile`, `BaseEmbedder`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `CodeChunk` (e.g. with `RepositoryAnalyticsEngine` and `DocumentationGenerator`) actually correct?**
  _`CodeChunk` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `SourceFile` (e.g. with `RepositoryAnalyticsEngine` and `EnhancedDependencyGraph`) actually correct?**
  _`SourceFile` has 23 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `FaissVectorStore` (e.g. with `AdvancedBugLocalizer` and `save_vector_store()`) actually correct?**
  _`FaissVectorStore` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `main()` (e.g. with `get_indexed_files()` and `get_indexed_symbols()`) actually correct?**
  _`main()` has 5 INFERRED edges - model-reasoned connections that need verification._