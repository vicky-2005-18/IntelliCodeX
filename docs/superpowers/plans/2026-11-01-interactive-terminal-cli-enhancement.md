# IntelliCodeX Interactive Terminal CLI Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the monolithic `cli.py` into a robust, modular, and buttery-smooth interactive terminal CLI with bulletproof terminal hygiene, persistent bottom status toolbar, flicker-free token streaming, fuzzy autocompletion, and interactive patch review.

**Architecture:** Decompose CLI responsibilities into focused submodules under `core/cli/` (`terminal_safety`, `state`, `ui/`, `completers`, and `commands/`) while preserving 100% backward compatibility in root `cli.py`. Terminal cleanup guarantees restoration of mouse modes and raw buffers on interrupts; Prompt-Toolkit provides non-intrusive status toolbars and fuzzy autocompletion; and Rich powers flicker-free live streaming and interactive unified diff review.

**Tech Stack:** Python 3.10+ (Python 3.12 / 3.14 target), `rich` (Live, Panel, Syntax, Table, Markdown), `prompt_toolkit` (PromptSession, FormattedTextToolbar, Completer), `subprocess`, `signal`, `atexit`.

**Spec:** [`docs/superpowers/specs/2026-11-01-interactive-terminal-cli-enhancement-design.md`](../specs/2026-11-01-interactive-terminal-cli-enhancement-design.md)

## Global Constraints

* Must maintain 100% backward compatibility for `cli.py` command line flags, environment variables, and public symbol imports.
* Must not add external dependencies beyond the existing `rich` and `prompt_toolkit`.
* Must cleanly restore terminal state (mouse tracking, cursor visibility, raw input) on `SIGINT` (Ctrl+C), `SIGTERM`, unhandled exceptions, and normal exit across Windows (PowerShell/CMD/Windows Terminal) and Linux/macOS.
* Must not cause text or cursor flickering during live LLM token streaming.
* Must pass existing test suites (`tests/test_cli.py`, `tests/test_tui_and_packaging.py`, `tests/test_ci_pipeline.py`) without modifying their assertions.

## Review Focus

1. **Ctrl+C during LLM streaming**: Must immediately halt streaming, restore terminal cursor and mouse modes, and cleanly return to the interactive prompt without raising unhandled `KeyboardInterrupt` tracebacks.
2. **Terminal Mouse Mode Exit Bleed**: Exiting the CLI (or killing it) while mouse tracking was enabled must send ANSI disable sequence `\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?25h` so the parent terminal does not receive mouse position escape junk.
3. **Multi-line Paste**: Pasting multi-line text (e.g. stack traces or code snippets) must not trigger execution on every newline; the entire paste buffer must remain in the prompt until Enter is pressed.
4. **Incomplete Markdown During Streaming**: Live-streaming tokens that contain unclosed code fences or bold markers must not crash or cause Rich parsing artifacts before the closing token arrives.
5. **Dynamic Model / Backend Switch Fallback**: Switching backend from `ollama` to `tfidf` (or when Ollama drops offline mid-session) must update the bottom status bar dynamically and prevent `NoneType` attribute errors.

---

### Task 1: Terminal State Hygiene & Safety Subsystem

**Files:**
- Create: `core/cli/terminal_safety.py`
- Test: `tests/test_terminal_safety.py`

**Interfaces:**
- Produces:
  - `restore_terminal_mouse_modes() -> None`
  - `register_active_watcher(watcher: Any) -> None`
  - `cleanup_cli_resources(watcher: Optional[Any] = None) -> None`
  - `setup_terminal_signal_handlers() -> None`
  - `MOUSE_DISABLE_SEQUENCES: str`

- [ ] **Step 1: Write the failing test in `tests/test_terminal_safety.py`**

```python
import sys
from unittest.mock import patch, MagicMock
from core.cli.terminal_safety import (
    restore_terminal_mouse_modes,
    cleanup_cli_resources,
    register_active_watcher,
    setup_terminal_signal_handlers,
    MOUSE_DISABLE_SEQUENCES,
)

def test_restore_terminal_mouse_modes_emits_ansi_reset():
    mock_stdout = MagicMock()
    with patch("sys.stdout", mock_stdout):
        restore_terminal_mouse_modes()
        mock_stdout.write.assert_called_with(MOUSE_DISABLE_SEQUENCES)
        mock_stdout.flush.assert_called_once()

def test_cleanup_cli_resources_stops_watcher_and_restores_terminal():
    mock_watcher = MagicMock()
    register_active_watcher(mock_watcher)
    with patch("core.cli.terminal_safety.restore_terminal_mouse_modes") as mock_restore:
        cleanup_cli_resources()
        mock_watcher.stop.assert_called_once()
        mock_restore.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_terminal_safety.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli'`

