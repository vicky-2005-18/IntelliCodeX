"""
Repository Analytics Dashboard Engine (Phase 5)
Computes repository structure statistics, language breakdown, module sizes,
AI query telemetry, and an overall Repository Health Score (0-100).
"""
import os
from typing import List, Dict, Any
import networkx as nx
from core.chunker import CodeChunk
from core.parser import SourceFile


class RepositoryAnalyticsEngine:
    def compute_analytics(
        self,
        repo_id: str,
        source_files: List[SourceFile],
        chunks: List[CodeChunk],
        graph: nx.DiGraph,
        bugs_count: int = 0,
        query_count: int = 0,
    ) -> Dict[str, Any]:
        
        total_files = len(source_files)
        total_classes = sum(1 for c in chunks if c.kind == "class")
        total_functions = sum(1 for c in chunks if c.kind in ("function", "method"))
        total_dependencies = graph.number_of_edges()

        # Language distribution
        lang_map: Dict[str, int] = {}
        for sf in source_files:
            lang_map[sf.language] = lang_map.get(sf.language, 0) + 1

        # Module size breakdown (top 5 largest files by line count)
        file_sizes = []
        for sf in source_files:
            file_sizes.append({
                "file_path": sf.rel_path,
                "lines": len(sf.content.splitlines()),
                "chars": len(sf.content),
                "language": sf.language,
            })
        file_sizes.sort(key=lambda x: x["lines"], reverse=True)
        largest_modules = file_sizes[:5]

        # Circular dependencies penalty for Health Score
        file_subgraph = nx.DiGraph()
        for u, v, d in graph.edges(data=True):
            if d.get("relationship") in ("imports", "external_import"):
                file_subgraph.add_edge(u, v)

        circular_count = 0
        try:
            cycles = list(nx.simple_cycles(file_subgraph))
            circular_count = len([c for c in cycles if len(c) > 1])
        except Exception:
            pass

        # Repository Health Score Calculation (0 - 100)
        # Base score 95
        health_score = 95.0
        if circular_count > 0:
            health_score -= min(25.0, circular_count * 5.0)
        if total_files > 0:
            bug_ratio = bugs_count / max(1, total_files)
            health_score -= min(20.0, bug_ratio * 15.0)
        
        # Deduct if large unchunked modules exist (>500 lines)
        large_files_count = sum(1 for f in file_sizes if f["lines"] > 500)
        health_score -= min(15.0, large_files_count * 3.0)

        health_score = round(max(10.0, min(100.0, health_score)), 1)

        return {
            "repo_id": repo_id,
            "total_files": total_files,
            "total_classes": total_classes,
            "total_functions": total_functions,
            "total_dependencies": total_dependencies,
            "total_bugs_detected": bugs_count,
            "ai_queries_count": query_count,
            "circular_dependencies_count": circular_count,
            "health_score": health_score,
            "language_distribution": lang_map,
            "largest_modules": largest_modules,
        }
