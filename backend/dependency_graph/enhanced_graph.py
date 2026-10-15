"""
Enhanced Dependency & Knowledge Graph Engine (REQ-FUT-07)
Supports:
- Code symbol knowledge graph: files, classes, methods, functions, external libraries, API/DB endpoints
- Supported relationships: imports, external_import, defines_class, defines_function, defines_method, inherits, calls, api_call, database_call
- Entity and relationship querying with line citations, direction filtering, and multi-hop paths
- Explicit documentation of unsupported relationships (dynamic reflection, polymorphic dispatch, IPC events, DI)
- Circular dependency detection and Cytoscape.js export
"""
import ast
import os
import re
from typing import List, Dict, Any, Set, Tuple, Optional
import networkx as nx
from core.parser import SourceFile
from core.dependency_graph import resolve_import_to_file, extract_file_imports
from core.tree_sitter_chunker import extract_tree_sitter_chunks


SUPPORTED_RELATIONSHIPS = [
    {
        "type": "imports",
        "description": "Direct internal module/file import dependency with source line citation.",
        "internal": True,
    },
    {
        "type": "external_import",
        "description": "Third-party or standard library package import dependency.",
        "internal": False,
    },
    {
        "type": "defines_class",
        "description": "Class declaration enclosed within a source file.",
        "internal": True,
    },
    {
        "type": "defines_function",
        "description": "Top-level function declaration defined within a source file.",
        "internal": True,
    },
    {
        "type": "defines_method",
        "description": "Method declaration defined inside an enclosing class.",
        "internal": True,
    },
    {
        "type": "inherits",
        "description": "Object-oriented class inheritance relationship (subclass -> base class).",
        "internal": True,
    },
    {
        "type": "calls",
        "description": "Function or method invocation with line citation.",
        "internal": True,
    },
    {
        "type": "api_call",
        "description": "Outbound HTTP API invocation (GET, POST, fetch, requests).",
        "internal": False,
    },
    {
        "type": "database_call",
        "description": "Database query/execution invocation (execute, select, query, find).",
        "internal": False,
    },
]

UNSUPPORTED_RELATIONSHIPS = [
    {
        "type": "dynamic_reflection",
        "reason": "Runtime dynamic dispatch via getattr, setattr, eval, or globals() is not deterministically verifiable from static AST.",
    },
    {
        "type": "runtime_polymorphic_dispatch",
        "reason": "Duck-typing without static type hints or explicit inheritance cannot be inferred as verified fact.",
    },
    {
        "type": "ipc_event_bus",
        "reason": "Decoupled publish/subscribe message queues (Kafka, Redis, RabbitMQ) lack direct AST call edges.",
    },
    {
        "type": "framework_dependency_injection",
        "reason": "Container runtime-injected dependencies without explicit constructor AST calls are not statically linked.",
    },
]


