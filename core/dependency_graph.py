"""
Dependency Analysis Engine
- Builds a file-level import graph for Python repos using ast
- Exposes it as a networkx DiGraph for querying / visualization
"""
import ast
import os
from typing import List, Dict
import networkx as nx
from core.parser import SourceFile


def _module_to_relpath(module: str, all_modules: Dict[str, str]) -> str:
    """Best-effort resolution of an import string to a repo-relative file."""
    candidate = module.replace(".", os.sep) + ".py"
    return all_modules.get(candidate, module)  # fall back to raw module name (external dep)


def build_dependency_graph(source_files: List[SourceFile]) -> nx.DiGraph:
    graph = nx.DiGraph()

    # map every possible "package.module" path -> rel_path, for resolution
    all_modules = {sf.rel_path: sf.rel_path for sf in source_files}

    for sf in source_files:
        graph.add_node(sf.rel_path, language=sf.language)

    for sf in source_files:
        if sf.language != "python":
            continue
        try:
            tree = ast.parse(sf.content, filename=sf.rel_path)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]

            for t in targets:
                resolved = _module_to_relpath(t, all_modules)
                is_internal = resolved in all_modules
                graph.add_node(resolved, external=not is_internal)
                graph.add_edge(sf.rel_path, resolved, internal=is_internal)

    return graph


def files_likely_affected_by(graph: nx.DiGraph, changed_file: str) -> List[str]:
    """Reverse-dependency lookup: who imports this file? (useful for bug blast-radius)."""
    if changed_file not in graph:
        return []
    return list(nx.ancestors(graph, changed_file))
