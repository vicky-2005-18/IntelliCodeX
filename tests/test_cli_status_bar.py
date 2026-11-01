"""
Unit tests for the IntelliCodeX dynamic bottom status toolbar.
"""

from unittest.mock import MagicMock
import pytest
from prompt_toolkit.styles import Style

from core.cli.state import CLISessionState
from core.cli.ui.status_bar import (
    render_status_toolbar,
    format_status_summary,
    get_status_toolbar_style,
)


def test_status_toolbar_formatting_offline():
    """Verify plain text summary when running offline with TF-IDF."""
    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=None,
    )
    summary = format_status_summary(state)
    assert "Repo: sample_repo" in summary
    assert "Backend: tfidf" in summary
    assert "offline" in summary.lower()
    assert "Watcher: Inactive" in summary


def test_status_toolbar_returns_formatted_tokens():
    """Verify that render_status_toolbar returns a list of (style, text) tuples."""
    mock_llm = MagicMock()
    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="ollama",
        model_name="qwen2.5-coder:3b",
        embedder=None,
        llm=mock_llm,
        engine=None,
    )
    tokens = render_status_toolbar(state)
    assert isinstance(tokens, list)
    assert len(tokens) > 0
    for token in tokens:
        assert isinstance(token, tuple)
        assert len(token) == 2
        assert isinstance(token[0], str)
        assert isinstance(token[1], str)

    rendered_text = "".join(t[1] for t in tokens)
    assert "qwen2.5-coder:3b" in rendered_text
    assert "ollama" in rendered_text


def test_status_toolbar_token_styling():
    """Verify token styling contains required colors and semantic classes."""
    mock_llm = MagicMock()
    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True

    online_state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="ollama",
        model_name="qwen2.5-coder:3b",
        embedder=None,
        llm=mock_llm,
        engine=None,
        watcher=mock_watcher,
    )

    online_tokens = render_status_toolbar(online_state)

    # Brand styling should contain cyan
    brand_tokens = [t for t in online_tokens if "IntelliCodeX" in t[1]]
    assert len(brand_tokens) > 0
    assert any("cyan" in t[0] for t in brand_tokens)

    # Model styling should contain magenta
    model_tokens = [t for t in online_tokens if "qwen2.5-coder:3b" in t[1]]
    assert len(model_tokens) > 0
    assert any("magenta" in t[0] for t in model_tokens)

    # Online status styling should contain green
    online_status_tokens = [t for t in online_tokens if "online" in t[1].lower()]
    assert len(online_status_tokens) > 0
    assert any("green" in t[0] for t in online_status_tokens)

    # Watcher active styling should contain green
    watcher_active_tokens = [t for t in online_tokens if "Active" in t[1]]
    assert len(watcher_active_tokens) > 0
    assert any("green" in t[0] for t in watcher_active_tokens)

    # Offline state
    offline_state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=None,
        watcher=None,
    )
    offline_tokens = render_status_toolbar(offline_state)

    # Offline status styling should contain yellow
    offline_status_tokens = [t for t in offline_tokens if "offline" in t[1].lower()]
    assert len(offline_status_tokens) > 0
    assert any("yellow" in t[0] for t in offline_status_tokens)


def test_status_toolbar_file_filter_indicator():
    """Verify active_file_filter is shown when present and omitted when None."""
    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=None,
    )

    # Initially None: no Filter indicator
    summary_none = format_status_summary(state)
    tokens_none = render_status_toolbar(state)
    assert "Filter:" not in summary_none
    assert not any("Filter:" in t[1] for t in tokens_none)

    # Set filter: Filter indicator must appear
    state.set_file_filter("core/cli/state.py")
    summary_filtered = format_status_summary(state)
    tokens_filtered = render_status_toolbar(state)
    assert "Filter: core/cli/state.py" in summary_filtered
    assert any("core/cli/state.py" in t[1] for t in tokens_filtered)
    assert any("Filter:" in t[1] for t in tokens_filtered)

    # Clear filter: indicator disappears
    state.set_file_filter(None)
    summary_cleared = format_status_summary(state)
    assert "Filter:" not in summary_cleared


def test_status_toolbar_watcher_active_vs_inactive():
    """Verify watcher badge dynamically reflects active vs inactive status."""
    mock_watcher = MagicMock()
    mock_watcher.is_alive.return_value = True

    state = CLISessionState(
        repo_path="sample_repo",
        repo_id="sample_repo",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=None,
        watcher=mock_watcher,
    )

    summary_active = format_status_summary(state)
    assert "Watcher: Active" in summary_active

    # Watcher stopped
    mock_watcher.is_alive.return_value = False
    summary_stopped = format_status_summary(state)
    assert "Watcher: Inactive" in summary_stopped

    # Watcher set to None
    state.set_watcher(None)
    summary_none = format_status_summary(state)
    assert "Watcher: Inactive" in summary_none


def test_status_toolbar_dynamic_state_updates():
    """Verify status bar reflects state mutations dynamically."""
    state = CLISessionState(
        repo_path="repo_alpha",
        repo_id="repo_alpha_id",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=None,
    )

    # Initial check
    s1 = format_status_summary(state)
    assert "Repo: repo_alpha" in s1
    assert "Backend: tfidf" in s1

    # Switch repo
    state.switch_repo("repo_beta", "repo_beta_id")
    s2 = format_status_summary(state)
    assert "Repo: repo_beta" in s2
    assert "Repo: repo_alpha" not in s2

    # Switch backend & model
    mock_llm = MagicMock()
    state.switch_backend("ollama")
    state.llm = mock_llm
    state.switch_model("deepseek-coder:6.7b")
    s3 = format_status_summary(state)
    assert "Backend: ollama" in s3
    assert "Model: deepseek-coder:6.7b" in s3

    # Set and update persona
    state.set_persona("security")
    s4 = format_status_summary(state)
    assert "Persona: security" in s4


def test_status_toolbar_style_mapping():
    """Verify get_status_toolbar_style returns a valid prompt-toolkit Style dictionary."""
    style_dict = get_status_toolbar_style()
    assert isinstance(style_dict, dict)
    assert "toolbar.brand" in style_dict
    assert "toolbar.model" in style_dict
    assert "toolbar.status.online" in style_dict
    assert "toolbar.status.offline" in style_dict
    assert "toolbar.watcher.on" in style_dict
    assert "toolbar.watcher.off" in style_dict

    # Check that prompt_toolkit Style.from_dict accepts the dictionary
    style = Style.from_dict(style_dict)
    assert style is not None


def test_status_toolbar_indexed_files_count():
    """Verify repo files count is displayed when engine provides indexed files."""
    mock_engine = MagicMock()
    mock_engine.get_indexed_files.return_value = ["a.py", "b.py", "c.py"]

    state = CLISessionState(
        repo_path="my_project",
        repo_id="my_project_123",
        backend="tfidf",
        model_name="none",
        embedder=None,
        llm=None,
        engine=mock_engine,
    )

    summary = format_status_summary(state)
    assert "Repo: my_project (3 files)" in summary