class _PythonASTKnowledgeVisitor(ast.NodeVisitor):
    """
    Traverses Python AST to populate classes, methods, functions, inheritance,
    internal calls, and API/DB calls with line citations into the knowledge graph.
    """
    def __init__(self, sf: SourceFile, graph: nx.DiGraph, file_map: Dict[str, SourceFile]):
        self.sf = sf
        self.norm_path = sf.rel_path.replace("\\", "/")
        self.graph = graph
        self.file_map = file_map
        self.class_stack: List[str] = []
        self.current_function: Optional[str] = None

    def visit_ClassDef(self, node: ast.ClassDef):
        class_id = f"{self.norm_path}::{node.name}"
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)
        docstring = ast.get_docstring(node)

        self.graph.add_node(
            class_id,
            type="class",
            name=node.name,
            label=node.name,
            parent_file=self.norm_path,
            file_path=self.norm_path,
            start_line=start_line,
            end_line=end_line,
            docstring=docstring,
            external=False,
        )
        self.graph.add_edge(
            self.norm_path,
            class_id,
            relationship="defines_class",
            internal=True,
            source_file=self.norm_path,
            line=start_line,
        )

        # Class Inheritance
        for base in node.bases:
            base_name = None
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
                base_name = f"{base.value.id}.{base.attr}"

            if base_name:
                cand_in_file = f"{self.norm_path}::{base_name}"
                if cand_in_file in self.graph:
                    target_base = cand_in_file
                    is_internal = True
                else:
                    found_internal = None
                    for other_rel in self.file_map:
                        cand = f"{other_rel}::{base_name}"
                        if cand in self.graph:
                            found_internal = cand
                            break
                    if found_internal:
                        target_base = found_internal
                        is_internal = True
                    else:
                        target_base = f"base:{base_name}"
                        is_internal = False
                        if not self.graph.has_node(target_base):
                            self.graph.add_node(
                                target_base,
                                type="class",
                                name=base_name,
                                label=base_name,
                                external=True,
                            )
                self.graph.add_edge(
                    class_id,
                    target_base,
                    relationship="inherits",
                    internal=is_internal,
                    source_file=self.norm_path,
                    line=node.lineno,
                )

        self.class_stack.append(class_id)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_func(self, node):
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno)
        docstring = ast.get_docstring(node)

        if self.class_stack:
            parent_class = self.class_stack[-1]
            func_id = f"{parent_class}::{node.name}"
            node_type = "method"
            rel_type = "defines_method"
            parent_rel = parent_class
        else:
            func_id = f"{self.norm_path}::{node.name}"
            node_type = "function"
            rel_type = "defines_function"
            parent_rel = self.norm_path

        self.graph.add_node(
            func_id,
            type=node_type,
            name=node.name,
            label=node.name,
            parent_file=self.norm_path,
            file_path=self.norm_path,
            parent_class=self.class_stack[-1] if self.class_stack else None,
            start_line=start_line,
            end_line=end_line,
            docstring=docstring,
            external=False,
        )
        self.graph.add_edge(
            parent_rel,
            func_id,
            relationship=rel_type,
            internal=True,
            source_file=self.norm_path,
            line=start_line,
        )

        prev_func = self.current_function
        self.current_function = func_id
        self.generic_visit(node)
        self.current_function = prev_func

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_func(node)

    def visit_Call(self, node: ast.Call):
        caller_id = self.current_function or self.norm_path
        call_name = ""
        call_attr = None

        if isinstance(node.func, ast.Name):
            call_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            call_name = node.func.attr
            call_attr = node.func

        line = getattr(node, "lineno", 1)

        # 1. API Calls
        if call_name and call_name.lower() in ("get", "post", "put", "delete", "request", "fetch"):
            if not self.graph.has_node("API:HTTP_Endpoint"):
                self.graph.add_node("API:HTTP_Endpoint", type="api", label="HTTP API", external=True)
            self.graph.add_edge(
                caller_id,
                "API:HTTP_Endpoint",
                relationship="api_call",
                internal=False,
                source_file=self.norm_path,
                line=line,
            )

        # 2. Database Calls
        elif call_name and call_name.lower() in ("execute", "find", "query", "insert", "update", "delete_one", "select"):
            if not self.graph.has_node("DB:Database_Query"):
                self.graph.add_node("DB:Database_Query", type="database", label="Database Query", external=True)
            self.graph.add_edge(
                caller_id,
                "DB:Database_Query",
                relationship="database_call",
                internal=False,
                source_file=self.norm_path,
                line=line,
            )

        # 3. Direct Function Calls in same file or known symbols
        if call_name:
            cand_same_file = f"{self.norm_path}::{call_name}"
            if cand_same_file in self.graph and cand_same_file != caller_id:
                self.graph.add_edge(
                    caller_id,
                    cand_same_file,
                    relationship="calls",
                    symbol=call_name,
                    internal=True,
                    source_file=self.norm_path,
                    line=line,
                )
            elif call_attr and isinstance(call_attr.value, ast.Name) and call_attr.value.id in ("self", "cls") and self.class_stack:
                cand_method = f"{self.class_stack[-1]}::{call_name}"
                if cand_method != caller_id:
                    self.graph.add_edge(
                        caller_id,
                        cand_method,
                        relationship="calls",
                        symbol=call_name,
                        internal=True,
                        source_file=self.norm_path,
                        line=line,
                    )

        self.generic_visit(node)


