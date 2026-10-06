"""
Multi-Language Repository Parser Engine (Phase 10)
Supports Python, JavaScript, TypeScript, Java, C++, C#, Go.
Utilizes AST for Python, regex structure parsing for multi-language, with tree-sitter hooks.
"""
import re
import ast
from typing import List, Dict, Any, Optional
from core.parser import SourceFile, walk_repository, detect_language
from core.chunker import CodeChunk, _fallback_chunk


# Extended extension map
EXT_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".rs": "rust",
}


def parse_generic_file(sf: SourceFile) -> List[CodeChunk]:
    """Pattern-based structure extractor for non-Python languages (JS, TS, Java, Go, C++, C#)."""
    lines = sf.content.splitlines()
    if not lines:
        return [_fallback_chunk(sf)]

    chunks: List[CodeChunk] = []

    # Common function/class patterns for JS/TS/Java/Go/C++/C#
    patterns = [
        # Functions / Methods
        (r'^\s*(?:public|private|protected|static|async|function|func|def|inline|const|let|var)?\s*([a-zA-Z_]\w*)\s*\([^\)]*\)\s*(?::|{|=>)', "function"),
        # Classes / Interfaces / Structs
        (r'^\s*(?:export\s+)?(?:public|private|protected|abstract|class|interface|struct|type)\s+([a-zA-Z_]\w*)', "class"),
    ]

    import_patterns = [
        r'^\s*import\s+.*',
        r'^\s*from\s+.*import.*',
        r'^\s*#include\s+.*',
        r'^\s*using\s+.*',
    ]

    imports = []
    for line in lines:
        for imp_pat in import_patterns:
            if re.search(imp_pat, line):
                imports.append(line.strip())
                break

    # Scanned symbol boundaries
    symbols = []
    for idx, line in enumerate(lines):
        line_num = idx + 1
        for pat, kind in patterns:
            match = re.search(pat, line)
            if match:
                name = match.group(1)
                # Ignore noise keywords
                if name in ("if", "for", "while", "switch", "return", "catch", "new", "import", "package"):
                    continue
                symbols.append({"name": name, "kind": kind, "start_line": line_num})
                break

    if not symbols:
        return [_fallback_chunk(sf)]

    # Pair start_line to estimated end_line
    for i in range(len(symbols)):
        curr = symbols[i]
        start = curr["start_line"]
        end = symbols[i + 1]["start_line"] - 1 if i + 1 < len(symbols) else len(lines)
        if end < start:
            end = start
        snippet = "\n".join(lines[start - 1:end])

        chunks.append(CodeChunk(
            chunk_id=f"{sf.rel_path}::{curr['name']}",
            file_path=sf.rel_path,
            language=sf.language,
            kind=curr["kind"],
            name=curr["name"],
            start_line=start,
            end_line=end,
            code=snippet,
            docstring=None,
            imports=imports,
        ))

    return chunks


def parse_and_chunk_file(sf: SourceFile) -> List[CodeChunk]:
    if sf.language == "python":
        from core.chunker import chunk_python_file
        return chunk_python_file(sf)
    return parse_generic_file(sf)


def parse_repository_files(repo_path: str) -> List[SourceFile]:
    """Walk repository and detect all multi-language files."""
    return walk_repository(repo_path)
