"""
Unit & Integration Tests for Patch Generation Engine (Phase 1)
"""
import os
import tempfile

from backend.patch_generator import (
    generate_git_diff,
    PatchEngine,
    validate_patch,
    compute_patch_quality_score,
    merge_snippet_into_file,
    extract_code_and_explanation,
)
from backend.patch_generator.patch_validator import validate_python_syntax

from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.chunker import CodeChunk


def test_git_diff_generation():
    orig = "def add(a, b):\n    return a + b\n"
    patched = "def add(a, b):\n    if a is None or b is None:\n        return 0\n    return a + b\n"
    diff = generate_git_diff(orig, patched, "math.py")

    assert "diff --git a/math.py b/math.py" in diff
    assert "+    if a is None or b is None:" in diff


def test_patch_engine_fallback():
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="test.py::func",
        file_path="test.py",
        language="python",
        kind="function",
        name="func",
        start_line=1,
        end_line=5,
        code="def calculate(data):\n    return data['val']\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    engine = PatchEngine(store, embedder, llm=None)
    result = engine.generate_patch("test_repo", "KeyError: 'val' in calculate", "test.py")

    assert result["patch_id"] is not None
    assert result["confidence_score"] > 0.0
    assert "diff --git" in result["git_diff"]
    assert result["status"] == "pending"
    assert result["validation"]["has_changes"] is True
    assert result["llm_generated"] is False


def test_llm_parser_extracts_code_block():
    response = (
        "Here is the fix:\n"
        "```python\n"
        "def foo():\n    return data.get('key', None)\n"
        "```\n"
        "This uses .get() to avoid KeyError."
    )
    code, explanation = extract_code_and_explanation(response)
    assert "data.get('key', None)" in code
    assert "KeyError" in explanation


def test_python_syntax_validation():
    valid = validate_python_syntax("def foo():\n    return 1\n")
    assert valid["valid"] is True

    invalid = validate_python_syntax("def foo(\n    return 1\n")
    assert invalid["valid"] is False


def test_compute_patch_quality_score():
    score = compute_patch_quality_score(
        localization_confidence=0.8,
        syntax_valid=True,
        git_apply_valid=True,
        has_changes=True,
        llm_generated=True,
    )
    assert 0.5 < score <= 0.99


def test_merge_snippet_into_file():
    full = "line1\nline2\nline3\nline4\n"
    original_snippet = "line2\nline3\n"
    patched_snippet = "line2_fixed\nline3_fixed\n"
    result = merge_snippet_into_file(full, original_snippet, patched_snippet)
    assert result is not None
    assert "line2_fixed" in result
    assert "line1\n" in result


def test_patch_engine_with_full_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = "calc.py"
        abs_path = os.path.join(tmpdir, file_path)
        original_content = (
            "# calculator module\n"
            "def calculate(data):\n"
            "    return data['val']\n"
            "\n"
            "def other():\n"
            "    pass\n"
        )
        with open(abs_path, "w") as f:
            f.write(original_content)

        embedder = TfidfEmbedder(dim=16)
        chunk = CodeChunk(
            chunk_id="calc.py::calculate",
            file_path=file_path,
            language="python",
            kind="function",
            name="calculate",
            start_line=2,
            end_line=3,
            code="def calculate(data):\n    return data['val']\n",
        )
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        engine = PatchEngine(store, embedder, llm=None, repo_path=tmpdir)
        result = engine.generate_patch("test_repo", "KeyError: 'val' in calculate", file_path)

        assert result["target_file"] == file_path
        assert "calculator module" in result["original_code"]
        assert result["validation"]["has_changes"] is True


def test_validate_patch_no_changes():
    code = "def foo():\n    pass\n"
    validation = validate_patch(code, generate_git_diff(code, code, "f.py"), "python", original_code=code)
    assert validation["has_changes"] is False