- [ ] **Step 3: Implement `core/cli/terminal_safety.py`**

Implement `restore_terminal_mouse_modes`, `register_active_watcher`, `cleanup_cli_resources`, and `setup_terminal_signal_handlers`. Use ANSI disable sequences `\x1b[?9l\x1b[?1000l\x1b[?1001l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?25h`, register `atexit` cleanup, and handle Windows Console mode resets when available.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_terminal_safety.py -v`  
Expected: PASS (all tests green)

- [ ] **Step 5: Commit**

```bash
git add core/cli/terminal_safety.py tests/test_terminal_safety.py
git commit -m "feat(cli): implement robust terminal safety and mouse restoration subsystem"
```

---

### Task 2: Session State Management

**Files:**
- Create: `core/cli/state.py`
- Test: `tests/test_cli_state.py`

**Interfaces:**
- Consumes: `core/embedder.py`, `core/llm_client.py`, `rag/query_engine.py`
- Produces:
  - `class CLISessionState`:
    - Attributes: `repo_path: str`, `repo_id: str`, `backend: str`, `model_name: str`, `embedder: Any`, `llm: Optional[Any]`, `engine: Any`, `watcher: Optional[Any]`, `active_file_filter: Optional[str]`, `persona: str`
    - Methods: `switch_repo(new_path: str) -> None`, `switch_backend(backend: str) -> None`, `switch_model(model_name: str) -> None`, `set_file_filter(filter_str: Optional[str]) -> None`

- [ ] **Step 1: Write the failing test in `tests/test_cli_state.py`**

```python
from unittest.mock import MagicMock
from core.cli.state import CLISessionState

def test_session_state_initialization():
    mock_embedder = MagicMock()
    mock_engine = MagicMock()
    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="tfidf",
        model_name="qwen2.5-coder:3b",
        embedder=mock_embedder,
        llm=None,
        engine=mock_engine,
    )
    assert state.repo_path == "sample_repo"
    assert state.backend == "tfidf"
    assert state.active_file_filter is None

def test_session_state_switch_file_filter():
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "model", None, None, None)
    state.set_file_filter("auth.py")
    assert state.active_file_filter == "auth.py"
    state.set_file_filter(None)
    assert state.active_file_filter is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_state.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli.state'`

- [ ] **Step 3: Implement `core/cli/state.py`**

Implement `CLISessionState` dataclass encapsulating runtime CLI state, dynamic switches for model and backend, and safe thread synchronization for watcher state.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_state.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/cli/state.py tests/test_cli_state.py
git commit -m "feat(cli): implement central CLI session state management"
```

---

### Task 3: Dynamic Bottom Status Toolbar

**Files:**
- Create: `core/cli/ui/status_bar.py`
- Test: `tests/test_cli_status_bar.py`

**Interfaces:**
- Consumes: `core/cli/state.py::CLISessionState`
- Produces:
  - `render_status_toolbar(state: CLISessionState) -> List[Tuple[str, str]]`: Formatted text tokens for `prompt_toolkit.layout.FormattedTextToolbar`
  - `format_status_summary(state: CLISessionState) -> str`: Plain text representation for testing

- [ ] **Step 1: Write the failing test in `tests/test_cli_status_bar.py`**

```python
from unittest.mock import MagicMock
from core.cli.state import CLISessionState
from core.cli.ui.status_bar import render_status_toolbar, format_status_summary

def test_status_toolbar_formatting_offline():
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "none", None, None, None)
    summary = format_status_summary(state)
    assert "Repo: sample_repo" in summary
    assert "Backend: tfidf" in summary

def test_status_toolbar_returns_formatted_tokens():
    state = CLISessionState("sample_repo", "sample_repo", "ollama", "qwen2.5-coder:3b", None, MagicMock(), None)
    tokens = render_status_toolbar(state)
    assert isinstance(tokens, list)
    rendered_text = "".join(t[1] for t in tokens)
    assert "qwen2.5-coder:3b" in rendered_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_status_bar.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli.ui'`

- [ ] **Step 3: Implement `core/cli/ui/status_bar.py`**

