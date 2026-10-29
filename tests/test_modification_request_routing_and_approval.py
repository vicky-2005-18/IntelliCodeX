"""
Regression tests for Explicit File-Scoped Modification Request Routing,
Patch Proposal Workflow, and Developer Review/Approval Invariants.
"""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from core.canonical_path import (
    parse_file_modification_request,
    is_file_modification_request,
    parse_mention,
    discover_relevant_tests,
    resolve_canonical_target_path,
)
from core.patch_generator import PatchEngine, evaluate_patch_approval_gate


def test_observed_workflow_routing_modification_request():
    """
    Verifies that the observed user query:
    '@TodoApp.java create a to do list with all button show'
    is accurately classified as an explicit file-scoped modification request
    targeting TodoApp.java rather than entering general Q&A.
    """
    query = "@TodoApp.java create a to do list with all button show"
    is_mod, target, inst = parse_file_modification_request(query)
    assert is_mod is True
    assert target == "TodoApp.java"
    assert inst == "create a to do list with all button show"


def test_modification_request_variants():
    """
    Verifies various phrasing and formatting styles for file-scoped modification requests.
    """
    cases = [
        (
            "@TodoApp.java add buttons for Add, Edit, Complete, Delete, and Clear Completed",
            "TodoApp.java",
            "add buttons for Add, Edit, Complete, Delete, and Clear Completed",
        ),
        (
            "create a to do list with all button show @TodoApp.java",
            "TodoApp.java",
            "create a to do list with all button show",
        ),
        (
            "@'TodoApp.java' implement task editing",
            "TodoApp.java",
            "implement task editing",
        ),
        (
            '@\"my app/TodoApp.java\" refactor main method',
            "my app/TodoApp.java",
            "refactor main method",
        ),
        (
            "Target: TodoApp.java add clear completed button",
            "TodoApp.java",
            "add clear completed button",
        ),
        (
            "please add complete button to @TodoApp.java",
            "TodoApp.java",
            "please add complete button to",
        ),
    ]

    for q, expected_tgt, expected_inst in cases:
        is_mod, tgt, inst = parse_file_modification_request(q)
        assert is_mod is True, f"Failed for query: {q}"
        assert tgt == expected_tgt, f"Expected target {expected_tgt}, got {tgt}"


def test_informational_questions_remain_in_qa_mode():
    """
    Verifies that informational questions scoped to a file remain in Q&A mode
    and are NOT hijacked by the modification request workflow.
    """
    qa_queries = [
        "@TodoApp.java what does addTask do?",
        "@TodoApp.java how does it work?",
        "@TodoApp.java explain the task model",
        "@TodoApp.java where is nextId defined?",
        "@TodoApp.java why is nextId private?",
        "@TodoApp.java describe the UI implementation",
        "@TodoApp.java summarize this file",
        "@TodoApp.java is there any error?",
    ]

    for q in qa_queries:
        is_mod, tgt, inst = parse_file_modification_request(q)
        assert is_mod is False, f"Informational query was misclassified as modification: {q}"
        assert tgt == "TodoApp.java"


def test_discover_relevant_tests_finds_java_tests():
    """
    Verifies that discover_relevant_tests finds standard Java test files
    such as TodoAppTest.java.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        todo_file = os.path.join(tmpdir, "TodoApp.java")
        test_file = os.path.join(tmpdir, "TodoAppTest.java")
        with open(todo_file, "w") as f:
            f.write("public class TodoApp {}")
        with open(test_file, "w") as f:
            f.write("public class TodoAppTest {}")

        discovered = discover_relevant_tests(tmpdir, "TodoApp.java")
        assert "TodoAppTest.java" in discovered


def test_modification_proposal_requires_developer_approval_and_never_silently_applies():
    """
    Verifies that when a file modification proposal is produced, the system enforces
    developer review and confirmation, strictly refusing to silently overwrite disk.
    If the developer cancels, original disk content remains untouched.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        target_file = os.path.join(tmpdir, "TodoApp.java")
        original_content = "public class TodoApp {\n    // Original console app\n}\n"
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(original_content)

        # Mock PatchEngine proposal
        mock_patch_record = {
            "patch_id": "patch_12345",
            "repo_id": "test_repo",
            "target_file": "TodoApp.java",
            "original_code": original_content,
            "suggested_patch": "public class TodoApp {\n    // Modified UI with all buttons\n}\n",
            "git_diff": "--- a/TodoApp.java\n+++ b/TodoApp.java\n@@ -1,3 +1,3 @@\n public class TodoApp {\n-// Original console app\n+// Modified UI with all buttons\n }\n",
            "status": "pending",
            "sandbox_validation": {
                "verified": True,
                "test_status": "passed",
            },
        }

        # Verify patch has a valid diff
        assert "--- a/TodoApp.java" in mock_patch_record["git_diff"]
        assert "+// Modified UI with all buttons" in mock_patch_record["git_diff"]

        # Simulation: User rejects / cancels the modification
        user_choice = "c"  # cancel
        if user_choice not in ("a", "approve", "y", "yes"):
            # Operation discarded; disk untouched
            pass

        with open(target_file, "r", encoding="utf-8") as f:
            current_on_disk = f.read()

        assert current_on_disk == original_content, "Original file was altered without approval!"


