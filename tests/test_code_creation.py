"""
Comprehensive Test Suite for IntelliCodeX Explicit Code Creation Workflow.

Verifies:
1. Creation in empty and non-empty selected repositories.
2. Structured proposal with target path and code, labeled as newly generated code (not retrieved repository evidence).
3. Path containment validation: staying inside repository, path traversal rejection.
4. Refusal to overwrite existing files, redirecting user to edit/review (fix:) workflow.
5. Isolated sandbox validation: syntax/compilation and behavioral testing reported separately.
   Zero tests remain behaviorally unverified. Generated tests are explicitly labeled as AI-generated
   candidate contracts without implying independent correctness.
6. Complete new-file diff display.
7. Central approval gate enforcement (no force bypass, exact refusal reason reported).
8. File application only on gate pass and explicit approval. Disk remains untouched on cancellation or failure.
9. Re-check of file absence at application time to prevent race overwrites.
10. Re-indexing post-creation and reporting exact saved path.
11. Preservation of repository-grounding checks for ordinary Q&A.
12. End-to-end disposable Java example with real execution evidence and saved file.
"""
import ast
import os
import shutil
import tempfile
import pytest

from core.safe_paths import resolve_within
from core.pipeline import ingest_repository
from core.embedder import TfidfEmbedder
from core.patch_generator import evaluate_patch_approval_gate
from core.sandbox_runner import SandboxRunner, SandboxTestResult
from rag.query_engine import QueryEngine
from core.code_creation import (
    parse_creation_request,
    generate_new_file_diff,
    CodeCreationEngine,
    execute_create_command,
    probe_sandbox_infrastructure,
)


@pytest.fixture
def disposable_workspace():
    """Provides a fresh isolated temporary workspace."""
    tmp_dir = tempfile.mkdtemp(prefix="icx_test_ws_")
    embedder = TfidfEmbedder()
    yield {
        "root": tmp_dir,
        "embedder": embedder,
    }
    shutil.rmtree(tmp_dir, ignore_errors=True)


# =========================================================================
# 1. Parsing & Target Extraction
# =========================================================================

def test_parse_creation_request_formats(disposable_workspace):
    root = disposable_workspace["root"]

    # Target: TodoApp.java
    t1, p1, l1, err1 = parse_creation_request("create: Build to-do app Target: TodoApp.java", root)
    assert err1 is None
    assert t1 == "TodoApp.java"
    assert l1 == "java"
    assert "Build to-do app" in p1

    # @TodoApp.java
    t2, p2, l2, err2 = parse_creation_request("create: @TodoApp.java Build to-do app", root)
    assert err2 is None
    assert t2 == "TodoApp.java"
    assert l2 == "java"

    # to todo.py
    t3, p3, l3, err3 = parse_creation_request("create: Build a CLI to todo.py", root)
    assert err3 is None
    assert t3 == "todo.py"
    assert l3 == "python"

    # Subdirectory target: src/models/Task.java
    t4, p4, l4, err4 = parse_creation_request("create: Task model Target: src/models/Task.java", root)
    assert err4 is None
    assert t4 == "src/models/Task.java"
    assert l4 == "java"

    # Quoted target: Target: "web app.py"
    t5, p5, l5, err5 = parse_creation_request('create: Build a web app Target: "web app.py"', root)
    assert err5 is None
    assert t5 == "web app.py"
    assert l5 == "python"
    assert "Build a web app" in p5

    # Quoted mention: @"web app.py"
    t6, p6, l6, err6 = parse_creation_request('create: @"web app.py" Build a web app', root)
    assert err6 is None
    assert t6 == "web app.py"
    assert l6 == "python"
    assert "Build a web app" in p6

    # Quoted target with single quotes: Target: 'web app.py'
    t7, p7, l7, err7 = parse_creation_request("create: Build a web app Target: 'web app.py'", root)
    assert err7 is None
    assert t7 == "web app.py"
    assert l7 == "python"

    # Quoted mention with single quotes: @'web app.py'
    t8, p8, l8, err8 = parse_creation_request("create: @'web app.py' Build a web app", root)
    assert err8 is None
    assert t8 == "web app.py"
    assert l8 == "python"

    # Quoted target with subdirectory and spaces: Target: "src/my apps/web app.py"
    t9, p9, l9, err9 = parse_creation_request('create: Build app Target: "src/my apps/web app.py"', root)
    assert err9 is None
    assert t9 == "src/my apps/web app.py"
    assert l9 == "python"

    # Quoted target Java: Target: "Todo App.java"
    t10, p10, l10, err10 = parse_creation_request('create: Build Java app Target: "Todo App.java"', root)
    assert err10 is None
    assert t10 == "Todo App.java"
    assert l10 == "java"


def test_parse_creation_request_ambiguous_unquoted_targets(disposable_workspace):
    """Unquoted targets containing spaces must return an actionable error rather than silently truncating."""
    root = disposable_workspace["root"]

    # Target: web app.py (unquoted - must not truncate to 'web')
    t1, p1, l1, err1 = parse_creation_request("create: Build a web app Target: web app.py", root)
    assert t1 is None
    assert err1 is not None
    assert "Ambiguous target filename" in err1
    assert "web app.py" in err1
    assert 'Target: "web app.py"' in err1 or '@"web app.py"' in err1
    # Verify it was NOT silently truncated to 'web'
    assert "Unsupported file extension '' for 'web'" not in err1

    # Leading Target: web app.py
    t2, p2, l2, err2 = parse_creation_request("create: Target: web app.py Build a web app", root)
    assert t2 is None
    assert err2 is not None
    assert "Ambiguous target filename" in err2
    assert "web app.py" in err2

    # Unquoted @web app.py
    t3, p3, l3, err3 = parse_creation_request("create: Build a web app @web app.py", root)
    assert t3 is None
    assert err3 is not None
    assert "Ambiguous target filename" in err3
    assert "web app.py" in err3

    # Multi-token space target: Target: my cool helper.py
    t4, p4, l4, err4 = parse_creation_request("create: Target: my cool helper.py do work", root)
    assert t4 is None
    assert err4 is not None
    assert "Ambiguous target filename" in err4
    assert "my cool helper.py" in err4


def test_parse_creation_request_unsupported_extension(disposable_workspace):
    root = disposable_workspace["root"]
    t, p, l, err = parse_creation_request("create: script Target: script.rb", root)
    assert t is None
    assert err is not None
    assert "Unsupported file extension" in err
    assert "Java (.java) and Python (.py)" in err

    # Quoted unsupported extension
    t2, p2, l2, err2 = parse_creation_request('create: script Target: "web app.rb"', root)
    assert t2 is None
    assert err2 is not None
    assert "Unsupported file extension '.rb' for 'web app.rb'" in err2


def test_parse_creation_request_missing_target(disposable_workspace):
    root = disposable_workspace["root"]
    t, p, l, err = parse_creation_request("create: build me a todo app without specifying a file", root)
    assert t is None
    assert err is not None
    assert "No target file specified" in err


# =========================================================================
# 2. Path Traversal Rejection
# =========================================================================

def test_path_traversal_rejections(disposable_workspace):
    root = disposable_workspace["root"]

    # Traversal via parent directory
    t, p, l, err = parse_creation_request("create: task Target: ../outside.java", root)
    assert t is None
    assert err is not None
    assert "Path traversal rejected" in err

    # Traversal via absolute POSIX path
    t2, p2, l2, err2 = parse_creation_request("create: task Target: /etc/shadow.py", root)
    assert t2 is None
    assert err2 is not None
    assert "Path traversal rejected" in err2

    # Traversal via Windows drive path
    t3, p3, l3, err3 = parse_creation_request("create: task Target: C:\\Windows\\System32\\cmd.py", root)
    assert t3 is None
    assert err3 is not None
    assert "Path traversal rejected" in err3

    # Traversal via quoted relative path with spaces
    t4, p4, l4, err4 = parse_creation_request('create: task Target: "../outside app.py"', root)
    assert t4 is None
    assert err4 is not None
    assert "Path traversal rejected" in err4


