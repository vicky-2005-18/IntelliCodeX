"""
Enhanced Dependency Graph Engine (Phase 4)
Supports file imports, class inheritances, function call graphs, API/DB calls,
external library dependencies, circular dependency detection, and Cytoscape.js export.
"""
import ast
import os
import re
from typing import List, Dict, Any, Set, Tuple
import networkx as nx
from core.parser import SourceFile


class EnhancedDependencyGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

    def build(self, source_files: List[SourceFile]) -> nx.DiGraph:
        self.graph.clear()
        file_map = {sf.rel_path: sf for sf in source_files}

        # Add all files as primary nodes
        for sf in source_files:
            self.graph.add_node(
                sf.rel_path,
                type="file",
                language=sf.language,
                label=os.path.basename(sf.rel_path),
                external=False,
            )

        for sf in source_files:
            if sf.language == "python":
                self._parse_python_dependencies(sf, file_map)
            else:
                self._parse_generic_dependencies(sf, file_map)

        return self.graph

    def _parse_python_dependencies(self, sf: SourceFile, file_map: Dict[str, SourceFile]):
        try:
            tree = ast.parse(sf.content, filename=sf.rel_path)
        except SyntaxError:
            return

        # 1. Imports
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                targets = [node.module]

            for t in targets:
                target_rel = t.replace(".", os.sep) + ".py"
                is_internal = target_rel in file_map
                if is_internal:
                    self.graph.add_edge(sf.rel_path, target_rel, relationship="imports", internal=True)
                else:
                    ext_node = f"ext:{t.split('.')[0]}"
                    if not self.graph.has_node(ext_node):
                        self.graph.add_node(ext_node, type="external", language="python", label=ext_node, external=True)
                    self.graph.add_edge(sf.rel_path, ext_node, relationship="external_import", internal=False)

        # 2. Class & Function Call Relationships
        current_class = None
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_id = f"{sf.rel_path}::{node.name}"
                self.graph.add_node(class_id, type="class", label=node.name, parent_file=sf.rel_path, external=False)
                self.graph.add_edge(sf.rel_path, class_id, relationship="defines_class", internal=True)

                # Class Inheritance
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        self.graph.add_edge(class_id, f"base:{base.id}", relationship="inherits", internal=False)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_id = f"{sf.rel_path}::{node.name}"
                self.graph.add_node(func_id, type="function", label=node.name, parent_file=sf.rel_path, external=False)
                self.graph.add_edge(sf.rel_path, func_id, relationship="defines_function", internal=True)

            elif isinstance(node, ast.Call):
                # Call Detection (API, DB, internal function calls)
                call_name = ""
                if isinstance(node.func, ast.Name):
                    call_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    call_name = node.func.attr

                if call_name:
                    if call_name.lower() in ("get", "post", "put", "delete", "request", "fetch"):
                        self.graph.add_edge(sf.rel_path, "API:HTTP_Endpoint", relationship="api_call", internal=False)
                    elif call_name.lower() in ("execute", "find", "query", "insert", "update", "delete_one", "select"):
                        self.graph.add_edge(sf.rel_path, "DB:Database_Query", relationship="database_call", internal=False)

    def _parse_generic_dependencies(self, sf: SourceFile, file_map: Dict[str, SourceFile]):
        lines = sf.content.splitlines()
        for line in lines:
            # Check for HTTP API calls
            if re.search(r'\b(fetch|axios|http\.get|http\.post|requests\.get)\b', line, re.IGNORECASE):
                if not self.graph.has_node("API:HTTP_Endpoint"):
                    self.graph.add_node("API:HTTP_Endpoint", type="api", label="HTTP API", external=True)
                self.graph.add_edge(sf.rel_path, "API:HTTP_Endpoint", relationship="api_call", internal=False)

            # Check for DB calls
            if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|find_one|db\.)\b', line):
                if not self.graph.has_node("DB:Database_Query"):
                    self.graph.add_node("DB:Database_Query", type="database", label="Database Query", external=True)
                self.graph.add_edge(sf.rel_path, "DB:Database_Query", relationship="database_call", internal=False)

    def detect_circular_dependencies(self) -> List[List[str]]:
        """Finds circular dependency cycles in file imports."""
        # Create subgraph of file-to-file import edges
        file_subgraph = nx.DiGraph()
        for u, v, d in self.graph.edges(data=True):
            if d.get("relationship") in ("imports", "external_import"):
                file_subgraph.add_edge(u, v)

        try:
            cycles = list(nx.simple_cycles(file_subgraph))
            return [cycle for cycle in cycles if len(cycle) > 1]
        except Exception:
            return []

    def export_cytoscape(self) -> Dict[str, List[Dict[str, Any]]]:
        """Exports graph in Cytoscape.js format for interactive UI rendering."""
        elements = {"nodes": [], "edges": []}

        for node, data in self.graph.nodes(data=True):
            elements["nodes"].append({
                "data": {
                    "id": str(node),
                    "label": data.get("label", str(node)),
                    "type": data.get("type", "node"),
                    "language": data.get("language", "unknown"),
                    "external": data.get("external", False),
                }
            })

        for u, v, data in self.graph.edges(data=True):
            elements["edges"].append({
                "data": {
                    "id": f"{u}->{v}",
                    "source": str(u),
                    "target": str(v),
                    "relationship": data.get("relationship", "depends_on"),
                    "internal": data.get("internal", True),
                }
            })

        return elements
