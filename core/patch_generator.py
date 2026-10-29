"""
Multi-File Context-Aware Code Patch Generator Engine (Milestone 1)
Extracts code context via RAG, localizes root causes, prompts LLM or runs heuristic guards,
merges snippet fixes into full repository files, generates unified git diffs, validates syntax,
and executes iterative test-driven closed-loop sandbox validation.
"""
import copy
import difflib
import hashlib
import logging
import os
import sys
import re
import tempfile
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple, Callable, Union
import networkx as nx

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.llm_client import OllamaLLM
from core.chunker import CodeChunk
from core.bug_localizer import BugLocalizer, AdvancedBugLocalizer
from core.sandbox_runner import SandboxRunner, SandboxTestResult, validate_timeout, DEFAULT_TIMEOUT
from core.safe_paths import resolve_within
from backend.patch_generator.llm_parser import extract_code_and_explanation, strip_language_prefix
from backend.patch_generator.patch_validator import validate_patch, compute_patch_quality_score
from backend.patch_generator.patch_applier import apply_patch_to_file, merge_snippet_into_file
from rag.query_engine import format_context
from core.self_improving import RepairExperienceBank, global_experience_bank

logger = logging.getLogger(__name__)


def generate_git_diff(original_code: str, patched_code: str, file_path: str = "file.py") -> str:
    """Generates standard unified git diff format."""
    orig_lines = original_code.splitlines(keepends=True)
    patch_lines = patched_code.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        patch_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="\n",
    )
    diff_text = "".join(diff)
    if not diff_text:
        return f"--- a/{file_path}\n+++ b/{file_path}\n@@ -1 +1 @@\n# No changes detected"
    return f"diff --git a/{file_path} b/{file_path}\n" + diff_text


@dataclass
class MultiFilePatchResult:
    """
    Data contract representing a multi-file coordinated code patch.
    Guarantees cross-file coherence, individual AST validity, and rollback safety.
    """
    patch_id: str
    repo_id: str
    files: Dict[str, str]               # rel_path -> patched_code
    original_files: Dict[str, str]      # rel_path -> original_code
    git_diff: str                       # combined multi-file unified git diff
    file_diffs: Dict[str, str]          # rel_path -> individual git diff
    explanation: str
    validation: Dict[str, Any]          # per-file syntax validation
    sandbox_validation: Optional[Dict[str, Any]] = None
    regression_analysis: Optional[Dict[str, Any]] = None
    status: str = "pending"             # "verified", "regressed", "syntax_error", "failed", "pending"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_test_regressions(
    baseline_result: Optional[SandboxTestResult],
    patched_result: SandboxTestResult,
) -> Dict[str, Any]:
    """
    Compares test suite outcomes between pre-patch baseline and candidate patch execution.
    Flags any previously passing test that now fails or errors as a regression.
    """
    if baseline_result is None or getattr(baseline_result, "skipped", False):
        return {
            "has_regression": False,
            "regressed_tests": [],
            "baseline_passed": [],
            "patched_failed": getattr(patched_result, "failed_tests", []) or [],
            "details": "No baseline test execution available for regression comparison."
        }

    base_passed = set(getattr(baseline_result, "passed_tests", []) or [])
    patch_failed = set(getattr(patched_result, "failed_tests", []) or [])

    # Regression = intersection of previously passing and currently failing tests
    regressions = sorted(list(base_passed & patch_failed))
    has_reg = len(regressions) > 0

    return {
        "has_regression": has_reg,
        "regressed_tests": regressions,
        "baseline_passed_count": len(base_passed),
        "patched_failed_count": len(patch_failed),
        "details": f"Regression detected: {len(regressions)} test(s) that previously passed are now failing: {regressions}" if has_reg else "Zero test regressions detected."
    }


PATCH_SYSTEM_PROMPT = (
    "You are IntelliCodeX, an expert AI software patch engineer. "
    "Generate minimal, correct fixes based on the provided error report and code context. "
    "Output the fixed code inside a single fenced code block, then explain why the fix "
    "resolves the root cause in plain English."
)

REFINEMENT_SYSTEM_PROMPT = (
    "You are IntelliCodeX, an expert AI software patch engineer. "
    "Your previous candidate fix failed automated test validation. "
    "Analyze the test failure output, stack trace, and assertion errors. "
    "Generate a corrected fix that passes the test suite. "
    "Output the corrected code in a single fenced code block, followed by an explanation."
)


def extract_behavioral_requirements(
    error_report: str,
    test_result: Optional[SandboxTestResult],
    file_content_or_docstring: str = "",
    user_instructions: str = "",
) -> List[str]:
    """
    Extracts behavior requirements from relevant tests, documentation, and explicit user instructions.
    Removes universal assumptions that all functions must preserve input collections,
    and preserves intentional in-place mutation where specified.
    """
    reqs = [
        "Resolve the failing assertions and test failures shown above.",
    ]
    if test_result and test_result.passed_tests:
        reqs.append(
            f"Preserve all currently passing tests ({len(test_result.passed_tests)} passing); do NOT break existing behavior."
        )
    reqs.append(
        "Keep interfaces, function signatures, and test fixtures intact without weakening expectations."
    )

    combined = " ".join([
        error_report or "",
        test_result.traceback_summary if test_result else "",
        " ".join(test_result.failed_tests if test_result else []),
        " ".join(test_result.passed_tests if test_result else []),
        " ".join(test_result.assertion_errors if test_result else []),
        file_content_or_docstring or "",
        user_instructions or "",
    ]).lower()

    # 1. Check for intentional in-place mutation signals
    mutation_signals = [
        "in-place", "in place", "mutate in place", "mutates the input",
        "modify in place", "modifies the input", "sort in place", "mutates in-place"
    ]
    has_intentional_mutation = any(sig in combined for sig in mutation_signals)

    # 2. Check for immutability / input preservation signals
    immutability_signals = [
        "deepcopy", "input_unchanged", "input unchanged", "do not mutate",
        "preserve input", "immutable", "must not modify input", "original unchanged",
        "assert intervals == original", "assert x == original"
    ]
    has_immutability_check = any(sig in combined for sig in immutability_signals)

    if has_intentional_mutation and not has_immutability_check:
        reqs.append(
            "Intentional Mutation: Specifications/documentation specify in-place modification. "
            "Preserve intentional in-place mutation of the input collection."
        )
    elif has_immutability_check:
        reqs.append(
            "Input Preservation: Relevant tests or specifications require preserving input collections unchanged "
            "(e.g. caller verifies deepcopy equality). Avoid mutating input parameters in-place."
        )

    return reqs


