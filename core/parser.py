"""
Repository Parser Module
- Walks a repo directory
- Detects language by extension
- Filters out irrelevant files (build artifacts, deps, binaries)
"""
import os
from dataclasses import dataclass
from typing import List

LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".go": "go",
    ".cpp": "cpp",
    ".c": "c",
    ".rs": "rust",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    "dist", "build", ".idea", ".vscode", "target", "egg-info",
}


@dataclass
class SourceFile:
    path: str          # absolute path on disk
    rel_path: str       # path relative to repo root (used as an ID)
    language: str
    content: str


def detect_language(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return LANGUAGE_BY_EXT.get(ext, "unknown")


def walk_repository(repo_root: str) -> List[SourceFile]:
    """Walk repo_root and return every recognized source file."""
    repo_root = os.path.abspath(repo_root)
    files: List[SourceFile] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for fname in filenames:
            lang = detect_language(fname)
            if lang == "unknown":
                continue
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, repo_root)
            try:
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            files.append(SourceFile(abs_path, rel_path, lang, content))

    return files


if __name__ == "__main__":
    import sys
    for sf in walk_repository(sys.argv[1] if len(sys.argv) > 1 else "."):
        print(f"[{sf.language}] {sf.rel_path} ({len(sf.content)} chars)")
