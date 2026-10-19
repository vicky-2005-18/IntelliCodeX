"""
Unit and Integration Tests for IntelliCodeX Code Runner (core/code_runner.py).

Tests:
1. Canonical path resolution & containment (rejects traversal, missing, ambiguous, unsupported).
2. Language detection (Java, Python, JavaScript).
3. Java main class & package extraction.
4. Infrastructure probing (Docker CLI missing, daemon unavailable, container toolchain missing).
5. Sandbox security flags & read-only enforcement.
6. Real Docker execution (Java compilation into /tmp with stdin, Python, JavaScript, compile/runtime error).
7. Missing dependency pattern detection (Python, JS, Java).
8. Ctrl+C trap & guaranteed container cleanup.
9. Repository-scoped activity logging & persistence.
10. Autocomplete and help registration.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.code_runner import (
    build_docker_run_command,
    detect_missing_dependencies,
    detect_run_language,
    execute_run_command,
    extract_java_main_class,
    parse_run_target,
    probe_run_infrastructure,
)
from core.persistence import get_repo_id, load_repo_conversation


class TestCodeRunnerPathAndLanguage(unittest.TestCase):
    """Tests target path resolution, traversal rejection, and language detection."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="icx_test_runner_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_detect_run_language(self):
        self.assertEqual(detect_run_language("TodoApp.java"), "java")
        self.assertEqual(detect_run_language("calculator.py"), "python")
        self.assertEqual(detect_run_language("app.js"), "javascript")
        self.assertEqual(detect_run_language("server.mjs"), "javascript")
        self.assertEqual(detect_run_language("module.cjs"), "javascript")
        self.assertIsNone(detect_run_language("main.cpp"))
        self.assertIsNone(detect_run_language("program.rs"))
        self.assertIsNone(detect_run_language("notes.txt"))

    def test_parse_run_target_valid_files(self):
        py_file = os.path.join(self.test_dir, "calculator.py")
        with open(py_file, "w") as f:
            f.write("print('hello')\n")

        java_file = os.path.join(self.test_dir, "TodoApp.java")
        with open(java_file, "w") as f:
            f.write("public class TodoApp { public static void main(String[] args) {} }\n")

        # Test with @ prefix
        rel, lang, err = parse_run_target("run: @calculator.py", self.test_dir)
        self.assertIsNone(err)
        self.assertEqual(rel, "calculator.py")
        self.assertEqual(lang, "python")

        # Test with run space and without @
        rel, lang, err = parse_run_target("run TodoApp.java", self.test_dir)
        self.assertIsNone(err)
        self.assertEqual(rel, "TodoApp.java")
        self.assertEqual(lang, "java")

    def test_parse_run_target_missing_file(self):
        rel, lang, err = parse_run_target("run: @ghost.py", self.test_dir)
        self.assertIsNone(rel)
        self.assertIsNotNone(err)
        self.assertIn("does not match any file", err)

    def test_parse_run_target_traversal_rejection(self):
        rel, lang, err = parse_run_target("run: @../secret.py", self.test_dir)
        self.assertIsNone(rel)
        self.assertIsNotNone(err)
        self.assertIn("traversal", err.lower())

    def test_parse_run_target_ambiguous_matches(self):
        sub1 = os.path.join(self.test_dir, "pkg1")
        sub2 = os.path.join(self.test_dir, "pkg2")
        os.makedirs(sub1)
        os.makedirs(sub2)
        with open(os.path.join(sub1, "util.py"), "w") as f:
            f.write("# util 1\n")
        with open(os.path.join(sub2, "util.py"), "w") as f:
            f.write("# util 2\n")

        rel, lang, err = parse_run_target("run: @util.py", self.test_dir)
        self.assertIsNone(rel)
        self.assertIsNotNone(err)
        self.assertIn("Ambiguous", err)
        self.assertIn("pkg1/util.py", err)
        self.assertIn("pkg2/util.py", err)

    def test_parse_run_target_unsupported_language(self):
        cpp_file = os.path.join(self.test_dir, "main.cpp")
        with open(cpp_file, "w") as f:
            f.write("int main() { return 0; }\n")

        rel, lang, err = parse_run_target("run: @main.cpp", self.test_dir)
        self.assertIsNone(rel)
        self.assertIsNotNone(err)
        self.assertIn("Unsupported language extension", err)


