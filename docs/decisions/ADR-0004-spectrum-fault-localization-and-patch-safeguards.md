# ADR-0004: Spectrum Fault Localization (Ochiai) & Defensive Patch Generation with Backups

* **Status**: Accepted
* **Date**: 2026-09-17
* **Deciders**: IntelliCodeX Core Team
* **Technical Area**: Fault Localization & Patch Generation

## Context & Problem Statement
Automated bug repair requires two distinct capabilities:
1. Accurately pinpointing the root cause code element (file, function, line) from error traces or test execution logs.
2. Generating context-aware code patches that fix the defect while preventing regressions, avoiding unintended full-file rewrites, and guaranteeing safety when modifying files on disk.

## Decision Drivers
- Multi-signal localization combining dynamic test coverage metrics (Ochiai formula), stack trace regex parsing, semantic similarity, and architectural graph centrality.
- Deterministic, low-temperature LLM code repair (`temperature=0.1`).
- Strict validation pipeline: AST syntax checking, git diff generation, and dry-run validation.
- Safe on-disk file writes with automatic timestamped backup copies (`.bak`) and rollback support.

## Considered Options
1. **Direct Whole-File LLM Overwrites**: Ask LLM to rewrite entire file; prone to hallucinating away unrelated functions, formatting shifts, and syntax truncation.
2. **Unified Diff-Only Text Generation**: Ask LLM to output unified diff directly; models frequently miscount hunk line numbers (`@@ -l,s +l,s @@`), causing `patch` rejection.
3. **Snippet Generation + Python AST Merge + Diff Synthesizer**: LLM fixes targeted snippet; AST validator parses code; `difflib.unified_diff` creates exact Git diff; applier backs up target file before atomic write.

## Decision Outcome
Chosen Option: **Snippet Generation + Python AST Merge + Diff Synthesizer + Safe Applier**.

### Consequences
* **Positive**:
  - Eliminates hunk line number hallucination by generating exact diffs via Python's standard `difflib`.
  - Python AST syntax checking catches malformed edits before user application.
  - Safe file modification on disk with `.bak.<timestamp>` rollback capabilities.
* **Negative / Trade-offs**:
  - Complex multi-stage pipeline across localizer, patch engine, validator, and applier.
  - AST syntax validation for non-Python languages currently relies on heuristic checks and git apply dry-runs.

## Implementation References
- File: [`core/bug_localizer.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/bug_localizer.py)
- File: [`core/patch_generator.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/core/patch_generator.py)
- File: [`backend/patch_generator/patch_applier.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/backend/patch_generator/patch_applier.py)
- Verification Tests: [`tests/test_bug_localizer.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_bug_localizer.py), [`tests/test_patch_generator.py`](file:///c:/Users/vikas/Downloads/Major%20project%202%202026/intellicodex/tests/test_patch_generator.py)
