"""
Repository Parser Module
- Walks a repository directory recursively
- Detects programming languages and configuration files by extension
- Filters out irrelevant build artifacts, dependencies, binary files, and .gitignore patterns
- Integrates with tree-sitter loader to attach AST availability metadata to each source file
"""
import os
import sys
import fnmatch
from dataclasses import dataclass
from typing import List, Set

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.ts_loader import is_tree_sitter_available

# Comprehensive language mapping by file extension
LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".rs": "rust",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "bash",
}

# Directories to always skip during repository walking
IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", ".idea", ".vscode", "target", "egg-info",
    ".repos", ".storage", "coverage", ".next", "out", "vendor",
    ".pytest_cache", ".cache", "bin", "obj",
}

# Binary and non-text file extensions to skip
IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip",
    ".tar", ".gz", ".db", ".sqlite", ".faiss", ".pkl", ".onnx",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".mov",
}


@dataclass
class SourceFile:
    path: str               # Absolute path on disk
    rel_path: str           # Path relative to repository root (unique ID)
    language: str           # Detected language identifier
    content: str            # File text content
    has_tree_sitter: bool = False  # True if tree-sitter AST parser is available
    line_count: int = 0     # Number of lines in content
    size_bytes: int = 0     # Byte size of file


def detect_language(filename: str) -> str:
    """Detects language identifier from filename extension."""
    _, ext = os.path.splitext(filename.lower())
    return LANGUAGE_BY_EXT.get(ext, "unknown")


def load_gitignore_patterns(repo_root: str) -> List[str]:
    """Parses .gitignore file in repo_root if present."""
    gitignore_path = os.path.join(repo_root, ".gitignore")
    patterns: List[str] = []
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Normalize trailing slashes for directory matching
                        patterns.append(line.rstrip("/"))
        except OSError:
            pass
    return patterns


def is_ignored_by_gitignore(rel_path: str, gitignore_patterns: List[str]) -> bool:
    """Checks if relative path matches any .gitignore pattern."""
    normalized_path = rel_path.replace("\\", "/").strip("/")
    path_parts = normalized_path.split("/")
    
    for raw_pattern in gitignore_patterns:
        pattern = raw_pattern.strip().rstrip("/").replace("\\", "/")
        if not pattern:
            continue
        if fnmatch.fnmatch(normalized_path, pattern) or fnmatch.fnmatch(normalized_path, f"*/{pattern}"):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in path_parts):
            return True
    return False


def walk_repository(repo_root: str) -> List[SourceFile]:
    """
    Walks repo_root recursively and returns a list of all recognized, non-ignored source files
    populated with language detection and tree-sitter availability metadata.
    """
    repo_root = os.path.abspath(repo_root)
    files: List[SourceFile] = []
    gitignore_patterns = load_gitignore_patterns(repo_root)

    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Filter out ignored directory names in-place
        dirnames[:] = [
            d for d in dirnames 
            if d not in IGNORE_DIRS and not is_ignored_by_gitignore(
                os.path.relpath(os.path.join(dirpath, d), repo_root), gitignore_patterns
            )
        ]

        for fname in filenames:
            _, ext = os.path.splitext(fname.lower())
            if ext in IGNORE_EXTENSIONS:
                continue

            lang = detect_language(fname)
            if lang == "unknown":
                continue

            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, repo_root)

            if is_ignored_by_gitignore(rel_path, gitignore_patterns):
                continue

            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue

            has_ts = is_tree_sitter_available(lang)
            line_count = len(content.splitlines())
            size_bytes = len(content.encode("utf-8", errors="ignore"))

            files.append(SourceFile(
                path=abs_path,
                rel_path=rel_path,
                language=lang,
                content=content,
                has_tree_sitter=has_ts,
                line_count=line_count,
                size_bytes=size_bytes
            ))

    return files


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    res = walk_repository(target)
    print(f"Discovered {len(res)} source files in '{target}':")
    for sf in res:
        print(f"  [{sf.language.upper()}] {sf.rel_path} ({sf.line_count} lines, tree-sitter={sf.has_tree_sitter})")