class TestJavaClassExtraction(unittest.TestCase):
    """Tests Java package and class name extraction for execution."""

    def test_simple_class_no_package(self):
        src = """
        public class TodoApp {
            public static void main(String[] args) {
                System.out.println("Hello");
            }
        }
        """
        self.assertEqual(extract_java_main_class(src, "TodoApp.java"), "TodoApp")

    def test_class_with_package(self):
        src = """
        package com.example.todo;

        import java.util.List;

        public class TodoApp {
            public static void main(String[] args) {}
        }
        """
        self.assertEqual(extract_java_main_class(src, "com/example/todo/TodoApp.java"), "com.example.todo.TodoApp")

    def test_non_public_class_with_main(self):
        src = """
        package demo.app;

        class Calculator {
            public static void main(String[] args) {}
        }
        """
        self.assertEqual(extract_java_main_class(src, "Calculator.java"), "demo.app.Calculator")

    def test_fallback_to_filename(self):
        src = "// just comments\n"
        self.assertEqual(extract_java_main_class(src, "App.java"), "App")


class TestDependencyDetection(unittest.TestCase):
    """Tests pattern matching for missing project dependencies."""

    def test_python_missing_module(self):
        err = "ModuleNotFoundError: No module named 'requests'"
        deps = detect_missing_dependencies(err, "python")
        self.assertEqual(deps, ["requests"])

    def test_python_import_error(self):
        err = "ImportError: cannot import name 'FastAPI' from 'fastapi'"
        deps = detect_missing_dependencies(err, "python")
        self.assertEqual(deps, ["fastapi"])

    def test_javascript_missing_module(self):
        err = "Error: Cannot find module 'express'\nRequire stack:\n- /work/app.js"
        deps = detect_missing_dependencies(err, "javascript")
        self.assertEqual(deps, ["express"])

    def test_java_missing_package(self):
        err = "/work/App.java:1: error: package org.apache.commons.lang3 does not exist"
        deps = detect_missing_dependencies(err, "java")
        self.assertEqual(deps, ["org.apache.commons.lang3"])


class TestSandboxCommandConstruction(unittest.TestCase):
    """Tests Docker command construction and sandbox hardening flags."""

    def test_command_hardening_flags(self):
        docker_cmd, _ = build_docker_run_command(
            repo_path="/test/repo",
            target_rel="calculator.py",
            language="python",
            image="intellicodex-sandbox:latest",
            container_name="icx-test-123",
            is_interactive=False,
        )

        self.assertIn("--network", docker_cmd)
        idx_net = docker_cmd.index("--network")
        self.assertEqual(docker_cmd[idx_net + 1], "none")

        self.assertIn("--read-only", docker_cmd)
        self.assertIn("--tmpfs", docker_cmd)
        idx_tmpfs = docker_cmd.index("--tmpfs")
        self.assertEqual(docker_cmd[idx_tmpfs + 1], "/tmp:rw,exec")

        self.assertIn("--user", docker_cmd)
        idx_user = docker_cmd.index("--user")
        self.assertEqual(docker_cmd[idx_user + 1], "1000:1000")

        self.assertIn("--cap-drop", docker_cmd)
        idx_cap = docker_cmd.index("--cap-drop")
        self.assertEqual(docker_cmd[idx_cap + 1], "ALL")

        self.assertIn("--security-opt", docker_cmd)
        idx_sec = docker_cmd.index("--security-opt")
        self.assertEqual(docker_cmd[idx_sec + 1], "no-new-privileges")

        # Mount is read-only
        v_mount = [arg for arg in docker_cmd if ":/work:ro" in arg]
        self.assertTrue(len(v_mount) > 0, "Source mount must be read-only (:/work:ro)")

        # Privileged must NOT be present
        self.assertNotIn("--privileged", docker_cmd)

    def test_java_compiles_to_tmp(self):
        docker_cmd, container_cmd = build_docker_run_command(
            repo_path="/test/repo",
            target_rel="TodoApp.java",
            language="java",
            image="intellicodex-sandbox:latest",
            container_name="icx-test-java",
            is_interactive=False,
        )
        joined_cmd = " ".join(container_cmd)
        self.assertIn("javac -d /tmp /work/TodoApp.java", joined_cmd)
        self.assertIn("java -cp /tmp", joined_cmd)