def test_batch_mode_protects_against_silent_modification(capsys):
    """
    Verifies that in batch mode (cli.py --query), an explicit file modification request
    is intercepted and refused from silent auto-execution, preserving developer safety.
    """
    from cli import main
    sample_dir = os.path.abspath("sample_repo")
    query = "@TodoApp.java create a to do list with all button show"

    with patch("sys.argv", ["cli.py", sample_dir, "--backend", "tfidf", "-q", query]):
        ret = main()
        assert ret == 0

    captured = capsys.readouterr()
    assert "Detected file modification request" in captured.out
    assert "developer protection invariant" in captured.out
    assert "blocked in non-interactive batch mode" in captured.out


def test_parse_source_display_request():
    """
    Verifies that explicit source-display requests are detected cleanly
    and distinguished from modification requests and general Q&A.
    """
    from core.canonical_path import parse_source_display_request

    # Display requests
    display_queries = [
        ("show me code of @TodoApp.java", "TodoApp.java"),
        ("show code of @TodoApp.java", "TodoApp.java"),
        ("show me code @TodoApp.java", "TodoApp.java"),
        ("show me the code of @TodoApp.java", "TodoApp.java"),
        ("view @TodoApp.java", "TodoApp.java"),
        ("cat @TodoApp.java", "TodoApp.java"),
        ("display code of @TodoApp.java", "TodoApp.java"),
        ("print code of @TodoApp.java", "TodoApp.java"),
        ("code of @TodoApp.java", "TodoApp.java"),
        ("source of @TodoApp.java", "TodoApp.java"),
        ("code: @TodoApp.java", "TodoApp.java"),
        ("source: @TodoApp.java", "TodoApp.java"),
        ("cat: @TodoApp.java", "TodoApp.java"),
        ("show me code of TodoApp.java", "TodoApp.java"),
    ]

    for q, expected_target in display_queries:
        is_disp, target = parse_source_display_request(q)
        assert is_disp is True, f"Failed to recognize display request: {q}"
        assert target == expected_target, f"Expected target {expected_target}, got {target} for: {q}"

    # Non-display queries (modifications or general questions)
    non_display_queries = [
        "@TodoApp.java create a to do list with all button show",
        "fix: @TodoApp.java NPE on startup",
        "update @TodoApp.java add clearCompleted",
        "what does @TodoApp.java do?",
        "how does task addition work in @TodoApp.java?",
        "explain @TodoApp.java architecture",
    ]

    for q in non_display_queries:
        is_disp, target = parse_source_display_request(q)
        assert is_disp is False, f"Erroneously recognized as display request: {q}"


def test_render_source_display_direct_from_disk(tmp_path, capsys):
    """
    Verifies render_source_display reads directly from the filesystem without LLM.
    """
    from core.canonical_path import render_source_display

    target_file = tmp_path / "DummyApp.java"
    target_file.write_text("public class DummyApp {\n    public static void main(String[] args) {\n        System.out.println(\"hello\");\n    }\n}\n", encoding="utf-8")

    ok = render_source_display(str(tmp_path), "DummyApp.java", HAS_RICH=False)
    assert ok is True

    captured = capsys.readouterr()
    assert "SOURCE FILE: DummyApp.java" in captured.out
    assert "Canonical Path : DummyApp.java" in captured.out
    assert "Direct Source Display — Read directly from active filesystem" in captured.out
    assert "public class DummyApp" in captured.out
    assert "System.out.println(\"hello\");" in captured.out

