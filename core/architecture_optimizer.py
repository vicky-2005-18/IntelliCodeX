"""
Architecture Optimization & Circular Dependency Refactoring Engine (REQ-FUT-06)
Analyzes dependency graphs, call graphs, and source code to detect:
1. Circular dependency cycles (A -> B -> A, multi-hop cycles)
2. High-coupling architectural bottlenecks (God modules, high fan-in / fan-out)
3. Module instability metrics (Afferent Ca, Efferent Ce, Instability I = Ce / (Ca + Ce))
4. Large or overly complex functions and classes exceeding reliable line thresholds
Generates grounded refactoring recommendations with tradeoffs, limitations, and decoupling diffs.
"""
import ast
import os
import time
import difflib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Set, Tuple
import networkx as nx

from core.parser import SourceFile


@dataclass
class ModuleCoupling:
    module: str
    afferent_coupling: int  # Ca: incoming dependencies (who depends on this)
    efferent_coupling: int  # Ce: outgoing dependencies (what this depends on)
    instability: float      # I = Ce / (Ca + Ce), 0.0 = maximal stability, 1.0 = maximal instability
    is_bottleneck: bool = False
    warning: Optional[str] = None


@dataclass
class RefactoringRecommendation:
    """
    Grounded Refactoring Recommendation Contract (REQ-FUT-06).
    Every finding substantiates its advice with measured facts, source references,
    configured thresholds, explicit engineering tradeoffs, and static analysis limitations.
    """
    # Grounded Contract Fields
    finding_type: str                  # 'circular_dependency', 'high_coupling_bottleneck', 'complex_component'
    target: str                        # Target symbol or module cycle representation
    affected_files: List[str]          # Files involved
    affected_symbols: List[str]        # Specific symbol(s) involved if applicable
    supporting_evidence: Dict[str, Any]# Graph edges, measured Ca/Ce, or AST line counts
    source_locations: List[Dict[str, Any]] # Exact file/line references [{"file": ..., "line": ..., "statement": ...}]
    threshold_used: Dict[str, Any]     # Configuration threshold applied
    explanation: str                   # Factual explanation of structural pattern
    proposed_improvement: str          # Actionable decoupling or decomposition strategy
    tradeoffs: str                     # Engineering costs (indirection, extra files, mental model)
    limitations: str                   # Static analysis boundaries (dynamic dispatch, no runtime latency claims)
    confidence: str = "high"           # "high" | "medium"

    # Backward-compatible fields
    type: str = ""                     # Legacy: 'cycle_break', 'god_component_split', 'component_split'
    description: str = ""
    strategy: str = ""
    affected_nodes: List[str] = field(default_factory=list)
    suggested_diff: Optional[str] = None

    def __post_init__(self):
        if not self.type:
            if self.finding_type == "circular_dependency":
                self.type = "cycle_break"
            elif self.finding_type == "high_coupling_bottleneck":
                self.type = "god_component_split"
            else:
                self.type = "component_split"
        if not self.description:
            self.description = self.explanation
        if not self.strategy:
            self.strategy = self.proposed_improvement
        if not self.affected_nodes:
            self.affected_nodes = list(self.affected_files)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectureReport:
    total_modules: int
    total_dependencies: int
    cycles: List[List[str]]
    bottlenecks: List[ModuleCoupling]
    coupling_metrics: Dict[str, ModuleCoupling]
    recommendations: List[RefactoringRecommendation]
    health_score: float  # 0.0 to 100.0
    snapshot_info: Dict[str, Any] = field(default_factory=dict)
    measured_facts: Dict[str, Any] = field(default_factory=dict)
    ai_advisory: Dict[str, Any] = field(default_factory=dict)
    complex_components: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_modules": self.total_modules,
            "total_dependencies": self.total_dependencies,
            "cycles_count": len(self.cycles),
            "cycles": self.cycles,
            "bottlenecks": [asdict(b) for b in self.bottlenecks],
            "coupling_metrics": {k: asdict(v) for k, v in self.coupling_metrics.items()},
            "complex_components": self.complex_components,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "health_score": round(self.health_score, 1),
            "snapshot_info": self.snapshot_info,
            "measured_facts": self.measured_facts,
            "ai_advisory": self.ai_advisory,
        }

    def format_markdown(self) -> str:
        lines = [
            "# Architecture Optimization & Health Report",
            f"- **System Health Score**: {self.health_score:.1f} / 100.0",
            f"- **Total Analyzed Modules**: {self.total_modules}",
            f"- **Total Dependencies**: {self.total_dependencies}",
            f"- **Detected Circular Dependency Cycles**: {len(self.cycles)}",
            f"- **High-Coupling Bottlenecks**: {len(self.bottlenecks)}",
            f"- **Complex Components Detected**: {len(self.complex_components)}",
        ]

        if self.snapshot_info:
            repo_lbl = self.snapshot_info.get("repo_id") or "local"
            snap_lbl = self.snapshot_info.get("snapshot_id") or "current"
            is_stale = self.snapshot_info.get("is_stale", False)
            stale_str = "⚠️ Graph data may be stale" if is_stale else "✅ Fresh"
            lines.append(f"- **Repository Scope**: `{repo_lbl}` (Snapshot: `{snap_lbl}`) — {stale_str}")
            if self.snapshot_info.get("stale_warning"):
                lines.append(f"  > *Warning*: {self.snapshot_info['stale_warning']}")

        lines.append("")

        # Section 1: Measured Facts (Deterministic)
        lines.append("## 1. Measured Architectural Facts (Deterministic)")

        if self.cycles:
            lines.append("### Circular Dependency Cycles Detected")
            for idx, c in enumerate(self.cycles, start=1):
                cycle_str = " -> ".join(c + [c[0]])
                lines.append(f"{idx}. `{cycle_str}`")
            lines.append("")
        else:
            lines.append("### Circular Dependencies: None detected (Clean acyclic DAG)")
            lines.append("")

        if self.bottlenecks:
            lines.append("### High-Coupling Architectural Modules")
            lines.append("> *Note: High centrality alone is not inherently a defect. Stable utility or orchestrator modules legitimately exhibit high fan-in/fan-out. Heavy bidirectional coupling increases change-propagation risk.*")
            lines.append("")
            lines.append("| Module | Afferent ($C_a$) | Efferent ($C_e$) | Instability ($I$) | Assessment |")
            lines.append("| :--- | :---: | :---: | :---: | :--- |")
            for b in self.bottlenecks:
                lines.append(f"| `{b.module}` | {b.afferent_coupling} | {b.efferent_coupling} | {b.instability:.2f} | {b.warning or 'High coupling'} |")
            lines.append("")

        if self.complex_components:
            lines.append("### Overly Complex Components")
            lines.append("| Symbol | File | Lines | Type | Threshold |")
            lines.append("| :--- | :--- | :---: | :--- | :---: |")
            for cc in self.complex_components:
                lines.append(f"| `{cc.get('symbol')}` | `{cc.get('file')}:{cc.get('start_line', 1)}` | {cc.get('line_count')} | {cc.get('type')} | {cc.get('threshold')} lines |")
            lines.append("")

        # Section 2: Grounded Refactoring Recommendations
        if self.recommendations:
            lines.append("## 2. Grounded Refactoring Recommendations")
            for idx, r in enumerate(self.recommendations, start=1):
                lines.append(f"### {idx}. [{r.finding_type.upper()}] {r.target}")
                lines.append(f"- **Affected Files**: {', '.join(f'`{f}`' for f in r.affected_files)}")
                if r.source_locations:
                    locs_str = ", ".join(f"`{loc.get('file')}:{loc.get('line', '?')}`" for loc in r.source_locations if loc.get("file"))
                    if locs_str:
                        lines.append(f"- **Source Locations**: {locs_str}")
                lines.append(f"- **Evidence**: `{r.supporting_evidence}`")
                lines.append(f"- **Threshold Applied**: `{r.threshold_used}`")
                lines.append(f"- **Confidence**: `{r.confidence}`")
                lines.append(f"> **Explanation**: {r.explanation}")
                lines.append(f"\n**Proposed Improvement**:\n{r.proposed_improvement}\n")
                lines.append(f"**Engineering Tradeoffs**:\n{r.tradeoffs}\n")
                lines.append(f"**Static Analysis Limitations**:\n{r.limitations}\n")
                if r.suggested_diff:
                    lines.append(f"```diff\n{r.suggested_diff}\n```\n")
        else:
            lines.append("## 2. Grounded Refactoring Recommendations")
            lines.append("No architectural refactoring recommendations triggered under current thresholds.")
            lines.append("")

        # Section 3: AI Advisory
        lines.append("## 3. AI Architectural Advisory")
        adv_status = self.ai_advisory.get("status", "unavailable")
        adv_model = self.ai_advisory.get("model", "none")
        if adv_status == "generated" and self.ai_advisory.get("advisory"):
            lines.append(f"> *Model*: `{adv_model}` | *Status*: Generated from measured facts")
            lines.append(f"> *Notice*: {self.ai_advisory.get('notice', '')}")
            lines.append("")
            lines.append(self.ai_advisory["advisory"])
        else:
            notice = self.ai_advisory.get("notice") or "Deterministic analysis executed without LLM. All findings, metrics, and refactoring strategies are substantiated by static dependency and AST measurements."
            lines.append(f"> *Status*: `Deterministic Mode (LLM {adv_status})`")
            lines.append(f"> *Notice*: {notice}")

        lines.append("")
        return "\n".join(lines)


