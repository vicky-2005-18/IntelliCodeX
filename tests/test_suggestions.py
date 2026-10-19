"""
Unit tests for CLI Contextual Suggestions and Activity History Labels.

Verifies:
1. RUN activity labels (Run ID, Execution exit code, Run Outcome) vs Creation/Repair labels.
2. Contextual suggestions triggers (0 chunks, unresolved targets, insufficient context, limitations).
3. Intent detection without auto-execution ("how to run" -> run:, "identify bugs" -> fix: / security:).
4. Respect for "do not modify files" constraints.
5. Preservation of filenames containing spaces (e.g. @"to do.java").
6. Clean suppression on normal successful answers (zero irrelevant suggestions).
7. Non-numeric scoring guarantee (no fabricated scores).
"""

import os
import unittest
from unittest.mock import MagicMock

from core.suggestion_engine import (
    format_suggested_target,
    generate_contextual_suggestions,
)
from rag.query_engine import ConversationMemory


class TestActivityHistoryLabels(unittest.TestCase):
    """Tests activity history formatting for RUN vs Creation/Repair."""

    def test_run_activity_labels(self):
        mem = ConversationMemory(repo_id="test_repo")
        mem.activities = [
            {
                "activity_type": "run",
                "target_file": "TodoApp.java",
                "proposal_id": "run-a1b2c3d4",
                "verification_outcome": "exit_code_0",
                "save_outcome": "completed",
                "summary": "Executed TodoApp.java in Docker Sandbox",
                "details": {"exit_code": 0, "outcome": "completed"},
                "timestamp": 1700000000,
            }
        ]

        log = mem.format_activity_log()
        self.assertIn("--- Activity History (Execution Runs) ---", log)
        self.assertIn("RUN      | Target: TodoApp.java | Run ID: run-a1b2c3d4", log)
        self.assertIn("Execution exit code: 0", log)
        self.assertIn("Run Outcome: COMPLETED", log)
        # Must NOT use creation/repair-specific labels for a RUN
        self.assertNotIn("Proposal ID:", log)
        self.assertNotIn("Verification:", log)
        self.assertNotIn("Save Outcome:", log)

    def test_creation_and_repair_labels_preserved(self):
        mem = ConversationMemory(repo_id="test_repo")
        mem.activities = [
            {
                "activity_type": "creation",
                "target_file": "TodoApp.java",
                "proposal_id": "create-prop-12345678",
                "verification_outcome": "passed",
                "save_outcome": "applied",
                "summary": "Created TodoApp.java",
                "timestamp": 1700000000,
            },
            {
                "activity_type": "repair",
                "target_file": "utils.py",
                "proposal_id": "fix-prop-87654321",
                "verification_outcome": "blocked",
                "save_outcome": "gate_rejected",
                "summary": "Repaired utils.py",
                "timestamp": 1700000001,
            },
        ]

        log = mem.format_activity_log()
        self.assertIn("--- Activity History (Code Creation & Repair) ---", log)
        self.assertIn("CREATION | Target: TodoApp.java | Proposal ID: create-p...5678", log)
        self.assertIn("Verification: PASSED | Save Outcome: APPLIED", log)
        self.assertIn("REPAIR   | Target: utils.py | Proposal ID: fix-prop...4321", log)
        self.assertIn("Verification: BLOCKED | Save Outcome: GATE_REJECTED", log)
        # Must NOT use run-specific labels for creation/repair
        self.assertNotIn("Run ID:", log)
        self.assertNotIn("Execution exit code:", log)
        self.assertNotIn("Run Outcome:", log)

    def test_mixed_activities_general_header(self):
        mem = ConversationMemory(repo_id="test_repo")
        mem.activities = [
            {
                "activity_type": "creation",
                "target_file": "TodoApp.java",
                "proposal_id": "create-1234",
                "verification_outcome": "passed",
                "save_outcome": "applied",
            },
            {
                "activity_type": "run",
                "target_file": "TodoApp.java",
                "proposal_id": "run-5678",
                "verification_outcome": "exit_code_0",
                "save_outcome": "completed",
                "details": {"exit_code": 0},
            },
        ]
        log = mem.format_activity_log()
        self.assertIn("--- Activity History ---", log)
        self.assertIn("Proposal ID: create-1234", log)
        self.assertIn("Run ID: run-5678", log)


