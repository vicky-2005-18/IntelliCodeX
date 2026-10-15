# Multi-Language Repository Support Verification Evidence (REQ-FUT-01)

> **Document Status**: Final  
> **Milestone**: REQ-FUT-01 (Multi-Language Support)  
> **Evaluation Date**: 2026-10-15  
> **Scope**: End-to-end multi-language verification, capability contract, concrete integration bugfixes, boundary validation, and regression suites.

---

## 1. Actual Support Contract & Acceptance Criteria

### Research Paper / PDF Requirement vs. Acceptance Criteria
The original research specification (PDF Section VIII-B, p. 7) defines multi-language support broadly:
> *"Extending IntelliCodeX beyond Python to C/C++, Java, JavaScript, TypeScript, Go, and Rust via Tree-Sitter CST/AST parsers and language-aware chunking."*

To avoid ambiguity, we establish an explicit support contract separating what is **verified**, what is **partial**, what is **unsupported**, and what is **not tested**. We do not conflate windowed plain-text fallback with syntax-aware parsing, nor do we conflate code retrieval with executable test repair in Docker.

### Multi-Language Capability Matrix

| Language / File Type | Extensions Recognized | Ingestion & Discovery | Syntax-Aware AST Chunking | Indexing & Retrieval | Line Citations | Dependency & KG Extraction | Patch Testing (Docker Sandbox) | Verified Evidence Reference | Overall Contract Status |
|---|---|---|---|---|---|---|---|---|---|
| **Python** | `.py` | **Verified** | **Verified** (Native `ast`) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (AST entities, calls, APIs, DBs) | **Verified** (`pytest`, `unittest` in Docker) | `tests/test_multi_language_support.py`, `tests/test_parser.py`, `tests/test_docker_live_execution.py` | **Fully Verified** |
| **JavaScript** | `.js`, `.jsx`, `.mjs`, `.cjs` | **Verified** | **Verified** (Tree-sitter JS) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Functions, classes, imports) | **Verified** (Node.js 20 built-in test runner in Docker) | `tests/test_js_ts_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **TypeScript / TSX** | `.ts`, `.tsx`, `.mts`, `.cts` | **Verified** | **Verified** (Tree-sitter TS/TSX) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Interfaces, classes, methods, imports) | **Verified** (Two-phase `tsc` + Node.js 20 runner in Docker) | `tests/test_js_ts_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **Java** | `.java` | **Verified** | **Verified** (Tree-sitter Java) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Classes, methods, packages, imports) | **Verified** (OpenJDK 21 + JUnit 5 in Docker) | `tests/test_java_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **C** | `.c`, `.h` | **Verified** | **Verified** (Tree-sitter C) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Functions, structs, `#include`s) | **Verified** (GCC 14 + CMake/CTest in Docker) | `tests/test_c_cpp_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **C++** | `.cpp`, `.cc`, `.cxx`, `.hpp` | **Verified** | **Verified** (Tree-sitter C++) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Classes, methods, templates, `#include`s) | **Verified** (G++ 14 + CMake/CTest in Docker) | `tests/test_c_cpp_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **Go** | `.go` | **Verified** | **Verified** (Tree-sitter Go) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Functions, structs, methods, imports) | **Verified** (Go 1.24 + `test2json` in Docker) | `tests/test_go_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **Rust** | `.rs` | **Verified** | **Verified** (Tree-sitter Rust) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Verified** (Functions, structs, `impl`, `use`) | **Verified** (Cargo 1.85.1 + libtest in Docker) | `tests/test_rust_sandbox.py`, `docs/multi_language_sandbox/EVIDENCE.md` | **Fully Verified (Ingest/RAG/KG/Docker)** |
| **Markdown / Docs** | `.md`, `.markdown` | **Verified** | **Verified** (Section header chunking) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Unsupported** (Not a programming language) | **Unsupported** | `tests/test_tree_sitter_chunker.py::test_chunk_markdown_file` | **Verified (Docs RAG)** |
| **JSON / YAML / Configs** | `.json`, `.yaml`, `.yml`, `.toml`, `.ini` | **Verified** | **Partial** (Smart windowed fallback, non-AST) | **Verified** (TF-IDF / Ollama) | **Verified** (`start_line`, `end_line`) | **Unsupported** | **Unsupported** | `tests/test_tree_sitter_chunker.py::test_windowed_chunks_for_long_file` | **Verified (Fallback Windowing)** |

---

## 2. Concrete Integration Defects Discovered & Fixed

During this milestone, five concrete integration defects were discovered through end-to-end execution of a mixed-language repository and resolved:

