# IntelliCodeX — Architecture, LLM Pipeline & File Modification Guide

This document provides a comprehensive technical breakdown of **IntelliCodeX**, explaining how the repository works, which LLM models and parameters are used, how code generation and file edits occur step-by-step, and how to build the best local AI code assistant.

---

## 1. Project Overview & Architecture

IntelliCodeX is a **privacy-preserving, locally-hosted Retrieval-Augmented Generation (RAG) framework** designed specifically for codebases. It performs repository indexing, AST semantic chunking, graph dependency analysis, bug localization, context-grounded Q&A, and automated patch generation.

### End-to-End Execution Flow

```
+-----------------------------------------------------------------------------------+
|                               1. INGESTION PIPELINE                               |
|                                                                                   |
|  Source Repo ---> [parser.py] ---> [chunker.py] ---> [embedder.py]               |
|                   (Walk Repo)     (Python AST)     (nomic-embed-text / TF-IDF)    |
|                                         |                    |                    |
|                                         v                    v                    |
|                                [dependency_graph.py]   [vectorstore.py]           |
|                                 (NetworkX Graph)       (FAISS Vector Index)       |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                              2. QUERY & ASSISTANT ENGINE                          |
|                                                                                   |
|  User Query ---> [assistant_engine.py] ---> Query Intent Classification          |
|                         |              ---> Similarity Search + Keyword Boosting  |
|                         v              ---> Context & Dependency Assembly         |
|                   [llm_client.py] (Ollama - qwen2.5-coder, Temp=0.2)             |
|                         |                                                         |
|                         v                                                         |
|                  Cited Answer with Line Numbers & File Paths                      |
+-----------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           3. PATCH GENERATION & FILE EDITING                      |
|                                                                                   |
|  Error Report ---> [patch_engine.py] ---> Bug Localization & Code Retrieval       |
|                          |           ---> LLM Patch Prompting (Temp=0.1)          |
|                          v                                                        |
|                    [patch_validator.py] (AST Syntax Check + git apply test)      |
|                          |                                                        |
|                          v                                                        |
|                    [patch_applier.py] (Merge snippet into full file)              |
|                          |                                                        |
|                          v                                                        |
|                   Unified Git Diff Generated (diff --git a/file b/file)           |
|                          |                                                        |
|                          v                                                        |
|                   Developer Approval -> Safe Disk Write (.bak backup created)     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Models & Generation Parameters

IntelliCodeX is optimized for high-performance, local execution with strict privacy guarantees.

### Primary Models

| Component | Model Name | Role | Provider / Engine |
| :--- | :--- | :--- | :--- |
| **LLM (Generation)** | `qwen2.5-coder` (e.g. `3b` for 4GB VRAM GPU, `7b`/`14b` for 8GB+ VRAM) | Reasoning, Code Explanation, Patch Generation | Ollama Local AI Server |
| **Embeddings** | `nomic-embed-text` | Code & Text Vector Embeddings | Ollama Local AI Server |
| **Fallback Embeddings** | `TfidfEmbedder` (scikit-learn TF-IDF + SVD) | Offline, zero-dependency embedding fallback | Pure Python / scikit-learn |

---

### Hyperparameters & Settings

#### A. RAG & Chat Generation (`core/llm_client.py` & `backend/services/assistant_engine.py`)
- **Temperature**: `0.2`
  - *Why*: Low temperature keeps the model grounded, analytical, and strictly aligned with the retrieved context code. It minimizes hallucinations.
- **Top-K Retrieval**: `5` chunks (selected from raw top `15` similarity results after intent-based boosting).
- **Stream**: `False` (synchronous full response).
- **Timeout**: `300s` (allows CPU/GPU inference processing without dropping connections).
- **System Prompt**: Enforces ground truth retrieval. Instructs the LLM to cite file paths, line ranges, and refuse to answer if the context does not contain relevant code.

#### B. Code Patch Generation (`backend/patch_generator/patch_engine.py`)
- **Temperature**: `0.1`
  - *Why*: Extremely low temperature forces deterministic code generation, exact syntax compliance, and precise bug fixes.
- **System Prompt**: `PATCH_SYSTEM_PROMPT`
  - *Role*: Expert AI software patch engineer. Demands minimal code edits, returns code inside standard markdown fences (`python ... `), followed by a clear root-cause explanation.

---

## 3. How the LLM Generates Code & Modifies Files

IntelliCodeX handles code generation and file editing in a safe, multi-stage pipeline:

```
[ Error / Prompt ] ---> [ Context RAG ] ---> [ LLM Inference ] ---> [ Code Parsing ]
                                                                            |
[ Disk File Update ] <-- [ .bak Backup ] <-- [ Validation ] <-- [ Git Diff Merge ]
```

### Step 1: Code Retrieval & Context Assembly
1. **Bug Localization** (`backend/bug_localizer/advanced_localizer.py`): When an error or stack trace is provided, the localizer extracts frame identifiers (file names, function names, line numbers) and queries FAISS for code similarity.
2. **Context Formatting**: Relevant code snippets (`CodeChunk`), line numbers, and dependency graph relationships (which module imports what) are structured into a clean prompt.

### Step 2: Prompting & Code Extraction
1. **Ollama Call**: The prompt is sent via `http://localhost:11434/api/generate`.
2. **Parsing Code Blocks** (`backend/patch_generator/llm_parser.py`): The output from `qwen2.5-coder` is parsed using regular expressions (`extract_code_and_explanation`) to isolate the patched code block from explanation text. Language prefixes (e.g. `python`, `javascript`) are stripped.

