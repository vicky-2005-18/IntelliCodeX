"""
Multi-File Context-Aware Code Patch Generator Engine (Milestone 1)
Extracts code context via RAG, localizes root causes, prompts LLM or runs heuristic guards,
merges snippet fixes into full repository files, generates unified git diffs, validates syntax,
and executes iterative test-driven closed-loop sandbox validation.
"""
import copy
import difflib
import logging
import os
import sys
import re
import tempfile
import uuid
import time
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


def validate_candidate_interface(
    original_code: str,
    candidate_code: str,
    language: str = "python",
) -> Tuple[bool, Optional[str]]:
    """
    Validates that a candidate patch preserves required public interfaces,
    has valid syntax, and does not substitute test code for target implementation.
    """
    if not candidate_code or not candidate_code.strip():
        return False, "Candidate code is empty."

    if language.lower() in ("python", "py"):
        import ast

        try:
            cand_ast = ast.parse(candidate_code)
        except SyntaxError as e:
            return False, f"Python syntax error in candidate: {e}"
        except Exception as e:
            return False, f"Failed to parse candidate AST: {e}"

        orig_ast = None
        if original_code and original_code.strip():
            try:
                orig_ast = ast.parse(original_code)
            except Exception:
                orig_ast = None

        if orig_ast:
            # Extract top-level public functions and classes from original code
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

            # Extract top-level symbols from candidate
            cand_funcs = {
                node.name
                for node in cand_ast.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            cand_classes = {
                node.name
                for node in cand_ast.body
                if isinstance(node, ast.ClassDef)
            }
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

    return True, None


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
    if not target_file or not suggested:
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
        sec_coverage = str(sec_val.get("security_coverage", "unknown")).lower().strip()
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
        elif sec_status != "passed" or not sec_approved:
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
        import hashlib
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

        current_snippet = snippet
        current_explanation = ""
        llm_generated = False
        iteration_history: List[Dict[str, Any]] = []
        final_test_result: Optional[SandboxTestResult] = None

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
                )

            patched_full, diff_original = self._assemble_patched_file(
                full_original, snippet, current_snippet, using_full_file, top_candidate, language=language
            )

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
                    extra_files=kwargs.get("extra_files"),
                )
                final_test_result = test_res


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

                if test_res.success or test_res.skipped:
                    break
            else:
                break

        # Final patch assembly and scoring
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

        test_passed = final_test_result.success if final_test_result else False
        test_skipped = final_test_result.skipped if final_test_result else True
        passed_count = final_test_result.passed_count if final_test_result else 0
        is_truly_verified = bool(test_passed and not test_skipped and passed_count > 0)

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
        import hashlib
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
            "created_at": time.time(),
        }

        # Security scan candidate patched code before recording as approved repair
        cand_sec_status = "unscanned"
        cand_sec_coverage = "unknown"
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
                cand_sec_approved = bool(cand_sec_status == "passed")
                cand_sec_findings_cnt = cand_sec.get("failing_findings_count", 0)
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

        if using_full_file:
            patched_full = merge_snippet_into_file(
                full_original,
                snippet,
                suggested_snippet,
                start_line=top_candidate.get("line_number", 1),
            )
            if patched_full is not None:
                return patched_full, diff_original

            # If snippet merge failed, check if suggested_snippet is a valid full-file replacement
            is_valid, _ = validate_candidate_interface(full_original, suggested_snippet, language=language)
            if is_valid:
                return suggested_snippet, diff_original
            # Mismatched context / rejected replacement: do NOT corrupt full_original with detached snippet
            return full_original, diff_original
        else:
            if full_original and suggested_snippet and len(suggested_snippet.strip()) < len(full_original.strip()):
                cand_snip = top_candidate.get("snippet", "")
                if cand_snip and cand_snip in full_original:
                    merged = merge_snippet_into_file(
                        full_original,
                        cand_snip,
                        suggested_snippet,
                        start_line=top_candidate.get("line_number", 1),
                    )
                    if merged:
                        return merged, diff_original
            return suggested_snippet, diff_original


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
    ) -> tuple:
        if self.llm:
            try:
                prompt = self._build_llm_prompt(
                    error_report, file_path, snippet, rag_context, localization
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
                )
                temp = getattr(self.llm, "temperature", 0.0)
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

        return (
            f"Diagnostic Test / Traceback Evidence:\n{error_report}\n\n"
            f"Error Type: {error_type}\n"
            f"Target File to repair: {file_path}\n\n"
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
    ) -> str:
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

        return (
            f"Diagnostic Test / Traceback Evidence:\n{error_report}\n\n"
            f"Target File to repair: {file_path}\n\n"
            f"Original Target Implementation:\n```{self._detect_language(file_path)}\n{snippet}\n```\n\n"
            f"Previous Failed Patch Candidate:\n```{self._detect_language(file_path)}\n{current_patch}\n```\n\n"
            f"Automated Test / Verification Failure Summary:\n"
            f"Failed Tests:\n{failed_tests_str}\n\n"
            f"{passed_tests_section}"
            f"Assertion / Verification Errors:\n{assertions_str}\n\n"
            f"Test Traceback / Output Evidence (Diagnostic):\n```\n{traceback_str}\n```\n\n"
            f"CRITICAL REQUIREMENTS:\n"
            f"{reqs_str}\n"
            f"- You are repairing the implementation in '{file_path}'.\n"
            f"- DO NOT output test functions (def test_*). DO NOT output tests from test suites.\n"
            f"- Preserve required public interfaces and functions from the original implementation.\n\n"
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
