"""
Spectrum-Based Bug Localization (SBFL) & Multi-Signal Error Diagnostics Engine
Combines Ochiai suspiciousness scoring, multi-language stack trace parsing,
FAISS semantic similarity vector ranking, and dependency call-graph centrality.
"""
import os
import sys
import re
import math
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Set
import networkx as nx

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.chunker import CodeChunk


def calculate_ochiai_score(ef: int, ep: int, nf: int, np: int) -> float:
    """
    Calculates Ochiai suspiciousness score for a code element (file/function/line).
    
    Formula: Ochiai = ef / sqrt(nf * (ef + ep))
      ef: failing test executions covering the element
      ep: passing test executions covering the element
      nf: total failing test executions
      np: total passing test executions
    """
    if nf <= 0 or (ef + ep) <= 0:
        return 0.0
    denominator = math.sqrt(nf * (ef + ep))
    if denominator == 0.0:
        return 0.0
    return round(float(ef) / denominator, 4)


@dataclass
class CoverageRecord:
    element_id: str  # e.g., "auth.py" or "auth.py::login"
    failing_exec_count: int = 0
    passing_exec_count: int = 0


def calculate_ochiai_spectrum(
    coverage_records: List[CoverageRecord],
    total_failing: int,
    total_passing: int
) -> Dict[str, float]:
    """Calculates Ochiai suspiciousness scores across all covered code elements."""
    scores = {}
    for record in coverage_records:
        score = calculate_ochiai_score(
            ef=record.failing_exec_count,
            ep=record.passing_exec_count,
            nf=total_failing,
            np=total_passing
        )
        scores[record.element_id] = score
    return scores


@dataclass
class StackFrame:
    """Single stack frame extracted from an error traceback."""
    file_path: str
    line_number: int
    function: str
    language: str = "unknown"

    def __getitem__(self, item: str) -> Any:
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "function": self.function,
            "language": self.language,
        }


@dataclass
class ParsedStackTrace:
    """Structured representation of a parsed error traceback."""
    error_type: str
    error_message: str
    frames: List[StackFrame] = field(default_factory=list)

    def __getitem__(self, item: str) -> Any:
        if item == "parsed_frames":
            return [f.to_dict() for f in self.frames]
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "parsed_frames": [f.to_dict() for f in self.frames],
            "frames": self.frames,
        }


class StackTraceParser:
    """Multi-language error log and stack trace parser (Python, JS/TS, Java, Go, C/C++, Rust)."""

    ERROR_PATTERN = re.compile(
        r"([A-Za-z_]\w*(?:Error|Exception|Fault|Failure|"
        r"TypeError|ValueError|KeyError|AttributeError|"
        r"NullPointerException|IndexOutOfBoundsException|"
        r"RuntimeException|panic))(?::\s*(.*))?",
        re.MULTILINE,
    )

    def parse(self, error_report: str) -> ParsedStackTrace:
        error_type, error_msg = self._extract_error(error_report)
        frames: List[StackFrame] = []
        frames.extend(self._parse_python_frames(error_report))
        frames.extend(self._parse_js_frames(error_report))
        frames.extend(self._parse_java_frames(error_report))
        frames.extend(self._parse_go_frames(error_report))
        frames.extend(self._parse_cpp_frames(error_report))
        frames.extend(self._parse_rust_frames(error_report))

        return ParsedStackTrace(
            error_type=error_type,
            error_message=error_msg,
            frames=frames,
        )

    def _extract_error(self, error_report: str) -> Tuple[str, str]:
        match = self.ERROR_PATTERN.search(error_report)
        if match:
            return match.group(1), (match.group(2) or "").strip()
        first_line = error_report.strip().splitlines()[0] if error_report.strip() else ""
        return "UnknownError", first_line

    def _parse_python_frames(self, text: str) -> List[StackFrame]:
        frames = []
        for path, line, func in re.findall(
            r'File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+([A-Za-z_]\w*))?',
            text,
        ):
            frames.append(StackFrame(path, int(line), func or "<module>", "python"))
        return frames

    def _parse_js_frames(self, text: str) -> List[StackFrame]:
        frames = []
        for func, path, line, _col in re.findall(
            r"at\s+(?:([A-Za-z_]\w*)\s+\()?([^:\s]+):(\d+):(\d+)\)?",
            text,
        ):
            frames.append(StackFrame(path, int(line), func or "<anonymous>", "javascript"))
        return frames

    def _parse_java_frames(self, text: str) -> List[StackFrame]:
        frames = []
        for func, path, line in re.findall(
            r"at\s+[\w\.]+\.([A-Za-z_]\w*)\(([^:]+):(\d+)\)",
            text,
        ):
            frames.append(StackFrame(path, int(line), func, "java"))
        return frames

    def _parse_go_frames(self, text: str) -> List[StackFrame]:
        frames = []
        for path, line, func in re.findall(
            r"([\w/\\.-]+\.go):(\d+)\s+(?:\+0x[\da-f]+\s+)?(\w+)\(",
            text,
        ):
            frames.append(StackFrame(path, int(line), func, "go"))
        for path, line in re.findall(r"in\s+([\w/\\.-]+\.go):(\d+)", text):
            frames.append(StackFrame(path, int(line), "<unknown>", "go"))
        return frames

    def _parse_cpp_frames(self, text: str) -> List[StackFrame]:
        frames = []
        for func, path, line in re.findall(
            r"(\w+)\([^)]*\)\s+at\s+([\w/\\.-]+\.(?:cpp|cc|c|h|hpp)):(\d+)",
            text,
        ):
            frames.append(StackFrame(path, int(line), func, "cpp"))
        return frames

    def _parse_rust_frames(self, text: str) -> List[StackFrame]:
        frames = []
        for path, line, col in re.findall(
            r"at\s+([\w/\\.-]+\.rs):(\d+):(\d+)",
            text,
        ):
            frames.append(StackFrame(path, int(line), "<rust>", "rust"))
        return frames


