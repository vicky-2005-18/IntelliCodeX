# Design Document: IntelliCodeX Interactive Terminal CLI Enhancement & Modularization

> **Document Path**: `docs/superpowers/specs/2026-11-01-interactive-terminal-cli-enhancement-design.md`  
> **Status**: Approved Design Document (Post-Builder Review)  
> **Target Release**: Semester 1 CLI Core & Local Intelligence Engine  
> **Owner**: Core Engineering  

---

## 1. Intent & Purpose

IntelliCodeX is a privacy-preserving, local-first repository intelligence and automated repair engine. The interactive terminal CLI (`cli.py`) is the primary user interface for developers investigating codebases, querying RAG pipelines, analyzing dependency call-graphs, and synthesizing bug fixes.

Over recent development cycles, `cli.py` has grown into a 5,880-line monolithic file combining argument parsing, mascot animations, terminal mouse tracking, prompt-toolkit sessions, command dispatching, RAG streaming, and interactive code review. 

### Why This Work Is Needed:
1. **Terminal State Hygiene & Escape Artifacts**: Mouse tracking escape codes (`\x1b[?1000h`, `\x1b[?1002h`) can leave the terminal in a corrupt state if interrupted (Ctrl+C) or exited abruptly on Windows Terminal, CMD, or PowerShell, printing raw ANSI escape characters (e.g. `^[[<0;24;12M`) when the mouse moves.
2. **Streaming Flicker & UI Overlap**: Token streaming from local LLMs (Ollama) frequently conflicts with rich spinners and mascot rendering, leading to visual flickering, duplicated lines, and choppy console output.
3. **Monolithic Codebase Risk**: Modifying CLI features or adding new command handlers requires editing a massive single file, increasing regression risks and slowing down development.
4. **Interactive Patch Review Friction**: Reviewing synthesized patches currently relies on text prompts rather than a colorized, keyboard-driven diff reviewer with quick actions (apply with backup, run sandbox tests, view full diff, reject).
5. **Multi-Line Paste Accidental Execution**: Pasting multi-line stack traces or snippets into the prompt can trigger line-by-line command execution instead of treating the paste as a single cohesive input.

---

## 2. Goals, Non-Goals & Anti-Goals

### Goals
* **G1. Clean Modularization**: Decompose the 5,880-line `cli.py` into cohesive, well-tested submodules under `core/cli/` while maintaining 100% backward compatibility for `python cli.py [args]`.
* **G2. Guaranteed Terminal Hygiene**: Ensure bulletproof cleanup on normal exit, `SIGINT` (Ctrl+C), `SIGTERM`, and unhandled exceptions, restoring mouse tracking, cursor visibility, and terminal raw modes across Windows and Unix hosts.
* **G3. Smooth, Flicker-Free Output**: Stream LLM tokens cleanly using Rich live viewports without overlapping spinners or mascot ANSI glitches.
* **G4. Persistent Bottom Status Toolbar**: Render a pinned, non-intrusive status bar via `prompt_toolkit` displaying: Active Repository, Model & Provider (Ollama/TF-IDF), Ollama Daemon Health, Background Watcher Status, and Context Token Usage.
* **G5. Fuzzy Autocompletion & Command Palette**: Provide rich tab-autocompletion with inline documentation for all commands (`explain:`, `fix:`, `search:`, `deps:`, `callers:`, `watch:`, `security:`, `index-stats`, etc.) and dynamic completion for repo-relative file paths and indexed symbols.
* **G6. Interactive Patch Reviewer**: Provide a colorized unified diff screen with single-key review actions: `[a]` Apply with `.bak`, `[t]` Test in Sandbox, `[v]` View full context diff, and `[r]` Reject/Refine.
* **G7. Safe Paste & Multi-Line Handling**: Support bracketed paste mode so pasting multiline tracebacks or code snippets does not trigger premature execution.

### Non-Goals
* Re-implementing a fullscreen curses/Textual desktop window application (taking over the alternate screen buffer).
* Modifying core backend RAG, SBFL, or sandbox algorithms (those remain stable and verified).
* Deprecating headless CLI execution (`--ci`, non-interactive batch commands).

