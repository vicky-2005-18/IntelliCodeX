"""
Architecture Optimization & Circular Dependency Refactoring Engine (REQ-FUT-06)
Analyzes dependency graphs and call graphs to detect:
1. Circular dependency cycles (A -> B -> A, multi-hop cycles)
2. High-coupling architectural bottlenecks (God modules, high fan-in / fan-out)
3. Module instability metrics (Afferent Ca, Efferent Ce, Instability I = Ce / (Ca + Ce))
Generates automated refactoring recommendations and decoupling diffs.
"""
import ast
import os
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
    type: str  # 'cycle_break', 'god_component_split', 'interface_inversion'
    target: str
    description: str
    strategy: str
    affected_nodes: List[str] = field(default_factory=list)
    suggested_diff: Optional[str] = None


@dataclass
class ArchitectureReport:
    total_modules: int
    total_dependencies: int
    cycles: List[List[str]]
    bottlenecks: List[ModuleCoupling]
    coupling_metrics: Dict[str, ModuleCoupling]
    recommendations: List[RefactoringRecommendation]
    health_score: float  # 0.0 to 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_modules": self.total_modules,
            "total_dependencies": self.total_dependencies,
            "cycles_count": len(self.cycles),
            "cycles": self.cycles,
            "bottlenecks": [asdict(b) for b in self.bottlenecks],
            "coupling_metrics": {k: asdict(v) for k, v in self.coupling_metrics.items()},
            "recommendations": [asdict(r) for r in self.recommendations],
            "health_score": round(self.health_score, 1),
        }

    def format_markdown(self) -> str:
        lines = [
            f"# Architecture Optimization & Health Report",
            f"- **System Health Score**: {self.health_score:.1f} / 100.0",
            f"- **Total Analyzed Modules**: {self.total_modules}",
            f"- **Total Dependencies**: {self.total_dependencies}",
            f"- **Detected Circular Dependency Cycles**: {len(self.cycles)}",
            f"- **High-Coupling Bottlenecks**: {len(self.bottlenecks)}",
            "",
        ]

        if self.cycles:
            lines.append("## Circular Dependency Cycles Detected")
            for idx, c in enumerate(self.cycles, start=1):
                cycle_str = " -> ".join(c + [c[0]])
                lines.append(f"{idx}. `{cycle_str}`")
            lines.append("")

        if self.bottlenecks:
            lines.append("## High-Coupling Architectural Bottlenecks")
            lines.append("| Module | Afferent ($C_a$) | Efferent ($C_e$) | Instability ($I$) | Assessment |")
            lines.append("| :--- | :---: | :---: | :---: | :--- |")
            for b in self.bottlenecks:
                lines.append(f"| `{b.module}` | {b.afferent_coupling} | {b.efferent_coupling} | {b.instability:.2f} | {b.warning or 'High coupling'} |")
            lines.append("")

        if self.recommendations:
            lines.append("## Automated Refactoring Recommendations")
            for idx, r in enumerate(self.recommendations, start=1):
                lines.append(f"### {idx}. [{r.type.upper()}] {r.target}")
                lines.append(f"> **Problem**: {r.description}")
                lines.append(f"\n**Refactoring Strategy**: {r.strategy}\n")
                if r.suggested_diff:
                    lines.append(f"```diff\n{r.suggested_diff}\n```\n")

        return "\n".join(lines)


