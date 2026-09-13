"""
Multi-File Context-Aware Code Patch Generator Engine
Extracts code context via RAG, localizes root causes, prompts LLM or runs heuristic guards,
merges snippet fixes into full repository files, generates unified git diffs, and validates syntax.
"""
import difflib
import os
import sys
import re
import uuid
import time
from typing import List, Dict, Any, Optional, Tuple
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
from backend.patch_generator.llm_parser import extract_code_and_explanation, strip_language_prefix
from backend.patch_generator.patch_validator import validate_patch, compute_patch_quality_score
from backend.patch_generator.patch_applier import apply_patch_to_file, merge_snippet_into_file
from rag.query_engine import format_context


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


class PatchEngine:
    """
    Context-aware multi-file patch generation engine.
    """

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm: Optional[OllamaLLM] = None,
        graph: Optional[nx.DiGraph] = None,
        repo_path: Optional[str] = None,
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.graph = graph
        self.repo_path = repo_path
        self.localizer = BugLocalizer(store, embedder, graph)

    def generate_patch(
        self,
        repo_id: str,
        error_report: str,
        target_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generates a patch recommendation based on error report and repository context."""
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

        suggested_snippet, explanation, llm_generated = self._generate_fix(
            error_report=error_report,
            file_path=file_path,
            snippet=snippet,
            rag_context=rag_context,
            localization=localization,
            top_candidate=top_candidate,
            language=language,
        )

        if using_full_file:
            patched_full = merge_snippet_into_file(
                full_original,
                snippet,
                suggested_snippet,
                start_line=top_candidate.get("line_number", 1),
            )
            if patched_full is None:
                patched_full = suggested_snippet
                diff_original = snippet
            else:
                diff_original = full_original
        else:
            patched_full = suggested_snippet
            diff_original = snippet

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
            "llm_generated": llm_generated,
            "error_type": localization.get("error_type", "UnknownError"),
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

    def apply_patch(self, patch_record: Dict[str, Any]) -> Tuple[bool, str]:
        """Applies suggested patch directly to physical file on disk."""
        if not self.repo_path:
            return False, "repo_path is not set"
        target_file = patch_record.get("target_file")
        suggested = patch_record.get("suggested_patch")
        if not target_file or not suggested:
            return False, "Invalid patch record"
        res = apply_patch_to_file(self.repo_path, target_file, suggested)
        if res.get("success"):
            return True, f"Successfully applied patch to '{target_file}'!"
        return False, f"Failed to apply patch: {res.get('error', 'unknown error')}"

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
                    indent = line[: len(line) - len(stripped)]
                    fixed_lines.append(f"{indent}{var}.get('{key}', None)  # KeyError guard")
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