Implement `render_status_toolbar` returning colorized `(style, text)` tuples compatible with Prompt-Toolkit `bottom_toolbar`. Include active repo, model/backend status, file filter indicator, and watcher status.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_status_bar.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/cli/ui/status_bar.py tests/test_cli_status_bar.py
git commit -m "feat(cli): implement dynamic prompt status toolbar"
```

---

### Task 4: Flicker-Free Live Token Streaming

**Files:**
- Create: `core/cli/ui/streamer.py`
- Test: `tests/test_cli_streamer.py`

**Interfaces:**
- Consumes: `rich.console.Console`, `rich.live.Live`, `rich.markdown.Markdown`
- Produces:
  - `class TokenStreamer`:
    - `__init__(console: Optional[Console] = None)`
    - `stream(token_generator: Iterable[str], title: str = "Answer") -> str`: Streams tokens into live buffer and finalizes as Rich Markdown panel without flickering
    - `cancel() -> None`: Safely halts streaming and flushes partial output

- [ ] **Step 1: Write the failing test in `tests/test_cli_streamer.py`**

```python
from core.cli.ui.streamer import TokenStreamer

def test_token_streamer_accumulates_and_returns_full_text():
    tokens = ["def ", "hello():\n", "    return 'world'"]
    streamer = TokenStreamer()
    result = streamer.stream(iter(tokens))
    assert result == "def hello():\n    return 'world'"

def test_token_streamer_empty_stream():
    streamer = TokenStreamer()
    result = streamer.stream(iter([]))
    assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_streamer.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli.ui.streamer'`

- [ ] **Step 3: Implement `core/cli/ui/streamer.py`**

Implement `TokenStreamer` using `rich.live.Live` with `auto_refresh=False` and controlled `refresh_per_second=15`. Accumulate tokens safely without throwing exceptions on incomplete markdown code fences, and on stream completion render the finalized `rich.markdown.Markdown` panel.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_streamer.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/cli/ui/streamer.py tests/test_cli_streamer.py
git commit -m "feat(cli): implement flicker-free token streaming renderer"
```

---

### Task 5: Fuzzy Autocompleter & Command Palette

**Files:**
- Create: `core/cli/completers.py`
- Test: `tests/test_cli_completer.py`

**Interfaces:**
- Consumes: `prompt_toolkit.completion.Completer`, `prompt_toolkit.document.Document`
- Produces:
  - `class IntelliCodeXCompleter(Completer)`:
    - Supports fuzzy command matching (`explain:`, `fix:`, `deps:`, `watch:`, `security:`, `top`, `index-stats`, etc.)
    - `@`-triggered file path completion
    - AST symbol completion with signature preview
    - Preserves compatibility with existing `cli.IntelliCodeXCompleter` methods and attributes

- [ ] **Step 1: Write the failing test in `tests/test_cli_completer.py`**

```python
from prompt_toolkit.document import Document
from core.cli.completers import IntelliCodeXCompleter

def test_completer_fuzzy_command_matching():
    completer = IntelliCodeXCompleter()
    doc = Document("exp")
    matches = [c.text for c in completer.get_completions(doc, None)]
    assert "explain:" in matches

def test_completer_at_mention_file_matching():
    files = ["backend/auth.py", "core/embedder.py", "cli.py"]
    completer = IntelliCodeXCompleter(get_files_fn=lambda: files)
    doc = Document("review @auth")
    matches = [c.text for c in completer.get_completions(doc, None)]
    assert any("auth.py" in m for m in matches)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_completer.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli.completers'`

- [ ] **Step 3: Implement `core/cli/completers.py`**

Implement `IntelliCodeXCompleter` supporting command categories, `@` file mentions, symbol completions, and meta display text in prompt completion popups.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_completer.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/cli/completers.py tests/test_cli_completer.py
git commit -m "feat(cli): implement rich fuzzy autocompleter and symbol completion"
```

---

### Task 6: Interactive Patch & Unified Diff Reviewer

**Files:**
- Create: `core/cli/ui/diff_viewer.py`
- Test: `tests/test_cli_diff_viewer.py`

**Interfaces:**
- Consumes: `rich.panel.Panel`, `rich.syntax.Syntax`, `core/patch_generator.py`
- Produces:
  - `render_interactive_diff(patch_record: Dict[str, Any], on_action: Optional[Callable[[str], Any]] = None) -> str`
  - Single-key actions: `[a]` Apply, `[t]` Test in sandbox, `[v]` View full context diff, `[r]` Reject/Cancel

- [ ] **Step 1: Write the failing test in `tests/test_cli_diff_viewer.py`**

```python
from unittest.mock import patch, MagicMock
from core.cli.ui.diff_viewer import render_interactive_diff

def test_interactive_diff_display_and_action():
    patch_rec = {
        "patch_id": "patch_123",
        "target_file": "pkg/calc.py",
        "explanation": "Fix ZeroDivisionError",
        "git_diff": "--- a/pkg/calc.py\n+++ b/pkg/calc.py\n@@ -1 +1 @@\n-return 1/0\n+return 0",
        "sandbox_validation": {"test_status": "passed"}
    }
    with patch("builtins.input", return_value="a"):
        action = render_interactive_diff(patch_rec)
        assert action == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_diff_viewer.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli.ui.diff_viewer'`

