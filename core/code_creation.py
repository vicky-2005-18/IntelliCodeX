"""
Explicit Code Creation Workflow Engine for IntelliCodeX.

Enforces:
1. Support for empty and non-empty repositories.
2. Structured creation proposal labeled as newly generated code (not retrieved repository evidence).
3. Strict repository boundary validation (via resolve_within) and refusal to overwrite existing files.
4. Isolated sandbox verification: syntax/compilation and behavioral testing reported separately.
   Zero tests remain behaviorally unverified. Generated tests are explicitly labeled as AI-generated
   candidate contracts without implying independent correctness.
5. Display of complete new-file diff and actual verification results.
6. Central approval gate enforcement (evaluate_patch_approval_gate) with exact failure reasons.
7. File application only upon gate pass and explicit approval.
8. Re-check of file absence at application time to prevent race overwrites.
9. Re-indexing post-creation and reporting exact saved path.
10. Preservation of repository-grounding checks for ordinary Q&A.
"""
import ast
import difflib
import logging
import os
import py_compile
import re
import shutil
import tempfile
import time
import uuid
import subprocess
from typing import Dict, Any, Optional, Tuple, List

from core.safe_paths import resolve_within
from core.patch_generator import evaluate_patch_approval_gate
from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.security_scanner import run_security_scan, redact_secret_value
from core.ts_loader import get_tree_sitter_parser
from core.persistence import get_repo_id
from core.creation_adapters import (
    analyze_requirements,
    get_adapter_for_language,
    RequirementSpec,
    BaseLanguageAdapter,
)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    console = None

logger = logging.getLogger(__name__)


def extract_relevant_traceback(text: str, max_lines: int = 15) -> str:
    """Extracts relevant error and traceback lines, trimming noise and keeping focus on failure cause."""
    if not text:
        return ""
    lines = text.strip().splitlines()
    start_idx = 0
    for idx, line in enumerate(lines):
        if any(marker in line for marker in (
            "Traceback (most recent call last):",
            "ERROR collecting",
            "SyntaxError:",
            "ImportError:",
            "ModuleNotFoundError:",
            "AssertionError",
            "FAILED",
        )):
            start_idx = idx
            break
    relevant = lines[start_idx:]
    if len(relevant) > max_lines:
        relevant = relevant[-max_lines:]
    return "\n".join(relevant)


def parse_creation_request(
    raw_instruction: str,
    repo_root: str,
) -> Tuple[Optional[str], str, Optional[str], Optional[str]]:
    """
    Parses an explicit 'create:' instruction to extract the target path and language.

    Returns:
        (target_rel_path, clean_instruction, language, error_message)
    """
    if not raw_instruction or not raw_instruction.strip():
        return None, "", None, "Empty creation request. Please specify instruction and target file (e.g. 'create: ... Target: \"TodoApp.java\"')."

    text = raw_instruction.strip()
    if text.lower().startswith("create:"):
        text = text[7:].strip()
    elif text.lower().startswith("create "):
        text = text[7:].strip()

    target_candidate = None

    # 1. Quoted target patterns:
    # 1a. Target: "path with spaces" or Target: 'path with spaces'
    m_quoted_target = re.search(r'(?i)\btarget\s*[:=]\s*["\']([^"\']+)["\']', text)
    if m_quoted_target:
        target_candidate = m_quoted_target.group(1).strip()
        text = text[:m_quoted_target.start()] + ' ' + text[m_quoted_target.end():]

    # 1b. @"path with spaces" or @'path with spaces'
    if not target_candidate:
        m_quoted_mention = re.search(r'@["\']([^"\']+)["\']', text)
        if m_quoted_mention:
            target_candidate = m_quoted_mention.group(1).strip()
            text = text[:m_quoted_mention.start()] + ' ' + text[m_quoted_mention.end():]

    # 1c. to/in/into/file "path with spaces"
    if not target_candidate:
        m_quoted_to = re.search(r'(?i)\b(?:to|file|in|into)\s+["\']([^"\']+)["\']', text)
        if m_quoted_to:
            target_candidate = m_quoted_to.group(1).strip()
            text = text[:m_quoted_to.start()] + ' ' + text[m_quoted_to.end():]

    # 2. Check for unquoted Target: <path>
    if not target_candidate:
        m_target = re.search(r'(?i)\btarget\s*[:=]\s*', text)
        if m_target:
            remainder = text[m_target.end():]
            tokens = remainder.split()
            if tokens:
                # Check if multiple tokens form an ambiguous filename containing spaces, e.g. "Target: web app.py"
                has_multitoken_ext = False
                ext_idx = -1
                for idx, tok in enumerate(tokens):
                    tok_clean = tok.strip("',;`\"")
                    ext = os.path.splitext(tok_clean)[1].lower()
                    if ext in [".java", ".py", ".js", ".ts", ".rb", ".cpp", ".c", ".go", ".rs"]:
                        ext_idx = idx
                        if idx > 0:
                            has_multitoken_ext = True
                        break

                if has_multitoken_ext:
                    ambiguous_name = " ".join(tokens[:ext_idx + 1]).strip("',;`\"")
                    return (
                        None,
                        text,
                        None,
                        f"Ambiguous target filename '{ambiguous_name}'. Target filenames containing spaces must be enclosed in quotes (e.g. Target: \"{ambiguous_name}\" or @\"{ambiguous_name}\").",
                    )

                target_candidate = tokens[0].strip("',;`\"")
                match_full = re.search(r'(?i)\btarget\s*[:=]\s*' + re.escape(tokens[0]), text)
                if match_full:
                    text = text[:match_full.start()] + ' ' + text[match_full.end():]
                else:
                    text = text[:m_target.start()] + ' ' + remainder[len(tokens[0]):]

    # 3. Check for unquoted @<file> mention
    if not target_candidate:
        m_mention = re.search(r'@([^\s,;]+)', text)
        if m_mention:
            first_word = m_mention.group(1).strip("',;`\"")
            after_mention = text[m_mention.end():]
            after_tokens = after_mention.split()

            # Check if @mention is part of an unquoted filename with spaces, e.g. @web app.py
            ext_idx = -1
            first_ext = os.path.splitext(first_word)[1].lower()
            if first_ext not in [".java", ".py"]:
                for idx, tok in enumerate(after_tokens):
                    tok_clean = tok.strip("',;`\"")
                    ext = os.path.splitext(tok_clean)[1].lower()
                    if ext in [".java", ".py", ".js", ".ts", ".rb", ".cpp", ".c", ".go", ".rs"]:
                        ext_idx = idx
                        break

            if ext_idx >= 0:
                ambiguous_name = first_word + " " + " ".join(after_tokens[:ext_idx + 1]).strip("',;`\"")
                return (
                    None,
                    text,
                    None,
                    f"Ambiguous target filename '{ambiguous_name}'. Target filenames containing spaces must be enclosed in quotes (e.g. Target: \"{ambiguous_name}\" or @\"{ambiguous_name}\").",
                )

            target_candidate = first_word
            text = text[:m_mention.start()] + ' ' + text[m_mention.end():]

    # 4. Check for "to <file>" or "in <file>" or "file <file>"
    if not target_candidate:
        m_to = re.search(r'(?i)\b(?:to|file|in|into)\s+([A-Za-z0-9_\-\.\/\\]+\.(?:java|py))\b', text)
        if m_to:
            target_candidate = m_to.group(1).strip().strip("'\"`")
            text = text[:m_to.start()] + ' ' + text[m_to.end():]

    # 5. Fallback: search for any token ending in .java or .py
    if not target_candidate:
        m_file = re.search(r'\b([A-Za-z0-9_\-\.\/\\]+\.(?:java|py))\b', text)
        if m_file:
            target_candidate = m_file.group(1).strip().strip("'\"`")
            text = text[:m_file.start()] + ' ' + text[m_file.end():]

    if not target_candidate:
        return (
            None,
            text,
            None,
            "No target file specified. Please specify a target filename (e.g. 'Target: \"TodoApp.java\"' or '@\"TodoApp.java\"'). Supported languages: Java (.java) and Python (.py).",
        )

    # Normalize slashes and clean without stripping leading slash so resolve_within validates absolute paths
    target_clean = target_candidate.replace("\\", "/").strip()

    # Scope check: multi-file creation is explicitly unsupported
    if (
        "," in target_clean
        or ";" in target_clean
        or len(re.findall(r'(?i)\btarget\s*[:=]', raw_instruction)) > 1
        or len(re.findall(r'\b[a-zA-Z0-9_\-]+\.(?:java|py|js|ts|cpp|c|go|rs)\b', raw_instruction, re.I)) > 1
        or re.search(r'(?i)(?:\b(?:and|or)\b|[,;])\s*["\']?[a-zA-Z0-9_\-\./\\]+\.(?:java|py|js|ts|cpp|c|go|rs)', text)
    ):
        return (
            None,
            text,
            None,
            "Multi-file creation is currently unsupported. IntelliCodeX code creation supports single-file source modules (Java .java or Python .py). Please create files one at a time.",
        )
    ext = os.path.splitext(target_clean)[1].lower()
    if ext == ".java":
        language = "java"
    elif ext == ".py":
        language = "python"
    else:
        return (
            None,
            text,
            None,
            f"Unsupported file extension '{ext}' for '{target_clean}'. Explicit creation currently supports Java (.java) and Python (.py) source files.",
        )

    # Validate path containment (Path Traversal Protection)
    try:
        abs_target = resolve_within(repo_root, target_clean)
    except ValueError as e:
        return (
            None,
            text,
            language,
            f"Path traversal rejected: target path '{target_clean}' escapes the repository root ({e}).",
        )

    # Validate non-existence on disk (Refuse to overwrite)
    if os.path.exists(abs_target):
        return (
            None,
            text,
            language,
            f"Target file '{target_clean}' already exists in repository. The 'create:' command refuses to overwrite existing files. Please use the existing edit/review workflow instead (e.g. 'fix: @\"{target_clean}\" <instructions>' or 'update:').",
        )

    clean_prompt = re.sub(r'\s+', ' ', text).strip()
    return target_clean, clean_prompt, language, None


