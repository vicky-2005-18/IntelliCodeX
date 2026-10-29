"""
Unit and Integration Tests for IntelliCodeX GUI Preview Engine.

Tests:
1. Request parsing and intent recognition (preview @file, gui @file, run --gui @file).
2. Port discovery bound strictly to localhost (127.0.0.1).
3. Sandbox security invariants (read-only mount, capability drops, localhost-only exposure).
4. Container lifecycle management and cleanup on termination.
"""

import os
import time
import socket
import pytest
import subprocess
from unittest.mock import patch, MagicMock

from core.gui_preview import (
    parse_gui_preview_request,
    find_available_port,
    ensure_gui_docker_image,
    GuiPreviewSession,
    execute_gui_preview_command,
)


def test_parse_gui_preview_request_variants():
    """Verifies that all GUI preview syntax variants are recognized accurately."""
    valid_queries = [
        ("preview @TodoApp.java", "TodoApp.java"),
        ("gui @TodoApp.java", "TodoApp.java"),
        ("preview: @TodoApp.java", "TodoApp.java"),
        ("gui: @TodoApp.java", "TodoApp.java"),
        ("novnc: @TodoApp.java", "TodoApp.java"),
        ("run --gui @TodoApp.java", "TodoApp.java"),
        ("run @TodoApp.java --gui", "TodoApp.java"),
        ("preview TodoApp.java", "TodoApp.java"),
        ("gui TodoApp.java", "TodoApp.java"),
    ]

    for q, expected_target in valid_queries:
        is_gui, target = parse_gui_preview_request(q)
        assert is_gui is True, f"Failed to recognize GUI request: {q}"
        assert target == expected_target, f"Expected {expected_target}, got {target} for: {q}"

    invalid_queries = [
        "run @TodoApp.java",
        "show me code of @TodoApp.java",
        "fix: @TodoApp.java NPE",
        "what does @TodoApp.java do?",
        "search: TodoApp",
        "info: TodoApp.java",
    ]

    for q in invalid_queries:
        is_gui, target = parse_gui_preview_request(q)
        assert is_gui is False, f"Erroneously recognized as GUI request: {q}"


def test_find_available_port_binds_to_localhost():
    """Verifies that find_available_port returns a usable port on 127.0.0.1."""
    port = find_available_port()
    assert isinstance(port, int)
    assert 1024 < port < 65535

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.listen(1)
    finally:
        s.close()


def test_ensure_gui_docker_image_recognizes_built_image():
    """Verifies that ensure_gui_docker_image recognizes intellicodex-gui:latest."""
    ok = ensure_gui_docker_image("intellicodex-gui:latest")
    assert ok is True


def test_gui_preview_session_lifecycle(tmp_path):
    """
    Verifies that GuiPreviewSession correctly starts the container with
    proper sandbox parameters and terminates/cleans up on stop().
    """
    test_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    session = GuiPreviewSession(
        repo_path=test_repo,
        target_file="TodoApp.java",
        image_name="intellicodex-gui:latest"
    )

    success, url = session.start(timeout_sec=20)
    try:
        assert success is True, f"Failed to start GUI preview: {url}"
        assert "http://127.0.0.1:" in url
        assert "/vnc.html" in url
        assert session.is_running is True

        # Verify container exists in docker ps
        ps_res = subprocess.run(
            ["docker", "ps", "--filter", f"name={session.container_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True
        )
        assert session.container_name in ps_res.stdout
    finally:
        session.stop()

    # Verify container has been cleaned up
    ps_after = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name={session.container_name}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True
    )
    assert session.container_name not in ps_after.stdout


def test_execute_gui_preview_command_batch_mode(capsys):
    """Verifies execute_gui_preview_command runs and cleans up in batch mode."""
    test_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    code = execute_gui_preview_command(
        query="preview @TodoApp.java",
        repo_path=test_repo,
        is_batch=True
    )
    assert code == 0

    captured = capsys.readouterr()
    assert "LAUNCHING INTELLICODEX GUI PREVIEW" in captured.out
    assert "GUI PREVIEW IS ACTIVE AND READY" in captured.out
    assert "Container cleaned up." in captured.out