class TestInfrastructureProbing(unittest.TestCase):
    """Tests infrastructure probe with Docker available vs missing/failing."""

    @patch("shutil.which", return_value=None)
    def test_docker_cli_missing(self, mock_which):
        infra = probe_run_infrastructure("intellicodex-sandbox:latest", "python")
        self.assertFalse(infra["daemon_available"])
        self.assertIn("executable ('docker') not found", infra["infrastructure_blocker"])

    @patch("shutil.which", return_value="/usr/bin/docker")
    @patch("subprocess.run")
    def test_docker_daemon_unavailable(self, mock_run, mock_which):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "error during connect: daemon not running"
        mock_run.return_value = mock_proc

        infra = probe_run_infrastructure("intellicodex-sandbox:latest", "python")
        self.assertFalse(infra["daemon_available"])
        self.assertIn("Docker daemon unavailable", infra["infrastructure_blocker"])

    @patch("shutil.which", return_value="/usr/bin/docker")
    @patch("subprocess.run")
    def test_docker_image_lacks_javac(self, mock_run, mock_which):
        # 1st call: version -> success
        # 2nd call: javac -> failure
        res_v = MagicMock(returncode=0, stdout="24.0.0\n", stderr="")
        res_jc = MagicMock(returncode=127, stdout="", stderr="javac: command not found")
        mock_run.side_effect = [res_v, res_jc]

        infra = probe_run_infrastructure("custom-image:v1", "java")
        self.assertTrue(infra["daemon_available"])
        self.assertFalse(infra["toolchain_available"])
        self.assertIn("lacks javac compiler", infra["infrastructure_blocker"])