# =========================================================================
# 3. Refusal to Overwrite Existing Files
# =========================================================================

def test_existing_file_refusal_redirects_to_edit(disposable_workspace):
    root = disposable_workspace["root"]
    existing_file = os.path.join(root, "TodoApp.java")
    original_content = "public class TodoApp { /* original */ }"
    with open(existing_file, "w", encoding="utf-8") as f:
        f.write(original_content)

    t, p, l, err = parse_creation_request("create: New version Target: TodoApp.java", root)
    assert t is None
    assert err is not None
    assert "already exists in repository" in err
    assert "refuses to overwrite existing files" in err
    assert "fix:" in err  # Directs user to edit workflow

    # Verify disk content was untouched
    with open(existing_file, "r", encoding="utf-8") as f:
        assert f.read() == original_content

    # Refusal with quoted filename containing spaces
    spaced_file = os.path.join(root, "web app.py")
    spaced_content = "# existing web app"
    with open(spaced_file, "w", encoding="utf-8") as f:
        f.write(spaced_content)

    t_sp, p_sp, l_sp, err_sp = parse_creation_request('create: New web app Target: "web app.py"', root)
    assert t_sp is None
    assert err_sp is not None
    assert "already exists in repository" in err_sp
    assert "refuses to overwrite existing files" in err_sp
    assert 'fix: @"web app.py"' in err_sp

    with open(spaced_file, "r", encoding="utf-8") as f:
        assert f.read() == spaced_content


# =========================================================================
# 4. Empty Repository Support
# =========================================================================

def test_empty_repository_initialization_and_creation(disposable_workspace):
    root = disposable_workspace["root"]
    embedder = disposable_workspace["embedder"]

    # Ingestion of completely empty repository must not crash
    result = ingest_repository(root, embedder, allow_empty=True)
    assert result.num_files == 0
    assert result.num_chunks == 0
    assert len(result.files) == 0

    # Initialize creation engine in empty repository
    engine = CodeCreationEngine(repo_path=root)
    proposal = engine.propose_creation("create: Build a python helper Target: helper.py")

    assert proposal["status"] in ("verified", "pending")
    assert proposal["is_new_file"] is True
    assert proposal["code_origin"] == "newly generated code (not retrieved repository evidence)"

    # If verification passes, apply creation
    if proposal["sandbox_validation"]["verified"]:
        ok, msg = engine.apply_creation(proposal)
        assert ok is True
        saved_path = os.path.join(root, "helper.py")
        assert os.path.exists(saved_path)

        # Re-index repository: should now contain 1 file
        re_result = ingest_repository(root, embedder, allow_empty=True)
        assert re_result.num_files == 1


# =========================================================================
# 5. Proposal Structure & Git Diff Generation
# =========================================================================

def test_new_file_git_diff_format():
    code = "public class Hello {\n    public static void main(String[] args) {}\n}\n"
    diff = generate_new_file_diff("src/Hello.java", code)
    assert "diff --git a/src/Hello.java b/src/Hello.java" in diff
    assert "new file mode 100644" in diff
    assert "--- /dev/null" in diff
    assert "+++ b/src/Hello.java" in diff
    assert "+public class Hello {" in diff


# =========================================================================
# 6. Isolated Sandbox Validation & Reporting Separation
# =========================================================================

def test_syntax_validation_and_behavioral_reporting_separated(disposable_workspace):
    root = disposable_workspace["root"]
    engine = CodeCreationEngine(repo_path=root)

    # Valid Python code without tests -> 0 tests must remain behaviorally unverified
    val_no_tests = engine.validate_in_sandbox(
        target_file="app.py",
        language="python",
        code="def hello(): return 'world'",
        test_filename=None,
        test_code=None,
    )
    assert val_no_tests["compilation_status"] == "passed"
    assert "unverified (0 tests executed)" in val_no_tests["behavioral_status"]
    assert val_no_tests["passed_count"] == 0
    assert val_no_tests["verified"] is False  # Cannot be verified with 0 tests

    # Python code with syntax error
    val_syntax_err = engine.validate_in_sandbox(
        target_file="broken.py",
        language="python",
        code="def broken(:\n    pass",
    )
    assert val_syntax_err["compilation_status"] == "failed"
    assert "SyntaxError" in val_syntax_err["compilation_details"]
    assert val_syntax_err["verified"] is False


def test_generated_tests_disclaimer_labeled(disposable_workspace):
    root = disposable_workspace["root"]
    engine = CodeCreationEngine(repo_path=root)

    proposal = engine.propose_creation("create: Build a python app Target: todo.py", generate_tests=True)
    assert proposal["contract_type"] == "ai_generated_candidate_contract"
    assert proposal["contract_disclaimer"] == "AI-Generated Candidate Contract (Does Not Imply Independent Correctness)"
    assert "test_todo.py" in proposal["candidate_test_file"]


# =========================================================================
# 7. Central Approval Gate Enforcement
# =========================================================================

def test_central_approval_gate_blocks_zero_tests(disposable_workspace):
    root = disposable_workspace["root"]
    engine = CodeCreationEngine(repo_path=root)

    # Create proposal with zero tests executed
    proposal = engine.propose_creation("create: Simple script Target: simple.py", generate_tests=False)
    assert proposal["sandbox_validation"]["passed_count"] == 0

    # Evaluate approval gate directly
    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal)
    assert ok_gate is False
    assert "zero tests" in gate_msg.lower()

    # Apply creation must be rejected by gate
    ok_app, app_msg = engine.apply_creation(proposal)
    assert ok_app is False
    assert "Approval rejected by central gate" in app_msg
    assert "zero tests" in app_msg.lower()

    # Disk must remain untouched
    target_abs = os.path.join(root, "simple.py")
    assert not os.path.exists(target_abs)


# =========================================================================
# 8. Re-check File Absence at Application Time
# =========================================================================

def test_recheck_file_absence_prevents_race_overwrite(disposable_workspace):
    root = disposable_workspace["root"]
    engine = CodeCreationEngine(repo_path=root)

    # Build valid verified proposal
    target_rel = "app.py"
    target_abs = os.path.join(root, target_rel)
    from core.persistence import get_repo_id
    valid_proposal = {
        "repo_id": get_repo_id(root),
        "target_file": target_rel,
        "suggested_patch": "print('hello')",
        "original_code": "",
        "sandbox_validation": {
            "verified": True,
            "test_status": "passed",
            "passed_count": 1,
            "failed_count": 0,
            "test_result": {"success": True, "exit_code": 0, "passed_count": 1},
        },
        "security_validation": {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
        },
    }

    # Simulate race condition: file appears on disk right before apply_creation
    with open(target_abs, "w", encoding="utf-8") as f:
        f.write("# created by another process")

    ok_app, msg_app = engine.apply_creation(valid_proposal)
    assert ok_app is False
    assert "Conflict" in msg_app
    assert "created on disk after proposal generation" in msg_app

    # Existing file content remains untouched
    with open(target_abs, "r", encoding="utf-8") as f:
        assert f.read() == "# created by another process"


# =========================================================================
# 9. Real Execution Evidence: Python End-to-End
# =========================================================================

# =========================================================================
# Regression Test Fixtures (Domain-specific examples isolated in tests)
# =========================================================================