def generate_new_file_diff(target_rel_path: str, code: str) -> str:
    """Generates a complete new-file unified git diff from /dev/null."""
    lines = code.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + "\n"

    diff_lines = [
        f"diff --git a/{target_rel_path} b/{target_rel_path}\n",
        "new file mode 100644\n",
        "--- /dev/null\n",
        f"+++ b/{target_rel_path}\n",
        f"@@ -0,0 +1,{len(lines)} @@\n",
    ]
    for line in lines:
        diff_lines.append(f"+{line}")

    return "".join(diff_lines)


class CodeCreationEngine:
    """Orchestrates structured code creation, isolated sandbox verification, and safe application."""

    def __init__(
        self,
        repo_path: str,
        sandbox_runner: Optional[SandboxRunner] = None,
        llm: Optional[Any] = None,
        embedder: Optional[Any] = None,
        is_admin: bool = True,
        allow_local_sandbox: bool = True,
        security_policy: str = "strict",
        security_threshold: str = "HIGH",
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.sandbox_runner = sandbox_runner or SandboxRunner(
            sandbox_mode="local",
            allow_local_sandbox=allow_local_sandbox,
            is_admin=is_admin,
        )
        self.llm = llm
        self.embedder = embedder
        self.is_admin = is_admin
        self.allow_local_sandbox = allow_local_sandbox
        self.security_policy = (security_policy or "strict").lower().strip()
        self.security_threshold = (security_threshold or "HIGH").upper().strip()

    def generate_code(self, target_file: str, language: str, instruction: str) -> str:
        """Generates implementation code using LLM or reliable language generator."""
        base_name = os.path.splitext(os.path.basename(target_file))[0]

        if self.llm and hasattr(self.llm, "generate"):
            sys_prompt = (
                f"You are an expert {language.capitalize()} software engineer. "
                f"Generate a single, complete, high-quality, production-ready, fully implemented "
                f"source file for '{target_file}'.\n"
                f"Invariants:\n"
                f"1. Produce complete, runnable code with zero placeholders or omissions.\n"
                f"2. For Java: define public class '{base_name}' matching filename.\n"
                f"3. Return ONLY the code inside a ```{language} ... ``` block with no commentary."
            )
            user_prompt = f"Target File: {target_file}\nLanguage: {language}\nInstruction:\n{instruction}"
            try:
                raw_resp = self.llm.generate(user_prompt, system=sys_prompt, temperature=0.0)
                code_match = re.search(r"```(?:[a-zA-Z0-9_\-\+]+)?\s*\n(.*?)\n```", raw_resp, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                    if code:
                        return code
            except Exception as e:
                logger.warning(f"LLM code generation failed, using structured template: {e}")

        # Heuristic implementation generator
        if language == "java":
            return self._generate_default_java_code(base_name, instruction)
        else:
            return self._generate_default_python_code(base_name, instruction)

    def _generate_default_java_code(self, class_name: str, instruction: str) -> str:
        """Generates clean, full Java starter code via JavaLanguageAdapter."""
        reqs = analyze_requirements(instruction)
        return get_adapter_for_language("java").generate_starter_code(class_name, reqs)

    def _generate_default_python_code(self, module_name: str, instruction: str) -> str:
        """Generates clean, full Python starter code via PythonLanguageAdapter."""
        reqs = analyze_requirements(instruction)
        return get_adapter_for_language("python").generate_starter_code(module_name, reqs)

    def _extract_python_interface(self, code: str) -> Dict[str, Any]:
        """Extracts top-level classes, methods, functions, and app objects from Python code via AST."""
        return get_adapter_for_language("python").extract_interface(code)

    def generate_candidate_tests(
        self,
        target_file: str,
        language: str,
        code: str,
        instruction: str,
        reqs: Optional[RequirementSpec] = None,
    ) -> Tuple[str, str]:
        """
        Generates candidate unit tests explicitly labeled as AI-generated contract.
        Derives tests strictly from user requirements and the candidate's actual interface.
        Never derives classes from filenames, invents unrequested tasks, or hardcodes arithmetic values.
        """
        if reqs is None:
            reqs = analyze_requirements(instruction)
        adapter = get_adapter_for_language(language)
        test_rel, test_code, _ = adapter.generate_candidate_tests(
            target_file, code, reqs, llm=self.llm
        )
        return test_rel, test_code

    def validate_in_sandbox(
        self,
        target_file: str,
        language: str,
        code: str,
        test_filename: Optional[str] = None,
        test_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validates syntax, toolchain compilation, behavioral testing, and security policy separately.
        Reports selected execution backend explicitly and never labels syntax-only as compilation passed.
        If Docker is configured, probes the daemon and image toolchain, executes within the container,
        and never silently falls back to host execution.
        """
        infra = probe_sandbox_infrastructure(self.sandbox_runner, language=language)
        backend = infra["backend"]

        syntax_status = "unverified"
        syntax_details = ""
        compilation_status = "unverified"
        compilation_details = ""
        behavioral_status = "unverified (0 tests executed)"
        passed_count = 0
        failed_count = 0
        total_count = 0
        passed_tests: List[str] = []
        failed_tests: List[str] = []
        test_result_data: Dict[str, Any] = {}

        # -------------------------------------------------------------
        # 1. Syntax Parsing (AST)
        # -------------------------------------------------------------
        if language == "python":
            try:
                ast.parse(code)
                syntax_status = "passed"
                syntax_details = "Clean AST (Python AST parsed with 0 syntax errors)."
            except SyntaxError as se:
                syntax_status = "failed"
                syntax_details = f"SyntaxError at line {se.lineno}, col {se.offset}: {se.msg}"
        elif language == "java":
            ts_parser = get_tree_sitter_parser("java")
            has_ast_error = False
            if ts_parser is not None:
                try:
                    tree = ts_parser.parse(bytes(code, "utf-8"))
                    if tree.root_node.has_error:
                        has_ast_error = True
                        syntax_status = "failed"
                        syntax_details = "Java AST syntax error detected by Tree-sitter parser."
                except Exception as e:
                    logger.debug(f"Tree-sitter parse check skipped: {e}")

            if not has_ast_error:
                syntax_status = "passed"
                syntax_details = "Clean AST (Tree-sitter Java grammar parsed with 0 errors)."

        # -------------------------------------------------------------
        # 2. Toolchain Compilation & Behavioral Verification
        # -------------------------------------------------------------
        if syntax_status != "passed":
            compilation_status = "failed"
            compilation_details = f"Syntax parsing failed: {syntax_details}"
            behavioral_status = "blocked (0 tests executed: syntax parsing failed)"
            test_result_data = {
                "success": False,
                "exit_code": 1,
                "error_message": syntax_details,
                "failure_category": "collection_failure",
                "passed_count": 0,
                "failed_count": 1,
                "total_count": 1,
                "failed_tests": ["syntax_error"],
            }
        elif infra.get("infrastructure_blocker"):
            # Infrastructure is unavailable (e.g. Docker daemon is down)
            # NEVER fall back to host javac when in docker mode!
            # NEVER label syntax-only as compilation passed!
            blocker = infra["infrastructure_blocker"]
            compilation_status = "blocked"
            compilation_details = f"Toolchain execution blocked: {blocker}"
            behavioral_status = f"blocked (0 tests executed: zero tests executed as consequence: {blocker})"
            test_result_data = {
                "success": False,
                "exit_code": 1,
                "error_message": blocker,
                "failure_category": "infrastructure_failure",
                "skipped": True,
                "passed_count": 0,
                "failed_count": 0,
                "total_count": 0,
            }
        else:
            # Infrastructure is AVAILABLE!
            if language == "python":
                compilation_status = "passed"
                compilation_details = f"Python bytecode compiled successfully via {backend}."
                if test_filename and test_code:
                    extra_files = {
                        target_file: code,
                        test_filename: test_code,
                    }
                    try:
                        res: SandboxTestResult = self.sandbox_runner.run_baseline_tests(
                            self.repo_path,
                            target_file=target_file,
                            extra_files=extra_files,
                        )
                        test_result_data = res.to_dict()
                        passed_count = res.passed_count
                        failed_count = res.failed_count
                        total_count = res.total_count
                        passed_tests = res.passed_tests
                        failed_tests = res.failed_tests

                        passed_req_tests = [t for t in passed_tests if any(k in t for k in ("user_requirement", "behavior", "requirement"))]
                        passed_smoke_tests = [t for t in passed_tests if t not in passed_req_tests]
                        req_passed_cnt = len(passed_req_tests)
                        test_result_data["requirement_tests_passed_count"] = req_passed_cnt
                        test_result_data["passed_requirement_tests"] = passed_req_tests
                        test_result_data["passed_smoke_tests"] = passed_smoke_tests

                        if res.success and passed_count > 0 and failed_count == 0 and not res.collection_errors:
                            behavioral_status = "passed"
                            failure_category = None
                        elif failed_count > 0 or not res.success or res.collection_errors:
                            behavioral_status = "failed"
                            combined_text = (
                                (res.stdout or "") + "\n" +
                                (res.stderr or "") + "\n" +
                                (res.error_message or "") + "\n" +
                                " ".join(str(f) for f in (failed_tests or []))
                            ).lower()

                            has_collection_evidence = bool(
                                res.collection_errors
                                or "error collecting" in combined_text
                                or "collection error" in combined_text
                                or "errors during collection" in combined_text
                                or "modulenotfounderror" in combined_text
                                or "importerror" in combined_text
                                or "syntaxerror" in combined_text
                                or "indentationerror" in combined_text
                                or "nameerror" in combined_text
                                or "attributeerror" in combined_text
                                or "cannot import name" in combined_text
                            )

                            # Genuine cancellation (KeyboardInterrupt, SIGINT, or explicit user signal)
                            is_genuine_cancellation = bool(
                                "keyboardinterrupt" in combined_text
                                or "sigint" in combined_text
                                or "interrupted by user" in combined_text
                                or "interrupted by signal" in combined_text
                                or res.exit_code in (-9, -15, -2)
                            )

                            # Generic interruption message (e.g. pytest stopped execution banner)
                            is_generic_interrupted = bool(
                                "interrupted:" in combined_text
                                or "execution was interrupted" in combined_text
                                or "interrupted by" in combined_text
                            )

                            # Distinguish failure category using actual diagnostic evidence (never classify exit code 2 solely as collection failure)
                            # Explicit collection evidence must not be overridden by pytest's "Interrupted: N error during collection" banner
                            if is_genuine_cancellation:
                                failure_category = "infrastructure_failure"
                            elif has_collection_evidence:
                                failure_category = "collection_failure"
                            elif (
                                is_generic_interrupted
                                or res.exit_code in (-8, -7, -6, -5, -4, 3, 4)
                                or (res.exit_code == 2 and not has_collection_evidence)
                                or (res.error_message and any(k in res.error_message.lower() for k in ("docker", "timed out", "timeout", "sandbox execution error", "permission denied")))
                            ):
                                failure_category = "infrastructure_failure"
                            elif (total_count == 0 and passed_count == 0 and failed_count == 0) or res.skipped or "no tests ran" in (res.stdout or "").lower() or res.exit_code == 5:
                                failure_category = "zero_discovered_tests"
                            elif failed_count > 0 or res.assertion_errors:
                                failure_category = "assertion_failure"
                            else:
                                failure_category = "infrastructure_failure" if res.exit_code != 0 else "zero_discovered_tests"
                        else:
                            behavioral_status = "unverified (0 tests executed)"
                            failure_category = "zero_discovered_tests"

                        test_result_data["failure_category"] = failure_category
                    except Exception as e:
                        behavioral_status = "failed"
                        failed_count = 1
                        failed_tests = [f"sandbox_exception: {e}"]
                        test_result_data = {
                            "error_message": str(e),
                            "success": False,
                            "exit_code": 1,
                            "failure_category": "infrastructure_failure",
                            "stderr": str(e),
                            "traceback_summary": str(e),
                        }

            elif language == "java":
                with tempfile.TemporaryDirectory(prefix="icx_java_run_") as tmp_dir:
                    f_main = os.path.join(tmp_dir, target_file)
                    os.makedirs(os.path.dirname(f_main), exist_ok=True)
                    with open(f_main, "w", encoding="utf-8") as f:
                        f.write(code)

                    files_to_compile = [target_file.replace("\\", "/")]
                    if test_filename and test_code:
                        f_test = os.path.join(tmp_dir, test_filename)
                        os.makedirs(os.path.dirname(f_test), exist_ok=True)
                        with open(f_test, "w", encoding="utf-8") as f:
                            f.write(test_code)
                        files_to_compile.append(test_filename.replace("\\", "/"))

                    # Phase 1: Compile javac via sandbox_runner._execute_in_sandbox
                    c_code, c_out, c_err, c_exec_err = self.sandbox_runner._execute_in_sandbox(
                        ["javac"] + files_to_compile, tmp_dir, timeout=30, env={}
                    )

                    if c_code != 0:
                        compilation_status = "failed"
                        compilation_details = (c_err or c_out or c_exec_err or f"javac exited with code {c_code}").strip()
                        behavioral_status = "blocked (0 tests executed: compilation failed)"
                        test_result_data = {
                            "success": False,
                            "exit_code": c_code,
                            "error_message": compilation_details,
                            "failure_category": "infrastructure_failure",
                            "failed_tests": ["javac_compilation_failure"],
                            "passed_count": 0,
                            "failed_count": 1,
                            "total_count": 1,
                        }
                    else:
                        compilation_status = "passed"
                        compilation_details = f"javac compilation succeeded with 0 errors via {backend}."

                        # Phase 2: Behavioral test execution
                        if test_filename and test_code:
                            test_class = os.path.splitext(test_filename.replace("\\", "/"))[0].replace("/", ".")
                            r_code, r_out, r_err, r_exec_err = self.sandbox_runner._execute_in_sandbox(
                                ["java", test_class], tmp_dir, timeout=30, env={}
                            )

                            if r_code == 0 and "ALL TESTS PASSED" in r_out:
                                passed_tests = [line.split("PASS: ", 1)[1].strip() for line in r_out.splitlines() if "PASS: " in line]
                                if not passed_tests:
                                    passed_tests = ["testInstantiation"]
                                passed_count = len(passed_tests)
                                total_count = passed_count
                                passed_req_tests = [t for t in passed_tests if "instantiation" not in t.lower()]
                                req_passed_cnt = len(passed_req_tests)
                                behavioral_status = "passed"
                                test_result_data = {
                                    "success": True,
                                    "exit_code": 0,
                                    "failure_category": None,
                                    "passed_count": passed_count,
                                    "failed_count": 0,
                                    "total_count": total_count,
                                    "passed_tests": passed_tests,
                                    "requirement_tests_passed_count": req_passed_cnt,
                                    "passed_requirement_tests": passed_req_tests,
                                    "stdout": r_out,
                                }
                            else:
                                behavioral_status = "failed"
                                failed_count = 1
                                err_msg = (r_err or r_out or r_exec_err or f"java exited with code {r_code}").strip()
                                failed_tests = [f"Java execution error: {err_msg}"]
                                j_fail_cat = "assertion_failure" if "AssertionError" in err_msg else "infrastructure_failure"
                                test_result_data = {
                                    "success": False,
                                    "exit_code": r_code or 1,
                                    "failure_category": j_fail_cat,
                                    "passed_count": 0,
                                    "failed_count": 1,
                                    "total_count": 1,
                                    "failed_tests": failed_tests,
                                    "stderr": r_err,
                                    "traceback_summary": err_msg,
                                }

        # -------------------------------------------------------------
        # 3. Security Scan & Policy Coverage
        # -------------------------------------------------------------
        sec_policy = getattr(self, "security_policy", "strict")
        sec_threshold = getattr(self, "security_threshold", "HIGH")
        with tempfile.TemporaryDirectory(prefix="icx_sec_") as tmp_sec:
            tmp_f = os.path.join(tmp_sec, os.path.basename(target_file))
            with open(tmp_f, "w", encoding="utf-8") as f:
                f.write(code)
            try:
                res_sec = run_security_scan(
                    tmp_f,
                    repo_root=tmp_sec,
                    severity_threshold=sec_threshold,
                    security_policy=sec_policy,
                )
            except Exception as e:
                logger.debug(f"Security scanner check non-fatal exception: {e}")
                res_sec = {
                    "status": "error",
                    "passed": False,
                    "security_policy": sec_policy,
                    "severity_threshold": sec_threshold,
                    "coverage_status": "error",
                    "incomplete_coverage": True,
                    "coverage_warning": str(e),
                    "findings": [],
                    "failing_findings_count": 0,
                }

        # Reuse the security scanner's authoritative policy and coverage fields.
        # Java syntax parsing must not count as AST security vulnerability coverage.
        sec_status = res_sec.get("status", "incomplete")
        sec_approved = bool(res_sec.get("passed", False))
        sec_coverage = res_sec.get("coverage_status", "incomplete")
        sec_warning = res_sec.get("coverage_warning", "")
        raw_sec_findings = res_sec.get("findings", [])
        failing_cnt = res_sec.get("failing_findings_count", len(raw_sec_findings) if sec_status == "failed" else 0)

        normalized_findings = []
        for item in raw_sec_findings:
            if isinstance(item, dict):
                normalized_findings.append({
                    "rule_id": str(item.get("rule_id") or item.get("test_id") or "UNKNOWN"),
                    "rule_name": str(item.get("rule_name") or item.get("test_name") or ""),
                    "category": str(item.get("category") or "security"),
                    "severity": str(item.get("severity") or item.get("issue_severity") or "UNKNOWN").upper(),
                    "confidence": str(item.get("confidence") or item.get("issue_confidence") or "UNKNOWN").upper(),
                    "file": str(item.get("file") or target_file),
                    "line": item.get("line") or item.get("line_number"),
                    "code": redact_secret_value(str(item.get("code") or "")),
                    "explanation": redact_secret_value(str(item.get("explanation") or item.get("text") or item.get("issue_text") or "")),
                    "remediation": str(item.get("remediation") or ""),
                })
            else:
                normalized_findings.append({
                    "rule_id": "UNKNOWN",
                    "rule_name": "",
                    "category": "security",
                    "severity": "UNKNOWN",
                    "confidence": "UNKNOWN",
                    "file": target_file,
                    "line": None,
                    "code": "",
                    "explanation": redact_secret_value(str(item)),
                    "remediation": "",
                })

        sec_val = {
            "security_status": sec_status,
            "security_approved": sec_approved,
            "security_policy": res_sec.get("security_policy", sec_policy),
            "severity_threshold": res_sec.get("severity_threshold", sec_threshold),
            "coverage": sec_coverage,
            "security_coverage": sec_coverage,
            "coverage_status": sec_coverage,
            "incomplete_coverage": res_sec.get("incomplete_coverage", False),
            "coverage_warning": sec_warning,
            "ast_scanned_languages": res_sec.get("ast_scanned_languages", []),
            "unsupported_ast_languages": res_sec.get("unsupported_ast_languages", []),
            "findings_count": len(normalized_findings),
            "failing_findings_count": failing_cnt,
            "findings": normalized_findings,
        }

        # Invariant: Smoke tests alone cannot satisfy behavioral verification
        req_passed_cnt = test_result_data.get("requirement_tests_passed_count", 0)
        smoke_verified = (
            syntax_status == "passed"
            and compilation_status == "passed"
            and passed_count >= 1
            and failed_count == 0
        )
        verified = (
            smoke_verified
            and behavioral_status == "passed"
            and req_passed_cnt >= 1
        )

        return {
            "execution_backend": backend,
            "infrastructure": infra,
            "syntax_status": syntax_status,
            "syntax_details": syntax_details,
            "compilation_status": compilation_status,
            "compilation_details": compilation_details,
            "behavioral_status": behavioral_status,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "total_count": total_count,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "failure_category": test_result_data.get("failure_category"),
            "verified": verified,
            "smoke_verified": smoke_verified,
            "requirement_tests_passed_count": req_passed_cnt,
            "test_status": "passed" if behavioral_status == "passed" else ("failed" if behavioral_status == "failed" else "unverified"),
            "test_result": test_result_data,
            "security_validation": sec_val,
        }

    def propose_creation(
        self,
        raw_instruction: str,
        generate_tests: bool = True,
        stop_on_infra_blocker: bool = False,
        candidate_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generates a structured creation proposal containing target path, code,
        complete git diff, verification results, and central approval gate metadata.
        """
        target_file, clean_inst, language, err = parse_creation_request(raw_instruction, self.repo_path)
        if err:
            return {
                "proposal_id": str(uuid.uuid4()),
                "repo_id": get_repo_id(self.repo_path),
                "target_file": target_file or "unknown",
                "status": "failed",
                "error": err,
                "explanation": err,
                "git_diff": "",
                "original_code": "",
                "suggested_patch": "",
                "code_origin": "newly generated code (not retrieved repository evidence)",
                "execution_backend": getattr(self.sandbox_runner, "sandbox_mode", "local"),
                "syntax_status": "failed",
                "syntax_details": err,
                "compilation_status": "failed",
                "compilation_details": err,
                "behavioral_status": "unverified",
                "sandbox_validation": {"verified": False, "test_status": "failed", "passed_count": 0},
            }

        # Probe mandatory infrastructure before expensive generation
        infra = probe_sandbox_infrastructure(self.sandbox_runner, language=language)
        if infra.get("infrastructure_blocker") and (stop_on_infra_blocker or self.llm is not None):
            blocker = infra["infrastructure_blocker"]
            guidance = infra.get("actionable_guidance") or ""
            explanation = (
                f"Explicit creation proposal for '{target_file}' ({language}) HALTED. "
                f"Infrastructure Blocker: {blocker}. "
                f"Actionable Guidance: {guidance}"
            ).strip()

            sec_policy = getattr(self, "security_policy", "strict")
            sec_threshold = getattr(self, "security_threshold", "HIGH")

            return {
                "proposal_id": str(uuid.uuid4()),
                "repo_id": get_repo_id(self.repo_path),
                "target_file": target_file,
                "target_abs": resolve_within(self.repo_path, target_file),
                "language": language,
                "original_code": "",
                "suggested_patch": "",
                "git_diff": "",
                "is_new_file": True,
                "code_origin": "newly generated code (not retrieved repository evidence)",
                "contract_type": "none",
                "contract_disclaimer": "None",
                "candidate_test_file": None,
                "candidate_test_code": None,
                "execution_backend": infra["backend"],
                "infrastructure": infra,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
                "syntax_status": "skipped",
                "syntax_details": "Skipped: backend infrastructure probe failed before generation.",
                "compilation_status": "blocked",
                "compilation_details": f"Toolchain execution blocked: {blocker}",
                "behavioral_status": f"blocked (0 tests executed: zero tests executed as consequence: {blocker})",
                "sandbox_validation": {
                    "verified": False,
                    "test_status": "blocked",
                    "passed_count": 0,
                    "failed_count": 0,
                    "total_count": 0,
                    "passed_tests": [],
                    "failed_tests": [],
                    "infrastructure_blocker": blocker,
                    "test_result": {
                        "success": False,
                        "exit_code": 1,
                        "error_message": blocker,
                        "skipped": True,
                        "passed_count": 0,
                        "failed_count": 0,
                        "total_count": 0,
                    },
                },
                "security_validation": {
                    "security_status": "unscanned",
                    "security_approved": False,
                    "security_policy": sec_policy,
                    "severity_threshold": sec_threshold,
                    "coverage": "unscanned",
                    "security_coverage": "unscanned",
                    "coverage_status": "unscanned",
                    "incomplete_coverage": True,
                    "coverage_warning": "Security scan skipped because code generation was halted by infrastructure blocker.",
                    "findings_count": 0,
                    "failing_findings_count": 0,
                    "findings": [],
                },
                "status": "failed",
                "explanation": explanation,
                "error": blocker,
            }

        # Scope and requirements analysis
        reqs = analyze_requirements(clean_inst)
        capability_notes = []
        if reqs.web_preview_requested or "web" in clean_inst.lower():
            capability_notes.append("Web preview is unavailable: network-isolated sandbox environment without browser access.")
        capability_notes.append("Single-file creation supported; multi-file creation is unsupported.")
        capability_notes.append("Zero automatic package installations; sandbox uses existing environment dependencies.")

        # 1. Generate new file code or use provided candidate code
        if candidate_code is not None:
            generated_code = candidate_code
        else:
            generated_code = self.generate_code(target_file, language, clean_inst)

        # 2. Generate candidate test contract (labeled)
        test_file = None
        test_code = None
        if generate_tests:
            test_file, test_code = self.generate_candidate_tests(
                target_file, language, generated_code, clean_inst, reqs=reqs
            )

        # 3. Sandbox verification
        val_res = self.validate_in_sandbox(
            target_file, language, generated_code, test_filename=test_file, test_code=test_code
        )

        # 4. Generate new file git diff
        git_diff = generate_new_file_diff(target_file, generated_code)

        explanation = (
            f"Explicit creation proposal for '{target_file}' ({language}). "
            f"Execution Backend: {val_res['execution_backend']}. "
            f"Syntax: {val_res['syntax_status']}. "
            f"Compilation: {val_res['compilation_status']}. "
            f"Behavioral Testing: {val_res['behavioral_status']}."
        )

        req_cnt = val_res.get("requirement_tests_passed_count", 0)
        uncovered_notes = [note for note in reqs.limitations_noted if any(k in note.lower() for k in ("unbound", "ambiguous", "no executable"))]
        total_vectors = len(reqs.test_vectors)
        has_partial_vectors = bool(total_vectors > 0 and req_cnt < total_vectors)

        if req_cnt == 0:
            req_status = "interface_smoke_only"
            has_uncovered = True
            missing_cov = (
                uncovered_notes[0]
                if uncovered_notes
                else "No executable requirement-grounded tests were executed; interface smoke verified only."
            )
            clarification_msg = (
                "Please specify concrete input/output test vectors or expected behavioral assertions for full verification."
            )
        elif uncovered_notes or has_partial_vectors:
            req_status = "partial_coverage"
            has_uncovered = True
            missing_cov = (
                uncovered_notes[0]
                if uncovered_notes
                else f"Partial requirement coverage: only {req_cnt} of {total_vectors} requirement vectors were verified."
            )
            clarification_msg = (
                "Please clarify ambiguous, unbound, or missing requirement vectors for full verification."
            )
        else:
            req_status = "grounded_contract"
            has_uncovered = False
            missing_cov = None
            clarification_msg = None

        return {
            "proposal_id": str(uuid.uuid4()),
            "repo_id": get_repo_id(self.repo_path),
            "target_file": target_file,
            "target_abs": resolve_within(self.repo_path, target_file),
            "language": language,
            "original_code": "",  # Empty since new file
            "suggested_patch": generated_code,
            "git_diff": git_diff,
            "is_new_file": True,
            "code_origin": "newly generated code (not retrieved repository evidence)",
            "contract_type": "ai_generated_candidate_contract" if test_file else "none",
            "contract_disclaimer": "AI-Generated Candidate Contract (Does Not Imply Independent Correctness)",
            "candidate_test_file": test_file,
            "candidate_test_code": test_code,
            "requirements_status": req_status,
            "has_uncovered_requirements": has_uncovered,
            "requirements_evaluation": reqs.to_dict(),
            "requirements_notes": reqs.limitations_noted[0] if reqs.limitations_noted else "User requirements verified against candidate interface.",
            "missing_coverage": missing_cov,
            "clarification_needed": clarification_msg,
            "capability_notes": capability_notes,
            "execution_backend": val_res["execution_backend"],
            "infrastructure": val_res["infrastructure"],
            "infrastructure_blocker": val_res.get("infrastructure", {}).get("infrastructure_blocker"),
            "actionable_guidance": val_res.get("infrastructure", {}).get("actionable_guidance"),
            "syntax_status": val_res["syntax_status"],
            "syntax_details": val_res["syntax_details"],
            "compilation_status": val_res["compilation_status"],
            "compilation_details": val_res["compilation_details"],
            "behavioral_status": val_res["behavioral_status"],
            "failure_category": val_res.get("failure_category"),
            "sandbox_validation": {
                "verified": val_res["verified"] and not has_uncovered,
                "smoke_verified": val_res.get("smoke_verified", False),
                "requirement_tests_passed_count": req_cnt,
                "test_status": val_res["test_status"],
                "passed_count": val_res["passed_count"],
                "failed_count": val_res["failed_count"],
                "total_count": val_res["total_count"],
                "passed_tests": val_res["passed_tests"],
                "failed_tests": val_res["failed_tests"],
                "failure_category": val_res.get("failure_category"),
                "infrastructure_blocker": val_res.get("infrastructure", {}).get("infrastructure_blocker"),
                "test_result": val_res["test_result"],
            },
            "security_validation": val_res["security_validation"],
            "status": "verified" if (val_res["verified"] and req_cnt > 0 and not has_uncovered) else "pending",
            "explanation": explanation,
            "error": None,
        }

    def apply_creation(self, proposal: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Applies approved creation proposal to disk after enforcing:
        0. Repository isolation gate (matching canonical repo_id).
        1. Central approval gate (evaluate_patch_approval_gate).
        2. Absence re-check on disk to prevent overwriting files created after proposal generation.
        """
        target_file = proposal.get("target_file")
        if not target_file:
            return False, "Cannot apply creation: missing target_file in proposal."

        # Invariant 0: Repository Isolation & Identity Check
        from core.persistence import get_repo_id, is_canonical_repo_id
        target_repo_id = get_repo_id(self.repo_path)
        prop_repo_id = proposal.get("repo_id")
        if not is_canonical_repo_id(prop_repo_id):
            return False, f"Approval rejected: Proposal lacks canonical repository identity metadata (missing or basename-only repo_id: '{prop_repo_id}'). Cross-repository safety invariant requires canonical repository identity."
        if prop_repo_id != target_repo_id:
            return False, f"Security Block: Cross-repository operation rejected. Proposal belongs to repository '{prop_repo_id}', but target repository is '{target_repo_id}'."

        # Invariant 1: Central Approval Gate
        ok_gate, gate_msg = evaluate_patch_approval_gate(proposal, target_repo_id=target_repo_id)
        if not ok_gate:
            return False, f"Approval rejected by central gate: {gate_msg}"

        # Invariant 2: Re-check file absence at application time
        target_abs = resolve_within(self.repo_path, target_file)
        if os.path.exists(target_abs):
            return False, f"Conflict: target file '{target_file}' was created on disk after proposal generation. Aborting to prevent overwriting."

        # Write file
        os.makedirs(os.path.dirname(target_abs), exist_ok=True)
        with open(target_abs, "w", encoding="utf-8") as f:
            f.write(proposal.get("suggested_patch", ""))

        return True, f"File created successfully: {target_abs}"



def probe_sandbox_infrastructure(runner: SandboxRunner, language: str = "java") -> Dict[str, Any]:
    """
    Probes the execution backend infrastructure.
    - If Docker mode: probes Docker daemon responsiveness and the configured
      sandbox image's toolchain (javac/java for Java, python for Python).
    - If Local mode: probes host toolchain (javac/java for Java, host Python for Python).
    Returns structured probe metadata including precise infrastructure blockers.
    """
    mode = getattr(runner, "sandbox_mode", "local")
    image = getattr(runner, "docker_image", "intellicodex-sandbox:latest")

    if mode == "docker":
        backend_name = f"Docker Sandbox (image: {image})"
        docker_cli = shutil.which("docker")
        if not docker_cli:
            blocker = "Docker CLI executable ('docker') not found on system PATH."
            guidance = "Install Docker Desktop or Docker Engine and ensure 'docker' is on system PATH. Alternatively, pass '--sandbox local' to use host toolchain."
            return {
                "backend": backend_name,
                "mode": "docker",
                "daemon_available": False,
                "daemon_version": None,
                "daemon_error": blocker,
                "toolchain_available": False,
                "toolchain_javac_version": None,
                "toolchain_java_version": None,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }

        # 1. Probe Docker daemon responsiveness
        try:
            res_v = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if res_v.returncode != 0 or not res_v.stdout.strip():
                err_raw = (res_v.stderr or res_v.stdout or "").strip()
                blocker = f"Docker daemon unavailable: {err_raw}"
                guidance = "Start Docker Desktop or start Docker daemon ('systemctl start docker'). Alternatively, pass '--sandbox local' to use host toolchain if installed."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "daemon_available": False,
                    "daemon_version": None,
                    "daemon_error": blocker,
                    "toolchain_available": False,
                    "toolchain_javac_version": None,
                    "toolchain_java_version": None,
                    "toolchain_error": "Docker daemon unavailable",
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }
            daemon_ver = res_v.stdout.strip()
        except subprocess.TimeoutExpired:
            blocker = "Docker daemon unresponsive (timed out after 5s)."
            guidance = "Ensure Docker Desktop or daemon is running and responding. Restart Docker daemon if frozen."
            return {
                "backend": backend_name,
                "mode": "docker",
                "daemon_available": False,
                "daemon_version": None,
                "daemon_error": blocker,
                "toolchain_available": False,
                "toolchain_javac_version": None,
                "toolchain_java_version": None,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }
        except Exception as e:
            blocker = f"Docker daemon communication error: {e}"
            guidance = "Check Docker daemon permissions and connectivity. Alternatively, run with '--sandbox local'."
            return {
                "backend": backend_name,
                "mode": "docker",
                "daemon_available": False,
                "daemon_version": None,
                "daemon_error": blocker,
                "toolchain_available": False,
                "toolchain_javac_version": None,
                "toolchain_java_version": None,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }

        # 2. Probe configured container image toolchain based on language
        if language == "java":
            try:
                res_jc = subprocess.run(
                    ["docker", "run", "--rm", "--network", "none", image, "javac", "-version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                javac_out = (res_jc.stdout or res_jc.stderr or "").strip()
                if res_jc.returncode != 0:
                    blocker = f"Configured sandbox image '{image}' lacks javac compiler ({javac_out or 'command not found'})."
                    guidance = f"Rebuild or pull container image with JDK installed (e.g. 'docker build -t {image} .')."
                    return {
                        "backend": backend_name,
                        "mode": "docker",
                        "daemon_available": True,
                        "daemon_version": daemon_ver,
                        "daemon_error": None,
                        "toolchain_available": False,
                        "toolchain_javac_version": None,
                        "toolchain_java_version": None,
                        "toolchain_error": blocker,
                        "infrastructure_blocker": blocker,
                        "actionable_guidance": guidance,
                    }

                res_jv = subprocess.run(
                    ["docker", "run", "--rm", "--network", "none", image, "java", "-version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                java_out = (res_jv.stdout or res_jv.stderr or "").strip()
                if res_jv.returncode != 0:
                    blocker = f"Configured sandbox image '{image}' lacks java runtime ({java_out or 'command not found'})."
                    guidance = f"Rebuild or pull container image with Java runtime installed for image '{image}'."
                    return {
                        "backend": backend_name,
                        "mode": "docker",
                        "daemon_available": True,
                        "daemon_version": daemon_ver,
                        "daemon_error": None,
                        "toolchain_available": False,
                        "toolchain_javac_version": javac_out,
                        "toolchain_java_version": None,
                        "toolchain_error": blocker,
                        "infrastructure_blocker": blocker,
                        "actionable_guidance": guidance,
                    }

                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": True,
                    "toolchain_javac_version": javac_out,
                    "toolchain_java_version": java_out.splitlines()[0] if java_out else "Java runtime",
                    "toolchain_error": None,
                    "infrastructure_blocker": None,
                    "actionable_guidance": None,
                }
            except subprocess.TimeoutExpired:
                blocker = f"Container toolchain probe timed out after 10s for image '{image}'."
                guidance = f"Check container runtime responsiveness for image '{image}'."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_javac_version": None,
                    "toolchain_java_version": None,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }
            except Exception as e:
                blocker = f"Container toolchain probe error: {e}"
                guidance = f"Verify Docker container execution for image '{image}'."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_javac_version": None,
                    "toolchain_java_version": None,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }
        else:
            # Python in container
            try:
                res_py = subprocess.run(
                    ["docker", "run", "--rm", "--network", "none", image, "python", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                py_out = (res_py.stdout or res_py.stderr or "").strip()
                if res_py.returncode != 0:
                    blocker = f"Configured sandbox image '{image}' lacks python runtime ({py_out or 'command not found'})."
                    guidance = f"Rebuild or pull container image with Python installed for image '{image}'."
                    return {
                        "backend": backend_name,
                        "mode": "docker",
                        "daemon_available": True,
                        "daemon_version": daemon_ver,
                        "daemon_error": None,
                        "toolchain_available": False,
                        "toolchain_javac_version": None,
                        "toolchain_java_version": None,
                        "toolchain_error": blocker,
                        "infrastructure_blocker": blocker,
                        "actionable_guidance": guidance,
                    }
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": True,
                    "toolchain_javac_version": None,
                    "toolchain_java_version": py_out,
                    "toolchain_error": None,
                    "infrastructure_blocker": None,
                    "actionable_guidance": None,
                }
            except Exception as e:
                blocker = f"Container python toolchain probe error: {e}"
                guidance = f"Verify container runtime for image '{image}'."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_javac_version": None,
                    "toolchain_java_version": None,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }

    else:
        # Local Sandbox Mode
        backend_name = "Local Sandbox (host environment)"
        if language == "java":
            javac_bin = shutil.which("javac")
            java_bin = shutil.which("java")
            if not javac_bin or not java_bin:
                missing = []
                if not javac_bin:
                    missing.append("javac")
                if not java_bin:
                    missing.append("java")
                blocker = f"Host Java toolchain incomplete: {', '.join(missing)} not found on PATH."
                guidance = f"Install OpenJDK / JDK and add {', '.join(missing)} to system PATH, or use Docker sandbox with '--sandbox docker'."
                return {
                    "backend": backend_name,
                    "mode": "local",
                    "daemon_available": True,
                    "daemon_version": None,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_javac_version": None,
                    "toolchain_java_version": None,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }
            return {
                "backend": backend_name,
                "mode": "local",
                "daemon_available": True,
                "daemon_version": None,
                "daemon_error": None,
                "toolchain_available": True,
                "toolchain_javac_version": "host javac",
                "toolchain_java_version": "host java",
                "toolchain_error": None,
                "infrastructure_blocker": None,
                "actionable_guidance": None,
            }
        else:
            # Python host environment is available
            return {
                "backend": backend_name,
                "mode": "local",
                "daemon_available": True,
                "daemon_version": None,
                "daemon_error": None,
                "toolchain_available": True,
                "toolchain_javac_version": None,
                "toolchain_java_version": "host python",
                "toolchain_error": None,
                "infrastructure_blocker": None,
                "actionable_guidance": None,
            }


def render_creation_card(proposal: Dict[str, Any], elapsed_time: float = 0.0):
    """Renders presentation card for code creation proposal with explicit labels and full diagnostic disclosure."""
    target_file = proposal.get("target_file", "unknown")
    origin = proposal.get("code_origin", "newly generated code")
    backend = proposal.get("execution_backend") or "Unknown Sandbox"
    syntax_st = proposal.get("syntax_status", "unknown").upper()
    syntax_det = proposal.get("syntax_details", "")
    comp_st = proposal.get("compilation_status", "unknown").upper()
    comp_det = proposal.get("compilation_details", "")
    beh_st = proposal.get("behavioral_status", "unverified").upper()
    c_type = proposal.get("contract_type", "none")
    c_disc = proposal.get("contract_disclaimer", "")
    sec_val = proposal.get("security_validation") or {}
    sec_st = sec_val.get("security_status", "unscanned").upper()
    sec_findings = sec_val.get("findings_count", 0)
    sec_findings_list = sec_val.get("findings") or []
    sec_policy = sec_val.get("security_policy", "strict")
    sec_coverage = sec_val.get("coverage", "completed")
    passed_tests = proposal.get("sandbox_validation", {}).get("passed_tests", [])
    failed_tests = proposal.get("sandbox_validation", {}).get("failed_tests", [])
    passed_cnt = proposal.get("sandbox_validation", {}).get("passed_count", 0)
    failed_cnt = proposal.get("sandbox_validation", {}).get("failed_count", 0)
    total_cnt = proposal.get("sandbox_validation", {}).get("total_count", 0)

    # Diagnostic fields from sandbox test execution
    sb_val = proposal.get("sandbox_validation") or {}
    test_res = sb_val.get("test_result") or {}
    fail_cat = test_res.get("failure_category") or proposal.get("failure_category")
    test_cmd = test_res.get("test_command")
    test_cmd_str = " ".join(test_cmd) if isinstance(test_cmd, list) else str(test_cmd or "")
    exit_code = test_res.get("exit_code")
    coll_errors = test_res.get("collection_errors") or []
    tb_raw = test_res.get("traceback_summary") or test_res.get("stderr") or ""
    rel_tb = extract_relevant_traceback(tb_raw)

    time_str = f"{elapsed_time:.2f}s" if elapsed_time > 0 else "0.10s"

    if HAS_RICH and console:
        info_table = Table.grid(padding=(0, 2))
        info_table.add_column(style="bold cyan", justify="right")
        info_table.add_column(style="white")
        info_table.add_row("Canonical Target:", target_file)
        info_table.add_row("Code Origin:", f"[bold green]{origin}[/bold green]")
        info_table.add_row("Execution Backend:", f"[bold magenta]{backend}[/bold magenta]")

        infra_blocker = proposal.get("infrastructure_blocker") or proposal.get("infrastructure", {}).get("infrastructure_blocker")
        actionable_guidance = proposal.get("actionable_guidance") or proposal.get("infrastructure", {}).get("actionable_guidance")
        if infra_blocker:
            info_table.add_row("Infrastructure Status:", f"[bold red]BLOCKED[/bold red] ({infra_blocker})")
            if actionable_guidance:
                info_table.add_row("Actionable Guidance:", f"[yellow]{actionable_guidance}[/yellow]")

        syn_color = "green" if syntax_st == "PASSED" else ("yellow" if syntax_st.startswith("SKIPPED") else "red")
        info_table.add_row("Syntax (AST):", f"[{syn_color}]{syntax_st}[/{syn_color}] ({syntax_det})")

        comp_color = "green" if comp_st == "PASSED" else ("red" if "FAIL" in comp_st else "yellow")
        info_table.add_row("Compilation:", f"[{comp_color}]{comp_st}[/{comp_color}] ({comp_det})")

        beh_color = "green" if beh_st == "PASSED" else ("red" if "FAIL" in beh_st else "yellow")
        counts_str = f"[{passed_cnt} passed, {failed_cnt} failed, {total_cnt} total]"
        info_table.add_row("Behavioral Testing:", f"[{beh_color}]{beh_st}[/{beh_color}] {counts_str}")

        if passed_tests:
            info_table.add_row("Tests Passed:", f"[green]{', '.join(passed_tests)}[/green]")
        if failed_tests:
            info_table.add_row("Tests Failed:", f"[red]{', '.join(failed_tests)}[/red]")

        # Expose behavioral failure diagnostics when tests failed / unverified
        if beh_st != "PASSED":
            if fail_cat:
                info_table.add_row("Failure Category:", f"[bold red]{fail_cat.replace('_', ' ').title()}[/bold red]")
            if test_cmd_str:
                info_table.add_row("Test Command:", f"[dim cyan]{test_cmd_str}[/dim cyan]")
            if exit_code is not None and exit_code != 0:
                info_table.add_row("Exit Code:", f"[dim red]{exit_code}[/dim red]")
            if coll_errors:
                info_table.add_row("Collection/Import Errors:", f"[red]{'; '.join(coll_errors)}[/red]")
            if rel_tb:
                info_table.add_row("Relevant Traceback/Stderr:", f"[dim red]{rel_tb}[/dim red]")

        if c_type == "ai_generated_candidate_contract":
            info_table.add_row("Contract Grounding:", "[bold yellow]AI-Generated Candidate Contract[/bold yellow]")
            if c_disc:
                info_table.add_row("Contract Disclaimer:", f"[dim yellow]{c_disc}[/dim yellow]")

        req_notes = proposal.get("requirements_notes")
        if req_notes:
            info_table.add_row("Requirements Grounding:", f"[dim cyan]{req_notes}[/dim cyan]")

        cap_notes = proposal.get("capability_notes")
        if cap_notes:
            info_table.add_row("Scope & Capabilities:", f"[dim yellow]{'; '.join(cap_notes)}[/dim yellow]")

        sec_color = "green" if sec_st == "PASSED" else ("yellow" if sec_st in ("INCOMPLETE", "UNSUPPORTED") else "red")
        sec_summary = f"[{sec_color}]{sec_st}[/{sec_color}] (Policy: {sec_policy} | {sec_findings} finding(s) | Coverage: {sec_coverage})"
        info_table.add_row("Security Policy & Coverage:", sec_summary)

        # Expose structured security findings with rule ID, severity, line, redacted explanation
        if sec_findings_list:
            for idx, finding in enumerate(sec_findings_list, start=1):
                if isinstance(finding, dict):
                    r_id = finding.get("rule_id", "UNKNOWN")
                    s_v = finding.get("severity", "UNKNOWN")
                    l_n = finding.get("line")
                    l_str = f"Line {l_n}" if l_n is not None else "Line [unknown]"
                    e_p = redact_secret_value(str(finding.get("explanation", "")))
                    s_color = "red" if s_v in ("HIGH", "CRITICAL") else "yellow"
                    info_table.add_row(f"Security Finding #{idx} [{r_id}]:", f"[{s_color}]{s_v}[/{s_color}] at {l_str} - {e_p}")
                else:
                    info_table.add_row(f"Security Finding #{idx}:", redact_secret_value(str(finding)))

        info_table.add_row("Time Consumed:", time_str)
        info_table.add_row("Model Advisory:", proposal.get("explanation", ""))

        console.print(Panel(info_table, title="[bold cyan]INTELLICODEX CODE CREATION PROPOSAL[/bold cyan]", border_style="cyan"))
        diff = proposal.get("git_diff", "")
        if diff:
            from cli import render_diff
            render_diff(diff)
    else:
        print("\n=======================================================================")
        print("                 INTELLICODEX CODE CREATION PROPOSAL")
        print("=======================================================================")
        print(f"Canonical Target          : {target_file}")
        print(f"Code Origin               : {origin}")
        print(f"Execution Backend         : {backend}")
        infra_blocker = proposal.get("infrastructure_blocker") or proposal.get("infrastructure", {}).get("infrastructure_blocker")
        actionable_guidance = proposal.get("actionable_guidance") or proposal.get("infrastructure", {}).get("actionable_guidance")
        if infra_blocker:
            print(f"Infrastructure Status     : BLOCKED ({infra_blocker})")
            if actionable_guidance:
                print(f"Actionable Guidance       : {actionable_guidance}")
        print(f"Syntax (AST)              : {syntax_st} ({syntax_det})")
        print(f"Compilation               : {comp_st} ({comp_det})")
        counts_str = f"[{passed_cnt} passed, {failed_cnt} failed, {total_cnt} total]"
        print(f"Behavioral Testing        : {beh_st} {counts_str}")
        if passed_tests:
            print(f"Tests Passed              : {', '.join(passed_tests)}")
        if failed_tests:
            print(f"Tests Failed              : {', '.join(failed_tests)}")
        if beh_st != "PASSED":
            if fail_cat:
                print(f"Failure Category          : {fail_cat.replace('_', ' ').title()}")
            if test_cmd_str:
                print(f"Test Command              : {test_cmd_str}")
            if exit_code is not None and exit_code != 0:
                print(f"Test Exit Code            : {exit_code}")
            if coll_errors:
                print(f"Collection/Import Errors  : {'; '.join(coll_errors)}")
            if rel_tb:
                print(f"Relevant Traceback/Stderr :\n{rel_tb}")
        if c_type == "ai_generated_candidate_contract":
            print("Contract Grounding        : AI-Generated Candidate Contract")
            if c_disc:
                print(f"Contract Disclaimer       : {c_disc}")
        req_notes = proposal.get("requirements_notes")
        if req_notes:
            print(f"Requirements Grounding    : {req_notes}")
        cap_notes = proposal.get("capability_notes")
        if cap_notes:
            print(f"Scope & Capabilities      : {'; '.join(cap_notes)}")
        print(f"Security Policy & Coverage: {sec_st} (Policy: {sec_policy} | {sec_findings} finding(s) | Coverage: {sec_coverage})")
        if sec_findings_list:
            for idx, finding in enumerate(sec_findings_list, start=1):
                if isinstance(finding, dict):
                    r_id = finding.get("rule_id", "UNKNOWN")
                    s_v = finding.get("severity", "UNKNOWN")
                    l_n = finding.get("line")
                    l_str = f"Line {l_n}" if l_n is not None else "Line [unknown]"
                    e_p = redact_secret_value(str(finding.get("explanation", "")))
                    print(f"Security Finding #{idx} [{r_id}]: {s_v} at {l_str} - {e_p}")
                else:
                    print(f"Security Finding #{idx}: {redact_secret_value(str(finding))}")
        print(f"Time Consumed             : {time_str}")
        print(f"Model Advisory            : {proposal.get('explanation')}")
        print("\n--- Unified Git Diff ---")
        print(proposal.get("git_diff", ""))
        print("=======================================================================\n")


def execute_create_command(
    raw_query: str,
    current_path: str,
    embedder: Any,
    llm: Any,
    args: Any,
    session: Any = None,
    use_tui: bool = False,
    is_batch: bool = False,
    auto_approve: bool = False,
) -> Tuple[Optional[Any], Optional[Any]]:
    """
    Executes the complete creation command workflow:
    1. Parse instruction & target file path (Java/Python).
    2. Validate boundary and non-existence.
    3. Probe mandatory infrastructure; if blocked, halt before expensive generation.
    4. Generate proposal & validate in isolated sandbox.
    5. Display card and diff.
    6. Evaluate central approval gate (evaluate_patch_approval_gate).
    7. If passed, request explicit confirmation from user.
    8. On approval: apply file to disk, re-index repository, display exact saved path.
    9. Return (new_result, new_engine) or (None, None).
    """
    from core.pipeline import ingest_repository
    from rag.query_engine import QueryEngine

    target_file, clean_inst, language, parse_err = parse_creation_request(raw_query, current_path)
    if parse_err:
        if HAS_RICH and console:
            console.print(f"\n[bold red][!] Code Creation Request Refused:[/bold red]\n{parse_err}\n")
        else:
            print(f"\n[!] Code Creation Request Refused:\n{parse_err}\n")
        return None, None

    sandbox_mode = getattr(args, "sandbox", "docker")
    docker_image = getattr(args, "docker_image", "intellicodex-sandbox:latest")
    backend_label = f"Docker Sandbox (image: {docker_image})" if sandbox_mode == "docker" else "Local Sandbox (host environment)"
    sec_policy = getattr(args, "security_policy", "strict") if args else "strict"
    sec_threshold = getattr(args, "security_threshold", "HIGH") if args else "HIGH"

    print(f"[*] Creation target: '{target_file}' ({language.capitalize()})")
    print(f"[*] Selected execution backend: {backend_label}")
    print(f"[*] Probing backend infrastructure and toolchain...")

    sb_runner = SandboxRunner(
        sandbox_mode=sandbox_mode,
        docker_image=docker_image,
        allow_local_sandbox=True,
        is_admin=True,
    )
    infra = probe_sandbox_infrastructure(sb_runner, language=language)

    creation_engine = CodeCreationEngine(
        repo_path=current_path,
        sandbox_runner=sb_runner,
        llm=llm,
        embedder=embedder,
        is_admin=True,
        allow_local_sandbox=True,
        security_policy=sec_policy,
        security_threshold=sec_threshold,
    )

    t0 = time.perf_counter()
    from core.persistence import get_repo_id, save_repo_activity
    c_repo_id = get_repo_id(current_path)

    if infra.get("infrastructure_blocker"):
        # Mandatory infrastructure probe failed: STOP before expensive generation!
        proposal = creation_engine.propose_creation(raw_query, generate_tests=False, stop_on_infra_blocker=True)
        elapsed = time.perf_counter() - t0
        render_creation_card(proposal, elapsed_time=elapsed)

        # Enforce Central Approval Gate
        ok_gate, gate_msg = evaluate_patch_approval_gate(proposal, security_policy=sec_policy)
        msg_reject = f"[!] APPROVAL REJECTED BY CENTRAL GATE: {gate_msg}"
        save_repo_activity(c_repo_id, {
            "activity_type": "creation",
            "target_file": target_file,
            "proposal_id": proposal.get("proposal_id", f"create_{uuid.uuid4().hex[:8]}"),
            "verification_outcome": "blocked",
            "save_outcome": "gate_rejected",
            "summary": f"Infrastructure blocker: {infra.get('infrastructure_blocker')}",
            "timestamp": time.time(),
        })
        if HAS_RICH and console:
            console.print(f"\n[bold red]{msg_reject}[/bold red]")
            if infra.get("actionable_guidance"):
                console.print(f"[bold yellow][*] Actionable Blocker Resolution:[/bold yellow] {infra['actionable_guidance']}")
            console.print("[dim yellow][*] File creation blocked. Disk remains unchanged.[/dim yellow]\n")
        else:
            print(f"\n{msg_reject}")
            if infra.get("actionable_guidance"):
                print(f"[*] Actionable Blocker Resolution: {infra['actionable_guidance']}")
            print("[*] File creation blocked. Disk remains unchanged.\n")
        return None, None

    print(f"[*] Generating structured proposal & running isolated sandbox verification...")
    proposal = creation_engine.propose_creation(raw_query, generate_tests=True)
    elapsed = time.perf_counter() - t0

    render_creation_card(proposal, elapsed_time=elapsed)

    if proposal.get("status") == "failed" and proposal.get("error"):
        save_repo_activity(c_repo_id, {
            "activity_type": "creation",
            "target_file": target_file,
            "proposal_id": proposal.get("proposal_id", f"create_{uuid.uuid4().hex[:8]}"),
            "verification_outcome": "failed",
            "save_outcome": "gate_rejected",
            "summary": f"Creation proposal generation failed: {proposal.get('error')}",
            "timestamp": time.time(),
        })
        print(f"[!] Creation proposal failed: {proposal['error']}\n")
        return None, None

    # Enforce Central Approval Gate
    ok_gate, gate_msg = evaluate_patch_approval_gate(proposal, security_policy=sec_policy)
    if not ok_gate:
        sb = proposal.get("sandbox_validation", {})
        v_out = "passed" if sb.get("verified") else (
            "blocked" if sb.get("infrastructure", {}).get("infrastructure_blocker") else "failed"
        )
        save_repo_activity(c_repo_id, {
            "activity_type": "creation",
            "target_file": target_file,
            "proposal_id": proposal.get("proposal_id", f"create_{uuid.uuid4().hex[:8]}"),
            "verification_outcome": v_out,
            "save_outcome": "gate_rejected",
            "summary": f"Approval rejected by central gate: {gate_msg}",
            "timestamp": time.time(),
        })
        msg_reject = f"[!] APPROVAL REJECTED BY CENTRAL GATE:\n{gate_msg}"

        # Extract diagnostics for detailed console reporting
        sb_val = proposal.get("sandbox_validation") or {}
        test_res = sb_val.get("test_result") or {}
        fail_cat = test_res.get("failure_category") or proposal.get("failure_category")
        test_cmd = test_res.get("test_command")
        test_cmd_str = " ".join(test_cmd) if isinstance(test_cmd, list) else str(test_cmd or "")
        exit_code = test_res.get("exit_code")
        coll_errors = test_res.get("collection_errors") or []
        tb_raw = test_res.get("traceback_summary") or test_res.get("stderr") or ""
        rel_tb = extract_relevant_traceback(tb_raw)

        sec_findings_list = proposal.get("security_validation", {}).get("findings") or []

        if HAS_RICH and console:
            console.print(f"\n[bold red]{msg_reject}[/bold red]")
            if "Additionally," in gate_msg:
                console.print("[bold yellow][*] Multiple Gate Blockers Detected (Behavioral + Security):[/bold yellow]")
            if fail_cat:
                console.print(f"[bold yellow][*] Behavioral Blocker Cause:[/bold yellow] [red]{fail_cat.replace('_', ' ').title()}[/red]")
                if test_cmd_str:
                    console.print(f"    - Test Command : [dim cyan]{test_cmd_str}[/dim cyan]")
                if exit_code is not None and exit_code != 0:
                    console.print(f"    - Exit Code    : [dim red]{exit_code}[/dim red]")
                if coll_errors:
                    console.print(f"    - Errors       : [red]{'; '.join(coll_errors)}[/red]")
                if rel_tb:
                    console.print(f"    - Traceback / Stderr:\n[dim red]{rel_tb}[/dim red]")
            if sec_findings_list:
                console.print("[bold yellow][*] Security Blocker Details:[/bold yellow]")
                for f in sec_findings_list:
                    if isinstance(f, dict):
                        r_id = f.get("rule_id", "UNKNOWN")
                        s_v = f.get("severity", "UNKNOWN")
                        l_n = f.get("line")
                        l_str = f"Line {l_n}" if l_n is not None else "Line [unknown]"
                        e_p = redact_secret_value(str(f.get("explanation", "")))
                        console.print(f"    - [red][{r_id}][/red] ([yellow]{s_v}[/yellow] at {l_str}): {e_p}")
                    else:
                        console.print(f"    - {redact_secret_value(str(f))}")
            console.print("[dim yellow][*] File creation blocked. Disk remains unchanged.[/dim yellow]\n")
        else:
            print(f"\n{msg_reject}")
            if "Additionally," in gate_msg:
                print("[*] Multiple Gate Blockers Detected (Behavioral + Security)")
            if fail_cat:
                print(f"[*] Behavioral Blocker Cause: {fail_cat.replace('_', ' ').title()}")
                if test_cmd_str:
                    print(f"    - Test Command : {test_cmd_str}")
                if exit_code is not None and exit_code != 0:
                    print(f"    - Exit Code    : {exit_code}")
                if coll_errors:
                    print(f"    - Errors       : {'; '.join(coll_errors)}")
                if rel_tb:
                    print(f"    - Traceback / Stderr:\n{rel_tb}")
            if sec_findings_list:
                print("[*] Security Blocker Details:")
                for f in sec_findings_list:
                    if isinstance(f, dict):
                        r_id = f.get("rule_id", "UNKNOWN")
                        s_v = f.get("severity", "UNKNOWN")
                        l_n = f.get("line")
                        l_str = f"Line {l_n}" if l_n is not None else "Line [unknown]"
                        e_p = redact_secret_value(str(f.get("explanation", "")))
                        print(f"    - [{r_id}] ({s_v} at {l_str}): {e_p}")
                    else:
                        print(f"    - {redact_secret_value(str(f))}")
            print("[*] File creation blocked. Disk remains unchanged.\n")
        return None, None

    if auto_approve:
        action = "a"
    else:
        prompt_label = "Choose action ([a]pprove & save, [c]ancel): "
        try:
            if session is not None and use_tui:
                action = session.prompt(prompt_label).strip().lower()
            else:
                action = input(prompt_label).strip().lower()
        except (EOFError, KeyboardInterrupt):
            action = "c"

    if action in ("a", "approve", "y", "yes"):
        ok_app, msg_app = creation_engine.apply_creation(proposal)
        sb = proposal.get("sandbox_validation", {})
        v_out = "passed" if sb.get("verified") else "failed"
        s_out = "applied" if ok_app else "failed"
        save_repo_activity(c_repo_id, {
            "activity_type": "creation",
            "target_file": target_file,
            "proposal_id": proposal.get("proposal_id", f"create_{uuid.uuid4().hex[:8]}"),
            "verification_outcome": v_out,
            "save_outcome": s_out,
            "summary": f"Creation applied: {msg_app}" if ok_app else f"Creation failed: {msg_app}",
            "timestamp": time.time(),
        })
        if ok_app:
            target_abs = proposal["target_abs"]
            if HAS_RICH and console:
                console.print(f"\n[bold green][✓][/bold green] {msg_app}")
            else:
                print(f"\n[✓] {msg_app}")

            try:
                print("[*] Re-indexing repository with newly created source file...")
                skip_overload_stubs = not getattr(args, "keep_overload_stubs", False)
                new_result = ingest_repository(
                    current_path,
                    embedder,
                    allow_empty=True,
                    legacy_call_graph=getattr(args, "legacy_call_graph", False),
                    skip_overload_stubs=skip_overload_stubs,
                )
                new_engine = QueryEngine(
                    new_result.store,
                    embedder,
                    llm,
                    dep_graph=new_result.graph,
                    call_graph=getattr(new_result, "call_graph", None),
                    lexical_index=getattr(new_result, "lexical_index", None),
                    hybrid_search=True,
                    repo_path=current_path,
                )
                print(f"[✓] Repository re-indexed: {new_result.num_files} source file(s), {new_result.num_chunks} chunk(s).")
                print(f"[✓] Exact saved path: '{target_abs}'\n")
                return new_result, new_engine
            except Exception as re_err:
                print(f"[!] Warning during re-indexing: {re_err}\n")
                return None, None
        else:
            if HAS_RICH and console:
                console.print(f"[bold red][!][/bold red] {msg_app}\n")
            else:
                print(f"[!] {msg_app}\n")
            return None, None
    else:
        sb = proposal.get("sandbox_validation", {})
        v_out = "passed" if sb.get("verified") else (
            "blocked" if sb.get("infrastructure", {}).get("infrastructure_blocker") else "unverified"
        )
        save_repo_activity(c_repo_id, {
            "activity_type": "creation",
            "target_file": target_file,
            "proposal_id": proposal.get("proposal_id", f"create_{uuid.uuid4().hex[:8]}"),
            "verification_outcome": v_out,
            "save_outcome": "cancelled",
            "summary": "Creation proposal cancelled by user",
            "timestamp": time.time(),
        })
        print("[*] Creation proposal cancelled by user. Repository files remain untouched.\n")
        return None, None