class TestInteractiveExecutionAndLifecycle(unittest.TestCase):
    """Tests execution lifecycle, Ctrl+C handling, and activity logging."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="icx_test_exec_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("core.code_runner.probe_run_infrastructure")
    def test_blocks_on_infrastructure_failure(self, mock_probe):
        mock_probe.return_value = {
            "infrastructure_blocker": "Docker daemon unavailable: connection refused",
            "actionable_guidance": "Start Docker Desktop",
        }
        py_file = os.path.join(self.test_dir, "test.py")
        with open(py_file, "w") as f:
            f.write("print('hello')\n")

        exit_code = execute_run_command("run: @test.py", self.test_dir)
        self.assertEqual(exit_code, 1)

    @patch("core.code_runner.probe_run_infrastructure")
    @patch("subprocess.Popen")
    @patch("subprocess.run")
    def test_ctrl_c_cleans_up_container(self, mock_sub_run, mock_popen, mock_probe):
        mock_probe.return_value = {
            "daemon_available": True,
            "toolchain_available": True,
            "infrastructure_blocker": None,
        }
        py_file = os.path.join(self.test_dir, "loop.py")
        with open(py_file, "w") as f:
            f.write("import time; time.sleep(60)\n")

        mock_proc = MagicMock()
        mock_proc.wait.side_effect = KeyboardInterrupt
        mock_popen.return_value = mock_proc

        exit_code = execute_run_command("run: @loop.py", self.test_dir)
        self.assertEqual(exit_code, 130)

        # Verify docker rm -f was called to remove container
        rm_calls = [
            call for call in mock_sub_run.call_args_list
            if len(call[0]) > 0 and isinstance(call[0][0], list) and call[0][0][:3] == ["docker", "rm", "-f"]
        ]
        self.assertTrue(len(rm_calls) > 0, "Must call 'docker rm -f' on KeyboardInterrupt")

    def test_activity_logging_persistence(self):
        py_file = os.path.join(self.test_dir, "calc.py")
        with open(py_file, "w") as f:
            f.write("print(2 + 2)\n")

        class DummyEngine:
            def __init__(self):
                self.memory = MagicMock()
                self.memory.activities = []

        engine = DummyEngine()

        with patch("core.code_runner.probe_run_infrastructure") as mock_probe, \
             patch("subprocess.run") as mock_run:
            mock_probe.return_value = {
                "daemon_available": True,
                "toolchain_available": True,
                "infrastructure_blocker": None,
                "toolchain_version": "Python 3.11",
            }
            res_exec = MagicMock(returncode=0, stdout="4\n", stderr="")
            mock_run.return_value = res_exec

            exit_code = execute_run_command(
                "run: @calc.py",
                self.test_dir,
                engine=engine,
                auto_input="",
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(engine.memory.activities), 1)
            act = engine.memory.activities[0]
            self.assertEqual(act["activity_type"], "run")
            self.assertEqual(act["target_file"], "calc.py")
            self.assertEqual(act["save_outcome"], "completed")

            # Check persistent database
            repo_id = get_repo_id(self.test_dir)
            _, _, stored_acts = load_repo_conversation(repo_id)
            run_records = [a for a in stored_acts if a["activity_type"] == "run"]
            self.assertEqual(len(run_records), 1)
            self.assertEqual(run_records[0]["target_file"], "calc.py")


class TestRealDockerExecution(unittest.TestCase):
    """
    Real Docker execution tests against live local Docker daemon.
    Skips if Docker daemon is not running.
    """

    @classmethod
    def setUpClass(cls):
        cls.docker_available = False
        try:
            res = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res.returncode == 0 and res.stdout.strip():
                cls.docker_available = True
        except Exception:
            cls.docker_available = False

    def setUp(self):
        if not self.docker_available:
            self.skipTest("Docker daemon not available on host system")
        self.test_dir = tempfile.mkdtemp(prefix="icx_real_docker_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_real_python_execution(self):
        py_file = os.path.join(self.test_dir, "calculator.py")
        with open(py_file, "w") as f:
            f.write("import sys; print(f'PY_CALC_RES: {6 * 7}')\n")

        code = execute_run_command("run: @calculator.py", self.test_dir, auto_input="")
        self.assertEqual(code, 0)

    def test_real_javascript_execution(self):
        js_file = os.path.join(self.test_dir, "app.js")
        with open(js_file, "w") as f:
            f.write("console.log('JS_APP_RES: ' + (100 / 4));\n")

        code = execute_run_command("run: @app.js", self.test_dir, auto_input="")
        self.assertEqual(code, 0)

    def test_real_java_interactive_stdin_execution(self):
        java_file = os.path.join(self.test_dir, "EchoApp.java")
        with open(java_file, "w") as f:
            f.write(
                "import java.util.Scanner;\n"
                "public class EchoApp {\n"
                "    public static void main(String[] args) {\n"
                "        Scanner sc = new Scanner(System.in);\n"
                "        System.out.print('Prompt: ');\n"
                "        String word = sc.nextLine();\n"
                "        System.out.println('ECHO: ' + word.toUpperCase());\n"
                "    }\n"
                "}\n".replace("'", '"')
            )

        code = execute_run_command("run: @EchoApp.java", self.test_dir, auto_input="IntelliCodeX\n")
        self.assertEqual(code, 0)

    def test_real_java_compilation_error_reporting(self):
        bad_java = os.path.join(self.test_dir, "BadApp.java")
        with open(bad_java, "w") as f:
            f.write("public class BadApp { syntax error here }\n")

        code = execute_run_command("run: @BadApp.java", self.test_dir, auto_input="")
        self.assertNotEqual(code, 0)

    def test_real_missing_dependency_reporting(self):
        dep_py = os.path.join(self.test_dir, "needs_dep.py")
        with open(dep_py, "w") as f:
            f.write("import non_existent_library_icx_test_404\n")

        code = execute_run_command("run: @needs_dep.py", self.test_dir, auto_input="")
        self.assertNotEqual(code, 0)


class TestCLIIntegrationAndCompleter(unittest.TestCase):
    """Tests CLI COMMAND_CATEGORIES registration and autocomplete behavior."""

    def test_command_categories_registration(self):
        from cli import COMMAND_CATEGORIES
        search_cmds = COMMAND_CATEGORIES["Search & AI"]["commands"]
        run_entry = [cmd for cmd in search_cmds if cmd[0].startswith("run:")]
        self.assertEqual(len(run_entry), 1)
        self.assertIn("run:", run_entry[0][2])

    def test_completer_yields_matching_files(self):
        from cli import IntelliCodeXCompleter, HAS_PROMPT_TOOLKIT
        if not HAS_PROMPT_TOOLKIT:
            self.skipTest("prompt_toolkit not installed")

        from prompt_toolkit.document import Document

        completer = IntelliCodeXCompleter(
            get_files_fn=lambda: ["TodoApp.java", "calc.py", "app.js", "README.md", "data.csv"]
        )

        doc = Document("run: ")
        completions = [c.text for c in completer.get_completions(doc)]
        self.assertIn("@TodoApp.java", completions)
        self.assertIn("@calc.py", completions)
        self.assertIn("@app.js", completions)
        # Non-runnable files should not be suggested
        self.assertNotIn("@README.md", completions)
        self.assertNotIn("@data.csv", completions)


if __name__ == "__main__":
    unittest.main()