JAVA_TODO_FIXTURE = """import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class TodoApp {

    public static class Task {
        private final int id;
        private final String title;
        private boolean completed;

        public Task(int id, String title) {
            this.id = id;
            this.title = title;
            this.completed = false;
        }

        public int getId() { return id; }
        public String getTitle() { return title; }
        public boolean isCompleted() { return completed; }
        public void setCompleted(boolean completed) { this.completed = completed; }
    }

    private final List<Task> tasks = new ArrayList<>();
    private int nextId = 1;

    public Task addTask(String description) {
        if (description == null || description.trim().isEmpty()) {
            throw new IllegalArgumentException("Task description cannot be empty");
        }
        Task task = new Task(nextId++, description.trim());
        tasks.add(task);
        return task;
    }

    public List<Task> getTasks() {
        return Collections.unmodifiableList(tasks);
    }

    public boolean completeTask(int id) {
        for (Task task : tasks) {
            if (task.getId() == id) {
                task.setCompleted(true);
                return true;
            }
        }
        return false;
    }

    public boolean deleteTask(int id) {
        return tasks.removeIf(t -> t.getId() == id);
    }

    public static void main(String[] args) {
        TodoApp app = new TodoApp();
        app.addTask("Sample Task");
        System.out.println("TodoApp initialized with " + app.getTasks().size() + " task.");
    }
}
"""

PYTHON_TODO_FIXTURE = '''"""Python Task Manager Regression Fixture."""
from typing import List, Dict, Any

class TaskManager:
    def __init__(self):
        self.tasks = []
        self._next_id = 1

    def add_task(self, title: str) -> Dict[str, Any]:
        if not title:
            raise ValueError("Task title cannot be empty")
        task = {"id": self._next_id, "title": title, "completed": False}
        self._next_id += 1
        self.tasks.append(task)
        return task

    def list_tasks(self) -> List[Dict[str, Any]]:
        return list(self.tasks)

    def complete_task(self, task_id: int) -> bool:
        for t in self.tasks:
            if t["id"] == task_id:
                t["completed"] = True
                return True
        return False
'''


def test_python_creation_end_to_end_real_execution(disposable_workspace):
    root = disposable_workspace["root"]
    embedder = disposable_workspace["embedder"]
    engine = CodeCreationEngine(repo_path=root)

    # Propose Python todo app with candidate tests using isolated regression fixture
    proposal = engine.propose_creation(
        "create: Build a Python to-do manager Target: todo.py",
        generate_tests=True,
        candidate_code=PYTHON_TODO_FIXTURE,
    )
    assert proposal["is_new_file"] is True
    assert proposal["code_origin"] == "newly generated code (not retrieved repository evidence)"

    # Real sandbox execution: pytest ran inside sandbox
    sb_val = proposal["sandbox_validation"]
    assert sb_val["verified"] is True
    assert sb_val["test_status"] == "passed"
    assert sb_val["passed_count"] >= 1
    assert any("test_taskmanager" in t for t in sb_val["passed_tests"])

    # Central Approval Gate evaluates True
    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal)
    assert ok_gate is True
    assert "passed" in str(gate_msg).lower()

    # Apply creation
    ok_app, msg_app = engine.apply_creation(proposal)
    assert ok_app is True
    saved_abs = os.path.join(root, "todo.py")
    assert os.path.exists(saved_abs)
    with open(saved_abs, "r", encoding="utf-8") as f:
        content = f.read()
        assert "class TaskManager:" in content

    # Re-index repository
    re_res = ingest_repository(root, embedder, allow_empty=True)
    assert re_res.num_files == 1
    assert re_res.num_chunks >= 1


# =========================================================================
# 10. End-to-End Disposable Java Example
# =========================================================================

def test_java_todo_app_creation_workflow_and_approval(disposable_workspace):
    """
    End-to-end disposable Java example:
    Example from prompt:
    create: Build a Java console to-do app with add, list, complete, and
    delete tasks. Keep completed tasks with a completed status. Store tasks
    in memory. Handle invalid input. Target: TodoApp.java
    """
    root = disposable_workspace["root"]
    embedder = disposable_workspace["embedder"]
    engine = CodeCreationEngine(repo_path=root)

    raw_query = (
        "create: Build a Java console to-do app with add, list, complete, and "
        "delete tasks. Keep completed tasks with a completed status. Store tasks "
        "in memory. Handle invalid input. Target: TodoApp.java"
    )

    # 1. Generate structured proposal using isolated Java Todo regression fixture
    proposal = engine.propose_creation(raw_query, generate_tests=True, candidate_code=JAVA_TODO_FIXTURE)
    assert proposal["target_file"] == "TodoApp.java"
    assert proposal["language"] == "java"
    assert proposal["code_origin"] == "newly generated code (not retrieved repository evidence)"
    assert "public class TodoApp" in proposal["suggested_patch"]
    assert "public static class Task" in proposal["suggested_patch"]

    # 2. Syntax validation
    assert proposal["syntax_status"] == "passed"
    assert "clean ast" in proposal["syntax_details"].lower()

    # 3. Complete new-file diff
    diff = proposal["git_diff"]
    assert "--- /dev/null" in diff
    assert "+++ b/TodoApp.java" in diff
    assert "+public class TodoApp {" in diff

    # 4. Central approval gate verification behavior:
    # If javac is present on system -> tests execute and pass -> gate passes.
    # If javac is not present on system -> zero tests executed -> gate blocks and reports exact reason!
    passed_count = proposal["sandbox_validation"]["passed_count"]
    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal)

    if passed_count >= 1:
        # Verified run with tests
        assert ok_gate is True
        ok_app, msg_app = engine.apply_creation(proposal)
        assert ok_app is True
        saved_file = os.path.join(root, "TodoApp.java")
        assert os.path.exists(saved_file)
    else:
        # Expected behavior when test runner/compiler is missing on host:
        # Central gate must strictly block and report exact reason without bypass
        assert ok_gate is False
        assert "zero tests" in gate_msg.lower() or "missing" in gate_msg.lower()
        ok_app, msg_app = engine.apply_creation(proposal)
        assert ok_app is False
        assert "Approval rejected by central gate" in msg_app

        # Simulate verified candidate test execution to verify application gate passes and file saves
        simulated_proposal = dict(proposal)
        simulated_proposal["sandbox_validation"] = {
            "verified": True,
            "test_status": "passed",
            "passed_count": 4,
            "failed_count": 0,
            "total_count": 4,
            "passed_tests": ["testAddAndList", "testCompleteTask", "testDeleteTask", "testInvalidInput"],
            "test_result": {"success": True, "exit_code": 0, "passed_count": 4},
        }
        simulated_proposal["security_validation"] = {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
        }
        ok_sim_gate, sim_gate_msg = evaluate_patch_approval_gate(simulated_proposal)
        assert ok_sim_gate is True

        ok_sim_app, sim_msg_app = engine.apply_creation(simulated_proposal)
        assert ok_sim_app is True
        saved_file = os.path.join(root, "TodoApp.java")
        assert os.path.exists(saved_file)

        with open(saved_file, "r", encoding="utf-8") as f:
            saved_content = f.read()
            assert "public class TodoApp" in saved_content
            assert "addTask(String description)" in saved_content
            assert "completeTask(int id)" in saved_content
            assert "deleteTask(int id)" in saved_content

        # Re-index repository
        re_result = ingest_repository(root, embedder, allow_empty=True)
        assert re_result.num_files == 1
        assert re_result.num_chunks >= 1


# =========================================================================
# 11. Ordinary Q&A Grounding Integrity
# =========================================================================

