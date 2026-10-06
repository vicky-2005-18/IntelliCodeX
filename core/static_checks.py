"""
Deterministic static code checks for IntelliCodeX.
Detects:
1. Python AST syntax errors (ast.parse)
2. Python undefined names and missing imports (pyflakes)
3. Tree-sitter ERROR nodes for non-Python or general languages

Critical Principle: Never execute analyzed code. Pure static analysis only.
"""
import ast
import os
import re
from typing import List, Dict, Any, Optional

try:
    import pyflakes.api
    import pyflakes.messages
    import pyflakes.checker
    HAS_PYFLAKES = True
except ImportError:
    HAS_PYFLAKES = False

from core.ts_loader import get_tree_sitter_parser


def check_python_syntax(code: str, file_path: str = "") -> Optional[Dict[str, Any]]:
    """Checks Python source for syntax errors using ast.parse without executing code.
    
    Returns None if valid, or a dict containing error details if invalid.
    """
    try:
        ast.parse(code, filename=file_path or "<string>")
        return None
    except SyntaxError as e:
        return {
            "file": file_path,
            "line": e.lineno or 1,
            "column": e.offset or 1,
            "message": e.msg or "SyntaxError",
            "type": "SyntaxError",
            "source": "static",
            "code": (e.text or "").strip(),
        }


def check_python_pyflakes(code: str, file_path: str = "") -> List[Dict[str, Any]]:
    """Checks Python source for undefined names, missing imports, etc., using pyflakes."""
    findings: List[Dict[str, Any]] = []
    if not HAS_PYFLAKES:
        return findings

    # pyflakes reporter collecting message objects
    class SimpleReporter:
        def __init__(self):
            self.messages = []

        def unexpectedError(self, filename, msg):
            pass

        def syntaxError(self, filename, msg, lineno, offset, text):
            pass

        def flake(self, message):
            self.messages.append(message)

    try:
        reporter = SimpleReporter()
        pyflakes.api.check(code, file_path or "<string>", reporter)
        
        lines = code.splitlines()
        for msg in reporter.messages:
            lineno = getattr(msg, "lineno", 1)
            line_content = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
            
            # Categorize message
            msg_str = msg.message % msg.message_args if hasattr(msg, "message_args") and msg.message_args else str(msg)
            msg_type = type(msg).__name__
            if isinstance(msg, pyflakes.messages.UndefinedName):
                finding_type = "UndefinedName"
            elif isinstance(msg, (pyflakes.messages.UnusedImport, pyflakes.messages.ImportStarUsed)):
                finding_type = "ImportWarning"
            else:
                finding_type = msg_type

            findings.append({
                "file": file_path,
                "line": lineno,
                "column": getattr(msg, "col", 1),
                "message": msg_str,
                "type": finding_type,
                "source": "static",
                "code": line_content,
            })
    except Exception:
        pass

    return findings


def check_tree_sitter_errors(code: str, language: str, file_path: str = "") -> List[Dict[str, Any]]:
    """Traverses tree-sitter AST and locates ERROR nodes or MISSING nodes."""
    parser = get_tree_sitter_parser(language.lower())
    if parser is None:
        return []

    findings: List[Dict[str, Any]] = []
    try:
        tree = parser.parse(bytes(code, "utf8"))
        lines = code.splitlines()

        def _traverse(node):
            if node.type == "ERROR" or node.is_missing:
                start_row, start_col = node.start_point
                lineno = start_row + 1
                line_content = lines[start_row].strip() if 0 <= start_row < len(lines) else ""
                findings.append({
                    "file": file_path,
                    "line": lineno,
                    "column": start_col + 1,
                    "message": f"Syntax error (Tree-sitter {node.type} node)",
                    "type": "SyntaxError",
                    "source": "static",
                    "code": line_content,
                })
                # Don't recurse deeper into error subtree to prevent duplicated nested errors
                return

            for child in node.children:
                _traverse(child)

        _traverse(tree.root_node)
    except Exception:
        pass

    return findings


def run_static_checks(code: str, file_path: str = "", language: Optional[str] = None) -> List[Dict[str, Any]]:
    """Runs all applicable deterministic static checks for the specified file and language.
    
    Returns a unified list of static findings sorted by line number.
    """
    if language is None:
        ext = os.path.splitext(file_path)[1].lower() if file_path else ""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "tsx",
            ".java": "java",
            ".c": "c",
            ".cpp": "cpp",
            ".cc": "cpp",
            ".go": "go",
            ".rs": "rust",
        }
        language = ext_map.get(ext, "python" if not ext else "")

    findings: List[Dict[str, Any]] = []

    if language == "python":
        # 1. Syntax check first
        syntax_err = check_python_syntax(code, file_path)
        if syntax_err:
            return [syntax_err]

        # 2. Pyflakes check (undefined names, imports)
        pyflakes_errs = check_python_pyflakes(code, file_path)
        findings.extend(pyflakes_errs)
    elif language:
        # Non-Python tree-sitter check
        ts_errs = check_tree_sitter_errors(code, language, file_path)
        findings.extend(ts_errs)

    findings.sort(key=lambda x: (x.get("line", 0), x.get("column", 0)))
    return findings