class ArchitectureOptimizer:
    """
    Automated Architecture Optimizer & Circular Dependency Refactoring Engine.
    Detects cycles, package coupling metrics, bottlenecks, and complex components.
    Produces grounded recommendations with measured facts, source locations, and tradeoffs.
    """

    def __init__(
        self,
        high_coupling_threshold: int = 5,
        complexity_lines_threshold: int = 80,
        complexity_class_lines_threshold: int = 250,
    ):
        self.high_coupling_threshold = high_coupling_threshold
        self.complexity_lines_threshold = complexity_lines_threshold
        self.complexity_class_lines_threshold = complexity_class_lines_threshold

    def analyze(
        self,
        dep_graph: nx.DiGraph,
        source_files: Optional[List[SourceFile]] = None,
        llm: Optional[Any] = None,
        repo_id: Optional[str] = None,
        snapshot_id: str = "current",
        is_stale: bool = False,
        stale_warning: Optional[str] = None,
    ) -> ArchitectureReport:
        """
        Analyzes a dependency DiGraph to extract cycles, coupling metrics, bottlenecks,
        complex components, and grounded recommendations.
        """
        # 1. Build module-to-module clean subgraph
        mod_graph = nx.DiGraph()
        for node, d in dep_graph.nodes(data=True):
            if not str(node).startswith("ext:") and not str(node).startswith("API:") and not str(node).startswith("DB:"):
                clean_n = str(node).split("::")[0].replace("\\", "/")
                mod_graph.add_node(clean_n)

        for u, v, d in dep_graph.edges(data=True):
            # Only consider internal module/file dependencies
            rel = d.get("relationship", "")
            if rel in ("imports", "depends_on", "") and not str(v).startswith("ext:") and not str(v).startswith("API:") and not str(v).startswith("DB:"):
                # Clean node ids if they are symbols to files
                u_mod = u.split("::")[0] if "::" in str(u) else str(u)
                v_mod = v.split("::")[0] if "::" in str(v) else str(v)
                u_mod = u_mod.replace("\\", "/")
                v_mod = v_mod.replace("\\", "/")
                if u_mod != v_mod:
                    mod_graph.add_edge(u_mod, v_mod)

        # 2. Cycle Detection (Simple Cycles)
        cycles: List[List[str]] = []
        try:
            raw_cycles = list(nx.simple_cycles(mod_graph))
            # Sort cycles by length and normalize representation
            for rc in raw_cycles:
                if len(rc) >= 2:
                    # Canonical rotation starting with min node
                    min_idx = rc.index(min(rc))
                    norm_cycle = rc[min_idx:] + rc[:min_idx]
                    if norm_cycle not in cycles:
                        cycles.append(norm_cycle)
        except Exception:
            pass

        # 3. Module Coupling Metrics (Martin's Package Metrics: Ca, Ce, Instability)
        coupling_metrics: Dict[str, ModuleCoupling] = {}
        bottlenecks: List[ModuleCoupling] = []

        all_modules = set(mod_graph.nodes())
        if source_files:
            for sf in source_files:
                all_modules.add(sf.rel_path.replace("\\", "/"))

        for mod in sorted(all_modules):
            ca = mod_graph.in_degree(mod) if mod in mod_graph else 0
            ce = mod_graph.out_degree(mod) if mod in mod_graph else 0
            total_c = ca + ce
            instability = round(float(ce) / float(total_c), 3) if total_c > 0 else 0.0

            is_bottleneck = False
            warning = None
            if ca >= self.high_coupling_threshold and ce >= self.high_coupling_threshold:
                is_bottleneck = True
                warning = f"Hub Component (High Afferent & Efferent Coupling): Ca={ca}, Ce={ce}"
            elif ca >= int(self.high_coupling_threshold * 1.5):
                is_bottleneck = True
                warning = f"Critical Hotspot (Excessive Inbound Dependents): Ca={ca}"
            elif ce >= int(self.high_coupling_threshold * 1.5):
                is_bottleneck = True
                warning = f"Fragile Component (Excessive Outbound Dependencies): Ce={ce}"

            mc = ModuleCoupling(
                module=mod,
                afferent_coupling=ca,
                efferent_coupling=ce,
                instability=instability,
                is_bottleneck=is_bottleneck,
                warning=warning,
            )
            coupling_metrics[mod] = mc
            if is_bottleneck:
                bottlenecks.append(mc)

        # 4. Complex Components Analysis (Large functions/classes)
        complex_components: List[Dict[str, Any]] = []
        complex_recs: List[RefactoringRecommendation] = []
        sf_map = {sf.rel_path.replace("\\", "/"): sf for sf in source_files} if source_files else {}

        if source_files:
            for sf in source_files:
                norm_p = sf.rel_path.replace("\\", "/")
                if sf.language == "python" and sf.content:
                    try:
                        tree = ast.parse(sf.content, filename=norm_p)
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                end_l = getattr(node, "end_lineno", node.lineno)
                                lines_cnt = end_l - node.lineno + 1
                                if lines_cnt > self.complexity_lines_threshold:
                                    sym_name = node.name
                                    cc_item = {
                                        "symbol": sym_name,
                                        "file": norm_p,
                                        "start_line": node.lineno,
                                        "end_line": end_l,
                                        "line_count": lines_cnt,
                                        "type": "function",
                                        "threshold": self.complexity_lines_threshold,
                                    }
                                    complex_components.append(cc_item)
                                    complex_recs.append(self._generate_complex_component_recommendation(cc_item))
                            elif isinstance(node, ast.ClassDef):
                                end_l = getattr(node, "end_lineno", node.lineno)
                                lines_cnt = end_l - node.lineno + 1
                                if lines_cnt > self.complexity_class_lines_threshold:
                                    sym_name = node.name
                                    cc_item = {
                                        "symbol": sym_name,
                                        "file": norm_p,
                                        "start_line": node.lineno,
                                        "end_line": end_l,
                                        "line_count": lines_cnt,
                                        "type": "class",
                                        "threshold": self.complexity_class_lines_threshold,
                                    }
                                    complex_components.append(cc_item)
                                    complex_recs.append(self._generate_complex_component_recommendation(cc_item))
                    except SyntaxError:
                        pass
                elif sf.content:
                    # Generic line-count fallback for non-Python or non-parsed files
                    total_lines = len(sf.content.splitlines())
                    if total_lines > self.complexity_class_lines_threshold:
                        cc_item = {
                            "symbol": os.path.basename(norm_p),
                            "file": norm_p,
                            "start_line": 1,
                            "end_line": total_lines,
                            "line_count": total_lines,
                            "type": "file",
                            "threshold": self.complexity_class_lines_threshold,
                        }
                        complex_components.append(cc_item)
                        complex_recs.append(self._generate_complex_component_recommendation(cc_item))

        # 5. Synthesize Refactoring Recommendations
        recommendations: List[RefactoringRecommendation] = []

        # 5a. Circular Dependency Recommendations
        for cycle in cycles:
            rec = self._generate_cycle_recommendation(cycle, sf_map, mod_graph, llm)
            recommendations.append(rec)

        # 5b. God Component / Bottleneck Recommendations
        for b in bottlenecks:
            rec = self._generate_bottleneck_recommendation(b, sf_map, mod_graph)
            recommendations.append(rec)

        # 5c. Complex Component Recommendations
        recommendations.extend(complex_recs)

        # 6. Compute System Architectural Health Score (100 base)
        # Deductions: -15 per cycle (max 45), -8 per bottleneck (max 30), -5 per complex component (max 20)
        cycle_penalty = min(45.0, len(cycles) * 15.0)
        bottleneck_penalty = min(30.0, len(bottlenecks) * 8.0)
        complexity_penalty = min(20.0, len(complex_components) * 5.0)
        health_score = max(10.0, 100.0 - cycle_penalty - bottleneck_penalty - complexity_penalty)

        # 7. Formulate Snapshot Info and Measured Facts
        snapshot_dict = {
            "repo_id": repo_id,
            "snapshot_id": snapshot_id,
            "analyzed_at": time.time(),
            "is_stale": is_stale,
            "stale_warning": stale_warning,
        }

        measured_facts = {
            "total_modules": len(all_modules),
            "total_dependencies": mod_graph.number_of_edges(),
            "detected_cycles": cycles,
            "cycle_count": len(cycles),
            "bottlenecks": [asdict(b) for b in bottlenecks],
            "bottleneck_count": len(bottlenecks),
            "complex_components": complex_components,
            "coupling_metrics": {k: asdict(v) for k, v in coupling_metrics.items()},
        }

        # 8. Optional LLM Architectural Advisory (Strictly Grounded in Measured Facts)
        ai_advisory = self._generate_ai_advisory(measured_facts, llm)

        return ArchitectureReport(
            total_modules=len(all_modules),
            total_dependencies=mod_graph.number_of_edges(),
            cycles=cycles,
            bottlenecks=bottlenecks,
            coupling_metrics=coupling_metrics,
            recommendations=recommendations,
            health_score=health_score,
            snapshot_info=snapshot_dict,
            measured_facts=measured_facts,
            ai_advisory=ai_advisory,
            complex_components=complex_components,
        )

    def _generate_cycle_recommendation(
        self,
        cycle: List[str],
        sf_map: Dict[str, SourceFile],
        mod_graph: nx.DiGraph,
        llm: Optional[Any] = None,
    ) -> RefactoringRecommendation:
        """Proposes concrete decoupling strategies, source line citations, and code refactoring diffs for cycles."""
        cycle_repr = " <-> ".join(cycle)
        head, tail = cycle[0], cycle[1]

        # Extract import line citations and statements
        source_locations = []
        for i in range(len(cycle)):
            curr_mod = cycle[i]
            next_mod = cycle[(i + 1) % len(cycle)]
            sf = sf_map.get(curr_mod)
            if sf and sf.content:
                next_base = os.path.splitext(os.path.basename(next_mod))[0]
                lines = sf.content.splitlines()
                for idx, line in enumerate(lines, start=1):
                    if f"import {next_base}" in line or f"from {next_base}" in line or f"from .{next_base}" in line:
                        source_locations.append({
                            "file": curr_mod,
                            "line": idx,
                            "statement": line.strip(),
                            "target_import": next_mod,
                        })
                        break

        # Check if we have source code to generate suggested diff
        target_sf = sf_map.get(tail) or sf_map.get(head)
        diff_str = None

        if target_sf and target_sf.content:
            head_base = os.path.splitext(os.path.basename(head))[0]
            lines = target_sf.content.splitlines()
            import_line_idx = -1
            import_content = ""
            for idx, line in enumerate(lines):
                if f"import {head_base}" in line or f"from {head_base}" in line or f"from .{head_base}" in line:
                    import_line_idx = idx
                    import_content = line
                    break

            if import_line_idx != -1:
                orig_code = target_sf.content
                patched_lines = list(lines)
                patched_lines[import_line_idx] = f"# Deferred to avoid circular import: {import_content}"
                new_code = "\n".join(patched_lines) + "\n"
                diff_lines = list(difflib.unified_diff(
                    orig_code.splitlines(keepends=True),
                    new_code.splitlines(keepends=True),
                    fromfile=f"a/{target_sf.rel_path}",
                    tofile=f"b/{target_sf.rel_path}",
                ))
                if diff_lines:
                    diff_str = "".join(diff_lines[:20])

        cycle_edges = [[cycle[i], cycle[(i + 1) % len(cycle)]] for i in range(len(cycle))]
        strategy = (
            f"1. Dependency Inversion: Extract shared types, models, or function contracts into a dedicated leaf module (e.g. `{os.path.splitext(head)[0]}_types.py`).\n"
            f"2. Deferred / Lazy Import: Move `import {os.path.splitext(os.path.basename(head))[0]}` inside the specific function or method body where it is invoked.\n"
            f"3. Dependency Injection: Pass the collaborator instance as a function parameter or constructor argument."
        )

        tradeoffs = (
            "Creating separate interface/types modules increases total repository file count. "
            "Deferred local imports can mask import-time missing dependency failures until execution time."
        )

        limitations = (
            "Static AST detection finds top-level import statements; dynamic reflection (`importlib.import_module`) "
            "or runtime conditional guards (`if TYPE_CHECKING:`) may prevent actual runtime panics despite static cycle presence."
        )

        return RefactoringRecommendation(
            finding_type="circular_dependency",
            target=cycle_repr,
            affected_files=list(cycle),
            affected_symbols=[],
            supporting_evidence={"cycle": cycle, "cycle_edges": cycle_edges, "length": len(cycle)},
            source_locations=source_locations,
            threshold_used={"min_cycle_length": 2},
            explanation=f"Circular dependency between {len(cycle)} modules: {' -> '.join(cycle + [cycle[0]])}.",
            proposed_improvement=strategy,
            tradeoffs=tradeoffs,
            limitations=limitations,
            confidence="high",
            suggested_diff=diff_str,
        )

    def _generate_bottleneck_recommendation(
        self,
        bottleneck: ModuleCoupling,
        sf_map: Dict[str, SourceFile],
        mod_graph: nx.DiGraph,
    ) -> RefactoringRecommendation:
        """Proposes Single Responsibility Principle decomposition for high-coupling God modules."""
        target = bottleneck.module
        strategy = (
            f"1. Facade Pattern: Split `{target}` into cohesive single-responsibility domain sub-modules and maintain `{target}` as a light orchestrator facade.\n"
            f"2. Event / Callback Decoupling: Use observer callbacks or event dispatch to notify dependents without tight direct import coupling.\n"
            f"3. Inbound Contract Extraction: Module has {bottleneck.afferent_coupling} inbound dependents; isolate callers behind narrow interface boundaries."
        )

        tradeoffs = (
            "Decomposing central hub modules increases structural indirection and call layers. "
            "Splitting stable, tested central utility components risks introducing regressions without measurable throughput benefits."
        )

        limitations = (
            "High centrality alone is NOT an inherent design defect: central coordinators or foundational utilities naturally have high fan-in/fan-out. "
            "Coupling is derived purely from static import counts; runtime call frequency and execution latency are not measured. "
            "Do not claim performance improvements without dynamic profiling measurements."
        )

        return RefactoringRecommendation(
            finding_type="high_coupling_bottleneck",
            target=target,
            affected_files=[target],
            affected_symbols=[],
            supporting_evidence={
                "afferent_coupling_ca": bottleneck.afferent_coupling,
                "efferent_coupling_ce": bottleneck.efferent_coupling,
                "instability_i": bottleneck.instability,
                "is_hub": bool(bottleneck.afferent_coupling >= self.high_coupling_threshold and bottleneck.efferent_coupling >= self.high_coupling_threshold),
            },
            source_locations=[{"file": target, "line": 1, "statement": "module_root"}],
            threshold_used={"high_coupling_threshold": self.high_coupling_threshold},
            explanation=f"High-coupling architectural module in `{target}` ({bottleneck.warning or 'Excessive dependencies'}).",
            proposed_improvement=strategy,
            tradeoffs=tradeoffs,
            limitations=limitations,
            confidence="medium",
            suggested_diff=None,
        )

    def _generate_complex_component_recommendation(
        self,
        cc_item: Dict[str, Any],
    ) -> RefactoringRecommendation:
        """Proposes function/class decomposition for components exceeding lines threshold."""
        sym_name = cc_item.get("symbol", "unknown")
        file_path = cc_item.get("file", "unknown")
        lines_cnt = cc_item.get("line_count", 0)
        kind = cc_item.get("type", "component")
        thresh = cc_item.get("threshold", self.complexity_lines_threshold)

        strategy = (
            f"1. Extract Method / Sub-routine: Decompose `{sym_name}` into smaller, cohesive helper functions each performing one distinct step.\n"
            f"2. Separate Concerns: Extract business validation, data transformation, and formatting into separate domain units.\n"
            f"3. Parameter Object: If the component has many arguments/local states, bundle them into a dataclass or configuration object."
        )

        tradeoffs = (
            "Splitting linear logic into many small helpers can increase stack depth and require reading across multiple functions. "
            "Over-fragmentation can reduce overall readability if sub-routines are not naturally reusable."
        )

        limitations = (
            "Static line count is a structural heuristic and does not directly measure cyclomatic complexity, branch coverage, or execution time. "
            "No latency or speedup guarantees are implied without runtime profiling."
        )

        return RefactoringRecommendation(
            finding_type="complex_component",
            target=f"{file_path}::{sym_name}",
            affected_files=[file_path],
            affected_symbols=[sym_name],
            supporting_evidence={
                "line_count": lines_cnt,
                "symbol_type": kind,
                "start_line": cc_item.get("start_line"),
                "end_line": cc_item.get("end_line"),
            },
            source_locations=[{
                "file": file_path,
                "line": cc_item.get("start_line", 1),
                "end_line": cc_item.get("end_line", 1),
                "statement": f"{kind} {sym_name}",
            }],
            threshold_used={"threshold_lines": thresh},
            explanation=f"{kind.capitalize()} '{sym_name}' in `{file_path}` spans {lines_cnt} lines, exceeding the configured {thresh}-line threshold.",
            proposed_improvement=strategy,
            tradeoffs=tradeoffs,
            limitations=limitations,
            confidence="high",
            suggested_diff=None,
        )

    def _generate_ai_advisory(
        self,
        measured_facts: Dict[str, Any],
        llm: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Synthesizes an optional AI advisory strictly grounded in measured facts.
        Distinguishes generated advice from deterministic facts and explicitly reports
        unavailable inference if LLM is absent or encounters errors.
        """
        if llm is None:
            return {
                "status": "unavailable",
                "model": "none",
                "advisory": None,
                "notice": "Deterministic analysis executed without LLM. All findings, metrics, and refactoring strategies are substantiated by static dependency and AST measurements.",
            }

        # Check if LLM has generation capabilities
        prompt = (
            "You are an AI software architect reviewing deterministic static analysis measurements of a repository:\n"
            f"- Total Modules: {measured_facts.get('total_modules')}\n"
            f"- Total Dependencies: {measured_facts.get('total_dependencies')}\n"
            f"- Circular Dependency Cycles Detected: {measured_facts.get('cycle_count')} {measured_facts.get('detected_cycles')}\n"
            f"- Bottleneck Modules: {len(measured_facts.get('bottlenecks', []))}\n"
            f"- Complex Components Exceeding Thresholds: {len(measured_facts.get('complex_components', []))}\n\n"
            "Provide a concise, 2-3 paragraph executive architectural assessment grounded ONLY in these measured facts. "
            "Do NOT hallucinate additional files or invent performance numbers. "
            "State clearly that recommendations are advisory."
        )

        try:
            model_name = getattr(llm, "model", "local-llm")
            if hasattr(llm, "ask"):
                resp = llm.ask(prompt)
                adv_text = resp if isinstance(resp, str) else resp.get("answer", str(resp))
            elif hasattr(llm, "generate"):
                adv_text = llm.generate(prompt)
            else:
                adv_text = str(llm(prompt))

            return {
                "status": "generated",
                "model": model_name,
                "advisory": adv_text.strip(),
                "notice": "AI-generated advisory grounded in measured static facts. Static metrics alone do not guarantee performance or structural perfection without validation.",
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "model": getattr(llm, "model", "local-llm"),
                "advisory": None,
                "notice": f"Local LLM inference unavailable ({exc}). Deterministic measurements and recommendations remain fully functional.",
            }
