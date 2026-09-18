"""
AI-Powered Patch Generation Engine (Phase 1 & Milestone 1)
Retrieves repository context via RAG, queries Ollama LLM, formats Git-style diffs,
computes confidence scores, validates patches, executes sandbox test loops, and manages developer approval.
"""
import difflib
import os
import re
import uuid
import time
from typing import List, Dict, Any, Optional, Tuple, Callable

import networkx as nx

from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.llm_client import OllamaLLM
from core.chunker import CodeChunk
from core.sandbox_runner import SandboxRunner, SandboxTestResult
from backend.bug_localizer.advanced_localizer import AdvancedBugLocalizer
from backend.database.mongo import db_manager
from backend.patch_generator.llm_parser import extract_code_and_explanation, strip_language_prefix
from backend.patch_generator.patch_validator import validate_patch, compute_patch_quality_score
from backend.patch_generator.patch_applier import (
    apply_patch_to_file,
    merge_snippet_into_file,
)
from rag.query_engine import format_context

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


def generate_git_diff(original_code: str, patched_code: str, file_path: str = "file.py") -> str:
    """Generate standard unified git diff format."""
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


class PatchEngine:
    """
    Context-aware patch generation engine with closed-loop sandbox test verification.
    """

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm: Optional[OllamaLLM] = None,
        graph: Optional[nx.DiGraph] = None,
        repo_path: Optional[str] = None,
        sandbox_runner: Optional[SandboxRunner] = None,
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.graph = graph
        self.repo_path = repo_path
        self.localizer = AdvancedBugLocalizer(store, embedder, graph)
        self.sandbox_runner = sandbox_runner or SandboxRunner()

    def generate_patch(
        self,
        repo_id: str,
        error_report: str,
        target_file: Optional[str] = None,
        verify_in_sandbox: bool = False,
        test_command: Optional[str] = None,
        max_iterations: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Generate a patch recommendation based on error report and repository context."""
        if verify_in_sandbox and self.repo_path:
            return self.generate_and_verify_patch(
                repo_id=repo_id,
                error_report=error_report,
                target_file=target_file,
                test_command=test_command,
                max_iterations=max_iterations,
                progress_callback=progress_callback,
            )

        localization = self.localizer.localize(error_report, top_k=3)
        candidates = localization.get("candidates", [])

        if not candidates:
            return self._failed_patch(
                repo_id, target_file, "No relevant repository context was found matching the error report."
            )

        top_candidate = candidates[0]
        file_path = target_file or top_candidate["file_path"]
        snippet = top_candidate["snippet"]
        language = self._detect_language(file_path)
        localization_confidence = top_candidate["confidence_score"]

        # Read full file from disk when available
        full_original = self._read_file(file_path) or snippet
        using_full_file = full_original != snippet

        # Gather additional RAG context (same file + related chunks)
        rag_chunks = self._retrieve_rag_chunks(error_report, file_path, top_k=4)
        rag_context = format_context(rag_chunks) if rag_chunks else ""

        # Generate patched snippet via LLM or heuristic fallback
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
            full_original, snippet, suggested_snippet, using_full_file, top_candidate
        )

        git_diff = generate_git_diff(diff_original, patched_full, file_path)

        # Validate patch quality
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
            "status": "pending",
            "created_at": time.time(),
        }

        db_manager.insert("generated_patches", patch_record)
        return patch_record

    def generate_and_verify_patch(
        self,
        repo_id: str,
        error_report: str,
        target_file: Optional[str] = None,
        test_command: Optional[str] = None,
        max_iterations: int = 3,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Closed-Loop Agentic Test-Driven Repair (Milestone 1)."""
        localization = self.localizer.localize(error_report, top_k=3)
        candidates = localization.get("candidates", [])

        if not candidates:
            return self._failed_patch(
                repo_id, target_file, "No relevant repository context was found matching the error report."
            )

        top_candidate = candidates[0]
        file_path = target_file or top_candidate["file_path"]
        snippet = top_candidate["snippet"]
        language = self._detect_language(file_path)
        localization_confidence = top_candidate["confidence_score"]

        full_original = self._read_file(file_path) or snippet
        using_full_file = full_original != snippet

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
                full_original, snippet, current_snippet, using_full_file, top_candidate
            )

            # Test candidate patch inside isolated sandbox
            if self.repo_path:
                if progress_callback:
                    progress_callback(turn, max_iterations, f"Running sandbox test suite (Turn {turn}/{max_iterations})...")

                test_res = self.sandbox_runner.run_tests_with_patch(
                    repo_path=self.repo_path,
                    target_file=file_path,
                    patched_code=patched_full,
                    test_command=test_command,
                )
                final_test_result = test_res

                iteration_history.append({
                    "turn": turn,
                    "explanation": current_explanation,
                    "test_passed": test_res.success,
                    "skipped": test_res.skipped,
                    "duration": test_res.duration_seconds,
                    "failed_count": test_res.failed_count,
                    "passed_count": test_res.passed_count,
                    "assertion_errors": test_res.assertion_errors,
                })

                if test_res.success or test_res.skipped:
                    break
            else:
                break

        # Final patch assembly and scoring
        patched_full, diff_original = self._assemble_patched_file(
            full_original, snippet, current_snippet, using_full_file, top_candidate
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

        base_score = compute_patch_quality_score(
            localization_confidence=localization_confidence,
            syntax_valid=validation["syntax_valid"],
            git_apply_valid=validation["git_apply_valid"] or validation.get("git_apply_skipped", False),
            has_changes=validation["has_changes"],
            llm_generated=llm_generated,
        )
        if test_passed and not test_skipped:
            confidence_score = min(0.99, base_score + 0.15)
        elif not test_passed and not test_skipped:
            confidence_score = max(0.1, base_score - 0.25)
        else:
            confidence_score = base_score

        patch_id = str(uuid.uuid4())
        patch_record = {
            "patch_id": patch_id,
            "repo_id": repo_id,
            "target_file": file_path,
            "original_code": diff_original,
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
                "verified": test_passed,
                "skipped": test_skipped,
                "test_status": "passed" if test_passed else ("skipped" if test_skipped else "failed"),
                "iterations_count": len(iteration_history) or 1,
                "iteration_history": iteration_history,
                "test_result": final_test_result.to_dict() if final_test_result else None,
            },
            "llm_generated": llm_generated,
            "error_type": localization.get("error_type", "UnknownError"),
            "status": "verified" if (test_passed and not test_skipped) else "pending",
            "created_at": time.time(),
        }

        db_manager.insert("generated_patches", patch_record)
        return patch_record

    def update_patch_status(
        self,
        patch_id: str,
        status: str,
        manual_edit: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update approval status. When status is 'applied', writes the patch to disk.
        """
        record = db_manager.find_one("generated_patches", {"patch_id": patch_id})
        if not record:
            return None

        update_data: Dict[str, Any] = {"status": status}

        if manual_edit is not None:
            file_path = record["target_file"]
            update_data["suggested_patch"] = manual_edit
            update_data["git_diff"] = generate_git_diff(
                record["original_code"], manual_edit, file_path
            )
            update_data["manually_edited"] = True

        if status == "applied" and self.repo_path:
            content = manual_edit or record.get("suggested_patch", "")
            result = apply_patch_to_file(self.repo_path, record["target_file"], content)
            update_data["apply_result"] = result
            if not result.get("success"):
                update_data["status"] = "approved"
                db_manager.update("generated_patches", {"patch_id": patch_id}, update_data)
                return db_manager.find_one("generated_patches", {"patch_id": patch_id})

        db_manager.update("generated_patches", {"patch_id": patch_id}, update_data)
        return db_manager.find_one("generated_patches", {"patch_id": patch_id})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assemble_patched_file(
        self,
        full_original: str,
        snippet: str,
        suggested_snippet: str,
        using_full_file: bool,
        top_candidate: Dict[str, Any],
    ) -> Tuple[str, str]:
        if using_full_file:
            patched_full = merge_snippet_into_file(
                full_original,
                snippet,
                suggested_snippet,
                start_line=top_candidate.get("line_number", 1),
            )
            if patched_full is None:
                return suggested_snippet, snippet
            return patched_full, full_original
        return suggested_snippet, snippet

    def _read_file(self, file_path: str) -> Optional[str]:
        if not self.repo_path:
            return None
        abs_path = os.path.join(self.repo_path, file_path)
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
                llm_response = self.llm.generate(prompt, system=PATCH_SYSTEM_PROMPT, temperature=0.1)
                code, explanation = extract_code_and_explanation(llm_response)
                code = strip_language_prefix(code, language)
                if code and code.strip() != snippet.strip():
                    return code, explanation, True
            except Exception:
                pass

        patched, explanation = self._heuristic_fix(
            snippet, localization, top_candidate
        )
        return patched, explanation, False

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
                llm_response = self.llm.generate(prompt, system=REFINEMENT_SYSTEM_PROMPT, temperature=0.2)
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
        return (
            f"Bug / Error Report:\n{error_report}\n\n"
            f"Error Type: {localization.get('error_type', 'Unknown')}\n"
            f"Target File: {file_path}\n\n"
            f"Code to fix:\n```{self._detect_language(file_path)}\n{snippet}\n```\n\n"
            f"Additional repository context:\n{rag_context}\n\n"
            f"Generate the corrected version of the code snippet above. "
            f"Make minimal changes — only fix the bug. "
            f"Provide the fixed code in a single code block, then explain the fix."
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
        failed_tests_str = ", ".join(test_result.failed_tests) if test_result.failed_tests else "Automated Test Suite"
        assertions_str = "\n".join(f"- {err}" for err in test_result.assertion_errors) if test_result.assertion_errors else "Assertion failed during test execution."
        traceback_str = test_result.traceback_summary or test_result.stdout[-1000:]

        return (
            f"Bug / Error Report:\n{error_report}\n\n"
            f"Target File: {file_path}\n\n"
            f"Original Code:\n```{self._detect_language(file_path)}\n{snippet}\n```\n\n"
            f"Previous Failed Patch Candidate:\n```{self._detect_language(file_path)}\n{current_patch}\n```\n\n"
            f"Automated Test Failure Summary:\n"
            f"Failed Tests: {failed_tests_str}\n"
            f"Assertion Errors:\n{assertions_str}\n\n"
            f"Test Traceback / Output:\n```\n{traceback_str}\n```\n\n"
            f"Additional Repository Context:\n{rag_context}\n\n"
            f"Please analyze why the previous candidate failed tests and generate a corrected version of the code. "
            f"Ensure all edge cases and assertions are properly satisfied. "
            f"Output the corrected code in a single fenced code block, followed by an explanation."
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
            ".java": "java", ".go": "go", ".cpp": "cpp", ".cs": "csharp",
            ".rb": "ruby", ".rs": "rust",
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
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
