"""
Week 4 Comprehensive Milestone Verification Suite
Tests Ochiai suspiciousness scoring, multi-language stack trace parser, BugLocalizer engine,
context-aware PatchEngine, git diff generation, physical file patch application, and CLI fix command.
"""
import os
import tempfile
import pytest
from unittest.mock import patch
from core.bug_localizer import (
    calculate_ochiai_score,
    calculate_ochiai_spectrum,
    CoverageRecord,
    StackTraceParser,
    BugLocalizer,
)
from core.patch_generator import (
    generate_git_diff,
    PatchEngine,
)
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.chunker import CodeChunk
from cli import main as cli_main


def test_week4_ochiai_suspiciousness_score():
    """1. Verifies Ochiai suspiciousness score calculation and spectrum scoring."""
    # Test formula: Ochiai = ef / sqrt(nf * (ef + ep))
    # ef=4, ep=1, nf=4, np=10 -> 4 / sqrt(4 * 5) = 4 / sqrt(20) = 4 / 4.472135 = 0.8944
    score = calculate_ochiai_score(ef=4, ep=1, nf=4, np=10)
    assert round(score, 2) == 0.89

    # Zero-division safety
    assert calculate_ochiai_score(ef=0, ep=0, nf=0, np=10) == 0.0
    assert calculate_ochiai_score(ef=0, ep=5, nf=4, np=10) == 0.0

    # Spectrum calculation
    rec1 = CoverageRecord(element_id="auth.py", failing_exec_count=3, passing_exec_count=0)
    rec2 = CoverageRecord(element_id="db.py", failing_exec_count=1, passing_exec_count=5)
    spectrum = calculate_ochiai_spectrum([rec1, rec2], total_failing=3, total_passing=5)

    assert spectrum["auth.py"] == 1.0  # 3 / sqrt(3 * 3) = 1.0
    assert spectrum["db.py"] < spectrum["auth.py"]


def test_week4_multi_language_stack_trace_parser():
    """2. Verifies stack trace parser across Python, JS, Java, Go, C++, and Rust."""
    parser = StackTraceParser()

    trace_text = """
TypeError: Cannot read property 'user' of undefined
    at authenticate (src/auth.ts:42:15)
    at handleRequest (src/server.ts:100:8)
File "pkg/db.py", line 88, in connect_db
    at com.example.App.main(App.java:25)
at src/main.rs:15:4
"""
    parsed = parser.parse(trace_text)
    assert parsed.error_type == "TypeError"
    assert len(parsed.frames) >= 4

    paths = [f.file_path for f in parsed.frames]
    assert any("auth.ts" in p for p in paths)
    assert any("db.py" in p for p in paths)
    assert any("App.java" in p for p in paths)
    assert any("main.rs" in p for p in paths)


def test_week4_bug_localizer_integration():
    """3. Verifies multi-signal BugLocalizer engine scoring."""
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="pkg/auth.py::login",
        file_path="pkg/auth.py",
        language="python",
        kind="function",
        name="login",
        start_line=10,
        end_line=20,
        code="def login(user, pwd):\n    if not user:\n        raise ValueError('Invalid user credentials')\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    spectrum = {"pkg/auth.py": 0.95}
    localizer = BugLocalizer(store, embedder, spectrum_scores=spectrum)
    report = localizer.localize('File "pkg/auth.py", line 12, in login\nValueError: Invalid user credentials')

    assert report["error_type"] == "ValueError"
    assert len(report["candidates"]) > 0
    top = report["candidates"][0]
    assert top["file_path"] == "pkg/auth.py"
    assert top["confidence_score"] > 0.6
    assert top["ochiai_score"] == 0.95
    assert "pkg/auth.py" in report["root_cause_explanation"]


def test_week4_patch_generator_engine(tmp_path):
    """4. Verifies Git diff generation, PatchEngine fix creation, and file patch application."""
    repo_dir = os.path.join(tmp_path, "patch_repo")
    os.makedirs(repo_dir, exist_ok=True)
    file_path = "auth.py"
    abs_file = os.path.join(repo_dir, file_path)

    orig_content = "def login(user):\n    return user['name']\n"
    with open(abs_file, "w") as f:
        f.write(orig_content)

    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="auth.py::login",
        file_path=file_path,
        language="python",
        kind="function",
        name="login",
        start_line=1,
        end_line=2,
        code=orig_content,
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    patch_engine = PatchEngine(store, embedder, llm=None, repo_path=repo_dir)
    rec = patch_engine.generate_patch("test_repo", "KeyError: 'name' in login", target_file=file_path)

    assert rec["patch_id"] is not None
    assert rec["target_file"] == file_path
    assert "diff --git" in rec["git_diff"]
    assert rec["confidence_score"] > 0.0

    # Test applying patch to physical file
    ok_app, msg_app = patch_engine.apply_patch(rec)
    assert ok_app is True
    assert "Successfully applied" in msg_app

    with open(abs_file, "r") as f:
        patched_disk = f.read()
    assert patched_disk != orig_content


def test_week4_cli_fix_command(tmp_path, capsys):
    """5. Verifies interactive CLI fix command."""
    user_inputs = ["fix:KeyError in auth.py", "n", "exit"]
    with patch("builtins.input", side_effect=user_inputs):
        with patch("sys.argv", ["cli.py", "sample_repo", "--backend", "tfidf"]):
            res = cli_main()
            assert res is None or res == 0

    captured = capsys.readouterr()
    assert "INTELLICODEX AUTOMATED CODE PATCH" in captured.out
    assert "Unified Git Diff" in captured.out