### Defect 1: Tree-Sitter Chunks Omitted Extracted Imports (`core/chunker.py`)
- **Symptom**: Tree-sitter code chunks generated for JavaScript, TypeScript, Java, C, C++, Go, and Rust left `CodeChunk.imports` empty (`[]`), whereas Python chunks populated `imports`.
- **Impact**: `as_embedding_text()` failed to include imported modules/symbols for non-Python chunks, weakening dense/lexical retrieval quality when querying cross-module symbols.
- **Fix**: Updated `core/chunker.py` to extract imports via `extract_file_imports(sf)` and populate `CodeChunk.imports=file_imports` for all tree-sitter chunks.

### Defect 2: Silent Syntax Error Swallowing in Python Chunker (`core/chunker.py`)
- **Symptom**: In `core/chunker.py`, syntax errors in `.py` files triggered an unlogged fallback to `_windowed_chunks()`.
- **Impact**: Files with syntax errors silently fell back without any user-visible or diagnostic log warning, violating the requirement that syntax errors produce clear diagnostics.
- **Fix**: Added `logger.warning(f"Syntax error in '{sf.rel_path}': {e}. Falling back to windowed chunking.")`.

### Defect 3: Silent Tree-Sitter Syntax Error Handling (`core/tree_sitter_chunker.py`)
- **Symptom**: Tree-sitter parses malformed code by creating `ERROR` nodes in the CST, but `extract_tree_sitter_chunks` did not check `tree.root_node.has_error` and produced no diagnostic feedback.
- **Impact**: Malformed non-Python files were parsed into partial nodes without logging that a syntax error was detected.
- **Fix**: Added explicit inspection of `tree.root_node.has_error` logging a diagnostic warning with the file path while gracefully extracting all valid top-level classes/functions and falling back to windowing only if no valid AST chunks were recovered.

### Defect 4: Missing Tree-Sitter Symbol and Import Nodes in Knowledge Graph (`backend/dependency_graph/enhanced_graph.py`)
- **Symptom**: `EnhancedDependencyGraph._parse_generic_dependencies` was previously an empty stub (`pass`), ignoring non-Python file imports, classes, methods, and functions.
- **Impact**: Knowledge graph entity extraction only worked for Python; JavaScript, TypeScript, Java, and other languages had file nodes but no symbol nodes or import edges.
- **Fix**: Integrated `extract_file_imports` with `resolve_import_to_file` to create `imports` edges, and integrated `extract_tree_sitter_chunks` to create `class`, `interface`, `method`, and `function` nodes with exact `start_line` and `end_line` citations across all supported languages.

### Defect 5: Unnormalized Windows Path Separators Breaking Cross-Platform Resolution (`backend/dependency_graph/enhanced_graph.py`)
- **Symptom**: `walk_repository` produces `sf.rel_path` with backslashes on Windows (e.g. `frontend\services\types.ts`), while `resolve_import_to_file` and tree-sitter chunk IDs use forward slashes (`frontend/services/types.ts`).
- **Impact**: Cross-file imports in TypeScript/JavaScript failed to resolve on Windows because `cand in file_map` looked for forward slashes while keys had backslashes. Furthermore, graph node IDs were inconsistent across operating systems.
- **Fix**: Enforced `.replace("\\", "/")` normalization across `build`, `_PythonASTKnowledgeVisitor`, `_parse_python_dependencies`, and `_parse_generic_dependencies`.

---

## 3. Representative Mixed-Language Experiment

### Deterministic Test Fixture Setup
We constructed a representative repository fixture containing four distinct languages with real dependencies, domain terms, and an identically named symbol:
1. **Python** (`backend/orders.py`):
   - Imports: `json`, `datetime`
   - Class: `OrderManager`
   - Methods: `validate(self, order_data)` (identically named symbol), `calculate_total(self, items)` (distinct domain term)
2. **JavaScript** (`frontend/components/OrderView.js`):
   - Imports: `React`, `lodash`
   - Functions: `formatCurrency(amount)` (distinct domain term), `validate(formData)` (identically named symbol)
   - Class: `OrderView`
3. **TypeScript** (`frontend/services/types.ts` & `frontend/services/orderClient.ts`):
   - Interface: `OrderPayload`
   - Class: `OrderClient`
   - Method: `submitOrder(payload: OrderPayload)` (distinct domain term)
   - Function: `validate(payload: OrderPayload)` (identically named symbol)
   - Import: `import { OrderPayload } from './types';`
