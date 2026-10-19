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

        from core.persistence import get_repo_id
        engine = PatchEngine(store, embedder, llm=None, repo_path=tmpdir)
        rec = engine.generate_patch(get_repo_id(tmpdir), "KeyError: 'token' in login", file_path)

        # 1. Proposal is created in 'pending' status without modifying disk file
        assert rec["status"] == "pending"
        with open(abs_path, "r", encoding="utf-8") as f:
            assert f.read() == orig_code  # File untouched

        # 2. Reject discards proposal and leaves file untouched
        engine.update_patch_status(rec["patch_id"], status="rejected", user="developer_alice")
        with open(abs_path, "r", encoding="utf-8") as f:
            assert f.read() == orig_code

        # 3. Approve applies the patch with .bak backup and creates audit log
        rec["sandbox_validation"] = {
            "verified": True,
            "test_status": "passed",
            "iterations_count": 1,
        }
        rec["security_validation"] = {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
        }
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


def test_patch_synthesis_benchmark():
    """
    Evaluates Patch Synthesis across 5 reference bug cases in sandbox:
    1. KeyError on dictionary access
    2. ZeroDivisionError on divide
    3. IndexError on empty list pop
    4. TypeError on None argument
    5. AttributeError on missing method
    """
    reference_bugs = [
        ("func1.py", "def get_val(d):\n    return d['x']\n", "KeyError: 'x' in get_val"),
        ("func2.py", "def div(a, b):\n    return a / b\n", "ZeroDivisionError: division by zero in div"),
        ("func3.py", "def get_item(lst):\n    return lst[0]\n", "IndexError: list index out of range in get_item"),
        ("func4.py", "def format_text(s):\n    return s.strip()\n", "AttributeError: 'NoneType' object has no attribute 'strip'"),
        ("func5.py", "def compute(a, b):\n    return a + b\n", "TypeError: unsupported operand type(s) for + in compute"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        embedder = TfidfEmbedder(dim=16)
        all_chunks = []
        for f_name, code, err in reference_bugs:
            f_path = os.path.join(tmpdir, f_name)
            with open(f_path, "w", encoding="utf-8") as f:
                f.write(code)
            chk = CodeChunk(
                chunk_id=f"{f_name}::func",
                file_path=f_name,
                language="python",
                kind="function",
                name=f_name.split(".")[0],
                start_line=1,
                end_line=2,
                code=code,
            )
            all_chunks.append(chk)

        vecs = embedder.embed([c.as_embedding_text() for c in all_chunks])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add(all_chunks, vecs)

        engine = PatchEngine(store, embedder, llm=None, repo_path=tmpdir)
        synthesized_count = 0
        ast_valid_count = 0

        for f_name, code, err in reference_bugs:
            patch_rec = engine.generate_patch("bench_repo", err, f_name)
            if patch_rec and patch_rec.get("patch_id"):
                synthesized_count += 1
            if patch_rec.get("validation", {}).get("syntax_valid"):
                ast_valid_count += 1

        pass_rate = ast_valid_count / len(reference_bugs)
        print(f"\n[Patch Synthesis Benchmark] 5 Reference Bugs: Synthesized={synthesized_count}/5, AST Valid={ast_valid_count}/5 ({pass_rate:.1%})")
        assert synthesized_count == 5
        assert pass_rate >= 0.8


def test_multilanguage_tree_sitter_syntax_validation():
    """Verifies REQ-CORE-15 Tree-sitter AST pre-validation across JS, Go, and Rust."""
    from backend.patch_generator.patch_validator import validate_syntax

    # JavaScript
    valid_js = "function add(a, b) { return a + b; }"
    invalid_js = "function add(a, b) { return a + ; }"
    assert validate_syntax(valid_js, "javascript")["valid"] is True
    assert validate_syntax(invalid_js, "javascript")["valid"] is False

    # Go
    valid_go = "package main\nfunc main() {\n\tprintln(\"ok\")\n}"
    invalid_go = "package main\nfunc main( {\n"
    assert validate_syntax(valid_go, "go")["valid"] is True
    assert validate_syntax(invalid_go, "go")["valid"] is False

    # Rust
    valid_rust = "fn calc(x: i32) -> i32 { x + 1 }"
    invalid_rust = "fn calc(x: i32) -> { }"
    assert validate_syntax(valid_rust, "rust")["valid"] is True
    assert validate_syntax(invalid_rust, "rust")["valid"] is False


def test_search_replace_block_parsing():
    """Verifies REQ-CORE-15 search/replace block pattern parsing."""
    from backend.patch_generator.llm_parser import parse_search_replace_blocks, extract_code_and_explanation

    response = (
        "Here is the targeted fix for the nil pointer exception:\n\n"
        "<<<<<<< SEARCH\n"
        "def process(item):\n"
        "    return item.value\n"
        "=======\n"
        "def process(item):\n"
        "    if item is None:\n"
        "        return None\n"
        "    return item.value\n"
        ">>>>>>> REPLACE\n\n"
        "This guards against NoneType operands."
    )

    blocks = parse_search_replace_blocks(response)
    assert len(blocks) == 1
    assert "return item.value" in blocks[0][0]
    assert "if item is None:" in blocks[0][1]

    code, explanation = extract_code_and_explanation(response)
    assert "if item is None:" in code
    assert "This guards against NoneType operands" in explanation


def test_concurrent_modification_conflict_detection():
    """Verifies REQ-CORE-17 atomic code integration detects concurrent file modifications on disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = "service.py"
        abs_path = os.path.join(tmpdir, file_path)
        original_content = "def serve():\n    return 'v1'\n"
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(original_content)

        embedder = TfidfEmbedder(dim=16)
        chunk = CodeChunk(
            chunk_id="service.py::serve",
            file_path=file_path,
            language="python",
            kind="function",
            name="serve",
            start_line=1,
            end_line=2,
            code=original_content,
        )
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        from core.persistence import get_repo_id
        engine = PatchEngine(store, embedder, llm=None, repo_path=tmpdir)
        patch_rec = engine.generate_patch(get_repo_id(tmpdir), "Improve serve function", file_path)
        assert patch_rec["status"] == "pending"

        # Simulate concurrent external edit on disk after patch generation
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write("def serve():\n    # Modified by developer concurrently\n    return 'v2_in_flight'\n")

        patch_rec["sandbox_validation"] = {
            "verified": True,
            "test_status": "passed",
            "iterations_count": 1,
        }
        patch_rec["security_validation"] = {
            "security_status": "passed",
            "security_approved": True,
            "security_policy": "strict",
        }

        # Applying patch without force MUST detect conflict and refuse to overwrite
        ok, msg = engine.apply_patch(patch_rec, approved_by="alice", force=False)
        assert ok is False
        assert "Conflict detected" in msg

        # Ensure modified file on disk was preserved untouched
        with open(abs_path, "r", encoding="utf-8") as f:
            assert "v2_in_flight" in f.read()

        # Applying with force=True overrides conflict when developer confirms
        ok_force, msg_force = engine.apply_patch(patch_rec, approved_by="alice", force=True)
        assert ok_force is True
        assert "Successfully applied patch" in msg_force

        # Ensure .bak backup was created alongside target file
        backups = [f for f in os.listdir(tmpdir) if f.startswith("service.py.bak")]
        assert len(backups) > 0


def test_patch_generation_api_with_sandbox_options():
    """Verifies FastAPI /patches/generate endpoint passes sandbox verification parameters and records owner_id."""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.auth import User, create_access_token
    from backend.database import db_manager

    test_user = User(id="test_patch_user", username="patchdev", email="patchdev@test.com", role="developer")
    db_manager.insert("users", {
        "id": test_user.id,
        "username": test_user.username,
        "email": test_user.email,
        "role": test_user.role,
        "hashed_password": "dummy",
    })
    token = create_access_token(test_user)
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "main.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def run():\n    return 'initial'\n")

        embedder = TfidfEmbedder(dim=16)
        chunk = CodeChunk(
            chunk_id="main.py::run",
            file_path="main.py",
            language="python",
            kind="function",
            name="run",
            start_line=1,
            end_line=2,
            code="def run():\n    return 'initial'\n",
        )
        vecs = embedder.embed([chunk.as_embedding_text()])
        store = FaissVectorStore(dim=vecs.shape[1])
        store.add([chunk], vecs)

        repo_id = "test_api_patch_repo"
        db_manager.insert("repositories", {
            "repo_id": repo_id,
            "owner_id": test_user.id,
            "repo_path": tmpdir,
            "indexed_files": ["main.py"],
            "created_at": 123456789.0,
        })
        from backend.api.repos import ACTIVE_REPOS
        from rag.query_engine import QueryEngine
        ACTIVE_REPOS[repo_id] = {
            "store": store,
            "embedder": embedder,
            "graph": None,
            "engine": QueryEngine(store, embedder, llm=None),
            "meta": {"repo_id": repo_id, "repo_path": tmpdir, "owner_id": test_user.id},
        }

        # Request with verify_in_sandbox=False (standard generation)
        resp = client.post(
            "/api/patches/generate",
            json={
                "repo_id": repo_id,
                "error_report": "KeyError in main.py",
                "target_file": "main.py",
                "verify_in_sandbox": False,
                "max_iterations": 2,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["patch_id"] is not None
        assert data["owner_id"] == test_user.id
        assert data["target_file"] == "main.py"
        assert "suggested_patch" in data
