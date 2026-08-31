"""
Semantic Chunking Engine
- Python: AST-based extraction of functions/classes (with docstrings, signatures)
- JavaScript, TypeScript, TSX, Java: Tree-Sitter AST semantic chunking
- Other languages / unparsable files: fallback line-window chunking
"""
import ast
from dataclasses import dataclass, field
from typing import List, Optional
from core.parser import SourceFile
from core.tree_sitter_chunker import extract_tree_sitter_chunks


@dataclass
class CodeChunk:
    chunk_id: str        # e.g. "repo/file.py::ClassName.method_name"
    file_path: str
    language: str
    kind: str             # "function" | "class" | "method" | "interface" | "enum" | "type" | "block"
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
        return [_fallback_chunk(sf)]

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
            # also chunk methods individually for finer-grained retrieval
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
        chunks.append(_fallback_chunk(sf))

    return chunks


def _fallback_chunk(sf: SourceFile, window: int = 60) -> CodeChunk:
    """Non-Python or unparsable files: whole-file or windowed chunk."""
    lines = sf.content.splitlines()
    return CodeChunk(
        chunk_id=f"{sf.rel_path}::whole_file",
        file_path=sf.rel_path,
        language=sf.language,
        kind="block",
        name=sf.rel_path,
        start_line=1,
        end_line=max(1, len(lines)),
        code=sf.content,
    )


def chunk_file(sf: SourceFile) -> List[CodeChunk]:
    """Chunks a source file using Python AST or Tree-Sitter AST based on language."""
    if sf.language == "python":
        return chunk_python_file(sf)

    if sf.has_tree_sitter and sf.language in ("javascript", "typescript", "tsx", "java"):
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

    return [_fallback_chunk(sf)]


def chunk_repository(source_files: List[SourceFile]) -> List[CodeChunk]:
    all_chunks: List[CodeChunk] = []
    for sf in source_files:
        all_chunks.extend(chunk_file(sf))
    return all_chunks
