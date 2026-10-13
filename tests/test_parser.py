"""
Tests for Repository Parser Module
"""
import os
import tempfile
import pytest
from core.parser import (
    detect_language,
    load_gitignore_patterns,
    is_ignored_by_gitignore,
    walk_repository,
    SourceFile,
)


def test_detect_language():
    assert detect_language("main.py") == "python"
    assert detect_language("app.tsx") == "tsx"
    assert detect_language("server.js") == "javascript"
    assert detect_language("utils.ts") == "typescript"
    assert detect_language("Main.java") == "java"
    assert detect_language("main.go") == "go"
    assert detect_language("lib.rs") == "rust"
    assert detect_language("core.cpp") == "cpp"
    assert detect_language("header.h") == "c"
    assert detect_language("binary.exe") == "unknown"


def test_gitignore_matching():
    patterns = ["*.log", "build/", "secret.txt"]
    assert is_ignored_by_gitignore("app.log", patterns) is True
    assert is_ignored_by_gitignore("sub/dir/app.log", patterns) is True
    assert is_ignored_by_gitignore("build/output.js", patterns) is True
    assert is_ignored_by_gitignore("secret.txt", patterns) is True
    assert is_ignored_by_gitignore("main.py", patterns) is False


def test_walk_repository_sample_repo():
    files = walk_repository("sample_repo")
    assert len(files) > 0
    for sf in files:
        assert isinstance(sf, SourceFile)
        assert sf.language != "unknown"
        assert sf.line_count >= 0
        assert sf.size_bytes >= 0
        assert isinstance(sf.has_tree_sitter, bool)


def test_walk_repository_temp_multi_lang():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create Python file
        py_path = os.path.join(tmpdir, "test.py")
        with open(py_path, "w", encoding="utf-8") as f:
            f.write("def foo():\n    return 42\n")

        # Create TypeScript file
        ts_path = os.path.join(tmpdir, "index.ts")
        with open(ts_path, "w", encoding="utf-8") as f:
            f.write("const x: number = 42;\n")

        # Create ignored file
        log_path = os.path.join(tmpdir, "app.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("log line\n")

        # Create .gitignore
        with open(os.path.join(tmpdir, ".gitignore"), "w", encoding="utf-8") as f:
            f.write("*.log\n")

        results = walk_repository(tmpdir)
        rel_paths = [r.rel_path for r in results]

        assert "test.py" in rel_paths
        assert "index.ts" in rel_paths
        assert "app.log" not in rel_paths
        assert all(r.has_tree_sitter is True for r in results)


def test_walk_repository_includes_tests_and_docs_by_default():
    """Verify that walk_repository discovers files in tests/ and docs/ by default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "tests"))
        with open(os.path.join(tmpdir, "tests", "test_app.py"), "w", encoding="utf-8") as f:
            f.write("def test_one(): pass\n")

        os.makedirs(os.path.join(tmpdir, "docs"))
        with open(os.path.join(tmpdir, "docs", "architecture.md"), "w", encoding="utf-8") as f:
            f.write("# Architecture Overview\n")

        with open(os.path.join(tmpdir, "main.py"), "w", encoding="utf-8") as f:
            f.write("def main(): pass\n")

        default_files = walk_repository(tmpdir)
        default_paths = [r.rel_path.replace("\\", "/") for r in default_files]
        assert "main.py" in default_paths
        assert "tests/test_app.py" in default_paths
        assert "docs/architecture.md" in default_paths

        # Test optional exclusion flags
        no_tests = walk_repository(tmpdir, exclude_tests=True)
        no_tests_paths = [r.rel_path.replace("\\", "/") for r in no_tests]
        assert "tests/test_app.py" not in no_tests_paths
        assert "docs/architecture.md" in no_tests_paths

        no_docs = walk_repository(tmpdir, exclude_docs=True)
        no_docs_paths = [r.rel_path.replace("\\", "/") for r in no_docs]
        assert "docs/architecture.md" not in no_docs_paths
        assert "tests/test_app.py" in no_docs_paths

