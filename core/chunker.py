"""
Semantic Chunking Engine
- Python: AST-based extraction of functions/classes (with docstrings, signatures)
- JavaScript, TypeScript, TSX, Java, C, C++, Go, Rust: Tree-Sitter AST semantic chunking
- Markdown: Heading-level section chunking (#, ##, ###)
- Config & Markup (HTML, CSS, YAML, JSON, SQL, Bash, unparsable files): Smart windowed chunking
"""
import ast
import os
import sys
import re
from dataclasses import dataclass, field
from typing import List, Optional

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.parser import SourceFile
from core.tree_sitter_chunker import extract_tree_sitter_chunks


@dataclass
class CodeChunk:
    chunk_id: str        # e.g. "repo/file.py::ClassName.method_name"
    file_path: str
    language: str
    kind: str             # "function" | "class" | "method" | "interface" | "enum" | "type" | "struct" | "section" | "block"
    name: str
    start_line: int
    end_line: int
    code: str
    docstring: Optional[str] = None
    imports: List[str] = field(default_factory=list)

    def as_embedding_text(self) -> str:
        """What actually gets embedded — code + surrounding context."""
        parts = [f"# File: {self.file_path}", f"# {self.kind}: {self.name}"]
        if self.docstring:
            parts.append(f'"""{self.docstring}"""')
        if self.imports:
            parts.append("# imports: " + ", ".join(self.imports))
        parts.append(self.code)
        return "\n".join(parts)


def _extract_imports(tree: ast.Module) -> List[str]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.extend(f"{mod}.{alias.name}" for alias in node.names)
    return imports


def chunk_python_file(sf: SourceFile) -> List[CodeChunk]:
    chunks: List[CodeChunk] = []
    try:
        tree = ast.parse(sf.content, filename=sf.rel_path)
    except SyntaxError:
        return _windowed_chunks(sf)

    imports = _extract_imports(tree)
    lines = sf.content.splitlines()

    def make_chunk(node, kind):
        start = node.lineno
        end = getattr(node, "end_lineno", start)
        code = "\n".join(lines[start - 1:end])
        name = getattr(node, "name", "module")
        docstring = ast.get_docstring(node)
        return CodeChunk(
            chunk_id=f"{sf.rel_path}::{name}",
            file_path=sf.rel_path,
            language=sf.language,
            kind=kind,
            name=name,
            start_line=start,
            end_line=end,
            code=code,
            docstring=docstring,
            imports=imports,
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(make_chunk(node, "function"))
        elif isinstance(node, ast.ClassDef):
            chunks.append(make_chunk(node, "class"))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = sub.lineno
                    end = getattr(sub, "end_lineno", start)
                    code = "\n".join(lines[start - 1:end])
                    chunks.append(CodeChunk(
                        chunk_id=f"{sf.rel_path}::{node.name}.{sub.name}",
                        file_path=sf.rel_path,
                        language=sf.language,
                        kind="method",
                        name=f"{node.name}.{sub.name}",
                        start_line=start,
                        end_line=end,
                        code=code,
                        docstring=ast.get_docstring(sub),
                        imports=imports,
                    ))

    if not chunks:
        chunks.append(_windowed_chunks(sf)[0])

    return chunks


def _chunk_markdown_file(sf: SourceFile) -> List[CodeChunk]:
    """Chunks markdown documents by section headings (# Heading)."""
    lines = sf.content.splitlines()
    if not lines:
        return _windowed_chunks(sf)

    chunks: List[CodeChunk] = []
    heading_pattern = re.compile(r"^(#{1,4})\s+(.+)$")
    
    current_title = sf.rel_path
    current_lines: List[str] = []
    start_line = 1

    for idx, line in enumerate(lines, start=1):
        match = heading_pattern.match(line)
        if match:
            code_text = "\n".join(current_lines).strip()
            if code_text:
                chunks.append(CodeChunk(
                    chunk_id=f"{sf.rel_path}::{current_title} (L{start_line}-{idx-1})",
                    file_path=sf.rel_path,
                    language=sf.language,
                    kind="section",
                    name=current_title,
                    start_line=start_line,
                    end_line=idx - 1,
                    code=code_text,
                ))
            current_title = match.group(2).strip()
            current_lines = [line]
            start_line = idx
        else:
            current_lines.append(line)

    if current_lines:
        code_text = "\n".join(current_lines).strip()
        if code_text:
            chunks.append(CodeChunk(
                chunk_id=f"{sf.rel_path}::{current_title} (L{start_line}-{len(lines)})",
                file_path=sf.rel_path,
                language=sf.language,
                kind="section",
                name=current_title,
                start_line=start_line,
                end_line=len(lines),
                code=code_text,
            ))

    return chunks or _windowed_chunks(sf)


def _windowed_chunks(sf: SourceFile, window_size: int = 50, overlap: int = 10) -> List[CodeChunk]:
    """Chunks non-AST or unparsable files into overlapping line windows."""
    lines = sf.content.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return [CodeChunk(
            chunk_id=f"{sf.rel_path}::empty",
            file_path=sf.rel_path,
            language=sf.language,
            kind="block",
            name=sf.rel_path,
            start_line=1,
            end_line=1,
            code="",
        )]

    if total_lines <= window_size:
        return [CodeChunk(
            chunk_id=f"{sf.rel_path}::block",
            file_path=sf.rel_path,
            language=sf.language,
            kind="block",
            name=sf.rel_path,
            start_line=1,
            end_line=total_lines,
            code=sf.content,
        )]

    chunks: List[CodeChunk] = []
    step = window_size - overlap
    for start_idx in range(0, total_lines, step):
        end_idx = min(start_idx + window_size, total_lines)
        chunk_lines = lines[start_idx:end_idx]
        start_line = start_idx + 1
        end_line = end_idx
        chunks.append(CodeChunk(
            chunk_id=f"{sf.rel_path}::block_L{start_line}_L{end_line}",
            file_path=sf.rel_path,
            language=sf.language,
            kind="block",
            name=f"{sf.rel_path} (L{start_line}-{end_line})",
            start_line=start_line,
            end_line=end_line,
            code="\n".join(chunk_lines),
        ))
        if end_idx == total_lines:
            break

    return chunks


def chunk_file(sf: SourceFile) -> List[CodeChunk]:
    """Chunks a source file using AST (Python/Tree-Sitter), Sectioning (Markdown), or Windowing."""
    if sf.language == "python":
        return chunk_python_file(sf)

    if sf.language == "markdown":
        return _chunk_markdown_file(sf)

    ts_supported = ("javascript", "typescript", "tsx", "java", "c", "cpp", "go", "rust")
    if sf.has_tree_sitter and sf.language in ts_supported:
        ts_chunks = extract_tree_sitter_chunks(sf.content, sf.rel_path, sf.language)
        if ts_chunks:
            return [
                CodeChunk(
                    chunk_id=c["chunk_id"],
                    file_path=sf.rel_path,
                    language=sf.language,
                    kind=c["kind"],
                    name=c["name"],
                    start_line=c["start_line"],
                    end_line=c["end_line"],
                    code=c["code"],
                )
                for c in ts_chunks
            ]

    return _windowed_chunks(sf)


def chunk_repository(source_files: List[SourceFile]) -> List[CodeChunk]:
    all_chunks: List[CodeChunk] = []
    for sf in source_files:
        all_chunks.extend(chunk_file(sf))
    return all_chunks