class EnhancedDependencyGraph:
    """
    Generates and maintains a rich, queryable knowledge graph connecting
    files, classes, methods, functions, external libraries, and data/API endpoints.
    """
    def __init__(self):
        self.graph = nx.DiGraph()

    def build(
        self,
        source_files: List[SourceFile],
        call_graph: Optional[nx.DiGraph] = None,
    ) -> nx.DiGraph:
        """
        Builds the unified repository knowledge graph from source files and optional call graph.
        """
        self.graph.clear()
        file_map = {sf.rel_path.replace("\\", "/"): sf for sf in source_files}

        # 1. Add all files as primary nodes
        for sf in source_files:
            norm_rel = sf.rel_path.replace("\\", "/")
            line_count = len(sf.content.splitlines()) if sf.content else 1
            self.graph.add_node(
                norm_rel,
                type="file",
                language=sf.language,
                name=os.path.basename(norm_rel),
                label=os.path.basename(norm_rel),
                file_path=norm_rel,
                start_line=1,
                end_line=line_count,
                external=False,
            )

        # 2. Parse language dependencies
        for sf in source_files:
            if sf.language == "python":
                self._parse_python_dependencies(sf, file_map)
            else:
                self._parse_generic_dependencies(sf, file_map)

        # 3. Ingest resolved calls from fine-grained call graph if available
        if call_graph is not None:
            for u, v, data in call_graph.edges(data=True):
                caller_file = (data.get("caller_file") or "").replace("\\", "/")
                callee_file = (data.get("callee_file") or "").replace("\\", "/")
                call_line = data.get("call_line")
                symbol = data.get("symbol", "")

                # Ensure caller/callee nodes exist
                if not self.graph.has_node(u):
                    self.graph.add_node(
                        u,
                        type="function",
                        label=u.split("::")[-1],
                        name=u.split("::")[-1],
                        file_path=caller_file,
                        external=False,
                    )
                if not self.graph.has_node(v):
                    self.graph.add_node(
                        v,
                        type="function",
                        label=v.split("::")[-1],
                        name=v.split("::")[-1],
                        file_path=callee_file,
                        external=False,
                    )

                self.graph.add_edge(
                    u,
                    v,
                    relationship="calls",
                    symbol=symbol,
                    internal=(caller_file == callee_file),
                    source_file=caller_file,
                    line=call_line,
                )

        return self.graph

    def _parse_python_dependencies(self, sf: SourceFile, file_map: Dict[str, SourceFile]):
        norm_sf = sf.rel_path.replace("\\", "/")
        try:
            tree = ast.parse(sf.content, filename=norm_sf)
        except SyntaxError:
            return

        # 1. Imports (static, relative, and dynamic)
        for node in ast.walk(tree):
            targets = []
            line = getattr(node, "lineno", 1)
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level
                if node.module:
                    targets.append(f"{prefix}{node.module}")
                elif node.level > 0:
                    for alias in node.names:
                        targets.append(f"{prefix}{alias.name}")
            elif isinstance(node, ast.Call):
                # Dynamic imports
                if (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module") or \
                   (isinstance(node.func, ast.Name) and node.func.id == "__import__"):
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        targets.append(node.args[0].value)

            for t in targets:
                target_rel = resolve_import_to_file(norm_sf, t, file_map)
                if target_rel and target_rel in file_map:
                    self.graph.add_edge(
                        norm_sf,
                        target_rel,
                        relationship="imports",
                        internal=True,
                        source_file=norm_sf,
                        line=line,
                    )
                else:
                    ext_node = f"ext:{t.lstrip('.').split('.')[0]}"
                    if not self.graph.has_node(ext_node):
                        self.graph.add_node(
                            ext_node,
                            type="external",
                            name=ext_node,
                            language="python",
                            label=ext_node,
                            external=True,
                        )
                    self.graph.add_edge(
                        norm_sf,
                        ext_node,
                        relationship="external_import",
                        internal=False,
                        source_file=norm_sf,
                        line=line,
                    )

        # 2. Classes, Functions, Methods, and Calls using AST Visitor
        visitor = _PythonASTKnowledgeVisitor(sf, self.graph, file_map)
        visitor.visit(tree)

    def _parse_generic_dependencies(self, sf: SourceFile, file_map: Dict[str, SourceFile]):
        norm_sf = sf.rel_path.replace("\\", "/")
        # 1. Multi-language imports extraction
        raw_imports = extract_file_imports(sf)
        for imp in raw_imports:
            target_rel = resolve_import_to_file(norm_sf, imp, file_map)
            if target_rel and target_rel in file_map:
                self.graph.add_edge(
                    norm_sf,
                    target_rel,
                    relationship="imports",
                    internal=True,
                    source_file=norm_sf,
                )
            else:
                ext_pkg = imp.lstrip(".").split("/")[0].split(".")[0]
                ext_node = f"ext:{ext_pkg}"
                if not self.graph.has_node(ext_node):
                    self.graph.add_node(
                        ext_node,
                        type="external",
                        name=ext_pkg,
                        language=sf.language,
                        label=ext_node,
                        external=True,
                    )
                self.graph.add_edge(
                    norm_sf,
                    ext_node,
                    relationship="external_import",
                    internal=False,
                    source_file=norm_sf,
                )

        # 2. Tree-Sitter AST symbol extraction for non-Python code
        if sf.has_tree_sitter and sf.language in ("javascript", "typescript", "tsx", "java", "c", "cpp", "go", "rust"):
            ts_chunks = extract_tree_sitter_chunks(sf.content, norm_sf, sf.language)
            for c in ts_chunks:
                cid = c["chunk_id"].replace("\\", "/")
                kind = c["kind"]
                name = c["name"]
                start_l = c["start_line"]
                end_l = c["end_line"]

                self.graph.add_node(
                    cid,
                    type=kind,
                    name=name.split(".")[-1],
                    label=name,
                    parent_file=norm_sf,
                    file_path=norm_sf,
                    start_line=start_l,
                    end_line=end_l,
                    external=False,
                    language=sf.language,
                )

                if "." in name and kind == "method":
                    parent_cls_name = name.split(".")[0]
                    parent_cls_id = f"{norm_sf}::{parent_cls_name}"
                    if self.graph.has_node(parent_cls_id):
                        self.graph.add_edge(
                            parent_cls_id,
                            cid,
                            relationship="defines_method",
                            internal=True,
                            source_file=norm_sf,
                            line=start_l,
                        )
                    else:
                        self.graph.add_edge(
                            norm_sf,
                            cid,
                            relationship="defines_method",
                            internal=True,
                            source_file=norm_sf,
                            line=start_l,
                        )
                elif kind in ("class", "interface", "struct", "trait"):
                    self.graph.add_edge(
                        norm_sf,
                        cid,
                        relationship="defines_class",
                        internal=True,
                        source_file=norm_sf,
                        line=start_l,
                    )
                else:
                    self.graph.add_edge(
                        norm_sf,
                        cid,
                        relationship="defines_function",
                        internal=True,
                        source_file=norm_sf,
                        line=start_l,
                    )

        # 3. HTTP API and Database calls via regex
        lines = sf.content.splitlines()
        for idx, line in enumerate(lines, start=1):
            if re.search(r'\b(fetch|axios|http\.get|http\.post|requests\.get)\b', line, re.IGNORECASE):
                if not self.graph.has_node("API:HTTP_Endpoint"):
                    self.graph.add_node("API:HTTP_Endpoint", type="api", label="HTTP API", external=True)
                self.graph.add_edge(
                    norm_sf,
                    "API:HTTP_Endpoint",
                    relationship="api_call",
                    internal=False,
                    source_file=norm_sf,
                    line=idx,
                )

            if re.search(r'\b(SELECT|INSERT|UPDATE|DELETE|find_one|db\.)\b', line):
                if not self.graph.has_node("DB:Database_Query"):
                    self.graph.add_node("DB:Database_Query", type="database", label="Database Query", external=True)
                self.graph.add_edge(
                    norm_sf,
                    "DB:Database_Query",
                    relationship="database_call",
                    internal=False,
                    source_file=norm_sf,
                    line=idx,
                )

    def detect_circular_dependencies(self) -> List[List[str]]:
        """Finds circular dependency cycles in file imports."""
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
                    "file_path": data.get("file_path"),
                    "start_line": data.get("start_line"),
                    "end_line": data.get("end_line"),
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
                    "source_file": data.get("source_file"),
                    "line": data.get("line"),
                }
            })

        return elements

    # -------------------------------------------------------------------------
    # Knowledge Graph Query API
    # -------------------------------------------------------------------------

    def resolve_entity(self, query_str: str) -> List[str]:
        """
        Resolves an entity identifier or name to matching node IDs in the graph.
        Prioritizes:
        1. Exact node ID match
        2. Exact name/label match
        3. Qualified suffix match (e.g. 'Class.method' or '::symbol')
        4. Case-insensitive substring match
        """
        query_cleaned = query_str.strip()
        if not query_cleaned:
            return []

        # 1. Exact node ID
        if self.graph.has_node(query_cleaned):
            return [query_cleaned]

        exact_matches = []
        suffix_matches = []
        partial_matches = []
        q_lower = query_cleaned.lower()

        for node, data in self.graph.nodes(data=True):
            str_node = str(node)
            name = data.get("name", "")
            label = data.get("label", "")

            if name == query_cleaned or label == query_cleaned:
                exact_matches.append(str_node)
            elif str_node.endswith(f"::{query_cleaned}") or str_node.endswith(f"/{query_cleaned}"):
                suffix_matches.append(str_node)
            elif q_lower == name.lower() or q_lower == label.lower():
                exact_matches.append(str_node)
            elif q_lower in str_node.lower():
                partial_matches.append(str_node)

        if exact_matches:
            return exact_matches
        if suffix_matches:
            return suffix_matches
        return partial_matches

    def query_entity(
        self,
        entity_id_or_name: str,
        relationship: Optional[str] = None,
        direction: str = "both",
        depth: int = 1,
    ) -> Dict[str, Any]:
        """
        Queries the knowledge graph for a specific entity and its connected relationships.
        Returns entity attributes (file, line numbers, docstrings), incident relationships
        with line citations, and supported vs unsupported relationship metadata.
        """
        candidates = self.resolve_entity(entity_id_or_name)
        if not candidates:
            return {
                "found": False,
                "query": {
                    "entity": entity_id_or_name,
                    "relationship": relationship,
                    "direction": direction,
                    "depth": depth,
                },
                "entity": None,
                "matches": [],
                "relationships": [],
                "total_relationships": 0,
                "supported_relationships": SUPPORTED_RELATIONSHIPS,
                "unsupported_relationships": UNSUPPORTED_RELATIONSHIPS,
            }

        target_node = candidates[0]
        node_data = self.graph.nodes[target_node]

        entity_info = {
            "id": target_node,
            "name": node_data.get("name", node_data.get("label", target_node)),
            "label": node_data.get("label", target_node),
            "type": node_data.get("type", "unknown"),
            "file_path": node_data.get("file_path", node_data.get("parent_file")),
            "start_line": node_data.get("start_line"),
            "end_line": node_data.get("end_line"),
            "docstring": node_data.get("docstring"),
            "external": node_data.get("external", False),
            "language": node_data.get("language"),
        }

        matches_info = [
            {
                "id": c,
                "label": self.graph.nodes[c].get("label", c),
                "type": self.graph.nodes[c].get("type", "unknown"),
                "file_path": self.graph.nodes[c].get("file_path"),
                "start_line": self.graph.nodes[c].get("start_line"),
                "end_line": self.graph.nodes[c].get("end_line"),
            }
            for c in candidates
        ]

        # BFS for incident edges up to depth
        visited_nodes = {target_node}
        current_layer = [target_node]
        relationships = []
        seen_edges = set()

        for d in range(depth):
            next_layer = []
            for curr in current_layer:
                # Outgoing edges
                if direction in ("outgoing", "both"):
                    for _, v, edge_data in self.graph.out_edges(curr, data=True):
                        rel = edge_data.get("relationship", "depends_on")
                        if relationship and rel != relationship:
                            continue
                        edge_key = (curr, v, rel, "outgoing")
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            v_data = self.graph.nodes.get(v, {})
                            relationships.append({
                                "source": curr,
                                "source_name": self.graph.nodes.get(curr, {}).get("label", curr),
                                "source_type": self.graph.nodes.get(curr, {}).get("type", "unknown"),
                                "target": v,
                                "target_name": v_data.get("label", v),
                                "target_type": v_data.get("type", "unknown"),
                                "relationship": rel,
                                "direction": "outgoing",
                                "source_file": edge_data.get("source_file") or self.graph.nodes.get(curr, {}).get("file_path"),
                                "line": edge_data.get("line"),
                                "internal": edge_data.get("internal", True),
                                "symbol": edge_data.get("symbol"),
                            })
                            if v not in visited_nodes:
                                visited_nodes.add(v)
                                next_layer.append(v)

                # Incoming edges
                if direction in ("incoming", "both"):
                    for u, _, edge_data in self.graph.in_edges(curr, data=True):
                        rel = edge_data.get("relationship", "depends_on")
                        if relationship and rel != relationship:
                            continue
                        edge_key = (u, curr, rel, "incoming")
                        if edge_key not in seen_edges:
                            seen_edges.add(edge_key)
                            u_data = self.graph.nodes.get(u, {})
                            relationships.append({
                                "source": u,
                                "source_name": u_data.get("label", u),
                                "source_type": u_data.get("type", "unknown"),
                                "target": curr,
                                "target_name": self.graph.nodes.get(curr, {}).get("label", curr),
                                "target_type": self.graph.nodes.get(curr, {}).get("type", "unknown"),
                                "relationship": rel,
                                "direction": "incoming",
                                "source_file": edge_data.get("source_file") or u_data.get("file_path"),
                                "line": edge_data.get("line"),
                                "internal": edge_data.get("internal", True),
                                "symbol": edge_data.get("symbol"),
                            })
                            if u not in visited_nodes:
                                visited_nodes.add(u)
                                next_layer.append(u)

            current_layer = next_layer
            if not current_layer:
                break

        return {
            "found": True,
            "query": {
                "entity": entity_id_or_name,
                "relationship": relationship,
                "direction": direction,
                "depth": depth,
            },
            "entity": entity_info,
            "matches": matches_info,
            "relationships": relationships,
            "total_relationships": len(relationships),
            "supported_relationships": SUPPORTED_RELATIONSHIPS,
            "unsupported_relationships": UNSUPPORTED_RELATIONSHIPS,
        }

    def find_path(self, source: str, target: str, directed: bool = False) -> Dict[str, Any]:
        """
        Finds the shortest dependency or call path between two entities in the knowledge graph.
        """
        src_candidates = self.resolve_entity(source)
        tgt_candidates = self.resolve_entity(target)

        if not src_candidates:
            return {
                "found": False,
                "error": f"Source entity '{source}' could not be resolved in the knowledge graph.",
                "path": [],
            }
        if not tgt_candidates:
            return {
                "found": False,
                "error": f"Target entity '{target}' could not be resolved in the knowledge graph.",
                "path": [],
            }

        src_node = src_candidates[0]
        tgt_node = tgt_candidates[0]

        g = self.graph if directed else self.graph.to_undirected()

        try:
            path_nodes = nx.shortest_path(g, source=src_node, target=tgt_node)
            path_entities = [
                {
                    "id": n,
                    "label": self.graph.nodes[n].get("label", n),
                    "type": self.graph.nodes[n].get("type", "unknown"),
                    "file_path": self.graph.nodes[n].get("file_path"),
                    "start_line": self.graph.nodes[n].get("start_line"),
                }
                for n in path_nodes
            ]

            # Collect edges along the path
            path_edges = []
            for i in range(len(path_nodes) - 1):
                u, v = path_nodes[i], path_nodes[i + 1]
                # Look for forward edge
                edge_d = self.graph.get_edge_data(u, v)
                forward = True
                if not edge_d and not directed:
                    edge_d = self.graph.get_edge_data(v, u)
                    forward = False
                if edge_d:
                    path_edges.append({
                        "source": u if forward else v,
                        "target": v if forward else u,
                        "relationship": edge_d.get("relationship", "depends_on"),
                        "line": edge_d.get("line"),
                        "source_file": edge_d.get("source_file"),
                        "internal": edge_d.get("internal", True),
                    })

            return {
                "found": True,
                "path_exists": True,
                "source": src_node,
                "target": tgt_node,
                "length": len(path_nodes) - 1,
                "path": path_entities,
                "edges": path_edges,
            }
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return {
                "found": True,
                "path_exists": False,
                "source": src_node,
                "target": tgt_node,
                "length": 0,
                "path": [],
                "edges": [],
                "message": f"No {'directed' if directed else 'undirected'} path found connecting '{src_node}' to '{tgt_node}'.",
            }

    def list_entities(
        self,
        entity_type: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Lists entities indexed in the knowledge graph filtered by type and search prefix.
        """
        results = []
        s_lower = search.lower().strip() if search else None

        for node, data in self.graph.nodes(data=True):
            n_type = data.get("type", "unknown")
            if entity_type and n_type != entity_type:
                continue

            str_node = str(node)
            label = str(data.get("label", node))
            name = str(data.get("name", label))

            if s_lower:
                if s_lower not in str_node.lower() and s_lower not in label.lower() and s_lower not in name.lower():
                    continue

            results.append({
                "id": str_node,
                "name": name,
                "label": label,
                "type": n_type,
                "file_path": data.get("file_path"),
                "start_line": data.get("start_line"),
                "end_line": data.get("end_line"),
                "external": data.get("external", False),
            })
            if len(results) >= limit:
                break

        return results

    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns high-level statistics and relationship documentation for this knowledge graph.
        """
        type_counts: Dict[str, int] = {}
        for _, data in self.graph.nodes(data=True):
            t = data.get("type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1

        rel_counts: Dict[str, int] = {}
        for _, _, data in self.graph.edges(data=True):
            r = data.get("relationship", "other")
            rel_counts[r] = rel_counts.get(r, 0) + 1

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_types": type_counts,
            "relationship_types": rel_counts,
            "supported_relationships": SUPPORTED_RELATIONSHIPS,
            "unsupported_relationships": UNSUPPORTED_RELATIONSHIPS,
            "stale_graph_limitation": (
                "Knowledge graph is generated in memory from parsed AST files. "
                "Files modified externally while server or watcher is inactive require "
                "re-indexing (/api/repos/ingest or CLI restart) to synchronize graph state."
            ),
        }