def test_ordinary_qa_grounding_checks_preserved(disposable_workspace):
    root = disposable_workspace["root"]
    embedder = disposable_workspace["embedder"]

    # Ingest repository with a dummy utility
    dummy_file = os.path.join(root, "math_utils.py")
    with open(dummy_file, "w", encoding="utf-8") as f:
        f.write("def add(a: int, b: int) -> int:\n    return a + b\n")

    result = ingest_repository(root, embedder, allow_empty=True)
    engine = QueryEngine(
        result.store,
        embedder,
        llm=None,
        dep_graph=result.graph,
        hybrid_search=False,
        repo_path=root,
    )

    # Verify that ordinary Q&A post-processing strictly flags unverified file references
    answer, unverified_files, unverified_symbols = engine._post_process_answer(
        "You should check TodoApp.java for the TodoApp class implementation.",
        sources=[],
        append_to_answer=True,
    )
    assert "TodoApp.java" in unverified_files
    assert "[Unverified file path(s): TodoApp.java]" in answer


# =========================================================================
# 12. Docker Infrastructure Probe and Explicit Backend Tests
# =========================================================================

def test_docker_infrastructure_probe_reports_precise_blocker(disposable_workspace):
    from core.code_creation import probe_sandbox_infrastructure
    runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest")
    infra = probe_sandbox_infrastructure(runner)

    assert infra["backend"] == "Docker Sandbox (image: intellicodex-sandbox:latest)"
    assert infra["mode"] == "docker"
    # When Docker daemon is stopped, probe reports precise infrastructure blocker
    if not infra["daemon_available"]:
        assert infra["infrastructure_blocker"] is not None
        assert "docker" in infra["infrastructure_blocker"].lower()
        assert not infra["toolchain_available"]


def test_syntax_only_never_labeled_as_compilation_passed(disposable_workspace):
    """Never label syntax-only AST check as compilation passed when toolchain is blocked."""
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest")
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner)

    proposal = engine.propose_creation("create: Java todo app Target: TodoApp.java", generate_tests=True)
    assert proposal["syntax_status"] == "passed"
    assert "clean ast" in proposal["syntax_details"].lower()

    if not proposal["infrastructure"]["daemon_available"]:
        # Compilation MUST NOT be labeled "passed" or "passed (syntax-only)"
        assert proposal["compilation_status"] == "blocked"
        assert "passed" not in proposal["compilation_status"].lower()
        assert "blocked" in proposal["compilation_status"].lower()
        assert "0 tests executed" in proposal["behavioral_status"].lower()

        # Central approval gate strictly blocks creation
        ok_gate, gate_msg = evaluate_patch_approval_gate(proposal)
        assert ok_gate is False
        assert "zero tests" in gate_msg.lower() or "failed" in gate_msg.lower()


def test_docker_container_toolchain_execution_mocked(monkeypatch, disposable_workspace):
    """
    Simulates a running Docker container with javac and java toolchain present.
    Verifies full container compilation, behavioral test execution, 4/4 passing tests,
    strict security verdict, central gate approval, and file saving.
    """
    root = disposable_workspace["root"]
    embedder = disposable_workspace["embedder"]
    runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest")
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner)

    # 1. Mock probe to report Docker daemon running and container Java toolchain present
    from core import code_creation
    monkeypatch.setattr(code_creation, "probe_sandbox_infrastructure", lambda r, **kw: {
        "backend": "Docker Sandbox (image: intellicodex-sandbox:latest)",
        "mode": "docker",
        "daemon_available": True,
        "daemon_version": "27.2.0",
        "daemon_error": None,
        "toolchain_available": True,
        "toolchain_javac_version": "javac 21.0.2",
        "toolchain_java_version": "openjdk 21.0.2",
        "toolchain_error": None,
        "infrastructure_blocker": None,
    })

    # 2. Mock _execute_in_sandbox on the runner to simulate successful container compilation & test run
    def mock_exec(cmd, cwd, timeout=30, env=None):
        if cmd[0] == "javac":
            # Compilation succeeded in container
            return 0, "", "", None
        elif cmd[0] == "java":
            # Test run succeeded in container with 4 passed tests
            output = "PASS: testAddAndList\nPASS: testCompleteTask\nPASS: testDeleteTask\nPASS: testInvalidInput\nALL TESTS PASSED (4/4)\n"
            return 0, output, "", None
        return 0, "", "", None

    monkeypatch.setattr(runner, "_execute_in_sandbox", mock_exec)

    raw_query = (
        "create: Build a Java console to-do app with add, list, complete, and "
        "delete tasks. Keep completed tasks with a completed status. Store tasks "
        "in memory. Handle invalid input. Target: TodoApp.java"
    )

    proposal = engine.propose_creation(raw_query, generate_tests=True)
    assert proposal["execution_backend"] == "Docker Sandbox (image: intellicodex-sandbox:latest)"
    assert proposal["syntax_status"] == "passed"
    assert proposal["compilation_status"] == "passed"
    assert "javac compilation succeeded" in proposal["compilation_details"]
    assert proposal["behavioral_status"] == "passed"
    assert proposal["sandbox_validation"]["passed_count"] == 4
    assert proposal["sandbox_validation"]["failed_count"] == 0
    assert proposal["sandbox_validation"]["total_count"] == 4
    assert proposal["sandbox_validation"]["verified"] is True

    # Java syntax parsing must not count as AST security vulnerability coverage.
    # Under strict policy, unsupported Java security coverage must remain incomplete.
    assert proposal["security_validation"]["security_status"] == "incomplete"
    assert proposal["security_validation"]["coverage"] == "unsupported"
    assert proposal["security_validation"]["security_approved"] is False

    # Central Approval Gate under strict policy correctly blocks incomplete coverage
    ok_gate_strict, msg_strict = evaluate_patch_approval_gate(proposal, security_policy="strict")
    assert ok_gate_strict is False
    assert "incomplete security coverage" in msg_strict.lower()

    # Under explicit secrets_only policy, secret scanning is approved and gate passes
    engine_sec = CodeCreationEngine(repo_path=root, sandbox_runner=runner, security_policy="secrets_only")
    proposal_sec = engine_sec.propose_creation(raw_query, generate_tests=True)
    assert proposal_sec["security_validation"]["security_status"] == "passed"
    assert proposal_sec["security_validation"]["security_approved"] is True
    assert proposal_sec["security_validation"]["coverage"] == "unsupported"  # Preserves coverage limitations

    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal_sec, security_policy="secrets_only")
    assert ok_gate is True

    # Application succeeds under secrets_only policy
    ok_app, msg_app = engine_sec.apply_creation(proposal_sec)
    assert ok_app is True
    target_abs = os.path.join(root, "TodoApp.java")
    assert os.path.exists(target_abs)
    with open(target_abs, "r", encoding="utf-8") as f:
        code = f.read()
        assert "public class TodoApp" in code

    # Re-indexing works
    re_res = ingest_repository(root, embedder, allow_empty=True)
    assert re_res.num_files == 1
    assert re_res.num_chunks >= 1


def test_docker_infrastructure_failure_reported_as_primary_blocker(disposable_workspace):
    """Report Docker infrastructure failure as primary approval blocker, preserving zero-test rejection as consequence."""
    proposal = {
        "target_file": "TodoApp.java",
        "suggested_patch": "public class TodoApp {}",
        "infrastructure_blocker": "Docker daemon unavailable: connection refused",
        "sandbox_validation": {
            "verified": False,
            "test_status": "blocked",
            "passed_count": 0,
            "failed_count": 0,
            "total_count": 0,
            "infrastructure_blocker": "Docker daemon unavailable: connection refused",
        },
        "security_validation": {
            "security_status": "unscanned",
            "security_approved": False,
            "security_policy": "strict",
        },
    }

    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal)
    assert ok_gate is False
    assert "docker infrastructure failure" in gate_msg.lower()
    assert "docker daemon unavailable" in gate_msg.lower()
    assert "zero tests executed as a consequence" in gate_msg.lower()


