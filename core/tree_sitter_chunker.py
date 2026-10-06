"""
Tree-Sitter Semantic Chunking Engine
Extracts fine-grained semantic code chunks (functions, classes, methods, interfaces, structs, impls)
using Tree-Sitter AST node traversal for JavaScript, TypeScript, TSX, Java, C, C++, Go, and Rust.
"""
import logging
from typing import List, Optional
from core.ts_loader import get_tree_sitter_parser

logger = logging.getLogger(__name__)

# Node types that represent top-level or method-level code structures per language
CHUNK_NODE_TYPES = {
    "javascript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "generator_function_declaration": "function",
        "arrow_function": "function",
    },
    "typescript": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
        "arrow_function": "function",
    },
    "tsx": {
        "function_declaration": "function",
        "class_declaration": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "arrow_function": "function",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "method_declaration": "method",
        "constructor_declaration": "method",
    },
    "c": {
        "function_definition": "function",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "union_specifier": "union",
    },
    "cpp": {
        "function_definition": "function",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "enum_specifier": "enum",
        "namespace_definition": "namespace",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "type",
        "type_spec": "type",
    },
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "impl_item": "impl",
    },
}


def _extract_node_name(node, source_bytes: bytes) -> str:
    """Extracts identifier name from a Tree-Sitter AST node across multi-language AST variants."""
    # Direct child identifier search
    for child in node.children:
        if child.type in ("identifier", "property_identifier", "type_identifier", "field_identifier", "name"):
            return source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="ignore")
    
    # C/C++ function_declarator nesting
    if node.type == "function_definition":
        for child in node.children:
            if child.type in ("function_declarator", "declarator", "pointer_declarator"):
                return _extract_node_name(child, source_bytes)

    if node.type in ("function_declarator", "declarator", "pointer_declarator"):
        for child in node.children:
            if child.type in ("identifier", "field_identifier", "function_declarator"):
                return _extract_node_name(child, source_bytes)

    # Go type_declaration nesting
    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                return _extract_node_name(child, source_bytes)

    # JS/TS variable declarator
    if node.type in ("variable_declarator", "lexical_declaration"):
        for child in node.children:
            if child.type == "variable_declarator":
                return _extract_node_name(child, source_bytes)

    return "anonymous"


def _extract_js_ts_chunks(root_node, source_lines: List[str], source_bytes: bytes, rel_path: str, lang: str) -> List[dict]:
    chunks = []
    
    def walk(node, parent_class: Optional[str] = None):
        node_type = node.type

        if node_type in ("export_statement", "export_default_declaration"):
            for child in node.children:
                walk(child, parent_class)
            return

        if node_type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    name = _extract_node_name(child, source_bytes)
                    for val in child.children:
                        if val.type in ("arrow_function", "function_expression", "function"):
                            start_line = node.start_point[0] + 1
                            end_line = node.end_point[0] + 1
                            code = "\n".join(source_lines[start_line - 1:end_line])
                            chunks.append({
                                "chunk_id": f"{rel_path}::{name}",
                                "kind": "function",
                                "name": name,
                                "start_line": start_line,
                                "end_line": end_line,
                                "code": code,
                            })
            return

        if node_type in CHUNK_NODE_TYPES.get(lang, {}):
            kind = CHUNK_NODE_TYPES[lang][node_type]
            name = _extract_node_name(node, source_bytes)
            
            if parent_class and kind in ("method", "function"):
                full_name = f"{parent_class}.{name}"
                kind = "method"
            else:
                full_name = name

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            code = "\n".join(source_lines[start_line - 1:end_line])

            chunks.append({
                "chunk_id": f"{rel_path}::{full_name}",
                "kind": kind,
                "name": full_name,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            })

            current_class = name if kind in ("class", "interface") else parent_class
            for child in node.children:
                if child.type in ("class_body", "interface_body", "statement_block", "declaration_list"):
                    for sub in child.children:
                        walk(sub, current_class)
            return

        for child in node.children:
            walk(child, parent_class)

    walk(root_node)
    return chunks


def _extract_java_chunks(root_node, source_lines: List[str], source_bytes: bytes, rel_path: str) -> List[dict]:
    chunks = []

    def walk(node, parent_class: Optional[str] = None):
        node_type = node.type

        if node_type in CHUNK_NODE_TYPES["java"]:
            kind = CHUNK_NODE_TYPES["java"][node_type]
            name = _extract_node_name(node, source_bytes)

            if parent_class and kind == "method":
                full_name = f"{parent_class}.{name}"
            else:
                full_name = name

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            code = "\n".join(source_lines[start_line - 1:end_line])

            chunks.append({
                "chunk_id": f"{rel_path}::{full_name}",
                "kind": kind,
                "name": full_name,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            })

            current_class = name if kind in ("class", "interface", "enum") else parent_class
            for child in node.children:
                if child.type == "class_body":
                    for sub in child.children:
                        walk(sub, current_class)
            return

        for child in node.children:
            walk(child, parent_class)

    walk(root_node)
    return chunks