class ArchitectureOptimizer:
    """
    Automated Architecture Optimizer & Circular Dependency Refactoring Engine.
    """

    def __init__(self, high_coupling_threshold: int = 5):
        self.high_coupling_threshold = high_coupling_threshold

    def analyze(
        self,
        dep_graph: nx.DiGraph,
        source_files: Optional[List[SourceFile]] = None,
        llm: Optional[Any] = None,
    ) -> ArchitectureReport:
        """Analyzes a dependency DiGraph to extract cycles, coupling metrics, bottlenecks, and recommendations."""
        # 1. Build module-to-module clean subgraph
        mod_graph = nx.DiGraph()
        for u, v, d in dep_graph.edges(data=True):
            # Only consider internal module/file dependencies
            rel = d.get("relationship", "")
            if rel in ("imports", "depends_on", "") and not str(v).startswith("ext:") and not str(v).startswith("API:") and not str(v).startswith("DB:"):
                # Clean node ids if they are symbols to files
                u_mod = u.split("::")[0] if "::" in str(u) else str(u)
                v_mod = v.split("::")[0] if "::" in str(v) else str(v)
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
                all_modules.add(sf.rel_path)

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
            elif ca >= self.high_coupling_threshold * 1.5:
                is_bottleneck = True
                warning = f"Critical Hotspot (Excessive Inbound Dependents): Ca={ca}"
            elif ce >= self.high_coupling_threshold * 1.5:
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

        # 4. Synthesize Refactoring Recommendations
        recommendations: List[RefactoringRecommendation] = []
        sf_map = {sf.rel_path: sf for sf in source_files} if source_files else {}

        # 4a. Circular Dependency Recommendations
        for cycle in cycles:
            rec = self._generate_cycle_recommendation(cycle, sf_map, mod_graph, llm)
            recommendations.append(rec)

        # 4b. God Component / Bottleneck Recommendations
        for b in bottlenecks:
            rec = self._generate_bottleneck_recommendation(b, sf_map, mod_graph)
            recommendations.append(rec)

        # 5. Compute System Architectural Health Score (100 base)
        # Deductions: -15 per cycle, -8 per bottleneck component
        cycle_penalty = min(50.0, len(cycles) * 15.0)
        bottleneck_penalty = min(30.0, len(bottlenecks) * 8.0)
        health_score = max(10.0, 100.0 - cycle_penalty - bottleneck_penalty)

        return ArchitectureReport(
            total_modules=len(all_modules),
            total_dependencies=mod_graph.number_of_edges(),
            cycles=cycles,
            bottlenecks=bottlenecks,
            coupling_metrics=coupling_metrics,
            recommendations=recommendations,
            health_score=health_score,
        )

    def _generate_cycle_recommendation(
        self,
        cycle: List[str],
        sf_map: Dict[str, SourceFile],
        mod_graph: nx.DiGraph,
        llm: Optional[Any] = None,
    ) -> RefactoringRecommendation:
        """Proposes concrete decoupling strategies and code refactoring diffs for circular dependencies."""
        cycle_repr = " <-> ".join(cycle)
        head, tail = cycle[0], cycle[1]

        # Check if we have source code to find specific import statement
        target_sf = sf_map.get(tail) or sf_map.get(head)
        diff_str = None

        if target_sf and target_sf.content:
            head_base = os.path.splitext(os.path.basename(head))[0]
            tail_base = os.path.splitext(os.path.basename(tail))[0]

            lines = target_sf.content.splitlines()
            import_line_idx = -1
            import_content = ""
            for idx, line in enumerate(lines):
                if f"import {head_base}" in line or f"from {head_base}" in line or f"from .{head_base}" in line:
                    import_line_idx = idx
                    import_content = line
                    break

            if import_line_idx != -1:
                # Propose deferred import inside function or interface extraction
                orig_code = target_sf.content
                patched_lines = list(lines)
                # Comment out top-level import and note deferred placement
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

        strategy = (
            f"1. Dependency Inversion: Extract shared types and shared functions into a separate common module (e.g. `{os.path.splitext(head)[0]}_types.py`).\n"
            f"2. Deferred / Lazy Import: Move `import {os.path.splitext(os.path.basename(head))[0]}` inside the specific function or method body where it is called rather than module top-level.\n"
            f"3. Dependency Injection: Pass the required collaborator as an argument or constructor parameter instead of importing directly."
        )

        return RefactoringRecommendation(
            type="cycle_break",
            target=cycle_repr,
            description=f"Circular dependency between {len(cycle)} modules: {' -> '.join(cycle + [cycle[0]])}.",
            strategy=strategy,
            affected_nodes=list(cycle),
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
            f"1. Facade Pattern: Split `{target}` into focused single-responsibility domain sub-modules and keep `{target}` as a light orchestrator facade.\n"
            f"2. Event/Observer Decoupling: Use an event bus or pub/sub callbacks to notify dependents without tight direct import coupling.\n"
            f"3. Inbound Dependency Audit: Module has {bottleneck.afferent_coupling} inbound dependents; extract interface contracts to insulate callers from internal implementation changes."
        )

        return RefactoringRecommendation(
            type="god_component_split",
            target=target,
            description=f"High-coupling architectural bottleneck in `{target}` ({bottleneck.warning or 'Excessive dependencies'}).",
            strategy=strategy,
            affected_nodes=[target],
            suggested_diff=None,
        )