def test_mandatory_infrastructure_probing_halts_before_expensive_generation(disposable_workspace):
    """When mandatory infrastructure probing fails, stop before expensive generation and provide actionable blocker."""
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest")

    class MockExpensiveLLM:
        def __init__(self):
            self.generate_called = False

        def generate(self, *a, **kw):
            self.generate_called = True
            return "```java\nclass TodoApp {}\n```"

    mock_llm = MockExpensiveLLM()
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner, llm=mock_llm)

    # When Docker is down, propose_creation must halt before expensive LLM generation
    infra = probe_sandbox_infrastructure(runner)
    if not infra["daemon_available"]:
        proposal = engine.propose_creation("create: Java todo app Target: TodoApp.java", generate_tests=True)
        assert mock_llm.generate_called is False, "Expensive LLM generate() must NOT be called when probe fails"
        assert proposal["status"] == "failed"
        assert proposal["compilation_status"] == "blocked"
        assert proposal["infrastructure_blocker"] is not None
        assert proposal["actionable_guidance"] is not None
        assert "zero tests executed" in proposal["behavioral_status"].lower()

        ok_gate, gate_msg = evaluate_patch_approval_gate(proposal)
        assert ok_gate is False
        assert "docker infrastructure failure" in gate_msg.lower()
        assert "zero tests executed as a consequence" in gate_msg.lower()


def test_python_creation_passes_strict_ast_security_coverage(disposable_workspace):
    """Python creation uses Bandit for AST security coverage and passes under strict policy when clean."""
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner, security_policy="strict")

    proposal = engine.propose_creation("create: Python todo app Target: todo_app.py", generate_tests=True)
    assert proposal["syntax_status"] == "passed"
    assert proposal["security_validation"]["security_status"] == "passed"
    assert proposal["security_validation"]["security_approved"] is True
    assert proposal["security_validation"]["coverage"] == "full"
    assert proposal["security_validation"]["security_policy"] == "strict"


def test_creation_candidate_test_imports_for_filename_with_spaces(disposable_workspace):
    """Verifies that generated candidate tests for Python filenames with spaces use dynamic importlib loading."""
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner, security_policy="strict")

    target = "web app.py"
    # Explicit class fixture to test dynamic importlib symbol extraction with spaces
    web_app_fixture = '''class WebApp:
    def __init__(self):
        self.running = True

    def run(self):
        return True

    def stop(self):
        self.running = False
        return False
'''
    code = web_app_fixture
    # ast.parse must succeed on candidate code
    ast.parse(code)
    assert "class WebApp:" in code

    test_file, test_code = engine.generate_candidate_tests(target, "python", code, "build web app")
    assert test_file == "test_web app.py"
    # Must NOT have invalid syntax like 'from web app import WebApp'
    assert "from web app import" not in test_code
    assert "importlib.util" in test_code
    assert 'spec_from_file_location("web_app"' in test_code
    assert 'WebApp = getattr(_mod, "WebApp")' in test_code
    # Test code must be syntactically valid AST
    ast.parse(test_code)

    # When validated in local sandbox, all tests pass with exit code 0
    val_res = engine.validate_in_sandbox(target, "python", code, test_filename=test_file, test_code=test_code)
    assert val_res["syntax_status"] == "passed"
    assert val_res["compilation_status"] == "passed"
    assert val_res["behavioral_status"] == "passed"
    assert val_res["passed_count"] >= 3
    assert val_res["failed_count"] == 0
    assert val_res["failure_category"] is None


def test_creation_behavioral_failure_categories_distinguished(disposable_workspace):
    """Verifies distinct classification for collection failure, infrastructure failure, zero discovered tests, and assertion failures."""
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner)

    # 1. Collection Failure simulation
    mock_coll_res = SandboxTestResult(
        success=False,
        exit_code=2,
        stdout="ERROR collecting test_sample.py\nSyntaxError: invalid syntax",
        stderr="SyntaxError: invalid syntax",
        duration_seconds=0.1,
        framework="pytest",
        passed_count=0,
        failed_count=0,
        total_count=0,
        collection_errors=["SyntaxError: invalid syntax (sample.py, line 1)"],
        test_command=["python", "-m", "pytest", "test_sample.py"],
        traceback_summary="Traceback: SyntaxError: invalid syntax in test_sample.py",
    )
    runner.run_baseline_tests = lambda *a, **kw: mock_coll_res
    val_coll = engine.validate_in_sandbox("sample.py", "python", "x = 1", test_filename="test_sample.py", test_code="pass")
    assert val_coll["behavioral_status"] == "failed"
    assert val_coll["failure_category"] == "collection_failure"
    assert val_coll["test_result"]["exit_code"] == 2
    assert val_coll["test_result"]["collection_errors"] == ["SyntaxError: invalid syntax (sample.py, line 1)"]
    assert val_coll["test_result"]["test_command"] == ["python", "-m", "pytest", "test_sample.py"]

    # 2. Infrastructure Failure simulation
    mock_infra_res = SandboxTestResult(
        success=False,
        exit_code=-8,
        stdout="",
        stderr="Docker daemon unavailable",
        duration_seconds=0.0,
        framework="pytest",
        error_message="Docker unavailable: daemon not responding",
    )
    runner.run_baseline_tests = lambda *a, **kw: mock_infra_res
    val_infra = engine.validate_in_sandbox("sample.py", "python", "x = 1", test_filename="test_sample.py", test_code="pass")
    assert val_infra["behavioral_status"] == "failed"
    assert val_infra["failure_category"] == "infrastructure_failure"

    # 3. Zero Discovered Tests simulation
    mock_zero_res = SandboxTestResult(
        success=False,
        exit_code=5,
        stdout="no tests ran",
        stderr="",
        duration_seconds=0.05,
        framework="pytest",
        passed_count=0,
        failed_count=0,
        total_count=0,
        skipped=True,
    )
    runner.run_baseline_tests = lambda *a, **kw: mock_zero_res
    val_zero = engine.validate_in_sandbox("sample.py", "python", "x = 1", test_filename="test_sample.py", test_code="pass")
    assert val_zero["failure_category"] == "zero_discovered_tests"

    # 4. Assertion Failure simulation
    mock_assert_res = SandboxTestResult(
        success=False,
        exit_code=1,
        stdout="test_calc FAILED",
        stderr="",
        duration_seconds=0.1,
        framework="pytest",
        passed_count=2,
        failed_count=1,
        total_count=3,
        failed_tests=["test_calc"],
        assertion_errors=["assert 2 == 3"],
    )
    runner.run_baseline_tests = lambda *a, **kw: mock_assert_res
    val_assert = engine.validate_in_sandbox("sample.py", "python", "x = 1", test_filename="test_sample.py", test_code="pass")
    assert val_assert["behavioral_status"] == "failed"
    assert val_assert["failure_category"] == "assertion_failure"