### Anti-Goals
* Introducing heavy external dependencies beyond already-installed `rich` and `prompt_toolkit`.
* Breaking existing test suites (`tests/test_cli.py`, `tests/test_tui_and_packaging.py`).
* Introducing terminal redraw latency or input lag.

---

## 3. Approaches Considered & Trade-offs

### Approach 1: Polished & Modular REPL with Rich + Prompt-Toolkit (Selected)
* **Description**: Retain and modularize the existing scroll-friendly REPL architecture in `cli.py`, upgrading it with a persistent status bar, fuzzy completion, safe terminal teardown, flicker-free token streaming, and an interactive diff viewer.
* **Pros**: Builds directly on proven dependencies (`rich` and `prompt_toolkit`); preserves standard scrollback, native copy-paste, and headless automation; fixes terminal mouse artifacts; zero risk of terminal host incompatibilities.
* **Cons**: Uses standard stdout scrolling flow rather than a fixed multi-pane layout.
* **Decision**: **Selected by user** as the ideal balance of terminal-native UX, reliability, and low architectural risk.

### Approach 2: Fullscreen Terminal Application (Textual TUI Workspace)
* **Description**: Transition the interactive mode into an all-inclusive fullscreen terminal application using `textual` with a 3-pane dashboard.
* **Pros**: Native multi-window layouts, mouse-clickable tabs, and split views.
* **Cons**: Requires adding new dependency `textual`; hijacks terminal scrollback buffer; higher rendering quirks across older Windows console hosts.
* **Decision**: Rejected due to unnecessary weight and loss of native shell copy-paste/scrollback ergonomics.

### Approach 3: Minimal Core Stream + Web TUI Companion
* **Description**: Strip `cli.py` to bare stdout streaming and offload complex inspections to a local browser tab.
* **Pros**: Zero terminal complexity.
* **Cons**: Breaks the user's explicit preference for an interactive terminal CLI and forces context switching between terminal and browser.
* **Decision**: Rejected as counter to terminal-first workflow.

---

## 4. Architectural Design & Modularization

The monolithic `cli.py` will be structured into a clean package:

```
core/cli/
├── __init__.py               # Package export & backward-compatible symbol re-exports
├── state.py                  # CLISessionState: active repo, watcher, LLM, embedder, memory
├── terminal_safety.py        # Terminal cleanup, signal handlers, mouse mode restoration
├── completers.py             # Prompt-toolkit fuzzy completer (commands, files, symbols)
├── ui/
│   ├── __init__.py
│   ├── banner.py             # ASCII logo, mascot controller, and welcome banner
│   ├── status_bar.py         # Dynamic prompt_toolkit bottom toolbar (FormattedTextToolbar)
│   ├── streamer.py           # Smooth Live token streaming renderer (flicker-free buffer)
│   ├── diff_viewer.py        # Interactive Rich diff review modal with single-key actions
│   └── tables.py             # Formatted tables for index-stats, dependencies, security
└── commands/
    ├── __init__.py           # Command registry & dispatcher
    ├── base.py               # CommandHandler abstract protocol
    ├── query_handler.py      # Q&A, explain, compare, and multi-turn chat
    ├── fix_handler.py        # fix:, bug localization, and patch generation
    ├── repo_handler.py       # repo switching, indexing, and chunks inspection
    ├── watch_handler.py      # watch:start, watch:stop, watch:status
    ├── audit_handler.py      # security scan, architecture cycle audit, deps, callers
    ├── remote_handler.py     # --server remote client handling
    └── multi_repo_handler.py # multi-repo workspace querying
```

`cli.py` in the root repository will remain as a lightweight wrapper that re-exports all public symbols for test compatibility and delegates execution to `core.cli.main()`.

---

## 5. Subsystem Specifications & Builder Resolutions

### 5.1 Terminal State Hygiene (`core/cli/terminal_safety.py`)
* Standardize cleanup across `atexit.register()`, `signal.signal(signal.SIGINT, ...)`, and `signal.signal(signal.SIGTERM, ...)`.
* Ensure explicit ANSI mouse disable sequences are sent:
  ```python
  MOUSE_DISABLE_SEQUENCES = "\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?25h"
  ```