### Step 3: Merging & Diff Generation
1. **Full File Loading**: The engine reads the target file from the repository (`_read_file`).
2. **Snippet Merging** (`backend/patch_generator/patch_applier.py`): The function `merge_snippet_into_file()` replaces the exact modified lines inside the full original file while keeping all untouched code preserved.
3. **Git Diff Creation** (`generate_git_diff`): Using Python's standard `difflib.unified_diff`, a standard Git diff header is produced:
   ```diff
   diff --git a/backend/auth.py b/backend/auth.py
   --- a/backend/auth.py
   +++ b/backend/auth.py
   @@ -12,3 +12,4 @@
   - return user["token"]
   + return user.get("token", None)
   ```

### Step 4: Syntax & Safety Validation
Before applying edits, `backend/patch_generator/patch_validator.py` executes strict checks:
- **Syntax Check**: Uses Python AST parsing (`ast.parse`) to confirm the generated code compiles cleanly without syntax errors.
- **Git Apply Dry-Run**: Evaluates `git apply --check` to ensure the patch applies cleanly without merge conflicts.
- **Confidence Score**: Computes a total quality score based on localization confidence, syntax validity, diff validity, and changes made.

### Step 5: Safe Disk Modification & Backups
When the patch is approved by the user (`update_patch_status(status='applied')`):
1. **Backup Creation**: `apply_patch_to_file()` creates a timestamped copy (e.g., `auth.py.bak.1740000000`).
2. **File Overwrite**: Writes the clean, merged code into `auth.py` on disk.
3. **Rollback Safety**: If any file write fails, the system logs the error and restores/reverts status automatically.

---

## 4. Feature Index & Code Mapping

| Feature | Module File | Description |
| :--- | :--- | :--- |
| **Repository Parser** | [`core/parser.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/core/parser.py) | Recursively walks codebase, filtering binaries and language extensions. |
| **AST Semantic Chunker** | [`core/chunker.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/core/chunker.py) | Parses Python AST into function/class-level code chunks with metadata. |
| **Vector Database Layer** | [`core/vectorstore.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/core/vectorstore.py) | FAISS indexing with L2-normalized Cosine similarity search. |
| **Dependency Graph** | [`core/dependency_graph.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/core/dependency_graph.py) | Builds NetworkX directed graph of import references and module impact. |
| **LLM Client** | [`core/llm_client.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/core/llm_client.py) | Communicates with Ollama API (`qwen2.5-coder`). |
| **Assistant & Intent Engine** | [`backend/services/assistant_engine.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/backend/services/assistant_engine.py) | Intent classification (JWT, Auth, Arch, Unused code) + term boosting. |
| **Bug Localizer** | [`backend/bug_localizer/advanced_localizer.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/backend/bug_localizer/advanced_localizer.py) | Stack trace frame parsing & RAG similarity scoring. |
| **Patch Engine** | [`backend/patch_generator/patch_engine.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/backend/patch_generator/patch_engine.py) | Context assembly, LLM prompting (Temp=0.1), diff creation. |
| **Patch Applier & File Writer** | [`backend/patch_generator/patch_applier.py`](file:///c:/Users/vikas/Downloads/Major%20Project%202026/intellicodex/backend/patch_generator/patch_applier.py) | Safe file modification on disk with `.bak` backup creation. |

---

## 5. Roadmap to Build the Best AI Code Assistant

To transform IntelliCodeX into a state-of-the-art AI coding environment, implement the following key advancements:

### 1. Multi-Language AST Parsing via Tree-Sitter
- *Current state*: Python AST parsing in `chunker.py`. Non-Python files use whole-file chunking.
- *Best practice*: Integrate `tree-sitter` grammars (for JavaScript, TypeScript, C++, Java, Go, Rust) to extract class/function chunks across all programming languages.

### 2. Multi-turn Agentic Tool Calling & Iterative Fixes
- *Current state*: Single-shot patch generation.
- *Best practice*: Implement an interactive agent loop (like Antigravity / Claude Code) equipped with tools:
  - `read_file`, `write_file`, `run_tests`, `git_diff`.
  - Let the LLM run unit tests (`pytest`), observe test output, and iterate on the code until all tests pass.

### 3. High-Quality Code Model Selection & Fine-Tuning
- *Recommended Models*:
  - `qwen2.5-coder:7b` / `14b` or `32b` (State-of-the-art open-source code models).
  - `deepseek-coder-v2` / `deepseek-r1` (Extremely powerful for complex algorithmic reasoning).
- *Fine-Tuning*: Train LoRA / QLoRA adapters on repository-specific pull requests and commit diffs.

### 4. Codebase-wide Persistence & Incremental Re-indexing
- *Current state*: Memory-bound FAISS index.
- *Best practice*: Persist FAISS indices to disk (`faiss.write_index`) alongside a local SQLite database. Watch file system events (or Git commits) to only re-embed modified files.

---

## Summary Checklist to Run & Test
1. **Launch Ollama**:
   ```bash
   ollama pull qwen2.5-coder:3b
   ollama pull nomic-embed-text
   ollama serve
   ```
2. **Run Interactive CLI**:
   ```bash
   python cli.py sample_repo --backend ollama
   ```
3. **Launch Full Application**:
   Run `run.bat` or launch backend server via `uvicorn backend.main:app --reload`.