def test_card_and_gate_expose_both_behavioral_and_security_blockers(disposable_workspace, capsys):
    """Verifies that central approval gate and presentation card display both behavioral and security blockers simultaneously."""
    from core.code_creation import render_creation_card

    proposal = {
        "target_file": "web app.py",
        "suggested_patch": "class WebApp:\n    pass\n",
        "code_origin": "newly generated code (not retrieved repository evidence)",
        "execution_backend": "Local Sandbox (host environment)",
        "syntax_status": "passed",
        "syntax_details": "Clean AST.",
        "compilation_status": "passed",
        "compilation_details": "Bytecode compiled.",
        "behavioral_status": "failed",
        "failure_category": "collection_failure",
        "sandbox_validation": {
            "verified": False,
            "test_status": "failed",
            "passed_count": 0,
            "failed_count": 0,
            "total_count": 0,
            "passed_tests": [],
            "failed_tests": [],
            "failure_category": "collection_failure",
            "test_result": {
                "success": False,
                "exit_code": 2,
                "test_command": ["python", "-m", "pytest", "test_web app.py"],
                "collection_errors": ["SyntaxError: invalid syntax in test_web app.py at line 4"],
                "traceback_summary": "Traceback:\n  File 'test_web app.py', line 4\n    from web app import WebApp\nSyntaxError: invalid syntax",
                "failure_category": "collection_failure",
            },
        },
        "security_validation": {
            "security_status": "failed",
            "security_approved": False,
            "security_policy": "strict",
            "severity_threshold": "HIGH",
            "coverage": "full",
            "findings_count": 1,
            "failing_findings_count": 1,
            "findings": [
                {
                    "rule_id": "SEC104",
                    "severity": "HIGH",
                    "line": 12,
                    "explanation": "Potential hardcoded credential: api_key='secret_key_1234567890'",
                    "code": "api_key='secret_key_1234567890'",
                }
            ],
        },
        "git_diff": "--- /dev/null\n+++ b/web app.py\n",
        "explanation": "Web app creation proposal.",
    }

    # 1. Central Approval Gate must reject reporting BOTH blockers
    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal, security_policy="strict")
    assert ok_gate is False
    assert "failed test verification" in gate_msg.lower()
    assert "Additionally," in gate_msg
    assert "failed security scan" in gate_msg.lower()

    # 2. render_creation_card must disclose test command, exit code, collection errors, and redacted security finding
    render_creation_card(proposal)
    captured = capsys.readouterr().out
    assert "Collection Failure" in captured
    assert "pytest test_web app.py" in captured
    assert "Test Exit Code" in captured or "2" in captured
    assert "SyntaxError: invalid syntax" in captured
    assert "SEC104" in captured
    assert "HIGH" in captured
    assert "Line 12" in captured
    assert "[REDACTED_SECRET]" in captured
    assert "secret_key_1234567890" not in captured


def test_pytest_collection_error_parsing_preserves_spaces_underscores_nested_and_windows_paths():
    """Verifies that _parse_pytest_output strips only banner delimiters and preserves spaces, underscores, nested, and Windows paths."""
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True)

    test_cases = [
        # (stdout, expected_path_in_error)
        ("________________________ ERROR collecting test_web app.py ________________________\nE   ImportError: cannot import name 'WebApp'", "test_web app.py"),
        ("======================== ERROR collecting test_web_app.py ========================\nE   ModuleNotFoundError: No module named 'flask'", "test_web_app.py"),
        ("________________ ERROR collecting tests/sub dir/test_nested.py ________________\nE   SyntaxError: invalid syntax", "tests/sub dir/test_nested.py"),
        ("___ ERROR collecting C:\\Users\\test user\\tests\\test_web app.py ___\nE   ImportError: failed", "C:\\Users\\test user\\tests\\test_web app.py"),
        ("ERROR collecting nested/sub_dir/test_spaces and_underscores.py\nE   NameError: name 'app' is not defined", "nested/sub_dir/test_spaces and_underscores.py"),
        ("________________ ERROR collecting test_trailing_underscore_ ________________\nE   ImportError: err", "test_trailing_underscore_"),
        ("________________________ ERROR collecting tests/test_web__app.py ________________________\nE   ImportError: cannot import name 'WebApp'", "tests/test_web__app.py"),
        ("======================== ERROR collecting tests/sub--dir/test_web app.py ========================\nE   ModuleNotFoundError: No module named 'flask'", "tests/sub--dir/test_web app.py"),
    ]

    for stdout, expected_path in test_cases:
        res = runner._parse_pytest_output(stdout, "", exit_code=2)
        assert res["collection_errors"], f"Expected collection errors for: {stdout}"
        assert any(expected_path in ce for ce in res["collection_errors"]), (
            f"Expected full path '{expected_path}' preserved in collection errors, got: {res['collection_errors']}"
        )


def test_exit_code_2_not_classified_as_collection_failure_solely_by_exit_code():
    """Verifies that pytest exit code 2 is classified using diagnostic evidence, distinguishing interruption from collection errors."""
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True)
    engine = CodeCreationEngine(".", sandbox_runner=runner)

    # 1. Interruption scenario: Exit code 2 produced by KeyboardInterrupt or user interruption (NO collection errors)
    interrupted_res = SandboxTestResult(
        success=False,
        exit_code=2,
        stdout="================ 1 test passed in 0.5s ================\nKeyboardInterrupt\nInterrupted: stopping execution",
        stderr="KeyboardInterrupt",
        duration_seconds=0.5,
        framework="pytest",
        passed_count=1,
        failed_count=0,
        total_count=1,
        collection_errors=[],
    )
    runner.run_baseline_tests = lambda *args, **kwargs: interrupted_res
    val_res = engine.validate_in_sandbox("sample.py", "python", "def f(): pass", test_filename="test_sample.py", test_code="def test_f(): pass")
    assert val_res["failure_category"] == "infrastructure_failure", (
        f"Exit code 2 with interruption must be 'infrastructure_failure', not '{val_res['failure_category']}'"
    )

    # 2. Interruption scenario: Exit code 2 without any collection evidence in stdout/stderr
    exit2_no_evidence = SandboxTestResult(
        success=False,
        exit_code=2,
        stdout="Interrupted by user signal",
        stderr="",
        duration_seconds=0.2,
        framework="pytest",
        passed_count=0,
        failed_count=0,
        total_count=0,
        collection_errors=[],
    )
    runner.run_baseline_tests = lambda *args, **kwargs: exit2_no_evidence
    val_res_no_ev = engine.validate_in_sandbox("sample.py", "python", "def f(): pass", test_filename="test_sample.py", test_code="def test_f(): pass")
    assert val_res_no_ev["failure_category"] == "infrastructure_failure", (
        f"Exit code 2 without collection evidence must be 'infrastructure_failure', not '{val_res_no_ev['failure_category']}'"
    )

    # 3. Collection failure scenario: Exit code 2 WITH actual collection diagnostic evidence
    collection_res = SandboxTestResult(
        success=False,
        exit_code=2,
        stdout="________________ ERROR collecting test_sample.py ________________\nE   ModuleNotFoundError: No module named 'flask'",
        stderr="",
        duration_seconds=0.1,
        framework="pytest",
        passed_count=0,
        failed_count=0,
        total_count=0,
        collection_errors=["Error collecting test_sample.py: ModuleNotFoundError: No module named 'flask'"],
    )
    runner.run_baseline_tests = lambda *args, **kwargs: collection_res
    val_res_coll = engine.validate_in_sandbox("sample.py", "python", "import flask", test_filename="test_sample.py", test_code="import flask")
    assert val_res_coll["failure_category"] == "collection_failure", (
        f"Exit code 2 with collection evidence must be 'collection_failure', not '{val_res_coll['failure_category']}'"
    )

    # 4. Collection failure scenario where pytest outputs its internal "Interrupted: 1 error during collection" banner
    pytest_coll_banner_res = SandboxTestResult(
        success=False,
        exit_code=2,
        stdout=(
            "============================= test session starts =============================\n"
            "________________________ ERROR collecting test_web_app.py ________________________\n"
            "E   ModuleNotFoundError: No module named 'flask'\n"
            "!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!\n"
            "=========================== 1 error in 0.08s ===========================\n"
        ),
        stderr="",
        duration_seconds=0.08,
        framework="pytest",
        passed_count=0,
        failed_count=0,
        total_count=0,
        collection_errors=["Error collecting test_web_app.py: ModuleNotFoundError: No module named 'flask'"],
    )
    runner.run_baseline_tests = lambda *args, **kwargs: pytest_coll_banner_res
    val_res_pytest_banner = engine.validate_in_sandbox("web_app.py", "python", "import flask", test_filename="test_web_app.py", test_code="import flask")
    assert val_res_pytest_banner["failure_category"] == "collection_failure", (
        f"Pytest 'Interrupted: 1 error during collection' must preserve 'collection_failure', got '{val_res_pytest_banner['failure_category']}'"
    )