* Ensure stdout flushing and terminal echo restoration on Windows (`ENABLE_VIRTUAL_TERMINAL_INPUT`, `ENABLE_PROCESSED_INPUT`).

### 5.2 Dynamic Bottom Status Bar (`core/cli/ui/status_bar.py`)
* Implemented via `prompt_toolkit.layout.FormattedTextToolbar`.
* Renders a clean 1-line bar below the prompt:
  ```
  [IntelliCodeX] Repo: sample_repo (34 files) | Model: qwen2.5-coder:3b (Ollama ✓) | Watcher: Active | Dim: 768
  ```
* Dynamically updates when the repository changes, when Ollama falls back to TF-IDF, or when the file watcher pauses/resumes.
* *(Builder Call)*: Preserves the top mascot container structure for backward compatibility with `test_tui_and_packaging.py`, while avoiding visual flicker during active user input.

### 5.3 Live Token Streaming (`core/cli/ui/streamer.py`)
* Uses `rich.live.Live` with `refresh_per_second=15` and `auto_refresh=False`.
* *(Builder Call)*: Tokens are streamed into an unformatted character buffer during real-time generation to avoid partial-markdown rendering glitches (e.g. unclosed backticks). Upon generation completion, the completed text is formatted and rendered as a polished `rich.markdown.Markdown` panel.
* Automatically suspends any mascot spinners or background indicators during streaming to prevent line corruption.

### 5.4 Fuzzy Completer (`core/cli/completers.py`)
* Custom `prompt_toolkit.completion.Completer` providing:
  1. Primary commands (`explain:`, `fix:`, `search:`, `deps:`, `callers:`, `watch:`, `security:`, `top`, `index-stats`, `persona`, `model`, `repo`, `hooks`, `clear`, `exit`).
  2. Relative file path completion based on active indexed repository files.
  3. Symbol completion based on AST function and class nodes.
  4. Inline parameter hints and docstrings displayed in the completion dropdown.

### 5.5 Interactive Patch Reviewer (`core/cli/ui/diff_viewer.py`)
* Displays a colorized unified diff in a Rich panel with line numbers and sandbox validation status.
* Presents an interactive prompt:
  `[A]pply patch (with .bak) | [T]est in sandbox | [V]iew full diff | [R]eject / Cancel`
* *(Builder Call)*: If candidate sandbox validation was already performed during patch synthesis (standard behavior for `fix:`), its passing/failing status is clearly badged. If unverified or offline, `[T]` runs the candidate patch through `core/sandbox_runner.py` on-demand before application.

### 5.6 Test & Import Compatibility (`cli.py`)
* *(Builder Call)*: To guarantee zero regressions in `tests/test_cli.py` and `tests/test_tui_and_packaging.py`, root `cli.py` explicitly re-exports all public functions, classes, and constants (`check_ollama_available`, `resolve_repo_path`, `create_components`, `print_banner`, `print_help`, `main`, `MascotController`, `MascotSpinner`, `IntelliCodeXCompleter`, `FileHistory`, `should_use_tui`, `is_mascot_mouse_enabled`, etc.).

---

## 6. Verification & Test Plan

1. **Unit Testing**:
   - `tests/test_cli_modular.py`: Verify command dispatching, argument resolution, and session state.
   - `tests/test_terminal_safety.py`: Test signal handling and terminal restoration sequences.
   - `tests/test_cli_completer.py`: Test fuzzy matching against commands, files, and AST symbols.
   - `tests/test_diff_viewer.py`: Test diff rendering and keyboard action callbacks.
2. **Regression Verification**:
   - Run full existing CLI test suite: `pytest tests/test_cli.py tests/test_tui_and_packaging.py`.
   - Run CI pipeline test: `pytest tests/test_ci_pipeline.py`.
3. **Manual Interactive Verification**:
   - Test in Windows Terminal (PowerShell), CMD, and VS Code integrated terminal.
   - Verify Ctrl+C during prompt, during streaming, and during patch generation leaves clean terminal state without mouse escape junk.
   - Verify multi-line paste does not auto-execute.

---

## 7. Decisions Left to Builder
* Precise color theme accents (default to Cyan/Blue/Emerald palette matching existing IntelliCodeX branding).
* Exact cache eviction policy for symbol completions when repository files are edited by the watcher.
