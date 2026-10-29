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
    total_passing: int,
) -> Dict[str, float]:
    """Calculates Ochiai suspiciousness scores across all covered code elements."""
    scores = {}
    for record in coverage_records:
        score = calculate_ochiai_score(
            ef=record.failing_exec_count,
            ep=record.passing_exec_count,
            nf=total_failing,
            np=total_passing,
        )
        scores[record.element_id] = score
    return scores


def calculate_tarantula_score(ef: int, ep: int, nf: int, np: int) -> float:
    """
    Calculates Tarantula suspiciousness score for a code element.
    Formula: Tarantula = (ef / nf) / ((ef / nf) + (ep / np))
    """
    if nf <= 0 or ef <= 0:
        return 0.0
    failed_ratio = float(ef) / float(nf)
    passed_ratio = float(ep) / float(np) if np > 0 else 0.0
    denom = failed_ratio + passed_ratio
    if denom <= 0.0:
        return 0.0
    return round(failed_ratio / denom, 4)


def calculate_dstar_score(ef: int, ep: int, nf: int, np: int, star_power: int = 2) -> float:
    """
    Calculates DStar suspiciousness score for a code element.
    Formula: DStar = (ef ** star_power) / (ep + (nf - ef))
    """
    if nf <= 0 or ef <= 0:
        return 0.0
    denom = float(ep) + float(nf - ef)
    if denom <= 0.0:
        return round(float(ef ** star_power), 4)
    return round(float(ef ** star_power) / denom, 4)


@dataclass
class ElementCoverageMetrics:
    """Complete SBFL metrics for a single code element (file, function, or line)."""
    element_id: str
    ef: int = 0  # failing executions covering element
    ep: int = 0  # passing executions covering element
    nf: int = 0  # total failing executions
    np: int = 0  # total passing executions
    ochiai: float = 0.0
    tarantula: float = 0.0
    dstar: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "ef": self.ef,
            "ep": self.ep,
            "nf": self.nf,
            "np": self.np,
            "ochiai": self.ochiai,
            "tarantula": self.tarantula,
            "dstar": self.dstar,
        }


