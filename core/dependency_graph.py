"""
Multi-Language Dependency Analysis Engine
- Builds a file-level import and dependency graph across Python, JS/TS, Java, C/C++, Go, and Rust.
- Exposes graph as NetworkX DiGraph for querying, impact analysis, and centrality scoring.
"""
import ast
import os
import sys
import re
from typing import List, Dict, Optional, Set, Tuple
import networkx as nx

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.parser import SourceFile

# Regex patterns for static import extraction
JS_TS_IMPORT_PATTERN = re.compile(
    r'(?:import|export)\s+(?:.*?from\s+)?["\']([^"\']+)["\']|require\s*\(\s*["\']([^"\']+)["\']\s*\)|import\s*\(\s*["\']([^"\']+)["\']\s*\)'
)
JAVA_IMPORT_PATTERN = re.compile(r'import\s+([\w\.\*]+);')
C_CPP_INCLUDE_PATTERN = re.compile(r'#include\s+["\']([^"\']+)["\']')
GO_IMPORT_PATTERN = re.compile(r'import\s+\(\s*([\s\S]*?)\s*\)|import\s+(?:[\w_]+\s+)?["\']([^"\']+)["\']')
RUST_MOD_USE_PATTERN = re.compile(r'(?:mod\s+([\w_]+);|use\s+(?:crate::|super::|self::)?([\w_]+))')


def extract_file_imports(sf: SourceFile) -> List[str]:
    """Extracts raw import targets from a SourceFile across all supported languages."""
    imports: Set[str] = set()

    if sf.language == "python":
        try:
            tree = ast.parse(sf.content, filename=sf.rel_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        except SyntaxError:
            pass

    elif sf.language in ("javascript", "typescript", "tsx"):
        for match in JS_TS_IMPORT_PATTERN.finditer(sf.content):
            target = match.group(1) or match.group(2) or match.group(3)
            if target:
                imports.add(target)

    elif sf.language == "java":
        for match in JAVA_IMPORT_PATTERN.finditer(sf.content):
            imports.add(match.group(1))

    elif sf.language in ("c", "cpp"):
        for match in C_CPP_INCLUDE_PATTERN.finditer(sf.content):
            imports.add(match.group(1))

    elif sf.language == "go":
        for match in GO_IMPORT_PATTERN.finditer(sf.content):
            block, single = match.group(1), match.group(2)
            if single:
                imports.add(single)
            elif block:
                for line in block.splitlines():
                    sub = re.search(r'["\']([^"\']+)["\']', line)
                    if sub:
                        imports.add(sub.group(1))

    elif sf.language == "rust":
        for match in RUST_MOD_USE_PATTERN.finditer(sf.content):
            target = match.group(1) or match.group(2)
            if target:
                imports.add(target)

    return list(imports)


def resolve_import_to_file(source_rel_path: str, import_str: str, all_files: Dict[str, SourceFile]) -> Optional[str]:
    """
    Resolves raw import string (relative path, package name, header name) to a known repository relative file path.
    """
    normalized_source = source_rel_path.replace("\\", "/")
    normalized_import = import_str.replace("\\", "/")

    if normalized_import in all_files:
        return normalized_import

    source_dir = os.path.dirname(normalized_source)

    if normalized_import.startswith("./") or normalized_import.startswith("../"):
        combined = os.path.normpath(os.path.join(source_dir, normalized_import)).replace("\\", "/")
        extensions = ["", ".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".go", ".rs", ".h", ".hpp", ".cpp", ".c"]
        for ext in extensions:
            cand = combined + ext
            if cand in all_files:
                return cand
            index_cand = f"{combined}/index{ext}".replace("//", "/")
            if index_cand in all_files:
                return index_cand

    header_name = os.path.basename(normalized_import)
    for rel_path in all_files:
        if rel_path.replace("\\", "/").endswith("/" + header_name) or rel_path.replace("\\", "/") == header_name:
            return rel_path

    if "." in import_str:
        last_part = import_str.split(".")[-1]
        py_cand = import_str.replace(".", "/") + ".py"
        java_cand = import_str.replace(".", "/") + ".java"

        for rel_path in all_files:
            norm_rel = rel_path.replace("\\", "/")
            if norm_rel.endswith(py_cand) or norm_rel.endswith(java_cand) or norm_rel.endswith(f"/{last_part}.java"):
                return rel_path

    for rel_path in all_files:
        norm_rel = rel_path.replace("\\", "/")
        if norm_rel.endswith(f"/{import_str}.rs") or norm_rel.endswith(f"/{import_str}/mod.rs"):
            return rel_path
        if norm_rel.endswith(f"/{import_str}.go") or norm_rel.endswith(f"/{import_str}/") or norm_rel == f"{import_str}.go":
            return rel_path

    return None


def build_dependency_graph(source_files: List[SourceFile]) -> nx.DiGraph:
    """Builds a directed dependency graph across all source files in the repository."""
    graph = nx.DiGraph()
    all_files_map = {sf.rel_path.replace("\\", "/"): sf for sf in source_files}

    for sf in source_files:
        norm_path = sf.rel_path.replace("\\", "/")
        graph.add_node(norm_path, language=sf.language, external=False)

    for sf in source_files:
        source_norm = sf.rel_path.replace("\\", "/")
        raw_imports = extract_file_imports(sf)

        for imp in raw_imports:
            target_file = resolve_import_to_file(source_norm, imp, all_files_map)
            if target_file:
                graph.add_edge(source_norm, target_file, internal=True, raw_import=imp)
            else:
                graph.add_node(imp, external=True, language="external")
                graph.add_edge(source_norm, imp, internal=False, raw_import=imp)

    return graph


def files_likely_affected_by(graph: nx.DiGraph, changed_file: str) -> List[str]:
    """
    Reverse-dependency lookup: returns a list of internal repository files
    that depend (directly or transitively) on changed_file.
    """
    norm_target = changed_file.replace("\\", "/")
    if norm_target not in graph:
        return []
    
    ancestors = nx.ancestors(graph, norm_target)
    return [node for node in ancestors if not graph.nodes[node].get("external", False)]


def calculate_file_centrality(graph: nx.DiGraph) -> Dict[str, float]:
    """
    Calculates PageRank centrality scores for all internal files in the dependency graph.
    Higher score indicates a foundational file heavily relied upon across the repo.
    """
    if len(graph) == 0:
        return {}
    try:
        pr_scores = nx.pagerank(graph, alpha=0.85)
    except Exception:
        # Fallback to in-degree centrality if graph is degenerate
        pr_scores = nx.in_degree_centrality(graph)

    # Filter for internal files and normalize
    internal_scores = {
        node: score for node, score in pr_scores.items() 
        if not graph.nodes[node].get("external", False)
    }
    return internal_scores


def get_top_central_files(graph: nx.DiGraph, top_n: int = 10) -> List[Tuple[str, float]]:
    """Returns top N most central files sorted by PageRank score."""
    scores = calculate_file_centrality(graph)
    sorted_files = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_files[:top_n]