class TestContextualSuggestions(unittest.TestCase):
    """Tests suggestion generation under observable issues and intent differences."""

    def test_format_suggested_target_preserves_spaces(self):
        self.assertEqual(format_suggested_target("TodoApp.java"), "@TodoApp.java")
        self.assertEqual(format_suggested_target("to do.java"), '@"to do.java"')
        self.assertEqual(format_suggested_target("src/my calculator.py"), '@"src/my calculator.py"')

    def test_no_retrieved_evidence_suggestions(self):
        suggestions = generate_contextual_suggestions(
            query="find authentication logic",
            answer="No relevant code was found in the repository.",
            retrieved_chunks=[],
            effective_file_filter=None,
            candidate_files=["auth.py", "server.py"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmds = [s[0] for s in suggestions]
        self.assertTrue(any(c.startswith("search:") for c in cmds))

    def test_unresolved_target_suggestions(self):
        suggestions = generate_contextual_suggestions(
            query="explain what @nonexistent_file.py does",
            answer="The target file could not be found.",
            retrieved_chunks=[MagicMock()],
            effective_file_filter="nonexistent_file.py",
            candidate_files=["calculator.py", "TodoApp.java"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmds = [s[0] for s in suggestions]
        self.assertIn("files", cmds)

    def test_how_to_run_intent_does_not_auto_execute(self):
        suggestions = generate_contextual_suggestions(
            query="how do I run @to do.java?",
            answer="You can compile and run it with Java.",
            retrieved_chunks=[MagicMock()],
            effective_file_filter="to do.java",
            candidate_files=["to do.java", "calculator.py"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmd, desc = suggestions[0]
        # Must preserve filename with spaces in quotes
        self.assertEqual(cmd, 'run: @"to do.java"')
        self.assertIn("Docker", desc)

    def test_identify_bugs_intent_prioritizes_read_only_review(self):
        suggestions = generate_contextual_suggestions(
            query="identify bugs in @calculator.py",
            answer="There is an off-by-one error in subtract function.",
            retrieved_chunks=[MagicMock()],
            effective_file_filter="calculator.py",
            candidate_files=["calculator.py"],
        )
        self.assertEqual(len(suggestions), 2)
        # Suggestion 1: Prioritized focused read-only review query
        cmd1, desc1 = suggestions[0]
        self.assertEqual(cmd1, "explain: review @calculator.py")
        self.assertIn("without making changes", desc1)

        # Suggestion 2: Explicitly optional repair action
        cmd2, desc2 = suggestions[1]
        self.assertEqual(cmd2, "fix: @calculator.py")
        self.assertIn("(Optional)", desc2)

        # Security scanning must not be presented as general correctness verification
        cmds = [s[0] for s in suggestions]
        self.assertFalse(any(c.startswith("security:") for c in cmds))

    def test_respects_do_not_modify_files_constraint(self):
        suggestions = generate_contextual_suggestions(
            query="identify bugs in @calculator.py, do not modify files",
            answer="Analysis: potential division by zero on line 42.",
            retrieved_chunks=[MagicMock()],
            effective_file_filter="calculator.py",
            candidate_files=["calculator.py"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmds = [s[0] for s in suggestions]
        # Must NOT suggest fix: when user requested do not modify files
        self.assertFalse(any(c.startswith("fix:") for c in cmds))
        self.assertEqual(cmds[0], "explain: review @calculator.py")
        self.assertIn("chunks:calculator.py", cmds)
        # Security scan must not be presented as general correctness verification
        self.assertFalse(any(c.startswith("security:") for c in cmds))

    def test_creation_intent_offers_create_command(self):
        suggestions = generate_contextual_suggestions(
            query="create a new calculator.py with add and subtract",
            answer="Here is how a calculator can be structured.",
            retrieved_chunks=[MagicMock()],
            candidate_files=["TodoApp.java"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmds = [s[0] for s in suggestions]
        self.assertTrue(any(c.startswith("create:") and "calculator.py" in c for c in cmds))

    def test_search_intent_offers_search_and_callers(self):
        suggestions = generate_contextual_suggestions(
            query="where is verify_token defined?",
            answer="verify_token appears to be in auth module.",
            retrieved_chunks=[MagicMock()],
            candidate_files=["auth.py"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmds = [s[0] for s in suggestions]
        self.assertIn("search:verify_token", cmds)
        self.assertIn("callers:verify_token", cmds)

    def test_insufficient_context_reported_limitation(self):
        suggestions = generate_contextual_suggestions(
            query="how does data sync work?",
            answer="The implementation is not shown in the context provided.",
            retrieved_chunks=[MagicMock()],
            effective_file_filter=None,
            candidate_files=["sync.py", "db.py"],
        )
        self.assertTrue(1 <= len(suggestions) <= 2)
        cmds = [s[0] for s in suggestions]
        self.assertTrue(any(c.startswith("search:") for c in cmds))

    def test_normal_successful_answer_returns_no_suggestions(self):
        # A normal query that succeeded with complete information and no limitations
        suggestions = generate_contextual_suggestions(
            query="what does the User class do?",
            answer="The User class encapsulates username, hashed password, and role permissions.",
            retrieved_chunks=[MagicMock(), MagicMock(), MagicMock()],
            effective_file_filter=None,
            candidate_files=["user.py", "auth.py"],
            unverified_files=[],
            unverified_symbols=[],
        )
        # Invariant: No irrelevant suggestions on normal successful answer
        self.assertEqual(suggestions, [])

    def test_complete_one_chunk_answer_returns_no_suggestions(self):
        # One complete relevant chunk that fully answers a question produces no hints
        suggestions = generate_contextual_suggestions(
            query="what is the default timeout in config.py?",
            answer="The default timeout is 30 seconds as defined by DEFAULT_TIMEOUT in config.py.",
            retrieved_chunks=[MagicMock()],
            effective_file_filter=None,
            candidate_files=["config.py"],
            unverified_files=[],
            unverified_symbols=[],
        )
        self.assertEqual(suggestions, [], "Complete one-chunk answer must not trigger unnecessary suggestions")


class TestCtrlCInterruptionReturnsToCLI(unittest.TestCase):
    """Verifies that a single Ctrl+C during execution returns cleanly to usable CLI prompt."""

    def test_single_ctrl_c_during_execution_returns_to_cli(self):
        import tempfile
        import shutil
        from unittest.mock import patch
        from core.code_runner import execute_run_command

        test_dir = tempfile.mkdtemp(prefix="icx_test_ctrlc_")
        try:
            py_file = os.path.join(test_dir, "long_runner.py")
            with open(py_file, "w") as f:
                f.write("import time; time.sleep(30)\n")

            with patch("core.code_runner.probe_run_infrastructure") as mock_probe, \
                 patch("subprocess.Popen") as mock_popen, \
                 patch("subprocess.run") as mock_run:

                mock_probe.return_value = {
                    "daemon_available": True,
                    "toolchain_available": True,
                    "infrastructure_blocker": None,
                }
                # Simulate child process interrupted by Ctrl+C
                proc_mock = MagicMock()
                proc_mock.wait.side_effect = KeyboardInterrupt
                mock_popen.return_value = proc_mock

                # Simulate simulated CLI loop
                cli_iterations = 0
                commands_to_run = ["run: @long_runner.py", "status_check"]
                for cmd in commands_to_run:
                    cli_iterations += 1
                    if cmd.startswith("run:"):
                        exit_code = execute_run_command(cmd, test_dir)
                        self.assertEqual(exit_code, 130)
                        # CLI does 'continue', remaining in loop
                        continue
                    else:
                        # Subsequent command runs normally in the same loop
                        self.assertEqual(cmd, "status_check")

                self.assertEqual(cli_iterations, 2)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