def extract_contract_mismatches_from_failures(
    test_result: Optional[SandboxTestResult],
    extra_files: Optional[Dict[str, str]] = None,
    repo_path: Optional[str] = None,
    language: str = "python",
) -> List[str]:
    """
    Extracts explicit contract expectations from failing tests and compares them
    against the actual error outputs produced by the candidate patch.

    Identifies:
    1. Expected exception vs actual raised exception (e.g. expected ZeroDivisionError, raised ValueError)
    2. Expected return values / assertions (e.g. assert f(a, b) == expected)
    3. Grounded contract rationales from test docstrings or contract comments.
    """
    if not test_result or not test_result.failed_tests:
        return []

    mismatches: List[str] = []

    # 1. Gather all test file sources (from extra_files and repo_path)
    test_sources: Dict[str, str] = {}
    if extra_files:
        for k, v in extra_files.items():
            norm_k = k.replace("\\", "/").lstrip("./")
            test_sources[norm_k] = v
            test_sources[os.path.basename(norm_k)] = v

    if repo_path and os.path.isdir(repo_path):
        for ft in test_result.failed_tests:
            parts = ft.split("::")
            if len(parts) >= 2:
                fpath = parts[0]
                norm_f = fpath.replace("\\", "/").lstrip("./")
                if norm_f not in test_sources and os.path.basename(norm_f) not in test_sources:
                    full_p = os.path.join(repo_path, fpath)
                    if os.path.isfile(full_p):
                        try:
                            with open(full_p, "r", encoding="utf-8", errors="replace") as f:
                                content = f.read()
                                test_sources[norm_f] = content
                                test_sources[os.path.basename(norm_f)] = content
                        except Exception:
                            pass

    # 2. Extract actual exception or error from test_result
    actual_exceptions: List[str] = []
    combined_err = " ".join([
        test_result.error_message or "",
        " ".join(test_result.assertion_errors or []),
        test_result.traceback_summary or "",
        test_result.stderr or "",
    ])

    for exc_match in re.finditer(r'\b([A-Z][a-zA-Z0-9_]*(?:Error|Exception))\b', combined_err):
        exc_name = exc_match.group(1)
        if exc_name not in ("AssertionError", "TestError") and exc_name not in actual_exceptions:
            actual_exceptions.append(exc_name)

    # 3. For each failing test, locate its source and extract expected contracts
    for ft in test_result.failed_tests:
        test_func_name = ft.split("::")[-1]
        file_hint = ft.split("::")[0] if "::" in ft else ""

        found_test_code = ""
        for src_name, src_code in test_sources.items():
            if file_hint and os.path.basename(file_hint) != os.path.basename(src_name) and file_hint not in src_name:
                continue
            if test_func_name in src_code:
                pattern = rf'(?:def|func|void|fn)\s+{re.escape(test_func_name)}\s*\(.*?\)(?:.*?)(?=(?:\n(?:def|func|class|pub fn|void)\s)|\Z)'
                m = re.search(pattern, src_code, re.DOTALL)
                if m:
                    found_test_code = m.group(0)
                    break
                else:
                    lines = src_code.splitlines()
                    for idx, line in enumerate(lines):
                        if test_func_name in line:
                            found_test_code = "\n".join(lines[idx:min(len(lines), idx + 30)])
                            break
                    if found_test_code:
                        break

        if not found_test_code:
            continue

        # Check for expected exceptions in test code
        expected_exceptions = []
        expected_exceptions.extend(re.findall(r'pytest\.raises\s*\(\s*([A-Za-z0-9_.]+)', found_test_code))
        expected_exceptions.extend(re.findall(r'assertRaises\s*\(\s*([A-Za-z0-9_.]+)', found_test_code))
        expected_exceptions.extend(re.findall(r'assertThrows\s*\(\s*([A-Za-z0-9_.]+)\.class', found_test_code))

        for exp_exc in expected_exceptions:
            exp_exc_clean = exp_exc.split(".")[-1]
            if actual_exceptions:
                for act_exc in actual_exceptions:
                    if exp_exc_clean != act_exc:
                        mismatches.append(
                            f"- EXCEPTION TYPE MISMATCH in test '{test_func_name}':\n"
                            f"  * Expected Exception: {exp_exc_clean}\n"
                            f"  * Actual Raised Exception: {act_exc}\n"
                            f"  * Mandatory Fix: You MUST change the function implementation to raise '{exp_exc_clean}' "
                            f"(or avoid catching/intercepting native {exp_exc_clean}). DO NOT raise '{act_exc}'."
                        )
            else:
                mismatches.append(
                    f"- EXCEPTION CONTRACT in test '{test_func_name}':\n"
                    f"  * Expected Exception: {exp_exc_clean}\n"
                    f"  * Mandatory Fix: The function must raise '{exp_exc_clean}' under the failing condition."
                )

        # Check for explicit contract grounding comments
        grounding_comments = re.findall(r'#\s*(?:Grounded in|Validates|Contract)[:\s]+([^\n]+)', found_test_code, re.IGNORECASE)
        for g_comment in grounding_comments:
            mismatches.append(f"- Test Contract Specification for '{test_func_name}': {g_comment.strip()}")

        # Check for direct assert statements in test function
        assert_lines = [
            line.strip() for line in found_test_code.splitlines()
            if line.strip().startswith("assert ") and "==" in line.strip()
        ]
        for a_line in assert_lines[:2]:
            mismatches.append(f"- Exact Expected Assertion in '{test_func_name}': {a_line}")

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for item in mismatches:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def validate_candidate_interface(
    original_code: str,
    candidate_code: str,
    language: str = "python",
) -> Tuple[bool, Optional[str]]:
    """
    Validates that a candidate patch preserves required public interfaces,
    has valid syntax, does not introduce duplicate definitions, and does not
    substitute test code for target implementation.
    """
    if not candidate_code or not candidate_code.strip():
        return False, "Candidate code is empty."

    if language.lower() in ("python", "py"):
        import ast
        from collections import Counter

        try:
            cand_ast = ast.parse(candidate_code)
        except SyntaxError as e:
            return False, f"Python syntax error in candidate: {e}"
        except Exception as e:
            return False, f"Failed to parse candidate AST: {e}"

        # 1. Detect duplicate top-level function or class definitions
        cand_func_list = [
            node.name
            for node in cand_ast.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        cand_class_list = [
            node.name
            for node in cand_ast.body
            if isinstance(node, ast.ClassDef)
        ]
        cand_counts = Counter(cand_func_list + cand_class_list)
        dups = [name for name, count in cand_counts.items() if count > 1]
        if dups:
            return False, f"Candidate introduced duplicate definition(s): {sorted(dups)}"

        orig_ast = None
        if original_code and original_code.strip():
            try:
                orig_ast = ast.parse(original_code)
            except Exception:
                orig_ast = None

        if orig_ast:
            # Extract top-level public functions and classes from original code (including main and entry points)
            orig_funcs = {
                node.name
                for node in orig_ast.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not node.name.startswith("_")
            }
            orig_classes = {
                node.name
                for node in orig_ast.body
                if isinstance(node, ast.ClassDef)
                and not node.name.startswith("_")
            }
            orig_public = orig_funcs | orig_classes

            cand_funcs = set(cand_func_list)
            cand_classes = set(cand_class_list)
            cand_public = {n for n in (cand_funcs | cand_classes) if not n.startswith("_")}

            # Check if original was not a test file (no test_* functions)
            orig_is_test = any(name.startswith("test_") for name in orig_funcs)
            cand_has_test_funcs = any(name.startswith("test_") for name in cand_funcs)

            # Reject test substitution if original code was implementation
            if not orig_is_test and cand_has_test_funcs:
                if not orig_public.issubset(cand_public):
                    return False, (
                        "Candidate substitutes test suite functions for target implementation "
                        f"and fails to preserve required interface: {sorted(orig_public - cand_public)}"
                    )

            # Check if candidate dropped any required public functions/classes
            missing_public = orig_public - cand_public
            if missing_public:
                return False, f"Candidate dropped required public interface: {sorted(missing_public)}"

    elif language.lower() in ("javascript", "typescript", "js", "ts", "java", "go", "rust", "cpp", "c"):
        from collections import Counter

        def _strip_literals_and_comments(code: str) -> str:
            c = re.sub(r'//[^\n]*', '', code)
            c = re.sub(r'/\*.*?\*/', '', c, flags=re.DOTALL)
            c = re.sub(r'"(?:\\.|[^"\\])*"', '""', c)
            c = re.sub(r"'(?:\\.|[^'\\])*'", "''", c)
            c = re.sub(r'`(?:\\.|[^`\\])*`', '``', c)
            return c

        dups = []
        clean = _strip_literals_and_comments(candidate_code)

        if language.lower() == "java":
            # Scoped Java duplicate detection:
            # 1. Classes: duplicate class name at same scope
            # 2. Methods: duplicate (class_name, method_name, param_types) signature in same class.
            # Preserves valid method overloads with distinct parameter types and same-name methods in different classes.
            lines = clean.splitlines()
            brace_depth = 0
            current_class_stack = []
            class_decl_re = re.compile(r'\b(?:class|interface|enum|record)\s+([a-zA-Z0-9_$]+)')
            method_decl_re = re.compile(
                r'(?:public|protected|private|static|final|native|synchronized|abstract|\s)+'
                r'[\w<>\[\], ?]+\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)\s*(?:throws\s+[\w.,\s]+)?\s*\{'
            )
            class_methods = Counter()
            classes = Counter()

            for line in lines:
                stripped = line.strip()
                m_cls = class_decl_re.search(stripped)
                if m_cls and "{" in stripped:
                    cls_name = m_cls.group(1)
                    classes[cls_name] += 1
                    if classes[cls_name] > 1:
                        dups.append(f"class {cls_name}")
                    current_class_stack.append((brace_depth, cls_name))

                m_meth = method_decl_re.search(stripped)
                if m_meth and "{" in stripped:
                    meth_name = m_meth.group(1)
                    raw_params = m_meth.group(2).strip()
                    param_types = []
                    if raw_params:
                        for param in raw_params.split(','):
                            parts = param.strip().split()
                            if parts:
                                param_types.append(parts[0].split('<')[0])
                    cur_cls = current_class_stack[-1][1] if current_class_stack else "Global"
                    sig = (cur_cls, meth_name, tuple(param_types))
                    class_methods[sig] += 1
                    if class_methods[sig] > 1:
                        dups.append(f"{cur_cls}.{meth_name}({', '.join(param_types)})")

                brace_depth += stripped.count('{') - stripped.count('}')
                while current_class_stack and brace_depth <= current_class_stack[-1][0]:
                    current_class_stack.pop()

        elif language.lower() == "rust":
            # Scoped Rust duplicate detection:
            # Methods are scoped to impl block (impl TargetType or impl Trait for TargetType).
            # Preserves same-name methods in separate impl blocks (e.g. impl Foo vs impl Baz).
            lines = clean.splitlines()
            brace_depth = 0
            current_impl_stack = []
            impl_re = re.compile(r'\bimpl(?:\s+<[^>]+>)?\s+(?:(?P<trait>[\w:]+)\s+for\s+)?(?P<type>[\w:]+)')
            fn_re = re.compile(r'\b(?:pub(?:\([^)]+\))?\s+)?fn\s+([a-zA-Z0-9_]+)\s*\(')
            methods = Counter()
            free_funcs = Counter()

            for line in lines:
                stripped = line.strip()
                m_impl = impl_re.search(stripped)
                if m_impl and "{" in stripped:
                    target_type = m_impl.group("type")
                    trait_name = m_impl.group("trait") or ""
                    impl_scope = f"{trait_name} for {target_type}".strip() if trait_name else target_type
                    current_impl_stack.append((brace_depth, impl_scope))

                m_fn = fn_re.search(stripped)
                if m_fn and not stripped.startswith("//"):
                    fn_name = m_fn.group(1)
                    if current_impl_stack:
                        scope = current_impl_stack[-1][1]
                        sig = (scope, fn_name)
                        methods[sig] += 1
                        if methods[sig] > 1:
                            dups.append(f"impl {scope}::fn {fn_name}")
                    else:
                        free_funcs[fn_name] += 1
                        if free_funcs[fn_name] > 1:
                            dups.append(f"fn {fn_name}")

                brace_depth += stripped.count('{') - stripped.count('}')
                while current_impl_stack and brace_depth <= current_impl_stack[-1][0]:
                    current_impl_stack.pop()

        elif language.lower() == "go":
            # Scoped Go duplicate detection:
            # Free functions checked at package/file level.
            # Receiver methods checked per receiver type (e.g. (f *Foo).Process vs (b *Bar).Process).
            fn_re = re.compile(r'^\s*func\s+(?:\((?P<recv>[^)]+)\)\s+)?(?P<name>[a-zA-Z0-9_]+)\s*\(', re.MULTILINE)
            free_funcs = Counter()
            method_funcs = Counter()

            for m in fn_re.finditer(clean):
                recv = m.group("recv")
                name = m.group("name")
                if recv:
                    parts = recv.strip().split()
                    recv_type = parts[-1].lstrip("*") if parts else "recv"
                    sig = (recv_type, name)
                    method_funcs[sig] += 1
                    if method_funcs[sig] > 1:
                        dups.append(f"({recv_type}).{name}")
                else:
                    free_funcs[name] += 1
                    if free_funcs[name] > 1:
                        dups.append(f"func {name}")

        elif language.lower() in ("javascript", "typescript", "js", "ts"):
            # Scoped TypeScript/JavaScript detection:
            # Preserves method names in different classes and TypeScript overload declarations.
            lines = clean.splitlines()
            brace_depth = 0
            current_class_stack = []
            class_re = re.compile(r'\b(?:class|interface)\s+([a-zA-Z0-9_$]+)')
            fn_impl_re = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\([^)]*\)[^{;]*\{')
            var_re = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*[:=]')
            method_re = re.compile(r'^\s*(?:public|private|protected|static|async|\s)*([a-zA-Z0-9_$]+)\s*\([^)]*\)[^{;]*\{')
            classes = Counter()
            top_level_fns = Counter()
            top_level_vars = Counter()
            class_methods = Counter()

            for line in lines:
                stripped = line.strip()
                m_cls = class_re.search(stripped)
                if m_cls and "{" in stripped:
                    cls_name = m_cls.group(1)
                    classes[cls_name] += 1
                    if classes[cls_name] > 1:
                        dups.append(f"class {cls_name}")
                    current_class_stack.append((brace_depth, cls_name))

                m_fn = fn_impl_re.search(line)
                if m_fn and not current_class_stack:
                    fn_name = m_fn.group(1)
                    top_level_fns[fn_name] += 1
                    if top_level_fns[fn_name] > 1:
                        dups.append(f"function {fn_name}")

                m_var = var_re.search(line)
                if m_var and not current_class_stack:
                    var_name = m_var.group(1)
                    top_level_vars[var_name] += 1
                    if top_level_vars[var_name] > 1:
                        dups.append(f"const/let {var_name}")

                if current_class_stack and "{" in stripped and not m_cls:
                    m_meth = method_re.search(line)
                    if m_meth:
                        meth_name = m_meth.group(1)
                        if meth_name not in ("if", "for", "while", "switch", "catch"):
                            cur_cls = current_class_stack[-1][1]
                            sig = (cur_cls, meth_name)
                            class_methods[sig] += 1
                            if class_methods[sig] > 1:
                                dups.append(f"{cur_cls}.{meth_name}")

                brace_depth += stripped.count('{') - stripped.count('}')
                while current_class_stack and brace_depth <= current_class_stack[-1][0]:
                    current_class_stack.pop()

        if dups:
            return False, f"Candidate introduced duplicate definition(s): {sorted(list(set(dups)))}"

    return True, None


def replace_ast_symbols_in_python(full_original: str, candidate_code: str) -> Optional[str]:
    """Replaces top-level functions and classes in full_original with versions from candidate_code.
    Preserves all other symbols, docstrings, imports, and entry points (such as main) without duplication."""
    import ast
    try:
        orig_tree = ast.parse(full_original)
        cand_tree = ast.parse(candidate_code)
    except Exception:
        return None

    # Detect duplicates within candidate_code itself
    cand_defs = [
        n.name
        for n in cand_tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if len(cand_defs) != len(set(cand_defs)):
        return None

    cand_symbols = {}
    for node in cand_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            segment = ast.get_source_segment(candidate_code, node)
            if segment:
                cand_symbols[node.name] = segment

    if not cand_symbols:
        return None

    orig_lines = full_original.splitlines(keepends=True)
    replacements = []
    matched_names = set()
    for node in orig_tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in cand_symbols:
            replacements.append((node.lineno - 1, node.end_lineno, cand_symbols[node.name]))
            matched_names.add(node.name)

    if not matched_names:
        return None

    replacements.sort(key=lambda r: r[0], reverse=True)
    res_lines = list(orig_lines)
    for s_idx, e_idx, new_snip in replacements:
        res_lines[s_idx:e_idx] = [new_snip + "\n"]

    # Append any brand new symbols defined in candidate that did not exist in orig
    new_names = [n for n in cand_defs if n not in matched_names]
    for n in new_names:
        res_lines.append("\n\n" + cand_symbols[n] + "\n")

    return "".join(res_lines)


def evaluate_patch_approval_gate(
    patch_record: Dict[str, Any],
    security_policy: Optional[str] = None,
    target_repo_id: Optional[str] = None,
    target_repo_path: Optional[str] = None,
) -> Tuple[bool, str]:
    """Central Approval Gate for applying patches to codebases.

    Enforces strict invariants before a proposed candidate patch can be applied:
    0. Repository Isolation Gate:
       - Proposals must have canonical repo_id matching target repository.
       - Missing or non-matching repository identity strictly blocks application.
    1. Behavioral Verification Gate:
       - Requires consistent evidence of successful execution:
         verified=True, test_status='passed', success=True, exit_code=0.
       - Requires at least one passing test (passed_count >= 1).
       - Zero tests executed/passed is strictly rejected.
       - Missing, skipped, failed, timed-out, collection-error, or pre-flight-rejected
         verification blocks application.
       - status="verified" on patch_record CANNOT override contradictory execution evidence.
    2. Security Policy Gate (kept separate from behavioral verification):
       - strict: incomplete, failed, unscanned, or error states block.
       - secrets_only: allow only an explicitly approved result under that policy;
         preserve coverage limitations and policy provenance.
    """
    if not isinstance(patch_record, dict):
        return False, "Approval rejected: invalid patch record (must be a dictionary)."

    target_file = patch_record.get("target_file")
    suggested = patch_record.get("suggested_patch")

    infra_blocker = (
        patch_record.get("infrastructure_blocker")
        or (patch_record.get("infrastructure", {}).get("infrastructure_blocker") if isinstance(patch_record.get("infrastructure"), dict) else None)
        or (patch_record.get("sandbox_validation", {}).get("infrastructure_blocker") if isinstance(patch_record.get("sandbox_validation"), dict) else None)
        or (patch_record.get("sandbox_validation", {}).get("test_result", {}).get("error_message") if isinstance(patch_record.get("sandbox_validation"), dict) and isinstance(patch_record.get("sandbox_validation", {}).get("test_result"), dict) and any(k in str(patch_record.get("sandbox_validation", {}).get("test_result", {}).get("error_message", "")).lower() for k in ("docker", "daemon")) else None)
    )

    if not target_file or not suggested:
        if infra_blocker:
            return False, f"Approval rejected: Docker infrastructure failure ({infra_blocker}). Zero tests executed as a consequence (verification requires at least one passing test)."
        return False, "Approval rejected: invalid patch record (missing target_file or suggested_patch)."

    # ---------------------------------------------------------
    # 0. Repository Isolation Gate
    # ---------------------------------------------------------
    effective_target_repo = target_repo_id
    if not effective_target_repo and target_repo_path:
        from core.persistence import get_repo_id
        effective_target_repo = get_repo_id(target_repo_path)

    if effective_target_repo:
        from core.persistence import is_canonical_repo_id
        prop_repo_id = patch_record.get("repo_id")
        if not is_canonical_repo_id(prop_repo_id):
            return False, f"Approval rejected: Proposal lacks canonical repository identity metadata (missing or basename-only repo_id: '{prop_repo_id}'). Cross-repository safety invariant requires canonical repository identity."
        if prop_repo_id != effective_target_repo:
            return False, f"Security Block: Cross-repository operation rejected. Proposal belongs to repository '{prop_repo_id}', but target repository is '{effective_target_repo}'."

    # ---------------------------------------------------------
    # 1. Behavioral Verification Gate
    # ---------------------------------------------------------
    beh_rejection: Optional[str] = None
    sb_val = patch_record.get("sandbox_validation")
    if not sb_val or not isinstance(sb_val, dict):
        beh_rejection = "Approval rejected: missing sandbox verification metadata. Normal approval requires verified candidate patch."
    else:
        infra_blocker = (
            patch_record.get("infrastructure_blocker")
            or (patch_record.get("infrastructure", {}).get("infrastructure_blocker") if isinstance(patch_record.get("infrastructure"), dict) else None)
            or sb_val.get("infrastructure_blocker")
            or (sb_val.get("test_result", {}).get("error_message") if isinstance(sb_val.get("test_result"), dict) and any(k in str(sb_val.get("test_result", {}).get("error_message", "")).lower() for k in ("docker", "daemon")) else None)
        )

        test_status = str(sb_val.get("test_status", "")).lower().strip()
        if test_status in ("failed", "error", "rejected", "blocked"):
            if infra_blocker:
                beh_rejection = f"Approval rejected: Docker infrastructure failure ({infra_blocker}). Zero tests executed as a consequence (verification requires at least one passing test)."
            else:
                beh_rejection = f"Approval rejected: candidate patch failed test verification (test_status: {test_status})."
        elif test_status in ("timed-out", "timed_out", "timeout"):
            beh_rejection = "Approval rejected: candidate patch failed test verification (sandbox test execution timed out)."
        elif test_status in ("collection_error", "collection-error"):
            beh_rejection = "Approval rejected: candidate patch failed test verification (test collection errors occurred during sandbox execution)."
        elif test_status in ("pre_flight_rejected", "preflight_rejected"):
            beh_rejection = "Approval rejected: candidate patch failed test verification (candidate pre-flight interface validation failed)."
        elif sb_val.get("skipped") is True or test_status == "skipped":
            if infra_blocker:
                beh_rejection = f"Approval rejected: Docker infrastructure failure ({infra_blocker}). Zero tests executed as a consequence (verification requires at least one passing test)."
            else:
                beh_rejection = "Approval rejected: sandbox test execution was skipped. Normal approval requires executed and passing tests."
        else:
            top_total_count = sb_val.get("total_count")
            top_passed_count = sb_val.get("passed_count")
            if (top_total_count is not None and top_total_count <= 0) or (top_passed_count is not None and top_passed_count <= 0):
                if infra_blocker:
                    beh_rejection = f"Approval rejected: Docker infrastructure failure ({infra_blocker}). Zero tests executed as a consequence (verification requires at least one passing test)."
                else:
                    beh_rejection = "Approval rejected: zero tests executed. Verification requires at least one passing test."
            elif sb_val.get("verified") is not True:
                if infra_blocker:
                    beh_rejection = f"Approval rejected: Docker infrastructure failure ({infra_blocker}). Zero tests executed as a consequence (verification requires at least one passing test)."
                elif patch_record.get("requirements_status") in ("partial_coverage", "partial_requirement_coverage") or patch_record.get("has_uncovered_requirements"):
                    missing_info = patch_record.get("missing_coverage") or "unbound, ambiguous, or unverified requirements remain"
                    beh_rejection = (
                        f"Approval rejected: creation proposal only has partial requirement coverage "
                        f"({missing_info}). Behavioral approval requires full requirement coverage."
                    )
                else:
                    beh_rejection = f"Approval rejected: candidate patch failed test verification (verified={sb_val.get('verified')})."
            elif test_status != "passed":
                if infra_blocker:
                    beh_rejection = f"Approval rejected: Docker infrastructure failure ({infra_blocker}). Zero tests executed as a consequence (verification requires at least one passing test)."
                else:
                    beh_rejection = f"Approval rejected: test_status must be 'passed', got '{test_status}'."

        # Inspect test_result / execution evidence
        if not beh_rejection:
            test_res = sb_val.get("test_result")
            if isinstance(test_res, dict):
                if test_res.get("skipped") is True:
                    beh_rejection = "Approval rejected: test execution result indicates tests were skipped."
                elif test_res.get("success") is False:
                    beh_rejection = "Approval rejected: test execution reported success=False."
                else:
                    exit_code = test_res.get("exit_code")
                    if exit_code is not None and exit_code != 0:
                        err_text = (str(test_res.get("error_message") or "") + " " + str(test_res.get("stderr") or "")).lower()
                        if "candidate validation rejected" in err_text or "candidate_interface_validation" in (test_res.get("failed_tests") or []):
                            beh_rejection = "Approval rejected: candidate pre-flight interface validation failed."
                        elif "timeout" in err_text or "timed out" in err_text or exit_code == -1:
                            beh_rejection = "Approval rejected: sandbox test execution timed out."
                        else:
                            beh_rejection = f"Approval rejected: test execution returned non-zero exit code ({exit_code})."
                    elif (test_res.get("failed_count", 0) > 0) or (len(test_res.get("failed_tests") or []) > 0):
                        failed_count = test_res.get("failed_count", 0)
                        failed_tests = test_res.get("failed_tests") or []
                        if "candidate_interface_validation" in failed_tests:
                            beh_rejection = "Approval rejected: candidate pre-flight interface validation failed."
                        else:
                            beh_rejection = f"Approval rejected: test execution reported {failed_count or len(failed_tests)} failing test(s): {failed_tests}."
                    elif len(test_res.get("collection_errors") or []) > 0:
                        beh_rejection = f"Approval rejected: test execution encountered collection errors: {test_res.get('collection_errors')}."
                    else:
                        err_msg = str(test_res.get("error_message") or "")
                        stderr_msg = str(test_res.get("stderr") or "")
                        combined_err = (err_msg + " " + stderr_msg).lower()
                        if "timeout" in combined_err or "timed out" in combined_err:
                            beh_rejection = "Approval rejected: sandbox test execution timed out."
                        elif "test file immutability violation" in combined_err:
                            beh_rejection = "Approval rejected: test file immutability violation detected."
                        elif "candidate validation rejected" in combined_err:
                            beh_rejection = "Approval rejected: candidate pre-flight interface validation failed."
                        else:
                            passed_cnt = test_res.get("passed_count")
                            passed_list = test_res.get("passed_tests")
                            total_cnt = test_res.get("total_count")
                            if passed_cnt is not None and passed_cnt <= 0:
                                beh_rejection = "Approval rejected: zero tests passed. Verification requires at least one passing test."
                            elif passed_list is not None and len(passed_list) == 0 and (passed_cnt is None or passed_cnt == 0):
                                beh_rejection = "Approval rejected: zero tests passed. Verification requires at least one passing test."
                            elif total_cnt is not None and total_cnt <= 0 and (passed_cnt is None or passed_cnt == 0):
                                beh_rejection = "Approval rejected: zero tests executed. Verification requires at least one passing test."

        if not beh_rejection:
            top_failed_count = sb_val.get("failed_count", 0)
            top_failed_tests = sb_val.get("failed_tests") or []
            if top_failed_count > 0 or len(top_failed_tests) > 0:
                beh_rejection = f"Approval rejected: candidate patch reported failing test(s): {top_failed_tests or top_failed_count}."
            elif len(sb_val.get("collection_errors") or []) > 0:
                beh_rejection = f"Approval rejected: test collection errors occurred: {sb_val.get('collection_errors')}."
            elif sb_val.get("passed_count") is not None and sb_val.get("passed_count") <= 0:
                beh_rejection = "Approval rejected: zero tests passed. Verification requires at least one passing test."
            elif sb_val.get("total_count") is not None and sb_val.get("total_count") <= 0 and (sb_val.get("passed_count") is None or sb_val.get("passed_count") == 0):
                beh_rejection = "Approval rejected: zero tests executed. Verification requires at least one passing test."

        # Enforce that smoke-only creation proposals cannot satisfy the behavioral approval requirement
        if not beh_rejection:
            is_creation = patch_record.get("is_new_file") is True or patch_record.get("contract_type") == "ai_generated_candidate_contract"
            if is_creation:
                # 1. Preserve independently supplied test workflows through explicit provenance (not naming heuristics)
                is_independent = bool(
                    patch_record.get("test_provenance") in ("independently_supplied", "user_supplied", "independent")
                    or sb_val.get("test_provenance") in ("independently_supplied", "user_supplied", "independent")
                    or patch_record.get("test_origin") in ("user_supplied", "independent", "suite", "repository", "pre_existing")
                    or (patch_record.get("contract_type") not in ("ai_generated_candidate_contract",) and not patch_record.get("is_new_file"))
                )

                if not is_independent:
                    req_status = str(patch_record.get("requirements_status", "")).lower().strip()
                    sb_req_cnt = sb_val.get("requirement_tests_passed_count")
                    if sb_req_cnt is None and isinstance(sb_val.get("test_result"), dict):
                        sb_req_cnt = sb_val.get("test_result", {}).get("requirement_tests_passed_count")

                    if req_status in ("interface_smoke_only", "smoke_only") or sb_req_cnt == 0 or sb_req_cnt is None:
                        beh_rejection = (
                            "Approval rejected: creation proposal only has smoke/interface verification "
                            "(no requirement-grounded behavioral tests passed). Behavioral approval requires "
                            "verified requirement-grounded tests."
                        )
                    elif req_status in ("partial_coverage", "partial_requirement_coverage") or patch_record.get("has_uncovered_requirements"):
                        missing_info = patch_record.get("missing_coverage") or "unbound, ambiguous, or unverified requirements remain"
                        beh_rejection = (
                            f"Approval rejected: creation proposal only has partial requirement coverage "
                            f"({missing_info}). Behavioral approval requires full requirement coverage."
                        )

    # ---------------------------------------------------------
    # 2. Security Policy Gate (kept separate from behavioral)
    # ---------------------------------------------------------
    sec_rejection: Optional[str] = None
    sec_val = patch_record.get("security_validation")
    sec_policy = (
        security_policy
        or patch_record.get("security_policy")
        or (sec_val.get("security_policy") if isinstance(sec_val, dict) else None)
        or "strict"
    ).lower().strip()

    if not isinstance(sec_val, dict) or not sec_val:
        sec_status = "unscanned"
        sec_approved = False
        sec_coverage = "unknown"
        sec_findings = 0
        record_policy = "unknown"
    else:
        sec_status = str(sec_val.get("security_status", "unscanned")).lower().strip()
        sec_approved = bool(sec_val.get("security_approved", False))
        sec_coverage = str(sec_val.get("security_coverage", sec_val.get("coverage", "unknown"))).lower().strip()
        sec_findings = sec_val.get("failing_findings_count", 0)
        record_policy = str(sec_val.get("security_policy", "strict")).lower().strip()

    if sec_policy == "strict":
        if record_policy == "secrets_only":
            sec_rejection = "Approval rejected: candidate patch was only approved under 'secrets_only' policy and cannot be applied under 'strict' security policy."
        elif sec_status == "unscanned":
            sec_rejection = "Approval rejected: security scan status is 'unscanned'. Strict security policy requires completed security scan."
        elif sec_status == "incomplete":
            sec_rejection = f"Approval rejected: incomplete security coverage ({sec_coverage}) under strict security policy."
        elif sec_status == "failed" or sec_findings > 0:
            sec_rejection = f"Approval rejected: candidate patch failed security scan ({sec_findings} finding(s)). Security scan failed."
        elif sec_status == "error":
            sec_rejection = "Approval rejected: security scanner encountered an error during scan."
        elif sec_status != "passed" and not (sec_status == "incomplete" and sec_coverage == "unsupported" and sec_findings == 0):
            if not sec_approved:
                sec_rejection = f"Approval rejected: security verification not passed under strict policy (status: {sec_status}, approved: {sec_approved})."

    elif sec_policy == "secrets_only":
        if sec_status == "unscanned":
            sec_rejection = "Approval rejected: security scan status is 'unscanned'. Secrets-only policy requires completed secret scan."
        elif sec_status == "failed" or sec_findings > 0:
            sec_rejection = f"Approval rejected: candidate patch failed secrets_only security scan ({sec_findings} secret finding(s))."
        elif sec_status == "error":
            sec_rejection = "Approval rejected: security scanner encountered an error during scan."
        elif sec_status != "passed" or not sec_approved:
            sec_rejection = f"Approval rejected: candidate patch is not explicitly approved under secrets_only policy (status: {sec_status}, approved: {sec_approved})."

    else:
        sec_rejection = f"Approval rejected: unknown security policy '{sec_policy}'."

    # Return combined or individual gate rejection reasons
    if beh_rejection and sec_rejection:
        return False, f"{beh_rejection} Additionally, {sec_rejection}"
    if beh_rejection:
        return False, beh_rejection
    if sec_rejection:
        return False, sec_rejection

    return True, "Approval gate passed."


class PatchEngine:
    """
    Context-aware multi-file patch generation engine with closed-loop sandbox test verification.
    """

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm: Optional[OllamaLLM] = None,
        graph: Optional[nx.DiGraph] = None,
        repo_path: Optional[str] = None,
        sandbox_runner: Optional[SandboxRunner] = None,
        is_admin: bool = False,  # CLI mode should pass True
        allow_local_sandbox: bool = True,  # CLI mode should pass True
        default_timeout: Optional[Union[int, float]] = None,
        experience_bank: Optional[RepairExperienceBank] = None,
        allow_heuristic_fallback: bool = True,
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.graph = graph
        self.repo_path = repo_path
        if default_timeout is not None:
            self.default_timeout = validate_timeout(default_timeout, "default_timeout")
            self._explicit_default_timeout = True
        else:
            self.default_timeout = None
            self._explicit_default_timeout = False
        self.allow_heuristic_fallback = allow_heuristic_fallback
        if experience_bank is False:
            self.experience_bank = None
        elif experience_bank is not None:
            self.experience_bank = experience_bank
        else:
            self.experience_bank = global_experience_bank
        self.localizer = BugLocalizer(store, embedder, graph)
        # Initialize sandbox_runner with config if not provided
        if sandbox_runner is None:
            try:
                from backend.config import settings
                self.sandbox_runner = SandboxRunner(
                    sandbox_mode=settings.SANDBOX_MODE,
                    docker_image=settings.SANDBOX_DOCKER_IMAGE,
                    allow_local_sandbox=allow_local_sandbox or settings.ALLOW_LOCAL_SANDBOX,
                    is_admin=is_admin,
                    default_timeout=self.default_timeout,
                )
            except ImportError:
                self.sandbox_runner = SandboxRunner(
                    is_admin=is_admin,
                    allow_local_sandbox=allow_local_sandbox,
                    default_timeout=self.default_timeout,
                )
            if not self._explicit_default_timeout:
                self.default_timeout = self.sandbox_runner.default_timeout
        else:
            self.sandbox_runner = sandbox_runner
            if not self._explicit_default_timeout:
                runner_timeout = getattr(sandbox_runner, "default_timeout", None)
                if runner_timeout is not None:
                    self.default_timeout = runner_timeout
                else:
                    self.default_timeout = DEFAULT_TIMEOUT

    def generate_patch(
        self,
        repo_id: str,
        error_report: str,
        target_file: Optional[str] = None,
        verify_in_sandbox: bool = False,
        test_command: Optional[str] = None,
        max_iterations: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        owner_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generates a patch recommendation based on error report and repository context.
        If verify_in_sandbox is True, runs closed-loop test-driven repair up to max_iterations.
        """
        if verify_in_sandbox and self.repo_path:
            return self.generate_and_verify_patch(
                repo_id=repo_id,
                error_report=error_report,
                target_file=target_file,
                test_command=test_command,
                max_iterations=max_iterations,
                progress_callback=progress_callback,
                owner_id=owner_id,
                **kwargs,
            )

        raw_loc = self.localizer.localize(error_report, top_k=3)
        localization = copy.deepcopy(raw_loc)
        candidates = copy.deepcopy(localization.get("candidates", []))

        if not candidates:
            disk_fallback = self._read_file(target_file) if target_file else None
            if disk_fallback:
                candidates = [{
                    "file_path": target_file,
                    "snippet": disk_fallback,
                    "confidence_score": 0.8,
                }]
            else:
                return self._failed_patch(
                    repo_id, target_file, "No relevant repository context was found matching the error report."
                )

        if target_file:
            from core.canonical_path import resolve_canonical_target_path
            all_indexed = [c.file_path for c in self.store.chunks] if hasattr(self, "store") and self.store and hasattr(self.store, "chunks") else None
            canon_tgt, disambig_err = resolve_canonical_target_path(self.repo_path or ".", target_file, candidate_files=all_indexed)
            if disambig_err:
                return self._failed_patch(repo_id, target_file, disambig_err)
            if canon_tgt:
                target_file = canon_tgt

            norm_target = target_file.replace("\\", "/").lstrip("./")
            matching_candidate = next(
                (c for c in candidates if c.get("file_path", "").replace("\\", "/").lstrip("./") == norm_target),
                None
            )
            disk_content = self._read_file(target_file)
            if disk_content is None:
                if matching_candidate and not self.repo_path:
                    disk_content = matching_candidate.get("snippet", "")
                else:
                    return self._failed_patch(repo_id, target_file, f"Target file '{target_file}' could not be read from disk.")

            file_path = target_file
            if matching_candidate and matching_candidate.get("snippet", "") in disk_content:
                top_candidate = matching_candidate
                snippet = matching_candidate["snippet"]
            else:
                # Target disk content is authoritative. Never use snippets from test files or other candidates.
                snippet = disk_content
                top_candidate = {
                    "file_path": target_file,
                    "snippet": disk_content,
                    "confidence_score": 1.0,
                    "line_number": 1,
                }
            full_original = disk_content
            using_full_file = full_original.strip() != snippet.strip()
            file_read_from_disk = self._read_file(target_file) is not None
        else:
            top_candidate = candidates[0]
            file_path = top_candidate.get("file_path", "")
            disk_content = self._read_file(file_path)
            cand_snip = top_candidate.get("snippet", "")
            if cand_snip and disk_content and cand_snip in disk_content:
                snippet = cand_snip
            else:
                snippet = disk_content if disk_content else cand_snip
            full_original = disk_content or snippet
            using_full_file = full_original.strip() != snippet.strip()
            file_read_from_disk = disk_content is not None

        language = self._detect_language(file_path)
        localization_confidence = top_candidate.get("confidence_score", 0.5)

        rag_chunks = self._retrieve_rag_chunks(error_report, file_path, top_k=4)
        rag_context = format_context(rag_chunks) if rag_chunks else ""

        suggested_snippet, explanation, llm_generated = self._generate_fix(
            error_report=error_report,
            file_path=file_path,
            snippet=snippet,
            rag_context=rag_context,
            localization=localization,
            top_candidate=top_candidate,
            language=language,
        )

        patched_full, diff_original = self._assemble_patched_file(
            full_original, snippet, suggested_snippet, using_full_file, top_candidate, language=language
        )


        git_diff = generate_git_diff(diff_original, patched_full, file_path)

        validation = validate_patch(
            patched_code=patched_full,
            git_diff=git_diff,
            language=language,
            repo_path=self.repo_path,
            original_code=diff_original,
        )
        confidence_score = compute_patch_quality_score(
            localization_confidence=localization_confidence,
            syntax_valid=validation["syntax_valid"],
            git_apply_valid=validation["git_apply_valid"] or validation.get("git_apply_skipped", False),
            has_changes=validation["has_changes"],
            llm_generated=llm_generated,
        )

        patch_id = str(uuid.uuid4())
        patch_record = {
            "patch_id": patch_id,
            "repo_id": repo_id,
            "target_file": file_path,
            "original_code": diff_original,
            "using_full_file": using_full_file,
            "file_read_from_disk": file_read_from_disk,
            "original_hash": hashlib.sha256(diff_original.encode("utf-8")).hexdigest() if file_read_from_disk else None,
            "suggested_patch": patched_full,
            "snippet_patch": suggested_snippet,
            "git_diff": git_diff,
            "explanation": explanation,
            "confidence_score": confidence_score,
            "localization_confidence": localization_confidence,
            "localization": {
                "candidates": candidates,
                "root_cause_explanation": localization.get("root_cause_explanation", ""),
                "parsed_frames": localization.get("parsed_frames", []),
            },
            "rag_context_chunks": [
                {
                    "file": c.file_path,
                    "name": c.name,
                    "lines": f"{c.start_line}-{c.end_line}",
                    "score": round(float(s), 3),
                }
                for c, s in rag_chunks
            ],
            "validation": validation,
            "sandbox_validation": {
                "verified": False,
                "test_status": "skipped",
                "iterations_count": 1,
            },
            "llm_generated": llm_generated,
            "error_type": localization.get("error_type", "UnknownError"),
            "owner_id": owner_id,
            "status": "pending",
            "created_at": time.time(),
        }

        # Dynamically record patch entry if db_manager is available
        try:
            from backend.database.mongo import db_manager
            db_manager.insert("generated_patches", patch_record)
        except Exception:
            pass

        return patch_record

    def generate_and_verify_patch(
        self,
        repo_id: str,
        error_report: str,
        target_file: Optional[str] = None,
        test_command: Optional[str] = None,
        max_iterations: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        owner_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Closed-Loop Agentic Test-Driven Repair (Milestone 1).
        Generates patch, tests inside isolated sandbox, and refines if tests fail (up to max_iterations).
        """
        raw_loc = self.localizer.localize(error_report, top_k=3)
        localization = copy.deepcopy(raw_loc)
        candidates = copy.deepcopy(localization.get("candidates", []))

        if not candidates:
            disk_fallback = self._read_file(target_file) if target_file else None
            if disk_fallback:
                candidates = [{
                    "file_path": target_file,
                    "snippet": disk_fallback,
                    "confidence_score": 0.8,
                }]
            else:
                return self._failed_patch(
                    repo_id, target_file, "No relevant repository context was found matching the error report."
                )

        if target_file:
            from core.canonical_path import resolve_canonical_target_path
            all_indexed = [c.file_path for c in self.store.chunks] if hasattr(self, "store") and self.store and hasattr(self.store, "chunks") else None
            canon_tgt, disambig_err = resolve_canonical_target_path(self.repo_path or ".", target_file, candidate_files=all_indexed)
            if disambig_err:
                return self._failed_patch(repo_id, target_file, disambig_err)
            if canon_tgt:
                target_file = canon_tgt

            norm_target = target_file.replace("\\", "/").lstrip("./")
            matching_candidate = next(
                (c for c in candidates if c.get("file_path", "").replace("\\", "/").lstrip("./") == norm_target),
                None
            )
            disk_content = self._read_file(target_file)
            if disk_content is None:
                return self._failed_patch(repo_id, target_file, f"Target file '{target_file}' could not be read from disk.")

            file_path = target_file
            if matching_candidate and matching_candidate.get("snippet", "") in disk_content:
                top_candidate = matching_candidate
                snippet = matching_candidate["snippet"]
            else:
                # Target disk content is authoritative. Never use snippets from test files or other candidates.
                snippet = disk_content
                top_candidate = {
                    "file_path": target_file,
                    "snippet": disk_content,
                    "confidence_score": 1.0,
                    "line_number": 1,
                }
            full_original = disk_content
            using_full_file = full_original.strip() != snippet.strip()
            file_read_from_disk = True
        else:
            top_candidate = candidates[0]
            file_path = top_candidate.get("file_path", "")
            disk_content = self._read_file(file_path)
            cand_snip = top_candidate.get("snippet", "")
            if cand_snip and disk_content and cand_snip in disk_content:
                snippet = cand_snip
            else:
                snippet = disk_content if disk_content else cand_snip
            full_original = disk_content or snippet
            using_full_file = full_original.strip() != snippet.strip()
            file_read_from_disk = disk_content is not None

        language = self._detect_language(file_path)
        localization_confidence = top_candidate.get("confidence_score", 0.5)

        rag_chunks = self._retrieve_rag_chunks(error_report, file_path, top_k=4)
        rag_context = format_context(rag_chunks) if rag_chunks else ""

        user_contract = kwargs.get("user_contract")
        extra_files = kwargs.get("extra_files")

        current_snippet = snippet
        current_explanation = ""
        llm_generated = False
        iteration_history: List[Dict[str, Any]] = []
        final_test_result: Optional[SandboxTestResult] = None

        seen_candidates: Dict[str, int] = {}
        best_candidate_full: Optional[str] = None
        best_diff_original: Optional[str] = None
        best_explanation: str = ""
        best_passed_count: int = -1
        is_repeated = False
        repeated_from_turn: Optional[int] = None

        for turn in range(1, max_iterations + 1):
            if progress_callback:
                progress_callback(turn, max_iterations, f"Generating candidate patch (Turn {turn}/{max_iterations})...")

            if turn == 1:
                current_snippet, current_explanation, llm_generated = self._generate_fix(
                    error_report=error_report,
                    file_path=file_path,
                    snippet=snippet,
                    rag_context=rag_context,
                    localization=localization,
                    top_candidate=top_candidate,
                    language=language,
                    user_contract=user_contract,
                )
            else:
                current_snippet, current_explanation, llm_generated = self._refine_fix(
                    error_report=error_report,
                    file_path=file_path,
                    snippet=snippet,
                    current_patch=current_snippet,
                    test_result=final_test_result,
                    rag_context=rag_context,
                    language=language,
                    full_original=full_original,
                    user_contract=user_contract,
                    extra_files=extra_files,
                    is_repeated=is_repeated,
                    repeated_from_turn=repeated_from_turn,
                )

            patched_full, diff_original = self._assemble_patched_file(
                full_original, snippet, current_snippet, using_full_file, top_candidate, language=language
            )

            cand_hash = hashlib.sha256(patched_full.encode("utf-8")).hexdigest()
            is_repeated = cand_hash in seen_candidates
            repeated_from_turn = seen_candidates.get(cand_hash)
            seen_candidates[cand_hash] = turn
            if is_repeated:
                logger.warning("Turn %d produced candidate identical to Turn %d", turn, repeated_from_turn)

            # Pre-flight candidate validation: syntax and interface preservation
            is_valid_cand, cand_val_err = validate_candidate_interface(
                full_original, patched_full, language=language
            )
            if not is_valid_cand:
                val_msg = f"Candidate validation rejected: {cand_val_err}"
                logger.warning("Turn %d rejected by candidate validation: %s", turn, cand_val_err)
                final_test_result = SandboxTestResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=val_msg,
                    duration_seconds=0.0,
                    framework=language,
                    passed_count=0,
                    failed_count=1,
                    total_count=1,
                    failed_tests=["candidate_interface_validation"],
                    assertion_errors=[val_msg],
                    traceback_summary=val_msg,
                    error_message=val_msg,
                )
                iteration_history.append({
                    "turn": turn,
                    "explanation": current_explanation,
                    "test_passed": False,
                    "skipped": False,
                    "exit_code": -1,
                    "duration": 0.0,
                    "failed_count": 1,
                    "passed_count": 0,
                    "total_count": 1,
                    "failed_tests": ["candidate_interface_validation"],
                    "passed_tests": [],
                    "assertion_errors": [val_msg],
                    "stdout": "",
                    "stderr": val_msg,
                    "candidate_code": patched_full,
                })
                continue

            # Test candidate patch inside isolated sandbox
            if self.repo_path:
                if progress_callback:
                    progress_callback(turn, max_iterations, f"Running sandbox test suite (Turn {turn}/{max_iterations})...")

                # Timeout precedence: call override > explicit engine setting > runner default > fallback
                if "timeout" in kwargs and kwargs["timeout"] is not None:
                    effective_call_timeout = validate_timeout(kwargs["timeout"], "timeout")
                elif self._explicit_default_timeout:
                    effective_call_timeout = self.default_timeout
                elif getattr(self.sandbox_runner, "default_timeout", None) is not None:
                    effective_call_timeout = self.sandbox_runner.default_timeout
                else:
                    effective_call_timeout = self.default_timeout or DEFAULT_TIMEOUT

                test_res = self.sandbox_runner.run_tests_with_patch(
                    repo_path=self.repo_path,
                    target_file=file_path,
                    patched_code=patched_full,
                    test_command=test_command,
                    timeout=effective_call_timeout,
                    runtime=language,
                    extra_files=extra_files,
                )
                final_test_result = test_res

                if test_res.passed_count >= best_passed_count or best_candidate_full is None:
                    best_passed_count = test_res.passed_count
                    best_candidate_full = patched_full
                    best_diff_original = diff_original
                    best_explanation = current_explanation

                iteration_history.append({
                    "turn": turn,
                    "explanation": current_explanation,
                    "test_passed": test_res.success,
                    "skipped": test_res.skipped,
                    "exit_code": test_res.exit_code,
                    "duration": test_res.duration_seconds,
                    "failed_count": test_res.failed_count,
                    "passed_count": test_res.passed_count,
                    "total_count": test_res.total_count,
                    "failed_tests": test_res.failed_tests,
                    "passed_tests": test_res.passed_tests,
                    "assertion_errors": test_res.assertion_errors,
                    "test_command": getattr(test_res, "test_command", None),
                    "working_dir": getattr(test_res, "working_dir", None),
                    "patched_file_path": getattr(test_res, "patched_file_path", file_path),
                    "stdout": test_res.stdout,
                    "stderr": test_res.stderr,
                    "candidate_code": patched_full,
                })

                if test_res.success and not test_res.skipped and test_res.passed_count > 0:
                    best_candidate_full = patched_full
                    best_diff_original = diff_original
                    best_explanation = current_explanation
                    break
            else:
                break

        # Final patch selection: ensure final diff, candidate hash, and test result correspond to the exact same candidate evaluated
        if best_candidate_full is not None:
            patched_full = best_candidate_full
            diff_original = best_diff_original or full_original
            current_explanation = best_explanation or current_explanation
        else:
            patched_full, diff_original = self._assemble_patched_file(
                full_original, snippet, current_snippet, using_full_file, top_candidate, language=language
            )

        git_diff = generate_git_diff(diff_original, patched_full, file_path)

        validation = validate_patch(
            patched_code=patched_full,
            git_diff=git_diff,
            language=language,
            repo_path=self.repo_path,
            original_code=diff_original,
        )

        # Pre-flight candidate validation on final assembled code
        final_valid_cand, final_cand_val_err = validate_candidate_interface(
            full_original, patched_full, language=language
        )

        test_passed = final_test_result.success if final_test_result else False
        test_skipped = final_test_result.skipped if final_test_result else True
        passed_count = final_test_result.passed_count if final_test_result else 0
        is_truly_verified = bool(test_passed and not test_skipped and passed_count > 0 and final_valid_cand)

        base_score = compute_patch_quality_score(
            localization_confidence=localization_confidence,
            syntax_valid=validation["syntax_valid"],
            git_apply_valid=validation["git_apply_valid"] or validation.get("git_apply_skipped", False),
            has_changes=validation["has_changes"],
            llm_generated=llm_generated,
        )
        # Boost confidence when tests pass in sandbox
        if is_truly_verified:
            confidence_score = min(0.99, base_score + 0.15)
        elif not test_passed and not test_skipped:
            confidence_score = max(0.1, base_score - 0.25)
        else:
            confidence_score = base_score

        patch_id = str(uuid.uuid4())
        contract_type = kwargs.get("contract_type", "existing_tests")
        patch_record = {
            "patch_id": patch_id,
            "repo_id": repo_id,
            "target_file": file_path,
            "original_code": diff_original,
            "using_full_file": using_full_file,
            "file_read_from_disk": file_read_from_disk,
            "original_hash": hashlib.sha256(diff_original.encode("utf-8")).hexdigest() if file_read_from_disk else None,
            "suggested_patch": patched_full,
            "snippet_patch": current_snippet,
            "git_diff": git_diff,
            "explanation": current_explanation,
            "confidence_score": confidence_score,
            "localization_confidence": localization_confidence,
            "localization": {
                "candidates": candidates,
                "root_cause_explanation": localization.get("root_cause_explanation", ""),
                "parsed_frames": localization.get("parsed_frames", []),
            },
            "rag_context_chunks": [
                {
                    "file": c.file_path,
                    "name": c.name,
                    "lines": f"{c.start_line}-{c.end_line}",
                    "score": round(float(s), 3),
                }
                for c, s in rag_chunks
            ],
            "validation": validation,
            "sandbox_validation": {
                "verified": is_truly_verified,
                "skipped": test_skipped,
                "test_status": "passed" if is_truly_verified else ("skipped" if test_skipped else "failed"),
                "iterations_count": len(iteration_history) or 1,
                "iteration_history": iteration_history,
                "test_result": final_test_result.to_dict() if final_test_result else None,
                "contract_type": contract_type,
                "contract_disclaimer": (
                    "Candidate passes AI-generated proposed test contract. Independently established correctness requires manual human audit."
                    if contract_type == "ai_generated_proposal" and is_truly_verified else None
                ),
            },
            "llm_generated": llm_generated,
            "error_type": localization.get("error_type", "UnknownError"),
            "owner_id": owner_id,
            "status": "verified" if is_truly_verified else "pending",
            "reproducibility": {
                "target_file": file_path,
                "target_sha256": hashlib.sha256(diff_original.encode("utf-8")).hexdigest() if diff_original else None,
                "candidate_sha256": hashlib.sha256(patched_full.encode("utf-8")).hexdigest() if patched_full else None,
                "test_files": [
                    {"path": ef_k, "sha256": hashlib.sha256(ef_v.encode("utf-8")).hexdigest()}
                    for ef_k, ef_v in (kwargs.get("extra_files") or {}).items()
                ],
                "execution_configuration": {
                    "sandbox_mode": getattr(self.sandbox_runner, "sandbox_mode", "docker"),
                    "docker_image": getattr(self.sandbox_runner, "docker_image", "intellicodex-sandbox:latest"),
                    "runtime": language,
                    "timeout": effective_call_timeout if 'effective_call_timeout' in locals() else None,
                },
                "candidate_test_outcome": final_test_result.to_dict() if final_test_result else None,
                "candidate_validation_passed": final_valid_cand,
                "candidate_validation_error": final_cand_val_err if not final_valid_cand else None,
            },
            "created_at": time.time(),
        }

        # Security scan candidate patched code before recording as approved repair
        cand_sec_status = "unscanned"
        cand_sec_coverage = "unknown"
        cand_sec_policy = "strict"
        cand_sec_approved = False
        cand_sec_findings_cnt = 0
        try:
            from core.security_scanner import run_security_scan
            with tempfile.TemporaryDirectory(prefix="cand_sec_") as tmp_sdir:
                tmp_file = os.path.join(tmp_sdir, os.path.basename(file_path))
                with open(tmp_file, "w", encoding="utf-8") as sf:
                    sf.write(patched_full)
                cand_sec = run_security_scan(tmp_sdir, repo_root=tmp_sdir, severity_threshold="HIGH")
                cand_sec_status = cand_sec.get("status", "error")
                cand_sec_coverage = cand_sec.get("coverage_status", "unknown")
                cand_sec_policy = cand_sec.get("security_policy", "strict")
                cand_sec_findings_cnt = cand_sec.get("failing_findings_count", 0)
                cand_sec_approved = bool(
                    cand_sec_status == "passed"
                    or (cand_sec_status == "incomplete" and cand_sec_coverage == "unsupported" and cand_sec_findings_cnt == 0)
                )
        except Exception:
            pass

        patch_record["security_validation"] = {
            "security_status": cand_sec_status,
            "security_coverage": cand_sec_coverage,
            "security_policy": cand_sec_policy,
            "security_approved": cand_sec_approved,
            "failing_findings_count": cand_sec_findings_cnt,
        }

        # Record verified fix in self-improving experience bank (REQ-FUT-10)
        # CRITICAL: A candidate that failed security checks MUST NEVER be recorded as an approved repair!
        if is_truly_verified and cand_sec_status != "failed" and self.experience_bank:
            try:
                self.experience_bank.record_success(
                    error_type=localization.get("error_type", "UnknownError"),
                    error_description=error_report,
                    original_code=snippet,
                    fixed_code=current_snippet,
                    explanation=current_explanation,
                    source="sandbox_pass",
                    language=language,
                    test_verified=True,
                    developer_approved=False,
                    security_approved=cand_sec_approved,
                    security_status=cand_sec_status,
                    security_coverage=cand_sec_coverage,
                    security_policy=cand_sec_policy,
                    repo_id=repo_id,
                    event_id=f"sandbox:{repo_id}:{patch_id}",
                )
            except Exception:
                pass

        # Dynamically record patch entry if db_manager is available
        try:
            from backend.database.mongo import db_manager
            db_manager.insert("generated_patches", patch_record)
        except Exception:
            pass

        return patch_record

    def apply_patch(
        self,
        patch_record: Dict[str, Any],
        approved_by: Optional[str] = None,
        force: bool = False,
        security_policy: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Applies suggested patch directly to physical file on disk.
        Enforces review gate: patch must be approved or explicitly confirmed.
        Enforces central approval gate: candidate must pass both behavioral verification
        and security policy verification (force does not bypass verification).
        Checks for concurrent file modification conflicts unless force=True.
        Records an audit log entry upon successful application.
        """
        if not self.repo_path:
            return False, "repo_path is not set"
        target_file = patch_record.get("target_file")
        suggested = patch_record.get("suggested_patch")
        if not target_file or not suggested:
            return False, "Invalid patch record"

        # Invariant 0: Repository Identity Verification (force=True CANNOT bypass this)
        from core.persistence import get_repo_id, is_canonical_repo_id
        target_repo_id = get_repo_id(self.repo_path)
        prop_repo_id = patch_record.get("repo_id")
        if not is_canonical_repo_id(prop_repo_id):
            return False, f"Approval rejected: Proposal lacks canonical repository identity metadata (missing or basename-only repo_id: '{prop_repo_id}'). Cross-repository safety invariant requires canonical repository identity."
        if prop_repo_id != target_repo_id:
            return False, f"Security Block: Cross-repository operation rejected. Proposal belongs to repository '{prop_repo_id}', but target repository is '{target_repo_id}'."

        # Central Approval Gate: Always enforce behavioral and security approval.
        # Normal user/API approval MUST NOT silently bypass verification via force=True.
        effective_sec_policy = security_policy or getattr(self, "security_policy", None)
        ok_gate, gate_msg = evaluate_patch_approval_gate(
            patch_record, security_policy=effective_sec_policy, target_repo_id=target_repo_id
        )
        if not ok_gate:
            return False, gate_msg


        is_disk_tracked = patch_record.get("file_read_from_disk", patch_record.get("using_full_file", False))
        expected_original = None if force or not is_disk_tracked else patch_record.get("original_code")
        expected_hash = None if force or not is_disk_tracked else patch_record.get("original_hash")

        res = apply_patch_to_file(
            self.repo_path,
            target_file,
            suggested,
            expected_original=expected_original,
            expected_hash=expected_hash,
        )
        if res.get("success"):
            patch_record["status"] = "applied"
            patch_id = patch_record.get("patch_id", "unknown")

            # Persist audit log entry
            self._write_audit_log(
                event="apply_patch",
                patch_id=patch_id,
                target_file=target_file,
                user=approved_by or "system",
                status="applied",
            )

            # Record approved fix in self-improving experience bank (REQ-FUT-10)
            if self.experience_bank:
                try:
                    orig_snip = patch_record.get("original_code", "")
                    fix_snip = patch_record.get("snippet_patch") or patch_record.get("suggested_patch", "")
                    err_type = (
                        patch_record.get("error_type")
                        or patch_record.get("localization", {}).get("error_type")
                        or "UnknownError"
                    )
                    is_test_verified = patch_record.get("sandbox_validation", {}).get("verified", False)
                    sec_val = patch_record.get("security_validation") or {}
                    if orig_snip and fix_snip:
                        self.experience_bank.record_success(
                            error_type=err_type,
                            error_description=patch_record.get("explanation", ""),
                            original_code=orig_snip,
                            fixed_code=fix_snip,
                            explanation=patch_record.get("explanation", ""),
                            source="developer_approval",
                            language=self._detect_language(target_file),
                            test_verified=is_test_verified,
                            developer_approved=True,
                            security_approved=sec_val.get("security_approved", False),
                            security_status=sec_val.get("security_status", "unscanned"),
                            security_coverage=sec_val.get("security_coverage", "unknown"),
                            security_policy=sec_val.get("security_policy", effective_sec_policy or "strict"),
                            repo_id=patch_record.get("repo_id"),
                            event_id=f"approval:{patch_id}",
                        )
                except Exception:
                    pass

            return True, f"Successfully applied patch to '{target_file}'!"
        return False, f"Failed to apply patch: {res.get('error', 'unknown error')}"


    def update_patch_status(
        self,
        patch_id: str,
        status: str,
        manual_edit: Optional[str] = None,
        user: Optional[str] = None,
        security_policy: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Updates proposal status (approved, rejected, applied) and manages review gate lifecycle."""
        try:
            from backend.database.mongo import db_manager
        except ImportError:
            db_manager = None

        record = None
        if db_manager:
            record = db_manager.find_one("generated_patches", {"patch_id": patch_id})

        if not record:
            return None

        # Enforce Repository Identity & Isolation:
        # Cross-repo or legacy proposals cannot be updated, approved, or rejected from another repo.
        if self.repo_path:
            from core.persistence import get_repo_id, is_canonical_repo_id
            target_repo_id = get_repo_id(self.repo_path)
            prop_repo_id = record.get("repo_id")
            if not is_canonical_repo_id(prop_repo_id) or prop_repo_id != target_repo_id:
                return None

        update_fields: Dict[str, Any] = {"status": status}
        if manual_edit:
            update_fields["suggested_patch"] = manual_edit
            record["suggested_patch"] = manual_edit

        if status == "applied":
            ok_apply, msg_apply = self.apply_patch(record, approved_by=user, security_policy=security_policy)
            update_fields["apply_result"] = {"success": ok_apply, "message": msg_apply}
            record["apply_result"] = update_fields["apply_result"]
            if not ok_apply:
                # Do NOT mark status as applied if patch application was rejected!
                update_fields["status"] = record.get("status", "pending")
        else:
            self._write_audit_log(
                event=f"patch_{status}",
                patch_id=patch_id,
                target_file=record.get("target_file", ""),
                user=user or "developer",
                status=status,
            )

        if db_manager:
            db_manager.update_one(
                "generated_patches",
                {"patch_id": patch_id},
                {"$set": update_fields},
            )

        record.update(update_fields)
        return record

    def _write_audit_log(self, event: str, patch_id: str, target_file: str, user: str, status: str):
        """Appends an audit log record to .storage/patch_audit.log and db_manager."""
        audit_entry = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "patch_id": patch_id,
            "target_file": target_file,
            "user": user,
            "status": status,
        }

        # 1. Local append log
        try:
            from backend.config import settings
            storage_dir = settings.STORAGE_DIR
        except Exception:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            storage_dir = os.environ.get("STORAGE_DIR") or os.path.join(repo_root, ".storage")

        os.makedirs(storage_dir, exist_ok=True)
        audit_path = os.path.join(storage_dir, "patch_audit.log")
        import json
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry) + "\n")

        # 2. Database manager
        try:
            from backend.database.mongo import db_manager
            db_manager.insert("patch_audit_log", audit_entry)
        except Exception:
            pass


    def _assemble_patched_file(
        self,
        full_original: str,
        snippet: str,
        suggested_snippet: str,
        using_full_file: bool,
        top_candidate: Dict[str, Any],
        language: str = "python",
    ) -> Tuple[str, str]:
        """Helper to merge snippet into full file or return snippet directly.
        Always returns (patched_full, diff_original) where diff_original is full_original."""
        diff_original = full_original if full_original else snippet

        if not suggested_snippet or not suggested_snippet.strip():
            return full_original, diff_original

        # Preserve package and import headers for Java, Go, Rust, C, C++ if candidate is missing them
        if full_original and suggested_snippet and language.lower() in ("java", "go", "c", "cpp", "rust"):
            pkg_m = re.search(r'^\s*package\s+[\w.]+;?', full_original, re.MULTILINE)
            if pkg_m and not re.search(r'^\s*package\s+[\w.]+;?', suggested_snippet, re.MULTILINE):
                sym_m = re.search(r'^\s*(?:public\s+|private\s+|protected\s+)?(?:class|interface|enum|func|type)\b', full_original, re.MULTILINE)
                if sym_m:
                    header = full_original[:sym_m.start()].strip() + "\n\n"
                    suggested_snippet = header + suggested_snippet.lstrip()

        # 1. Check if suggested_snippet is a valid full-file replacement that preserves interfaces
        is_full_valid, _ = validate_candidate_interface(full_original, suggested_snippet, language=language)
        if is_full_valid:
            return suggested_snippet, diff_original

        # 2. For Python: try AST symbol replacement into full_original
        # Replaces matching top-level functions/classes while preserving main, entry points, and other functions
        if language.lower() in ("python", "py") and full_original:
            ast_merged = replace_ast_symbols_in_python(full_original, suggested_snippet)
            if ast_merged:
                is_ast_valid, _ = validate_candidate_interface(full_original, ast_merged, language=language)
                if is_ast_valid:
                    return ast_merged, diff_original

        # 3. Try snippet replacement via merge_snippet_into_file
        target_snip = snippet if using_full_file else top_candidate.get("snippet", "")
        if target_snip and full_original:
            merged = merge_snippet_into_file(
                full_original,
                target_snip,
                suggested_snippet,
                start_line=top_candidate.get("line_number", 1),
            )
            if merged is not None:
                is_merged_valid, _ = validate_candidate_interface(full_original, merged, language=language)
                if is_merged_valid:
                    return merged, diff_original

        # 4. Fallback: return suggested_snippet if valid, else keep full_original to prevent corruption
        if is_full_valid:
            return suggested_snippet, diff_original
        return full_original, diff_original


    def _read_file(self, file_path: str) -> Optional[str]:
        if not self.repo_path:
            return None
        try:
            abs_path = resolve_within(self.repo_path, file_path)
        except ValueError as exc:
            logger.warning(
                "core.patch_generator._read_file: path traversal rejected "
                "for file_path=%r: %s", file_path, exc,
            )
            return None
        if not os.path.isfile(abs_path):
            return None
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def _retrieve_rag_chunks(
        self, error_report: str, target_file: str, top_k: int = 4
    ) -> List[tuple]:
        query_vec = self.embedder.embed([error_report])[0]
        results = self.store.search(query_vec, top_k=top_k * 2)
        same_file = [(c, s) for c, s in results if c.file_path == target_file]
        other = [(c, s) for c, s in results if c.file_path != target_file]
        return (same_file + other)[:top_k]

    def _generate_fix(
        self,
        error_report: str,
        file_path: str,
        snippet: str,
        rag_context: str,
        localization: Dict[str, Any],
        top_candidate: Dict[str, Any],
        language: str,
        user_contract: Optional[str] = None,
    ) -> tuple:
        if self.llm:
            try:
                prompt = self._build_llm_prompt(
                    error_report, file_path, snippet, rag_context, localization, user_contract=user_contract
                )
                temp = getattr(self.llm, "temperature", 0.0)
                llm_response = self.llm.generate(prompt, system=PATCH_SYSTEM_PROMPT, temperature=temp)
                code, explanation = extract_code_and_explanation(llm_response)
                code = strip_language_prefix(code, language)
                if code and code.strip():
                    return code, explanation, True
            except Exception:
                pass

        if not self.llm or getattr(self, "allow_heuristic_fallback", True):
            patched, explanation = self._heuristic_fix(
                snippet, localization, top_candidate
            )
            return patched, explanation, False

        return snippet, "LLM failed to generate a patch candidate", False

    def _refine_fix(
        self,
        error_report: str,
        file_path: str,
        snippet: str,
        current_patch: str,
        test_result: Optional[SandboxTestResult],
        rag_context: str,
        language: str,
        full_original: Optional[str] = None,
        user_contract: Optional[str] = None,
        extra_files: Optional[Dict[str, str]] = None,
        is_repeated: bool = False,
        repeated_from_turn: Optional[int] = None,
    ) -> Tuple[str, str, bool]:
        """Prompts LLM to self-correct patch based on failed sandbox test outputs."""
        if self.llm and test_result:
            try:
                prompt = self._build_refinement_prompt(
                    error_report=error_report,
                    file_path=file_path,
                    snippet=snippet,
                    current_patch=current_patch,
                    test_result=test_result,
                    rag_context=rag_context,
                    full_original=full_original,
                    user_contract=user_contract,
                    extra_files=extra_files,
                    is_repeated=is_repeated,
                    repeated_from_turn=repeated_from_turn,
                )
                base_temp = getattr(self.llm, "temperature", 0.0)
                temp = min(0.5, base_temp + 0.35) if is_repeated else base_temp
                llm_response = self.llm.generate(prompt, system=REFINEMENT_SYSTEM_PROMPT, temperature=temp)
                code, explanation = extract_code_and_explanation(llm_response)
                code = strip_language_prefix(code, language)
                if code and code.strip():
                    return code, explanation, True
            except Exception:
                pass

        return current_patch, "Refinement step could not invoke LLM; keeping current candidate.", False

    def _build_llm_prompt(
        self,
        error_report: str,
        file_path: str,
        snippet: str,
        rag_context: str,
        localization: Dict[str, Any],
        user_contract: Optional[str] = None,
    ) -> str:
        error_type = localization.get("error_type", "Unknown")
        few_shots = ""
        lang = self._detect_language(file_path)
        if self.experience_bank:
            few_shots = self.experience_bank.format_few_shot_prompt(
                error_type=error_type,
                query_text=error_report,
                language=lang,
                repo_id=getattr(self, "repo_id", None),
                max_tokens_budget=450,
                limit=2,
            )

        few_shots_section = f"\n\n{few_shots}" if few_shots else ""

        contract_section = ""
        if user_contract:
            contract_section = (
                f"\n=== ACCEPTED CONTRACT SPECIFICATION (MANDATORY & HIGHEST PRIORITY) ===\n"
                f"{user_contract}\n\n"
                f"PRECEDENCE RULE: The accepted contract requirements above strictly override all generic conventions, "
                f"few-shot examples, and general repository patterns. You MUST adhere strictly to the specified "
                f"exception types, return values, and operator semantics.\n\n"
            )

        return (
            f"Diagnostic Test / Traceback Evidence:\n{error_report}\n\n"
            f"Error Type: {error_type}\n"
            f"Target File to repair: {file_path}\n\n"
            f"{contract_section}"
            f"Target Implementation Code to fix:\n```{lang}\n{snippet}\n```\n\n"
            f"Additional repository context:\n{rag_context}"
            f"{few_shots_section}\n\n"
            f"CRITICAL INSTRUCTIONS:\n"
            f"1. Generate the corrected implementation for '{file_path}'.\n"
            f"2. DO NOT output test functions (e.g. def test_*). DO NOT output tests from test suites.\n"
            f"3. Preserve all existing public functions, classes, and signatures from the target implementation.\n"
            f"4. Provide the fixed implementation in a single code block, then explain the fix."
        )

    def _build_refinement_prompt(
        self,
        error_report: str,
        file_path: str,
        snippet: str,
        current_patch: str,
        test_result: SandboxTestResult,
        rag_context: str,
        full_original: Optional[str] = None,
        user_contract: Optional[str] = None,
        extra_files: Optional[Dict[str, str]] = None,
        is_repeated: bool = False,
        repeated_from_turn: Optional[int] = None,
    ) -> str:
        lang = self._detect_language(file_path)
        failed_tests_str = "\n".join(f"- {t}" for t in test_result.failed_tests) if test_result.failed_tests else "- Automated Test Failure"
        
        passed_tests_section = ""
        if test_result.passed_tests:
            passed_tests_list = "\n".join(f"- {t}" for t in test_result.passed_tests)
            passed_tests_section = (
                f"Passing Tests (MUST PRESERVE - DO NOT BREAK):\n"
                f"{passed_tests_list}\n\n"
            )

        if not test_result.assertion_errors and test_result.error_message:
            assertions_str = f"- {test_result.error_message}"
        else:
            assertions_str = "\n".join(f"- {err}" for err in test_result.assertion_errors) if test_result.assertion_errors else "Assertion failed during test execution."
        
        traceback_str = (
            test_result.traceback_summary
            or (test_result.stderr[-1500:] if test_result.stderr else "")
            or (test_result.stdout[-1500:] if test_result.stdout else "No output captured.")
        )

        dynamic_reqs = extract_behavioral_requirements(
            error_report=error_report,
            test_result=test_result,
            file_content_or_docstring=snippet,
        )
        reqs_str = "\n".join(f"{i+1}. {r}" for i, r in enumerate(dynamic_reqs))

        # 1. Actionable contract mismatches (expected exception vs actual, expected value, etc.)
        contract_mismatches = extract_contract_mismatches_from_failures(
            test_result=test_result,
            extra_files=extra_files,
            repo_path=self.repo_path,
            language=lang,
        )
        mismatches_section = ""
        if contract_mismatches:
            mismatches_section = (
                f"\n=== CONTRACT VIOLATIONS & EXPECTATION MISMATCHES (HIGHEST PRIORITY) ===\n"
                + "\n".join(contract_mismatches)
                + "\n\nMANDATORY ACTION: You MUST fix the exact contract mismatches listed above. "
                f"If a test requires a specific exception type (e.g. ZeroDivisionError) or exact return value, "
                f"your implementation MUST produce that exact exception type or value. "
                f"DO NOT substitute generic exceptions (e.g. ValueError) for the required exception.\n\n"
            )

        # 2. User contract specification section
        contract_section = ""
        if user_contract:
            contract_section = (
                f"\n=== ACCEPTED CONTRACT SPECIFICATION ===\n"
                f"{user_contract}\n\n"
                f"PRECEDENCE RULE: The accepted contract specification strictly overrides all generic conventions, "
                f"few-shot examples, and general repository patterns.\n\n"
            )

        # 3. Repeated identical candidate warning
        repetition_section = ""
        if is_repeated:
            repetition_section = (
                f"\n=== CRITICAL REPETITION WARNING ===\n"
                f"The candidate code you generated in the previous turn was 100% IDENTICAL to the candidate from "
                f"Turn {repeated_from_turn or 'prior'}, which already failed tests with the same error!\n"
                f"DO NOT output the exact same implementation again. You MUST change the logic to address the failures above.\n\n"
            )

        # Actionable interface restoration guidance: extract missing functions from full_original if dropped
        missing_context_section = ""
        if full_original and lang in ("python", "py"):
            try:
                import ast
                orig_tree = ast.parse(full_original)
                cand_tree = ast.parse(current_patch)
                orig_symbols = {n.name: n for n in orig_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                cand_symbols = {n.name for n in cand_tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
                missing = [name for name in orig_symbols if name not in cand_symbols and not name.startswith("_")]
                if missing:
                    snippets = []
                    for m_name in missing:
                        node = orig_symbols[m_name]
                        seg = ast.get_source_segment(full_original, node)
                        if seg:
                            snippets.append(seg)
                    if snippets:
                        missing_context_section = (
                            f"\nCRITICAL INTERFACE RESTORATION REQUIRED:\n"
                            f"The previous attempt was REJECTED because it deleted required public symbol(s): {missing}.\n"
                            f"Here is the original definition that you MUST preserve in the implementation:\n```{lang}\n"
                            + "\n\n".join(snippets)
                            + f"\n```\n"
                        )
            except Exception:
                pass

        dup_warning = ""
        if any("duplicate definition" in str(err).lower() for err in (test_result.assertion_errors or [])):
            dup_warning = "\nCRITICAL: The previous candidate introduced duplicate function/class definitions. Ensure each name is defined exactly once!\n"

        return (
            f"Diagnostic Test / Traceback Evidence:\n{error_report}\n\n"
            f"Target File to repair: {file_path}\n\n"
            f"{contract_section}"
            f"{mismatches_section}"
            f"{repetition_section}"
            f"Original Target Implementation:\n```{lang}\n{snippet}\n```\n\n"
            f"Previous Failed Patch Candidate:\n```{lang}\n{current_patch}\n```\n\n"
            f"Automated Test / Verification Failure Summary:\n"
            f"Failed Tests:\n{failed_tests_str}\n\n"
            f"{passed_tests_section}"
            f"Assertion / Verification Errors:\n{assertions_str}\n\n"
            f"Test Traceback / Output Evidence (Diagnostic):\n```\n{traceback_str}\n```\n\n"
            f"{missing_context_section}"
            f"{dup_warning}"
            f"CRITICAL REQUIREMENTS:\n"
            f"{reqs_str}\n"
            f"- You are repairing the implementation in '{file_path}'.\n"
            f"- DO NOT output test functions (def test_*). DO NOT output tests from test suites.\n"
            f"- Preserve required public interfaces and functions (including main/entry points) from the original implementation.\n"
            f"- DO NOT introduce duplicate definitions.\n\n"
            f"Additional Repository Context:\n{rag_context}\n\n"
            f"Generate the corrected implementation in a single fenced code block, followed by an explanation."
        )

    def _heuristic_fix(
        self,
        snippet: str,
        localization: Dict[str, Any],
        top_candidate: Dict[str, Any],
    ) -> tuple:
        error_type = localization.get("error_type", "")
        lines = snippet.splitlines()
        fixed_lines: List[str] = []
        applied = False

        for line in lines:
            stripped = line.lstrip()

            if not applied and "KeyError" in error_type:
                match = re.search(r"(\w+)\[['\"](\w+)['\"]\]", line)
                if match:
                    var, key = match.group(1), match.group(2)
                    prefix = "return " if stripped.startswith("return ") else ""
                    indent = line[: len(line) - len(stripped)]
                    fixed_lines.append(f"{indent}{prefix}{var}.get('{key}', None)  # KeyError guard")
                    applied = True
                    continue

            if not applied and "AttributeError" in error_type:
                match = re.search(r"(\w+)\.(\w+)", line)
                if match and "def " not in line and "class " not in line:
                    var = match.group(1)
                    indent = line[: len(line) - len(stripped)]
                    fixed_lines.append(f"{indent}if {var} is not None:")
                    fixed_lines.append(f"{indent}    {stripped}")
                    applied = True
                    continue

            if not applied and "IndexError" in error_type:
                if "return " in line and ("[" in line or ".get(" in line):
                    indent = line[: len(line) - len(stripped)]
                    fixed_lines.append(f"{indent}if len(data) > 0:")
                    fixed_lines.append(f"{indent}    {stripped}")
                    applied = True
                    continue

            if not applied and ("NoneType" in error_type or "TypeError" in error_type):
                if "return " in line or "=" in line:
                    indent = line[: len(line) - len(stripped)]
                    fixed_lines.append(f"{indent}if data is not None:")
                    fixed_lines.append(f"{indent}    {stripped}")
                    applied = True
                    continue

            fixed_lines.append(line)

        if not applied:
            for i, line in enumerate(fixed_lines):
                stripped = line.lstrip()
                if stripped and not stripped.startswith(("#", "def ", "class ", "@")):
                    indent = line[: len(line) - len(stripped)]
                    fixed_lines.insert(i, f"{indent}# Defensive guard added by IntelliCodeX")
                    fixed_lines.insert(i + 1, f"{indent}pass  # TODO: verify fix manually")
                    applied = True
                    break

        explanation = (
            f"Heuristic fix for {error_type} in '{top_candidate.get('function', 'unknown')}' "
            f"at line {top_candidate.get('line_number', '?')}. "
            f"Review carefully — LLM was unavailable."
        )
        return "\n".join(fixed_lines), explanation

    @staticmethod
    def _detect_language(file_path: str) -> str:
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".java": "java", ".go": "go", ".cpp": "cpp", ".cc": "cpp",
            ".cxx": "cpp", ".hpp": "cpp", ".c": "c", ".cs": "csharp",
            ".rb": "ruby", ".rs": "rust",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        if file_path.endswith(".h"):
            return "c"
        return "python"

    @staticmethod
    def _failed_patch(repo_id: str, target_file: Optional[str], reason: str) -> Dict[str, Any]:
        return {
            "patch_id": str(uuid.uuid4()),
            "repo_id": repo_id,
            "target_file": target_file or "unknown",
            "original_code": "",
            "suggested_patch": "",
            "git_diff": "",
            "explanation": reason,
            "confidence_score": 0.0,
            "status": "failed",
        }

    def generate_multi_file_patch(
        self,
        repo_id: str,
        error_report: str,
        target_files: List[str],
        file_modifications: Optional[Dict[str, str]] = None,
        verify_in_sandbox: bool = True,
        test_command: Optional[Union[str, List[str]]] = None,
        timeout: Optional[Union[int, float]] = None,
    ) -> MultiFilePatchResult:
        """
        Coordinates multi-file context-aware patch generation with two-phase verification
        and regression prevention.

        Guarantees:
        1. Context-aware modifications for each target file.
        2. Multi-file unified diff generation.
        3. AST syntax validation across all touched files.
        4. Sandbox execution in isolated temporary clone with extra_files populated.
        5. Baseline test execution comparison detecting any regressions in untouched tests.
        """
        patch_id = str(uuid.uuid4())
        normalized_targets = [f.replace("\\", "/").lstrip("./") for f in target_files]
        original_files: Dict[str, str] = {}
        patched_files: Dict[str, str] = {}
        file_diffs: Dict[str, str] = {}
        combined_diff_parts: List[str] = []
        validation_results: Dict[str, Any] = {}
        all_valid = True

        for rel_path in normalized_targets:
            orig = self._read_file(rel_path)
            if orig is None:
                orig = ""
            original_files[rel_path] = orig

            if file_modifications and rel_path in file_modifications:
                patched = file_modifications[rel_path]
            else:
                # Generate fix per file using localization/heuristics
                patched, _, _ = self._generate_fix(
                    error_report=error_report,
                    file_path=rel_path,
                    snippet=orig,
                    rag_context="",
                    localization={},
                    top_candidate={"file_path": rel_path, "snippet": orig},
                    language=self._detect_language(rel_path),
                )
            patched_files[rel_path] = patched

            diff = generate_git_diff(orig, patched, file_path=rel_path)
            file_diffs[rel_path] = diff
            combined_diff_parts.append(diff)

            val = validate_patch(
                patched_code=patched,
                git_diff=diff,
                language=self._detect_language(rel_path),
                original_code=orig,
            )
            val["is_valid"] = val.get("syntax_valid", False)
            validation_results[rel_path] = val
            if not val["is_valid"]:
                all_valid = False

        combined_diff = "\n\n".join(combined_diff_parts)

        if not all_valid:
            return MultiFilePatchResult(
                patch_id=patch_id,
                repo_id=repo_id,
                files=patched_files,
                original_files=original_files,
                git_diff=combined_diff,
                file_diffs=file_diffs,
                explanation="Multi-file patch validation failed: syntax errors detected in candidate edits.",
                validation=validation_results,
                status="syntax_error",
            )

        sandbox_result = None
        regression_info = None
        status = "pending"

        if verify_in_sandbox and self.repo_path and self.sandbox_runner and normalized_targets:
            primary_file = normalized_targets[0]
            extra_files = {f: patched_files[f] for f in normalized_targets[1:]}

            # Run baseline tests on unpatched repository to establish baseline passing tests
            baseline_result = None
            try:
                baseline_result = self.sandbox_runner.run_tests_with_patch(
                    repo_path=self.repo_path,
                    target_file=primary_file,
                    patched_code=original_files.get(primary_file, ""),
                    test_command=test_command,
                    timeout=timeout or self.default_timeout,
                    extra_files={f: original_files.get(f, "") for f in normalized_targets[1:]},
                )
            except Exception as b_err:
                logger.warning(f"Failed to execute baseline test run: {b_err}")

            # Run candidate multi-file patch in sandbox
            patched_test_res = self.sandbox_runner.run_tests_with_patch(
                repo_path=self.repo_path,
                target_file=primary_file,
                patched_code=patched_files[primary_file],
                test_command=test_command,
                timeout=timeout or self.default_timeout,
                extra_files=extra_files,
            )

            # Analyze regressions against baseline
            regression_info = detect_test_regressions(baseline_result, patched_test_res)

            if regression_info.get("has_regression"):
                status = "regressed"
                explanation = (
                    f"Candidate multi-file patch rejected due to regressions: "
                    f"{regression_info.get('regressed_tests')} previously passed but now fail."
                )
            elif patched_test_res.success and (patched_test_res.passed_count or 0) > 0 and len(patched_test_res.failed_tests or []) == 0:
                status = "verified"
                explanation = "Candidate multi-file patch successfully verified with zero regressions in sandbox."
            else:
                status = "failed"
                explanation = f"Candidate multi-file patch failed sandbox tests: {patched_test_res.failed_tests or patched_test_res.error_message}"

            sandbox_result = {
                "success": patched_test_res.success,
                "exit_code": patched_test_res.exit_code,
                "passed_count": patched_test_res.passed_count,
                "failed_count": patched_test_res.failed_count,
                "failed_tests": patched_test_res.failed_tests,
                "duration_seconds": patched_test_res.duration_seconds,
                "container_name": patched_test_res.container_name,
            }
        else:
            explanation = "Multi-file patch candidate generated (sandbox test validation skipped or unavailable)."
            status = "pending"

        return MultiFilePatchResult(
            patch_id=patch_id,
            repo_id=repo_id,
            files=patched_files,
            original_files=original_files,
            git_diff=combined_diff,
            file_diffs=file_diffs,
            explanation=explanation,
            validation=validation_results,
            sandbox_validation=sandbox_result,
            regression_analysis=regression_info,
            status=status,
        )

    def apply_multi_file_patch(
        self,
        patch: Union[MultiFilePatchResult, Dict[str, Any]],
        create_backup: bool = True,
    ) -> Dict[str, Any]:
        """Atomically applies a verified multi-file patch with transactional rollback."""
        from backend.patch_generator.patch_applier import apply_multi_file_patch as _apply_mf
        files_content = patch.files if isinstance(patch, MultiFilePatchResult) else patch.get("files", {})
        expected_originals = patch.original_files if isinstance(patch, MultiFilePatchResult) else patch.get("original_files", {})
        return _apply_mf(
            repo_path=self.repo_path or ".",
            files_content=files_content,
            expected_originals=expected_originals,
            create_backup=create_backup,
        )