- [ ] **Step 3: Implement `core/cli/ui/diff_viewer.py`**

Implement `render_interactive_diff` rendering a colorized syntax-highlighted diff card with sandbox validation badge and prompt for `[A]pply | [T]est in sandbox | [V]iew full diff | [R]eject`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_diff_viewer.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/cli/ui/diff_viewer.py tests/test_cli_diff_viewer.py
git commit -m "feat(cli): implement interactive diff reviewer with sandbox test integration"
```

---

### Task 7: Modular Command Handlers & Registry

**Files:**
- Create: `core/cli/commands/__init__.py`
- Create: `core/cli/commands/base.py`
- Create: `core/cli/commands/query_handler.py`
- Create: `core/cli/commands/fix_handler.py`
- Create: `core/cli/commands/repo_handler.py`
- Create: `core/cli/commands/watch_handler.py`
- Create: `core/cli/commands/audit_handler.py`
- Test: `tests/test_cli_commands.py`

**Interfaces:**
- Consumes: `core/cli/state.py::CLISessionState`, `core/cli/ui/*`
- Produces:
  - `class CommandRegistry`:
    - `dispatch(raw_input: str, state: CLISessionState) -> bool`: Dispatches input to matching handler, returns True if handled, False if unknown.

- [ ] **Step 1: Write the failing test in `tests/test_cli_commands.py`**

```python
from unittest.mock import MagicMock
from core.cli.state import CLISessionState
from core.cli.commands import CommandRegistry

def test_command_registry_dispatch_exit():
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "none", None, None, None)
    registry = CommandRegistry()
    res = registry.dispatch("exit", state)
    assert res == "exit"

def test_command_registry_dispatch_watch_status():
    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True
    state = CLISessionState("sample_repo", "sample_repo", "tfidf", "none", None, None, None, watcher=mock_watcher)
    registry = CommandRegistry()
    res = registry.dispatch("watch:status", state)
    assert res is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_commands.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cli.commands'`

- [ ] **Step 3: Implement `core/cli/commands/`**

Implement `CommandRegistry` and modular command handlers: `QueryHandler` (Q&A/explain/compare), `FixHandler` (fix & test), `RepoHandler` (repos/ls/chunks), `WatchHandler` (watch lifecycle), and `AuditHandler` (security & architecture cycles).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_commands.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/cli/commands/ tests/test_cli_commands.py
git commit -m "feat(cli): implement modular command registry and decoupled handlers"
```

---

### Task 8: Package Assembly, Backward Compatibility Wrapper & Full Regression Verification

**Files:**
- Create: `core/cli/__init__.py`
- Modify: `cli.py` (transform into lightweight backward-compatible re-exporting wrapper)
- Test: `tests/test_cli.py`, `tests/test_tui_and_packaging.py`, `tests/test_ci_pipeline.py`

**Interfaces:**
- `core/cli/__init__.py`: exports `main()`, `create_interactive_session()`, and re-exports all symbols required by existing tests.
- Root `cli.py`: ~80-line wrapper delegating `main()` and re-exporting `__all__` for 100% backward compatibility.

- [ ] **Step 1: Implement `core/cli/__init__.py` assembling the subsystems**

Connect `terminal_safety`, `state`, `ui/`, `completers`, and `commands` into `main()`.

- [ ] **Step 2: Update root `cli.py` to re-export legacy symbols and delegate to `core.cli.main()`**

Ensure `check_ollama_available`, `resolve_repo_path`, `create_components`, `print_banner`, `print_help`, `main`, `MascotController`, `MascotSpinner`, `IntelliCodeXCompleter`, `FileHistory`, `should_use_tui`, `is_mascot_mouse_enabled`, `render_banner`, `render_markdown_panel`, `render_diff`, `render_files_table`, etc. are all cleanly exported from `cli.py`.

- [ ] **Step 3: Run full CLI test suites to verify 0 regressions**

Run: `pytest tests/test_cli.py tests/test_tui_and_packaging.py tests/test_ci_pipeline.py -v`  
Expected: 100% PASS with 0 failures and 0 errors.

- [ ] **Step 4: Commit**

```bash
git add core/cli/__init__.py cli.py
git commit -m "refactor(cli): complete modular CLI architecture with 100% backward compatibility"
```

- [ ] **Step 5: Update graphify knowledge graph per project rules**

Run: `python -c "import subprocess; subprocess.run(['graphify', 'update', '.'])"` or verify documentation sync.

