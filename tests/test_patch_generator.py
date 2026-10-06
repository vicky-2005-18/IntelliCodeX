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


def test_review_gate_lifecycle_and_audit_log():
    """Verify Phase 2.3: Proposals start pending, approve applies and records audit log, reject discards."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = "auth.py"
        abs_path = os.path.join(tmpdir, file_path)
        orig_code = "def login(user):\n    return user['token']\n"
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(orig_code)

        embedder = TfidfEmbedder(dim=16)
        chunk = CodeChunk(
            chunk_id="auth.py::login",
            file_path=file_path,
            language="python",
            kind="function",
            name="login",
            start_line=1,
            end_line=2,
            code=orig_code,
        )
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        engine = PatchEngine(store, embedder, llm=None, repo_path=tmpdir)
        rec = engine.generate_patch("test_repo", "KeyError: 'token' in login", file_path)

        # 1. Proposal is created in 'pending' status without modifying disk file
        assert rec["status"] == "pending"
        with open(abs_path, "r", encoding="utf-8") as f:
            assert f.read() == orig_code  # File untouched

        # 2. Reject discards proposal and leaves file untouched
        engine.update_patch_status(rec["patch_id"], status="rejected", user="developer_alice")
        with open(abs_path, "r", encoding="utf-8") as f:
            assert f.read() == orig_code

        # 3. Approve applies the patch with .bak backup and creates audit log
        ok_app, msg = engine.apply_patch(rec, approved_by="developer_bob")
        assert ok_app is True
        assert os.path.isfile(abs_path)
        with open(abs_path, "r", encoding="utf-8") as f:
            patched_content = f.read()
        assert patched_content != orig_code

        # Check patch_audit.log exists in configured storage directory
        from backend.config import settings
        audit_file = os.path.join(settings.STORAGE_DIR, "patch_audit.log")
        assert os.path.isfile(audit_file)
        with open(audit_file, "r", encoding="utf-8") as f:
            logs = f.read()
        assert rec["patch_id"] in logs
        assert "developer_bob" in logs