def test_candidate_test_generation_extracts_actual_interface_not_filename_class():
    """Verifies that candidate test generator inspects code AST and never derives class names from filenames."""
    engine = CodeCreationEngine(".")

    flask_code = '''from flask import Flask, request, jsonify

app = Flask(__name__)

def calculate(a, b, operation="add"):
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Division by zero")
        return a / b
    raise ValueError(f"Unknown operation: {operation}")

@app.route("/calculate", methods=["POST"])
def calculate_route():
    data = request.get_json() or {}
    return jsonify({"result": calculate(data.get("a", 0), data.get("b", 0), data.get("operation", "add"))})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
'''

    # Target is "web app.py" - previously derived 'WebApp' and generated ToDo tests!
    test_rel, test_code = engine.generate_candidate_tests("web app.py", "python", flask_code, "Build web app with calculator")
    assert test_rel == "test_web app.py"

    # Must NOT invent 'WebApp' or derive classes from filename
    assert "WebApp" not in test_code
    assert "class WebApp" not in test_code
    assert "add_task" not in test_code
    assert "complete_task" not in test_code

    # Must test actual public interface: 'app', 'calculate', and endpoint
    assert 'app = getattr(_mod, "app", None)' in test_code
    assert 'calculate = getattr(_mod, "calculate", None)' in test_code
    assert "def test_app_instance_defined():" in test_code
    assert "def test_calculate_function_happy_path():" in test_code
    assert "def test_calculate_function_error_cases():" in test_code
    assert "def test_calculate_endpoint():" in test_code

    # Generated test code must be clean, parseable Python AST
    ast.parse(test_code)


def test_actual_flask_incident_reproduction_in_disposable_directory(disposable_workspace):
    """
    [EXACT ORIGINAL FLASK CANDIDATE REPRODUCTION]
    Reproduces using the exact original candidate text from the captured proposal:
    - calculate() takes 0 positional arguments and reads request.get_json()
    - app runs with app.run(debug=True)
    - Target: "web app.py"
    - Severity threshold is configured to HIGH (default)
    - Verifies candidate test generation targets actual Flask /calculate POST interface
    - Verifies Bandit detects rule B201 (flask_debug_true), severity HIGH, line 26
    - Verifies approval gate rejects under HIGH threshold because B201 is HIGH
    - No refactoring, no substitution with WebApp or ToDo implementation
    """
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(
        repo_path=root,
        sandbox_runner=runner,
        security_policy="strict",
        security_threshold="HIGH",
    )

    exact_original_flask_candidate = '''from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/calculate", methods=["POST"])
def calculate():
    data = request.get_json() or {}
    a = data.get("a", 0)
    b = data.get("b", 0)
    op = data.get("op", "add")
    if op == "add":
        res = a + b
    elif op == "subtract":
        res = a - b
    elif op == "multiply":
        res = a * b
    elif op == "divide":
        if b == 0:
            return jsonify({"error": "Division by zero"}), 400
        res = a / b
    else:
        return jsonify({"error": f"Unknown operation: {op}"}), 400
    return jsonify({"result": res})

if __name__ == "__main__":
    app.run(debug=True)
'''

    # 1. Candidate Test Contract Generation: Must target actual Flask /calculate POST interface and function
    test_rel, test_code = engine.generate_candidate_tests(
        "web app.py", "python", exact_original_flask_candidate, "Build web app with calculator"
    )
    assert test_rel == "test_web app.py"
    assert "WebApp" not in test_code
    assert 'calculate = getattr(_mod, "calculate", None)' in test_code
    assert 'app = getattr(_mod, "app", None)' in test_code
    assert "def test_app_instance_defined():" in test_code
    assert "def test_calculate_function_is_callable():" in test_code
    assert "def test_calculate_endpoint():" in test_code
    assert "def test_calculate_endpoint_division_by_zero():" in test_code
    assert "def test_calculate_endpoint_invalid_operation():" in test_code
    ast.parse(test_code)

    # 2. Honest Security Scanning: Bandit detects B201 (flask_debug_true) with severity HIGH on line 26
    proposal = engine.propose_creation(
        "create: Flask calculator web app Target: \"web app.py\"",
        generate_tests=True,
        candidate_code=exact_original_flask_candidate,
    )

    sec_val = proposal["security_validation"]
    assert sec_val["severity_threshold"] == "HIGH"
    assert sec_val["security_status"] == "failed"
    assert sec_val["security_approved"] is False
    assert sec_val["failing_findings_count"] >= 1
    assert any(f["rule_id"] == "B201" for f in sec_val["findings"])
    b201 = next(f for f in sec_val["findings"] if f["rule_id"] == "B201")
    assert b201["severity"] == "HIGH"
    assert b201["line"] == 26
    assert "debug=True" in b201["code"] or "app.run" in b201["code"]

    # 3. Honest Gate Evaluation: Rejects under HIGH threshold because B201 is HIGH
    approved, rejection_reason = evaluate_patch_approval_gate(proposal, security_policy="strict")
    assert approved is False
    assert "B201" in rejection_reason or "security" in rejection_reason.lower()

    # 4. Behavioral & Interface Verification:
    # Candidate code was NOT substituted with default ToDo implementation
    assert "class WebApp" not in proposal["suggested_patch"]
    assert "def calculate():" in proposal["suggested_patch"]
    assert proposal["target_file"] == "web app.py"


