import ast
import os
import sys
import networkx as nx
from typing import List, Dict, Set, Optional, Tuple

sys.path.insert(0, os.path.abspath("."))
from core.parser import walk_repository, SourceFile
from core.chunker import chunk_repository, CodeChunk

def analyze_call_graph(chunks: List[CodeChunk], source_files: List[SourceFile], legacy: bool = False) -> nx.DiGraph:
    graph = nx.DiGraph()
    for chunk in chunks:
        graph.add_node(
            chunk.chunk_id,
            file_path=chunk.file_path,
            language=chunk.language,
            kind=chunk.kind,
            name=chunk.name
        )

    if legacy:
        symbol_table: Dict[str, List[CodeChunk]] = {}
        for chunk in chunks:
            simple_name = chunk.name.split(".")[-1].split("::")[-1]
            symbol_table.setdefault(simple_name, []).append(chunk)

        source_map = {sf.rel_path: sf for sf in source_files}
        from core.call_graph import extract_function_calls
        for chunk in chunks:
            sf = source_map.get(chunk.file_path)
            if not sf:
                continue
            raw_calls = extract_function_calls(sf)
            chunk_calls = [c for c in raw_calls if chunk.start_line <= c["line"] <= chunk.end_line]
            for call in chunk_calls:
                callee_name = call["name"]
                if callee_name in symbol_table:
                    for target_chunk in symbol_table[callee_name]:
                        if target_chunk.chunk_id != chunk.chunk_id:
                            graph.add_edge(
                                chunk.chunk_id,
                                target_chunk.chunk_id,
                                caller_file=chunk.file_path,
                                callee_file=target_chunk.file_path,
                                call_line=call["line"],
                                symbol=callee_name
                            )
        return graph

    # --- NEW ALGORITHM ---
    # 1. Index chunks by file and pre-sort by span length (ascending) for most-specific caller attribution
    chunks_by_file: Dict[str, List[CodeChunk]] = {}
    for c in chunks:
        chunks_by_file.setdefault(c.file_path, []).append(c)
    for f in chunks_by_file:
        chunks_by_file[f].sort(key=lambda c: (c.end_line - c.start_line, 0 if c.kind in ("method", "function") else 1))

    # 2. Build symbol indices
    # class_methods: (class_name, method_name) -> list[CodeChunk]
    class_methods: Dict[Tuple[str, str], List[CodeChunk]] = {}
    # top_level_functions: func_name -> list[CodeChunk]
    top_level_functions: Dict[str, List[CodeChunk]] = {}
    # classes: class_name -> list[CodeChunk]
    class_chunks: Dict[str, List[CodeChunk]] = {}
    # all_symbols: name -> list[CodeChunk]
    all_symbols: Dict[str, List[CodeChunk]] = {}

    for c in chunks:
        simple = c.name.split(".")[-1].split("::")[-1]
        all_symbols.setdefault(simple, []).append(c)
        if c.kind == "method" or "." in c.name:
            parts = c.name.split(".")
            cls_name = parts[-2] if len(parts) >= 2 else ""
            m_name = parts[-1]
            if cls_name and m_name:
                class_methods.setdefault((cls_name, m_name), []).append(c)
        elif c.kind == "function":
            top_level_functions.setdefault(c.name, []).append(c)
            top_level_functions.setdefault(simple, []).append(c)
        elif c.kind == "class":
            class_chunks.setdefault(c.name, []).append(c)
            class_chunks.setdefault(simple, []).append(c)

    # 3. Parse AST for Python files to collect class hierarchies, imports, and scoped call sites
    source_map = {sf.rel_path: sf for sf in source_files}

    for sf in source_files:
        f_chunks = chunks_by_file.get(sf.rel_path, [])
        if not f_chunks:
            continue

        if sf.language != "python":
            # Non-python fallback with dedupe and fan-out cap
            from core.call_graph import _extract_tree_sitter_calls
            raw_calls = _extract_tree_sitter_calls(sf.content, sf.rel_path, sf.language) if sf.has_tree_sitter else []
            for call in raw_calls:
                line = call["line"]
                callee_name = call["name"]
                # Most specific enclosing caller chunk
                caller_chunk = None
                for c in f_chunks:
                    if c.start_line <= line <= c.end_line:
                        caller_chunk = c
                        break
                if not caller_chunk:
                    continue

                candidates = all_symbols.get(callee_name, [])
                # Exclude self
                candidates = [cand for cand in candidates if cand.chunk_id != caller_chunk.chunk_id]
                # Fan-out cap: if > 3 candidates, drop
                if 1 <= len(candidates) <= 3:
                    for target in candidates:
                        graph.add_edge(
                            caller_chunk.chunk_id,
                            target.chunk_id,
                            caller_file=caller_chunk.file_path,
                            callee_file=target.file_path,
                            call_line=line,
                            symbol=callee_name
                        )
            continue

        # Python parsing
        try:
            tree = ast.parse(sf.content, filename=sf.rel_path)
        except SyntaxError:
            continue

        # Collect class hierarchy and imports in this file
        class_bases: Dict[str, List[str]] = {}
        imported_symbols: Dict[str, str] = {} # alias -> orig_name

        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_symbols[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_symbols[name] = alias.name
            elif isinstance(node, ast.ClassDef):
                bases = []
                for b in node.bases:
                    if isinstance(b, ast.Name):
                        bases.append(b.id)
                    elif isinstance(b, ast.Attribute):
                        bases.append(b.attr)
                class_bases[node.name] = bases

        def get_all_bases(cls_name: str, seen: Optional[Set[str]] = None) -> List[str]:
            if seen is None:
                seen = set()
            if cls_name in seen:
                return []
            seen.add(cls_name)
            result = []
            for b in class_bases.get(cls_name, []):
                result.append(b)
                result.extend(get_all_bases(b, seen))
            return result

        # Visitor to extract calls with local lexical scope
        class CallVisitor(ast.NodeVisitor):
            def __init__(self):
                self.current_class: Optional[str] = None
                self.local_var_types: Dict[str, str] = {}
                self.extracted_calls: List[dict] = []

            def visit_ClassDef(self, node):
                prev_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = prev_class

            def visit_FunctionDef(self, node):
                prev_vars = dict(self.local_var_types)
                # Scan arguments and body for type hints and simple instantiations
                for arg in node.args.args:
                    if arg.annotation and isinstance(arg.annotation, ast.Name):
                        self.local_var_types[arg.arg] = arg.annotation.id
                for child in node.body:
                    if isinstance(child, ast.Assign):
                        if isinstance(child.value, ast.Call) and isinstance(child.value.func, ast.Name):
                            for target in child.targets:
                                if isinstance(target, ast.Name):
                                    self.local_var_types[target.id] = child.value.func.id
                    elif isinstance(child, ast.AnnAssign):
                        if isinstance(child.target, ast.Name) and isinstance(child.annotation, ast.Name):
                            self.local_var_types[child.target.id] = child.annotation.id
                        elif isinstance(child.value, ast.Call) and isinstance(child.value.func, ast.Name):
                            if isinstance(child.target, ast.Name):
                                self.local_var_types[child.target.id] = child.value.func.id

                self.generic_visit(node)
                self.local_var_types = prev_vars

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                line = getattr(node, "lineno", 1)
                is_attr = False
                receiver = None
                receiver_type = None
                symbol = None

                if isinstance(node.func, ast.Name):
                    symbol = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    is_attr = True
                    symbol = node.func.attr
                    v = node.func.value
                    if isinstance(v, ast.Name):
                        receiver = v.id
                        if receiver in ("self", "cls"):
                            receiver_type = self.current_class
                        elif receiver in self.local_var_types:
                            receiver_type = self.local_var_types[receiver]
                        elif receiver in imported_symbols:
                            receiver_type = imported_symbols[receiver]
                    elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name):
                        receiver = v.func.id
                        receiver_type = v.func.id
                    else:
                        receiver = "<complex>"

                if symbol:
                    self.extracted_calls.append({
                        "line": line,
                        "symbol": symbol,
                        "is_attr": is_attr,
                        "receiver": receiver,
                        "receiver_type": receiver_type,
                        "enclosing_class": self.current_class,
                    })
                self.generic_visit(node)

        visitor = CallVisitor()
        visitor.visit(tree)

        for c_info in visitor.extracted_calls:
            line = c_info["line"]
            symbol = c_info["symbol"]
            is_attr = c_info["is_attr"]
            receiver = c_info["receiver"]
            receiver_type = c_info["receiver_type"]
            encl_class = c_info["enclosing_class"]

            # Most specific enclosing chunk in this file
            caller_chunk = None
            for c in f_chunks:
                if c.start_line <= line <= c.end_line:
                    caller_chunk = c
                    break
            if not caller_chunk:
                continue

            target_chunks: List[CodeChunk] = []

            if is_attr:
                if receiver in ("self", "cls"):
                    # Rule 1: Resolve self.method() / cls.method() to enclosing class and base classes only
                    if encl_class:
                        hierarchy = [encl_class] + get_all_bases(encl_class)
                        for cls_cand in hierarchy:
                            if (cls_cand, symbol) in class_methods:
                                target_chunks.extend(class_methods[(cls_cand, symbol)])
                                break  # found at most specific class in hierarchy
                else:
                    # Rule 3: For calls whose receiver is not self/cls: link ONLY if receiver's class is known
                    if receiver_type:
                        hierarchy = [receiver_type] + get_all_bases(receiver_type)
                        for cls_cand in hierarchy:
                            if (cls_cand, symbol) in class_methods:
                                target_chunks.extend(class_methods[(cls_cand, symbol)])
                                break
                        # Or if receiver is an imported module/file, check top level functions in that module
                        if not target_chunks:
                            for tf in top_level_functions.get(symbol, []):
                                if os.path.basename(tf.file_path).startswith(receiver_type):
                                    target_chunks.append(tf)
                    else:
                        # Receiver is unknown (e.g. dict.get, app.run) -> DROP EDGE!
                        continue
            else:
                # Direct call: func(...)
                # Search top_level_functions first
                if symbol in top_level_functions:
                    target_chunks = list(top_level_functions[symbol])
                elif symbol in class_chunks:
                    # Constructor call: MyClass(...)
                    target_chunks = list(class_chunks[symbol])

            # Filter out self-calls
            target_chunks = [t for t in target_chunks if t.chunk_id != caller_chunk.chunk_id]

            # Rule 4: Cap fan-out: if > 3 candidates, drop edge
            if 1 <= len(target_chunks) <= 3:
                for t in target_chunks:
                    graph.add_edge(
                        caller_chunk.chunk_id,
                        t.chunk_id,
                        caller_file=caller_chunk.file_path,
                        callee_file=t.file_path,
                        call_line=line,
                        symbol=symbol
                    )

    return graph

if __name__ == "__main__":
    repo_path = ".repos/bottle"
    sfs = walk_repository(repo_path)
    chunks = chunk_repository(sfs)
    cg_old = analyze_call_graph(chunks, sfs, legacy=True)
    cg_new = analyze_call_graph(chunks, sfs, legacy=False)
    print(f"Old Call Graph: {cg_old.number_of_nodes()} nodes, {cg_old.number_of_edges()} edges")
    print(f"New Call Graph: {cg_new.number_of_nodes()} nodes, {cg_new.number_of_edges()} edges")