class BugLocalizer:
    """
    Multi-signal Bug Localization Engine.
    Combines stack trace line matching, vector similarity search, dependency graph centrality,
    and Spectrum-Based Fault Localization (Ochiai scoring).
    """

    STACK_FRAME_BOOST = 0.35
    GRAPH_CENTRALITY_WEIGHT = 0.03

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        graph: Optional[nx.DiGraph] = None,
        spectrum_scores: Optional[Dict[str, float]] = None,
    ):
        self.store = store
        self.embedder = embedder
        self.graph = graph
        self.spectrum_scores = spectrum_scores or {}
        self.parser = StackTraceParser()

    def localize(self, error_report: str, top_k: int = 5) -> Dict[str, Any]:
        trace = self.parser.parse(error_report)
        parsed_frames = trace.frames

        query_vec = self.embedder.embed([error_report])[0]
        retrieved = self.store.search(query_vec, top_k=top_k * 3)

        frame_lookup = self._build_frame_lookup(parsed_frames)
        candidates = self._rank_candidates(retrieved, trace, frame_lookup)
        candidates = self._deduplicate_by_file(candidates)
        candidates.sort(key=lambda x: x["confidence_score"], reverse=True)
        top_candidates = candidates[:top_k]

        root_cause = self._build_root_cause_explanation(trace, top_candidates)

        return {
            "error_type": trace.error_type,
            "error_message": trace.error_message,
            "parsed_frames": [f.to_dict() for f in parsed_frames],
            "parsed_frames_count": len(parsed_frames),
            "candidates": top_candidates,
            "recommended_focus": top_candidates[0] if top_candidates else None,
            "root_cause_explanation": root_cause,
        }

    def _build_frame_lookup(self, frames: List[StackFrame]) -> Dict[str, StackFrame]:
        lookup: Dict[str, StackFrame] = {}
        for frame in frames:
            lookup[frame.file_path] = frame
            lookup[os.path.basename(frame.file_path)] = frame
        return lookup

    def _match_frame(
        self, chunk_path: str, frame_lookup: Dict[str, StackFrame]
    ) -> Optional[StackFrame]:
        for key, frame in frame_lookup.items():
            if chunk_path.endswith(key) or key.endswith(chunk_path):
                return frame
            if os.path.basename(chunk_path) == os.path.basename(key):
                return frame
        return None

    def _graph_context(self, file_path: str) -> Dict[str, Any]:
        if not self.graph or file_path not in self.graph:
            return {"in_degree": 0, "out_degree": 0, "callers": [], "callees": []}

        callers = [
            pred for pred in self.graph.predecessors(file_path)
            if self.graph.nodes.get(pred, {}).get("type") == "file"
        ]
        callees = [
            succ for succ in self.graph.successors(file_path)
            if self.graph.nodes.get(succ, {}).get("type") == "file"
        ]
        return {
            "in_degree": self.graph.in_degree(file_path),
            "out_degree": self.graph.out_degree(file_path),
            "callers": callers[:5],
            "callees": callees[:5],
        }

    def _rank_candidates(
        self,
        retrieved: List[Tuple],
        trace: ParsedStackTrace,
        frame_lookup: Dict[str, StackFrame],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        for chunk, sim_score in retrieved:
            matched_frame = self._match_frame(chunk.file_path, frame_lookup)
            base_score = float(sim_score)
            confidence = base_score

            if matched_frame:
                confidence = min(1.0, confidence + self.STACK_FRAME_BOOST + 0.15)

            graph_ctx = self._graph_context(chunk.file_path)
            graph_boost = min(0.15, graph_ctx["in_degree"] * self.GRAPH_CENTRALITY_WEIGHT)
            confidence = min(0.99, max(0.1, confidence + graph_boost))

            # Apply Ochiai spectrum score boost if available
            ochiai_score = self.spectrum_scores.get(chunk.file_path, 0.0)
            if ochiai_score > 0:
                confidence = min(0.99, confidence + (ochiai_score * 0.2))

            line_num = matched_frame.line_number if matched_frame else chunk.start_line
            func_name = matched_frame.function if matched_frame else chunk.name

            explanation = self._candidate_explanation(
                trace, chunk, matched_frame, graph_ctx, base_score, ochiai_score
            )

            candidates.append({
                "file_path": chunk.file_path,
                "function": func_name,
                "line_number": line_num,
                "confidence_score": round(confidence, 3),
                "semantic_similarity": round(base_score, 3),
                "ochiai_score": round(ochiai_score, 3),
                "explanation": explanation,
                "snippet": chunk.code,
                "kind": chunk.kind,
                "graph_context": {
                    "callers": graph_ctx["callers"],
                    "callees": graph_ctx["callees"],
                    "in_degree": graph_ctx["in_degree"],
                },
            })

        return candidates

    def _candidate_explanation(
        self,
        trace: ParsedStackTrace,
        chunk: CodeChunk,
        matched_frame: Optional[StackFrame],
        graph_ctx: Dict[str, Any],
        base_score: float,
        ochiai_score: float,
    ) -> str:
        parts = [
            f"Semantic match (similarity={base_score:.2f}) for {trace.error_type}",
        ]
        if trace.error_message:
            msg_preview = trace.error_message[:80]
            parts.append(f"message: '{msg_preview}'")

        if matched_frame:
            parts.insert(
                0,
                f"Stack trace points to {matched_frame.file_path}:{matched_frame.line_number} "
                f"in '{matched_frame.function}'.",
            )

        if ochiai_score > 0:
            parts.append(f"Ochiai suspiciousness score: {ochiai_score:.2f}.")

        parts.append(
            f"Code block '{chunk.name}' spans lines {chunk.start_line}-{chunk.end_line}."
        )

        if graph_ctx["callers"]:
            parts.append(f"Imported/called by: {', '.join(graph_ctx['callers'][:3])}.")
        if graph_ctx["callees"]:
            parts.append(f"Depends on: {', '.join(graph_ctx['callees'][:3])}.")

        return " ".join(parts)

    def _deduplicate_by_file(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[str, Dict[str, Any]] = {}
        for cand in candidates:
            fp = cand["file_path"]
            if fp not in best or cand["confidence_score"] > best[fp]["confidence_score"]:
                best[fp] = cand
        return list(best.values())

    def _build_root_cause_explanation(
        self,
        trace: ParsedStackTrace,
        candidates: List[Dict[str, Any]],
    ) -> str:
        if not candidates:
            return (
                f"No strong code matches found for {trace.error_type}. "
                "Try re-indexing the repository or providing a fuller stack trace."
            )

        top = candidates[0]
        explanation_parts = [
            f"Most likely root cause: {top['file_path']} in function '{top['function']}' "
            f"around line {top['line_number']} (confidence {top['confidence_score']:.0%}).",
        ]

        if trace.frames:
            deepest = trace.frames[0]
            explanation_parts.append(
                f"The stack trace originates at {deepest.file_path}:{deepest.line_number}."
            )

        if top.get("graph_context", {}).get("callers"):
            callers = top["graph_context"]["callers"]
            explanation_parts.append(
                f"This file is referenced by {len(callers)} upstream module(s), "
                f"suggesting a shared dependency or entry-point failure."
            )

        explanation_parts.append(top["explanation"])
        return " ".join(explanation_parts)


# Alias AdvancedBugLocalizer for backward compatibility
AdvancedBugLocalizer = BugLocalizer
