# ADR-0003: Multi-Language Semantic AST Chunking via Tree-Sitter Grammars

* **Status**: Accepted
* **Date**: 2026-09-17
* **Deciders**: IntelliCodeX Core Team
* **Technical Area**: Core Parsing / AST Chunking

## Context & Problem Statement
Early implementations of code chunkers relied on naive fixed-character or fixed-line splitting, or were restricted to Python's built-in `ast` module. Fixed-window chunking breaks functions and classes across arbitrary boundaries, destroying syntax semantics and degrading retrieval precision. Modern codebases comprise multiple languages including JavaScript, TypeScript, TSX, Java, C, C++, Go, and Rust.

## Decision Drivers
- High precision semantic chunking aligned with actual function, method, class, struct, and interface boundaries.
- Support for 8+ major programming languages without language-specific interpreter runtimes.
- Robust fallback for unsupported formats or unparseable source files.

## Considered Options
1. **Regular Expressions / Heuristic Line Parsing**: Fragile, easily broken by nested closures, multi-line signatures, or complex string literals.
2. **Language-Specific Native Compilers**: Requires JDK, Node.js, Go, Rust, GCC installed on the host system.
3. **Tree-Sitter Grammar Parsers (`tree-sitter` and `tree-sitter-<lang>`)**: High-performance, incremental, concrete syntax tree (CST) parsers compiled into C extensions with Python bindings.

## Decision Outcome
Chosen Option: **Tree-Sitter Grammars with Sliding Window Fallback**.

### Consequences
* **Positive**:
  - Fine-grained extraction of function, method, class, struct, and section chunks across Python, JS, TS, Java, C, C++, Go, and Rust.
  - Robust error recovery: syntax errors do not abort the entire file parse.
  - Clean fallback to sliding window chunking when grammars are absent or for markup/config files.
* **Negative / Trade-offs**:
  - Python wheel dependencies for each `tree-sitter-<lang>` language package.

## Implementation References
- File: [`core/ts_loader.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/ts_loader.py)
- File: [`core/tree_sitter_chunker.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/tree_sitter_chunker.py)
- File: [`core/chunker.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/chunker.py)
- Verification Tests: [`tests/test_tree_sitter_chunker.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_tree_sitter_chunker.py), [`tests/test_ts_loader.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_ts_loader.py)
