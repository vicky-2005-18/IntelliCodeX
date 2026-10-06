"""
Fine-Grained Symbol Call Graph Engine
- Extracts caller/callee function relationships across Python, JS/TS, Java, C/C++, Go, and Rust.
- Builds a function-level call graph (NetworkX DiGraph) mapping who calls which function/method.
- Computes symbol centrality (PageRank / In-degree) to highlight critical hot-spot functions.
"""
import ast
import os
import sys
import logging
from dataclasses import dataclass
from typing import List, Dict, Set, Optional, Tuple
import networkx as nx

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.parser import SourceFile
from core.chunker import CodeChunk
from core.ts_loader import get_tree_sitter_parser

logger = logging.getLogger(__name__)


@dataclass
class CallSite:
    caller_chunk_id: str
    caller_file: str
    callee_name: str
    line_number: int


def _extract_python_calls(content: str, rel_path: str) -> List[dict]:
    calls = []
    try:
        tree = ast.parse(content, filename=rel_path)
    except SyntaxError:
        return calls

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            line = getattr(node, "lineno", 1)
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name:
                calls.append({"name": name, "line": line})
    return calls


def _extract_tree_sitter_calls(content: str, rel_path: str, lang: str) -> List[dict]:
    parser = get_tree_sitter_parser(lang)
    if not parser:
        return []

    source_bytes = content.encode("utf-8", errors="ignore")
    try:
        tree = parser.parse(source_bytes)
        if not tree.root_node:
            return []
    except Exception:
        return []

    calls = []
    call_node_types = {
        "call_expression", "method_invocation", "function_call_expression",
        "macro_invocation", "expression_statement"
    }

    def walk(node):
        if node.type in call_node_types and len(node.children) > 0:
            fn_node = node.children[0]
            call_str = source_bytes[fn_node.start_byte:fn_node.end_byte].decode("utf-8", errors="ignore").strip()
            if call_str:
                simple_name = call_str.split(".")[-1].split("->")[-1].split("::")[-1]
                line = node.start_point[0] + 1
                calls.append({"name": simple_name, "full_call": call_str, "line": line})

        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return calls


def extract_function_calls(sf: SourceFile) -> List[dict]:
    """Extracts all function and method call sites from a SourceFile."""
    if sf.language == "python":
        return _extract_python_calls(sf.content, sf.rel_path)
    elif sf.has_tree_sitter:
        return _extract_tree_sitter_calls(sf.content, sf.rel_path, sf.language)
    return []


def build_call_graph(chunks: List[CodeChunk], source_files: List[SourceFile]) -> nx.DiGraph:
    """
    Builds a directed function-level Call Graph mapping caller chunks -> callee chunks.
    Nodes are chunk IDs (or symbol names). Edges represent function calls.
    """
    graph = nx.DiGraph()
    symbol_table: Dict[str, List[CodeChunk]] = {}

    for chunk in chunks:
        graph.add_node(
            chunk.chunk_id,
            file_path=chunk.file_path,
            language=chunk.language,
            kind=chunk.kind,
            name=chunk.name
        )
        simple_name = chunk.name.split(".")[-1].split("::")[-1]
        symbol_table.setdefault(simple_name, []).append(chunk)

    source_map = {sf.rel_path: sf for sf in source_files}

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


def find_callers_of_symbol(call_graph: nx.DiGraph, symbol_name: str) -> List[str]:
    """Returns a list of chunk IDs that call the specified symbol name."""
    callers = set()
    for u, v, data in call_graph.edges(data=True):
        if data.get("symbol") == symbol_name or symbol_name in v:
            callers.add(u)
    return list(callers)


def find_callees_of_chunk(call_graph: nx.DiGraph, chunk_id: str) -> List[str]:
    """Returns a list of target chunk IDs called by chunk_id."""
    if chunk_id not in call_graph:
        return []
    return list(call_graph.successors(chunk_id))


def calculate_symbol_centrality(call_graph: nx.DiGraph) -> Dict[str, float]:
    """
    Computes PageRank centrality scores for all function chunks in the call graph.
    Identifies hot-spot core functions that are central to project execution.
    """
    if len(call_graph) == 0:
        return {}
    try:
        return nx.pagerank(call_graph, alpha=0.85)
    except Exception:
        return nx.in_degree_centrality(call_graph)


def get_top_central_symbols(call_graph: nx.DiGraph, top_n: int = 10) -> List[Tuple[str, float]]:
    """Returns top N most central function/method symbols sorted by PageRank score."""
    scores = calculate_symbol_centrality(call_graph)
    sorted_symbols = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_symbols[:top_n]