def _extract_c_cpp_chunks(root_node, source_lines: List[str], source_bytes: bytes, rel_path: str, lang: str) -> List[dict]:
    chunks = []

    def walk(node, parent_container: Optional[str] = None):
        node_type = node.type

        if node_type in CHUNK_NODE_TYPES.get(lang, {}):
            kind = CHUNK_NODE_TYPES[lang][node_type]
            name = _extract_node_name(node, source_bytes)

            if parent_container and kind == "function":
                full_name = f"{parent_container}::{name}"
                kind = "method"
            else:
                full_name = name

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            code = "\n".join(source_lines[start_line - 1:end_line])

            chunks.append({
                "chunk_id": f"{rel_path}::{full_name}",
                "kind": kind,
                "name": full_name,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            })

            current_container = name if kind in ("class", "struct", "namespace") else parent_container
            for child in node.children:
                if child.type in ("field_declaration_list", "compound_statement", "declaration_list"):
                    for sub in child.children:
                        walk(sub, current_container)
            return

        for child in node.children:
            walk(child, parent_container)

    walk(root_node)
    return chunks


def _extract_go_chunks(root_node, source_lines: List[str], source_bytes: bytes, rel_path: str) -> List[dict]:
    chunks = []

    for child in root_node.children:
        if child.type in CHUNK_NODE_TYPES["go"]:
            kind = CHUNK_NODE_TYPES["go"][child.type]
            name = _extract_node_name(child, source_bytes)

            # For Go method declarations, extract receiver type if present
            if child.type == "method_declaration":
                receiver = ""
                for sub in child.children:
                    if sub.type == "parameter_list":
                        receiver = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore")
                        break
                if receiver:
                    name = f"{receiver}.{name}"

            start_line = child.start_point[0] + 1
            end_line = child.end_point[0] + 1
            code = "\n".join(source_lines[start_line - 1:end_line])

            chunks.append({
                "chunk_id": f"{rel_path}::{name}",
                "kind": kind,
                "name": name,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            })

    return chunks


def _extract_rust_chunks(root_node, source_lines: List[str], source_bytes: bytes, rel_path: str) -> List[dict]:
    chunks = []

    def walk(node, parent_impl: Optional[str] = None):
        node_type = node.type

        if node_type == "impl_item":
            impl_target = _extract_node_name(node, source_bytes)
            for child in node.children:
                if child.type == "declaration_list":
                    for sub in child.children:
                        if sub.type == "function_item":
                            name = _extract_node_name(sub, source_bytes)
                            full_name = f"{impl_target}::{name}" if impl_target != "anonymous" else name
                            start_line = sub.start_point[0] + 1
                            end_line = sub.end_point[0] + 1
                            code = "\n".join(source_lines[start_line - 1:end_line])
                            chunks.append({
                                "chunk_id": f"{rel_path}::{full_name}",
                                "kind": "method",
                                "name": full_name,
                                "start_line": start_line,
                                "end_line": end_line,
                                "code": code,
                            })
            return

        if node_type in CHUNK_NODE_TYPES["rust"]:
            kind = CHUNK_NODE_TYPES["rust"][node_type]
            name = _extract_node_name(node, source_bytes)

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            code = "\n".join(source_lines[start_line - 1:end_line])

            chunks.append({
                "chunk_id": f"{rel_path}::{name}",
                "kind": kind,
                "name": name,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            })
            return

        for child in node.children:
            walk(child, parent_impl)

    walk(root_node)
    return chunks


def extract_tree_sitter_chunks(content: str, rel_path: str, lang: str) -> List[dict]:
    """
    Parses content using Tree-Sitter and extracts semantic code chunks across all supported languages.
    Returns a list of chunk property dictionaries.
    """
    parser = get_tree_sitter_parser(lang)
    if not parser:
        return []

    source_bytes = content.encode("utf-8", errors="ignore")
    source_lines = content.splitlines()

    try:
        tree = parser.parse(source_bytes)
        if not tree.root_node:
            return []

        if lang in ("javascript", "typescript", "tsx"):
            return _extract_js_ts_chunks(tree.root_node, source_lines, source_bytes, rel_path, lang)
        elif lang == "java":
            return _extract_java_chunks(tree.root_node, source_lines, source_bytes, rel_path)
        elif lang in ("c", "cpp"):
            return _extract_c_cpp_chunks(tree.root_node, source_lines, source_bytes, rel_path, lang)
        elif lang == "go":
            return _extract_go_chunks(tree.root_node, source_lines, source_bytes, rel_path)
        elif lang == "rust":
            return _extract_rust_chunks(tree.root_node, source_lines, source_bytes, rel_path)
    except Exception as e:
        logger.warning(f"Tree-sitter chunking error on '{rel_path}' [{lang}]: {e}")
        return []

    return []