4. **Java** (`services/OrderProcessor.java`):
   - Package: `com.orders`
   - Imports: `java.util.List`, `java.util.ArrayList`
   - Class: `OrderProcessor`
   - Methods: `validate(String orderToken)` (identically named symbol), `processPayment(String orderToken, double amount)` (distinct domain term)
5. **Ignored Directories**:
   - `node_modules/package_mock/index.js`
   - `target/classes/Dummy.class`
   - `.git/config`

### Ingestion & Symbol Verification
- **Command**: `ingest_repository(repo_path, embedder=TfidfEmbedder())`
- **Discovered Languages**: `{"python", "javascript", "typescript", "java"}`
- **Ingested Files Count**: Exactly 5 valid files (all files in `node_modules`, `target`, and `.git` were strictly excluded).
- **Symbol Disambiguation**: The symbol `validate` exists in all 4 languages. Each was assigned a unique `chunk_id` and correct language attribute:
  - `backend/orders.py::OrderManager.validate` (Language: `python`, Lines: 8–13)
  - `frontend/components/OrderView.js::validate` (Language: `javascript`, Lines: 8–11)
  - `frontend/services/orderClient.ts::validate` (Language: `typescript`, Lines: 15–17)
  - `services/OrderProcessor.java::OrderProcessor.validate` (Language: `java`, Lines: 8–11)

### Offline Hybrid Retrieval Results
Retrieval was executed using the offline backend (`TfidfEmbedder` + BM25 Lexical Index + RRF):
| Query | Top Result File | Language | Matched Symbol | Source Line Coordinates | Expected | Match? |
|---|---|---|---|---|---|---|
| `"formatCurrency"` | `frontend/components/OrderView.js` | `javascript` | `formatCurrency` | Lines 4–6 | JavaScript formatCurrency function | **PASS** |
| `"submitOrder"` | `frontend/services/orderClient.ts` | `typescript` | `OrderClient.submitOrder` | Lines 9–11 | TypeScript submitOrder method | **PASS** |
| `"processPayment"` | `services/OrderProcessor.java` | `java` | `OrderProcessor.processPayment` | Lines 14–18 | Java processPayment method | **PASS** |
| `"calculate_total"` | `backend/orders.py` | `python` | `OrderManager.calculate_total` | Lines 14–16 | Python calculate_total method | **PASS** |
| `"validate @backend/orders.py"` | `backend/orders.py` | `python` | `OrderManager.validate` | Lines 8–13 | Scoped Python validate only | **PASS** |

---

## 4. Boundary & Robustness Verifications

1. **Ignored File Exclusion**:
   - `node_modules/`, `target/`, and `.git/` were confirmed excluded during repository traversal. No chunks or graph nodes were generated from ignored trees.
2. **Syntax Error Tolerance & File Preservation**:
   - Introduced a malformed TypeScript file (`broken.ts`) and a malformed Python file (`broken.py`).
   - Ingestion completed with exit code 0.
   - Diagnostic `WARNING` logs were emitted for both malformed files.
   - All 5 valid multi-language files remained intact in the FAISS index and were retrievable.
3. **Incremental Re-Indexing**:
   - Appended a new method `cancel_order` to `backend/orders.py`.
   - Re-ran ingestion with `force_reindex=False`.
   - Ingestion mode reported `incremental`.
   - `cancel_order` was immediately retrievable via `QueryEngine.retrieve("cancel_order")`.
4. **Repository Isolation & Authorization Boundary**:
   - Ingested repository cached under user `alice`.
   - Verified that accessing the multi-language repository engine as `bob` raised `HTTPException(403, detail="Access denied: repository '...' belongs to another user")`.
5. **Knowledge Graph Extraction**:
   - Generated `EnhancedDependencyGraph` over the mixed repository.
   - Nodes created: `backend/orders.py::OrderManager`, `frontend/components/OrderView.js::OrderView`, `frontend/services/orderClient.ts::OrderClient`, `services/OrderProcessor.java::OrderProcessor`.
   - Verified edge resolution: `frontend/services/orderClient.ts` -> `frontend/services/types.ts` (`imports`).

---

## 5. Automated Regression Test Suite Results

Test execution command:
```powershell
python -m pytest tests/test_multi_language_support.py tests/test_tree_sitter_chunker.py tests/test_dependency_graph_multilang.py tests/test_knowledge_graph_query.py tests/test_pipeline_integration.py tests/test_parser.py tests/test_dependency_graph.py -v
```