class DynamicCoverageMatrix:
    """
    Dynamic Execution Spectrum Matrix for Spectrum-Based Fault Localization (SBFL).
    Ingests live test execution data and coverage reports, tracks exact execution
    profiles (ef, ep, nf, np) across statements/lines, functions, and files, and
    generates Ochiai, Tarantula, and DStar ranking spectrums.
    """

    def __init__(self):
        # test_id -> {"passed": bool, "covered": Set[str]}
        self.tests: Dict[str, Dict[str, Any]] = {}
        self.element_failing_counts: Dict[str, int] = {}
        self.element_passing_counts: Dict[str, int] = {}
        self.total_failing: int = 0
        self.total_passing: int = 0
        self._dirty: bool = True
        self._metrics_cache: Dict[str, ElementCoverageMetrics] = {}

    def record_test(self, test_id: str, passed: bool, covered_elements: Any) -> None:
        """Records the execution of a test and its set of covered code elements."""
        self._dirty = True
        elements = set(covered_elements)
        self.tests[test_id] = {
            "passed": passed,
            "covered": elements,
        }
        self._recount()

    def record_test_lines(self, test_id: str, passed: bool, file_path: str, lines: Any) -> None:
        """Records executed line numbers for a test in a file."""
        norm_path = file_path.replace("\\", "/").lstrip("./")
        covered = {norm_path}
        for ln in lines:
            covered.add(f"{norm_path}:{ln}")
        self.record_test(test_id, passed, covered)

    def _recount(self) -> None:
        """Recomputes global counts from recorded tests."""
        self.element_failing_counts.clear()
        self.element_passing_counts.clear()
        self.total_failing = 0
        self.total_passing = 0

        for t_info in self.tests.values():
            if t_info["passed"]:
                self.total_passing += 1
                for el in t_info["covered"]:
                    self.element_passing_counts[el] = self.element_passing_counts.get(el, 0) + 1
            else:
                self.total_failing += 1
                for el in t_info["covered"]:
                    self.element_failing_counts[el] = self.element_failing_counts.get(el, 0) + 1

    def compute_metrics(self) -> Dict[str, ElementCoverageMetrics]:
        """Calculates Ochiai, Tarantula, and DStar metrics for every covered element."""
        if not self._dirty and self._metrics_cache:
            return self._metrics_cache

        all_elements = set(self.element_failing_counts.keys()) | set(self.element_passing_counts.keys())
        metrics: Dict[str, ElementCoverageMetrics] = {}

        for el in all_elements:
            ef = self.element_failing_counts.get(el, 0)
            ep = self.element_passing_counts.get(el, 0)
            och = calculate_ochiai_score(ef, ep, self.total_failing, self.total_passing)
            tar = calculate_tarantula_score(ef, ep, self.total_failing, self.total_passing)
            dst = calculate_dstar_score(ef, ep, self.total_failing, self.total_passing)

            metrics[el] = ElementCoverageMetrics(
                element_id=el,
                ef=ef,
                ep=ep,
                nf=self.total_failing,
                np=self.total_passing,
                ochiai=och,
                tarantula=tar,
                dstar=dst,
            )

        self._metrics_cache = metrics
        self._dirty = False
        return metrics

    def get_metrics(self, element_id: str) -> Optional[ElementCoverageMetrics]:
        """Retrieves metrics for a specific code element."""
        metrics = self.compute_metrics()
        return metrics.get(element_id)

    def to_spectrum_scores(self, metric: str = "ochiai", min_score: float = 0.0) -> Dict[str, float]:
        """Exports dictionary mapping element_id to score for the chosen metric."""
        metrics = self.compute_metrics()
        scores: Dict[str, float] = {}
        for el, m in metrics.items():
            val = getattr(m, metric.lower(), m.ochiai)
            if val >= min_score:
                scores[el] = val
        return scores

    def to_coverage_records(self) -> List[CoverageRecord]:
        """Exports elements as CoverageRecord dataclasses."""
        all_elements = set(self.element_failing_counts.keys()) | set(self.element_passing_counts.keys())
        return [
            CoverageRecord(
                element_id=el,
                failing_exec_count=self.element_failing_counts.get(el, 0),
                passing_exec_count=self.element_passing_counts.get(el, 0),
            )
            for el in sorted(all_elements)
        ]

    def get_top_suspicious_elements(self, metric: str = "ochiai", top_k: int = 20) -> List[Dict[str, Any]]:
        """Returns top-k most suspicious code elements sorted by metric."""
        metrics = self.compute_metrics()
        attr = metric.lower()
        sorted_m = sorted(
            metrics.values(),
            key=lambda m: getattr(m, attr, m.ochiai),
            reverse=True,
        )
        return [m.to_dict() for m in sorted_m[:top_k]]

    def summary(self) -> Dict[str, Any]:
        """Summarizes test counts and coverage statistics."""
        metrics = self.compute_metrics()
        top_ochiai = self.get_top_suspicious_elements("ochiai", top_k=5)
        return {
            "total_tests": len(self.tests),
            "total_failing": self.total_failing,
            "total_passing": self.total_passing,
            "total_covered_elements": len(metrics),
            "top_suspicious_elements": top_ochiai,
        }

    @classmethod
    def from_test_runs(cls, runs: List[Dict[str, Any]]) -> "DynamicCoverageMatrix":
        """
        Creates a DynamicCoverageMatrix from a list of test run dictionaries.
        Each run dict: {"test_id": str, "passed": bool, "covered_elements": List[str]}
        """
        matrix = cls()
        for idx, run in enumerate(runs):
            t_id = run.get("test_id", f"test_{idx}")
            passed = bool(run.get("passed", False))
            covered = run.get("covered_elements") or run.get("covered") or []
            matrix.record_test(t_id, passed, covered)
        return matrix

    @classmethod
    def from_pytest_cov_json(
        cls,
        report_data: Any,
        test_results: Optional[Dict[str, bool]] = None,
        failing_files: Optional[List[str]] = None,
    ) -> "DynamicCoverageMatrix":
        """
        Parses standard pytest-cov / coverage.py JSON report data.
        report_data can be a JSON file path, a JSON string, or a parsed dictionary.
        Correlates covered lines with passing and failing test outcomes.
        """
        import json
        if isinstance(report_data, (str, os.PathLike)) and os.path.exists(str(report_data)):
            with open(str(report_data), "r", encoding="utf-8") as f:
                data = json.load(f)
        elif isinstance(report_data, str):
            data = json.loads(report_data)
        elif isinstance(report_data, dict):
            data = report_data
        else:
            raise ValueError(f"Unsupported report_data type: {type(report_data)}")

        matrix = cls()
        files_data = data.get("files", {})
        norm_failing_files = {f.replace("\\", "/").lstrip("./") for f in (failing_files or [])}

        # If test_results provided: e.g. {"test_auth": False, "test_order": True}
        if test_results:
            for t_id, passed in test_results.items():
                all_covered: Set[str] = set()
                for f_path, f_info in files_data.items():
                    norm_f = f_path.replace("\\", "/").lstrip("./")
                    # Attribute files matching failure pattern or all covered files
                    exec_lines = f_info.get("executed_lines", [])
                    if not passed and norm_failing_files and norm_f not in norm_failing_files:
                        continue
                    all_covered.add(norm_f)
                    for ln in exec_lines:
                        all_covered.add(f"{norm_f}:{ln}")
                matrix.record_test(t_id, passed, all_covered)
        else:
            # Synthetic distribution based on failing_files
            for f_path, f_info in files_data.items():
                norm_f = f_path.replace("\\", "/").lstrip("./")
                exec_lines = f_info.get("executed_lines", [])
                covered = {norm_f} | {f"{norm_f}:{ln}" for ln in exec_lines}

                is_fail = norm_f in norm_failing_files if norm_failing_files else False
                if is_fail:
                    matrix.record_test(f"fail_trace_{norm_f}", False, covered)
                else:
                    matrix.record_test(f"pass_trace_{norm_f}", True, covered)

        return matrix

    @classmethod
    def from_matrix_dict(cls, matrix_dict: Dict[str, Dict[str, Any]]) -> "DynamicCoverageMatrix":
        """
        Creates a matrix from a dictionary mapping test_id to details:
        {"test_1": {"passed": False, "covered": ["auth.py:12", "auth.py::login"]}}
        """
        matrix = cls()
        for t_id, info in matrix_dict.items():
            passed = bool(info.get("passed", False))
            covered = info.get("covered", [])
            matrix.record_test(t_id, passed, covered)
        return matrix


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
        coverage_records: Optional[List[CoverageRecord]] = None,
        coverage_matrix: Optional[DynamicCoverageMatrix] = None,
        total_failing: int = 0,
        total_passing: int = 0,
    ):
        self.store = store
        self.embedder = embedder
        self.graph = graph
        self.spectrum_scores = dict(spectrum_scores) if spectrum_scores else {}
        self.coverage_matrix = coverage_matrix

        if coverage_matrix:
            self.spectrum_scores.update(coverage_matrix.to_spectrum_scores(metric="ochiai"))

        if coverage_records and total_failing > 0:
            calculated = calculate_ochiai_spectrum(coverage_records, total_failing, total_passing)
            self.spectrum_scores.update(calculated)
        self.parser = StackTraceParser()

    def load_coverage_matrix(self, matrix: DynamicCoverageMatrix) -> None:
        """Loads a DynamicCoverageMatrix and incorporates its Ochiai spectrum scores."""
        self.coverage_matrix = matrix
        self.spectrum_scores.update(matrix.to_spectrum_scores(metric="ochiai"))

    def load_pytest_cov_report(
        self,
        report_data: Any,
        test_results: Optional[Dict[str, bool]] = None,
        failing_files: Optional[List[str]] = None,
    ) -> DynamicCoverageMatrix:
        """Parses a pytest-cov report and loads it as the active coverage matrix."""
        matrix = DynamicCoverageMatrix.from_pytest_cov_json(
            report_data=report_data,
            test_results=test_results,
            failing_files=failing_files,
        )
        self.load_coverage_matrix(matrix)
        return matrix

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

            norm_file = chunk.file_path.replace("\\", "/").lstrip("./")
            base_file = os.path.basename(chunk.file_path)

            # Check line-level spectrum scores if lines are covered
            best_line = matched_frame.line_number if matched_frame else chunk.start_line
            best_line_score = 0.0
            if chunk.start_line and chunk.end_line and chunk.end_line >= chunk.start_line:
                for ln in range(chunk.start_line, chunk.end_line + 1):
                    ln_score = max(
                        self.spectrum_scores.get(f"{norm_file}:{ln}", 0.0),
                        self.spectrum_scores.get(f"{base_file}:{ln}", 0.0),
                    )
                    if ln_score > best_line_score:
                        best_line_score = ln_score
                        best_line = ln

            # Apply Ochiai spectrum score boost if available
            ochiai_score = max(
                best_line_score,
                self.spectrum_scores.get(chunk.chunk_id, 0.0),
                self.spectrum_scores.get(f"{norm_file}::{chunk.name}", 0.0),
                self.spectrum_scores.get(norm_file, 0.0),
                self.spectrum_scores.get(f"{base_file}::{chunk.name}", 0.0),
                self.spectrum_scores.get(base_file, 0.0),
                self.spectrum_scores.get(chunk.name, 0.0),
            )
            if ochiai_score > 0:
                confidence = min(0.99, confidence + (ochiai_score * 0.2))

            line_num = best_line if best_line_score > 0 else (matched_frame.line_number if matched_frame else chunk.start_line)
            func_name = matched_frame.function if matched_frame else chunk.name

            # Retrieve rich spectrum breakdown if coverage matrix is loaded
            spectrum_metrics = None
            if self.coverage_matrix:
                m = (
                    self.coverage_matrix.get_metrics(f"{norm_file}:{line_num}")
                    or self.coverage_matrix.get_metrics(f"{norm_file}::{func_name}")
                    or self.coverage_matrix.get_metrics(norm_file)
                )
                if m:
                    spectrum_metrics = m.to_dict()

            explanation = self._candidate_explanation(
                trace, chunk, matched_frame, graph_ctx, base_score, ochiai_score
            )
            if best_line_score > 0 and not matched_frame:
                explanation = f"Dynamic line {line_num} executed in failing tests (Ochiai={best_line_score:.2f}). " + explanation

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
                "spectrum_analysis": spectrum_metrics,
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
        elif ochiai_score > 0:
            parts.insert(
                0,
                "Candidate localized via Ochiai SBFL spectrum scoring (logical fault without active stack frame).",
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

    def _diagnose_violated_invariants(self, error_type: str, error_message: str) -> Optional[str]:
        """Diagnoses failure mechanisms and violated preconditions/invariants based on error type."""
        err_lower = error_type.lower()
        if "typeerror" in err_lower:
            return "Violated precondition: Type contract mismatch or unexpected NoneType operand passed to operation."
        if "valueerror" in err_lower:
            return "Violated precondition: Argument received has invalid state, shape, or domain bounds."
        if "keyerror" in err_lower:
            return "Violated invariant: Required mapping key is missing from dictionary/lookup structure."
        if "indexerror" in err_lower or "outofbounds" in err_lower:
            return "Violated invariant: Sequence index exceeds length boundary or list is empty."
        if "attributeerror" in err_lower or "nullpointer" in err_lower:
            return "Violated precondition: Invoked attribute or method on uninitialized or NoneType reference."
        if "zerodivision" in err_lower:
            return "Violated invariant: Divisor evaluates to zero without boundary guard."
        if "syntaxerror" in err_lower:
            return "Violated syntactic rule: Invalid grammar, unbalanced delimiter, or malformed statement."
        return None

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
        mode = "Reproduced cause (Stack Trace)" if trace.frames else "Suspected cause (SBFL & Static Reasoning)"
        explanation_parts = [
            f"[{mode}] Most likely root cause: {top['file_path']} in function '{top['function']}' "
            f"around line {top['line_number']} (confidence {top['confidence_score']:.0%}).",
        ]

        violated_inv = self._diagnose_violated_invariants(trace.error_type, trace.error_message)
        if violated_inv:
            explanation_parts.append(violated_inv)

        if trace.frames:
            deepest = trace.frames[0]
            explanation_parts.append(
                f"The stack trace originates at {deepest.file_path}:{deepest.line_number}."
            )
        elif top.get("ochiai_score", 0.0) > 0:
            explanation_parts.append(
                f"Spectrum-based fault localization (Ochiai metric {top['ochiai_score']:.2f}) indicates high fault suspiciousness."
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