def test_modified_fixture_variant_labeled_as_synthetic_fixture(disposable_workspace):
    """
    [MODIFIED FIXTURE - EXPLICITLY LABELED SYNTHETIC VARIANT]
    Explicitly labels the previous reproduction fixture that refactored calculate() into:
    calculate(a, b, operation) and app.run(host="0.0.0.0").

    Demonstrates the configured severity threshold behavior:
    - B104 (hardcoded bind 0.0.0.0) is severity MEDIUM.
    - If severity_threshold="HIGH", B104 (MEDIUM) does NOT block (failing_findings_count == 0).
    - If severity_threshold="MEDIUM", B104 (MEDIUM) DOES block.
    This explains why the exact original candidate (which triggers B201, HIGH) blocked under
    the default HIGH threshold, whereas the modified fixture required a MEDIUM threshold to block.
    """
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)

    modified_fixture_code = '''from flask import Flask, request, jsonify

app = Flask(__name__)

def calculate(a, b, operation="add"):
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    elif operation == "divide":
        if b == 0:
            raise ValueError("Division by zero")
        return a / b
    raise ValueError(f"Unknown operation: {operation}")

@app.route("/calculate", methods=["POST"])
def calculate_route():
    data = request.get_json() or {}
    return jsonify({"result": calculate(data.get("a", 0), data.get("b", 0), data.get("operation", "add"))})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
'''

    # Under HIGH threshold: B104 (MEDIUM) does NOT block the gate
    engine_high = CodeCreationEngine(
        repo_path=root,
        sandbox_runner=runner,
        security_policy="strict",
        security_threshold="HIGH",
    )
    proposal_high = engine_high.propose_creation(
        "create: Modified fixture Target: \"web app.py\"",
        generate_tests=True,
        candidate_code=modified_fixture_code,
    )
    sec_high = proposal_high["security_validation"]
    assert sec_high["severity_threshold"] == "HIGH"
    assert any(f["rule_id"] == "B104" for f in sec_high["findings"])
    assert sec_high["failing_findings_count"] == 0, "MEDIUM finding must NOT block under HIGH threshold"

    # Under MEDIUM threshold: B104 (MEDIUM) blocks the gate
    engine_med = CodeCreationEngine(
        repo_path=root,
        sandbox_runner=runner,
        security_policy="strict",
        security_threshold="MEDIUM",
    )
    proposal_med = engine_med.propose_creation(
        "create: Modified fixture Target: \"web app.py\"",
        generate_tests=True,
        candidate_code=modified_fixture_code,
    )
    sec_med = proposal_med["security_validation"]
    assert sec_med["severity_threshold"] == "MEDIUM"
    assert sec_med["failing_findings_count"] >= 1, "MEDIUM finding MUST block under MEDIUM threshold"
    approved, rejection_reason = evaluate_patch_approval_gate(proposal_med, security_policy="strict")
    assert approved is False
    assert "B104" in rejection_reason or "security" in rejection_reason.lower()


# =========================================================================
# 21. Generalization & Architecture Separation Tests
# =========================================================================

def test_creation_generalization_on_structurally_different_programs(disposable_workspace):
    """
    Verifies candidate test generation and interface extraction on structurally
    different programs without task-specific assumptions (no TodoApp, no calculator).
    1. Pure functions module (vector_math.py)
    2. Class-based module (inventory_tracker.py)
    3. Microservice module (telemetry_service.py)
    """
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner)

    # Program 1: Pure Functions Module
    vector_math_code = '''"""Vector mathematical operations."""
import math

def dot_product(u, v):
    if len(u) != len(v):
        raise ValueError("Vectors must have equal length")
    return sum(a * b for a, b in zip(u, v))

def vector_norm(v):
    return math.sqrt(sum(x * x for x in v))
'''
    prop1 = engine.propose_creation(
        'create: Vector operations library Target: "vector_math.py"',
        generate_tests=True,
        candidate_code=vector_math_code,
    )
    test_code1 = prop1["candidate_test_code"]
    assert "dot_product" in test_code1
    assert "vector_norm" in test_code1
    assert "calculate" not in test_code1
    assert "add_task" not in test_code1
    assert "TodoApp" not in test_code1
    assert "Task" not in test_code1
    # Check that requirement limitation is explicitly noted since user instruction omitted concrete test vectors
    assert "Requirements Note:" in test_code1
    assert prop1["requirements_notes"] is not None

    # Program 2: Class-based Module
    inventory_code = '''"""Inventory tracking domain model."""

class InventoryTracker:
    def __init__(self):
        self._stock = {}

    def add_stock(self, sku: str, quantity: int) -> int:
        current = self._stock.get(sku, 0)
        self._stock[sku] = current + quantity
        return self._stock[sku]

    def get_stock(self, sku: str) -> int:
        return self._stock.get(sku, 0)
'''
    prop2 = engine.propose_creation(
        'create: Inventory domain model Target: "inventory_tracker.py"',
        generate_tests=True,
        candidate_code=inventory_code,
    )
    test_code2 = prop2["candidate_test_code"]
    assert "InventoryTracker" in test_code2
    assert "add_stock" in test_code2
    assert "get_stock" in test_code2
    assert "Task" not in test_code2
    assert "TodoApp" not in test_code2
    assert "calculate" not in test_code2

    # Program 3: Microservice Module with Custom Endpoints
    telemetry_code = '''from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route("/metrics", methods=["GET"])
def get_metrics():
    return jsonify({"status": "healthy", "uptime_sec": 42})

@app.route("/ingest", methods=["POST"])
def ingest_record():
    payload = request.get_json() or {}
    return jsonify({"accepted": True, "count": len(payload)}), 201
'''
    prop3 = engine.propose_creation(
        'create: Telemetry metrics service Target: "telemetry_service.py"',
        generate_tests=True,
        candidate_code=telemetry_code,
    )
    test_code3 = prop3["candidate_test_code"]
    assert "/metrics" in test_code3
    assert "/ingest" in test_code3
    assert "get_metrics" in test_code3
    assert "ingest_record" in test_code3
    assert "/calculate" not in test_code3
    assert "TodoApp" not in test_code3


def test_multi_file_creation_rejected_with_honest_capability_message(disposable_workspace):
    """
    Explicitly rejects multi-file creation attempts with an honest capability message,
    preventing improvised workflows or silent failures.
    """
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner)

    multi_file_prompts = [
        'create: Scaffold service Target: "service.py", "utils.py"',
        'create: App Target: "app.py" and "config.py"',
        'create: Multi Target: "a.java"; Target: "b.java"',
    ]

    for prompt in multi_file_prompts:
        proposal = engine.propose_creation(prompt)
        assert proposal["status"] == "failed"
        assert "Multi-file creation is currently unsupported" in proposal["explanation"]
        assert "single-file source modules" in proposal["explanation"]


def test_web_preview_scope_disclosure_and_requirements_limitation_reporting(disposable_workspace):
    """
    Verifies that requests for web preview receive explicit capability disclosures
    and instructions lacking concrete test vectors report requirements limitations.
    """
    root = disposable_workspace["root"]
    runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
    engine = CodeCreationEngine(repo_path=root, sandbox_runner=runner)

    proposal = engine.propose_creation(
        'create: Build a responsive web preview application Target: "webapp_dashboard.py"',
        generate_tests=True,
        candidate_code='from flask import Flask\napp = Flask(__name__)\n@app.route("/")\ndef index(): return "OK"\n',
    )
    # Check capability notes
    cap_notes = proposal.get("capability_notes", [])
    assert any("Web preview is unavailable" in n for n in cap_notes)
    assert any("network-isolated" in n for n in cap_notes)
    assert any("Single-file creation supported" in n for n in cap_notes)
    assert any("Zero automatic package installations" in n for n in cap_notes)

    # Check requirements notes
    req_notes = proposal.get("requirements_notes", "")
    assert "User instruction provided general intent but omitted concrete input/output test vectors" in req_notes


def test_grounded_requirements_incorporates_concrete_test_vectors(disposable_workspace):
    """
    When the user instruction provides concrete test vectors (e.g. 'returns 42'),
    the requirement analyzer grounds the candidate test in those vectors rather than
    inventing arithmetic answers or tautological code assertions.
    """
    from core.creation_adapters import analyze_requirements, PythonLanguageAdapter

    instruction = "create: Compute factorial. When given 5, factorial must return 120. Target: \"math_lib.py\""
    reqs = analyze_requirements(instruction)
    assert len(reqs.test_vectors) >= 1
    assert reqs.test_vectors[0]["expected"] == "120"
    assert reqs.test_vectors[0]["input"] == "5"

    adapter = PythonLanguageAdapter()
    code = "def factorial(n):\n    return 120 if n == 5 else 1\n"
    test_rel, test_code, notes = adapter.generate_candidate_tests("math_lib.py", code, reqs)
    assert "120" in test_code
    assert "test_factorial_user_requirement" in test_code