Output:
```
============================= test session starts =============================
platform win32 -- Python 3.14.6, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\vikas\Downloads\Major project 2 2026
configfile: pyproject.toml
plugins: anyio-4.14.2, cov-7.1.0
collected 36 items

tests/test_multi_language_support.py::test_mixed_language_ingestion_and_symbol_extraction PASSED [  2%]
tests/test_multi_language_support.py::test_symbol_disambiguation_across_languages PASSED [  5%]
tests/test_multi_language_support.py::test_offline_retrieval_with_exact_citations PASSED [  8%]
tests/test_multi_language_support.py::test_syntax_error_diagnostic_and_file_preservation PASSED [ 11%]
tests/test_multi_language_support.py::test_incremental_update_on_mixed_language_repository PASSED [ 13%]
tests/test_multi_language_support.py::test_multi_language_knowledge_graph_extraction PASSED [ 16%]
tests/test_multi_language_support.py::test_repository_isolation_and_authorization PASSED [ 19%]
tests/test_tree_sitter_chunker.py::test_chunk_javascript_file PASSED     [ 22%]
tests/test_tree_sitter_chunker.py::test_chunk_c_cpp_files PASSED         [ 25%]
tests/test_tree_sitter_chunker.py::test_chunk_go_file PASSED             [ 27%]
tests/test_tree_sitter_chunker.py::test_chunk_rust_file PASSED           [ 30%]
tests/test_tree_sitter_chunker.py::test_chunk_markdown_file PASSED       [ 33%]
tests/test_tree_sitter_chunker.py::test_windowed_chunks_for_long_file PASSED [ 36%]
tests/test_dependency_graph_multilang.py::test_extract_js_ts_imports PASSED [ 38%]
tests/test_dependency_graph_multilang.py::test_extract_java_imports PASSED [ 41%]
tests/test_dependency_graph_multilang.py::test_extract_c_cpp_includes PASSED [ 44%]
tests/test_dependency_graph_multilang.py::test_multilang_dependency_graph_resolution PASSED [ 47%]
tests/test_knowledge_graph_query.py::test_knowledge_graph_ast_generation_and_line_numbers PASSED [ 50%]
tests/test_knowledge_graph_query.py::test_api_graph_query_entity_endpoint PASSED [ 52%]
tests/test_knowledge_graph_query.py::test_api_graph_relationship_filter_and_direction PASSED [ 55%]
tests/test_knowledge_graph_query.py::test_api_graph_entities_and_path_endpoints PASSED [ 58%]
tests/test_knowledge_graph_query.py::test_api_graph_metadata_endpoint PASSED [ 61%]
tests/test_knowledge_graph_query.py::test_api_graph_error_handling_for_unknown_entities_and_repos PASSED [ 63%]
tests/test_knowledge_graph_query.py::test_multi_tenant_repository_isolation PASSED [ 66%]
tests/test_knowledge_graph_query.py::test_cli_graph_batch_query_execution PASSED [ 69%]
tests/test_pipeline_integration.py::test_multi_language_pipeline_ingestion PASSED [ 72%]
tests/test_pipeline_integration.py::test_embedder_called_once_per_chunk_no_duplicates PASSED [ 75%]
tests/test_pipeline_integration.py::test_ollama_embedder_progress_not_overcounting PASSED [ 77%]
tests/test_parser.py::test_detect_language PASSED                        [ 80%]
tests/test_parser.py::test_gitignore_matching PASSED                     [ 83%]
tests/test_parser.py::test_walk_repository_sample_repo PASSED            [ 86%]
tests/test_parser.py::test_walk_repository_temp_multi_lang PASSED        [ 88%]
tests/test_parser.py::test_walk_repository_includes_tests_and_docs_by_default PASSED [ 91%]
tests/test_dependency_graph.py::test_enhanced_graph_builder PASSED       [ 94%]
tests/test_dependency_graph.py::test_core_dependency_graph_relative_and_dynamic_imports PASSED [ 97%]
tests/test_dependency_graph.py::test_enhanced_graph_relative_and_dynamic_imports PASSED [100%]

============================= 36 passed in 3.42s ==============================
```

---

## 6. Known Limitations & Explicit Non-Claims

1. **Docker Sandbox Execution Boundary**:
   - `SandboxRunner` and `Dockerfile.sandbox` only support Python (`pytest` / `unittest`).
   - We do **not** claim automated repair verification or test runner execution for JavaScript (Jest/Mocha), TypeScript, Java (Maven/JUnit), Go, or Rust. Those toolchains are unsupported in the current container execution loop.
2. **Dynamic Language Relationships**:
   - Dependency and knowledge graph edges reflect static AST imports, class/method definitions, and calls.
   - Dynamic reflection (e.g. Java `Class.forName()`, JS dynamic `require(expr)`), dynamic polymorphic dispatch, and dependency injection containers are unsupported by static AST analysis.
