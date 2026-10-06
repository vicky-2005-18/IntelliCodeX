"""
Full System Cross-Module Integration & Stress Testing Suite (Week 6 Day 5)
Tests end-to-end interaction across:
- Multi-language Tree-Sitter AST chunking
- Dependency Graph & Call Graph PageRank Centrality
- SQLite & FAISS Index Persistence
- SHA-256 Fast Change Detection & Incremental Re-Indexing
- Git Hook Management
- Ochiai Bug Localization & Automated Patch Engine
- Multi-Turn Conversation Memory, System Personas & Token Budgeting
- CLI Batch Mode & Performance Benchmarking
"""
import os
import tempfile
import subprocess
import pytest
from unittest.mock import patch
from core.parser import walk_repository
from core.chunker import chunk_repository
from core.dependency_graph import build_dependency_graph, get_top_central_files
from core.call_graph import build_call_graph, get_top_central_symbols
from core.persistence import (
    get_db_connection,
    save_index,
    load_index,
    detect_repository_changes,
    get_repo_id,
)
from core.pipeline import ingest_repository
from core.embedder import TfidfEmbedder
from core.bug_localizer import BugLocalizer, calculate_ochiai_score
from core.patch_generator import PatchEngine, generate_git_diff
from rag.query_engine import QueryEngine, ConversationMemory, PERSONAS
from core.git_hooks import install_git_hooks, check_git_hooks_status, uninstall_git_hooks
from core.benchmarking import run_benchmark
from cli import main as cli_main


def test_full_system_end_to_end_pipeline(tmp_path):
    """Stress tests complete end-to-end system workflow."""
    repo_dir = os.path.join(tmp_path, "full_system_repo")
    os.makedirs(repo_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, text=True, check=True)

    # 1. Create multi-language repository files
    auth_py = os.path.join(repo_dir, "auth.py")
    db_py = os.path.join(repo_dir, "db.py")
    api_ts = os.path.join(repo_dir, "api.ts")

    with open(auth_py, "w") as f:
        f.write("import db\n\ndef login(user):\n    if not user:\n        raise ValueError('User invalid')\n    return db.query_user(user)\n")

    with open(db_py, "w") as f:
        f.write("def query_user(u):\n    return {'name': u}\n")

    with open(api_ts, "w") as f:
        f.write("export interface User {\n    id: number;\n}\n\nexport function fetchUser(id: number): User {\n    return { id };\n}\n")

    embedder = TfidfEmbedder(dim=16)

    # 2. Ingest Repository & Verify Initial Index
    ingested1 = ingest_repository(repo_dir, embedder, save_to_disk=True)
    assert ingested1.num_files == 3
    assert ingested1.num_chunks >= 3
    assert ingested1.graph.number_of_nodes() >= 2

    # 3. Verify Centrality PageRank Scores
    top_files = get_top_central_files(ingested1.graph)
    assert len(top_files) > 0

    # 4. Verify Zero-Latency Cache Load
    cached_ingested = ingest_repository(repo_dir, embedder, force_reindex=False)
    assert cached_ingested.num_chunks == ingested1.num_chunks

    # 5. Modify auth.py and perform Incremental Re-Indexing
    with open(auth_py, "w") as f:
        f.write("import db\n\ndef login(user, token):\n    # Modified with token parameter!\n    if not token:\n        raise ValueError('Token missing')\n    return db.query_user(user)\n")

    delta = detect_repository_changes(repo_dir, walk_repository(repo_dir))
    assert delta.has_changes() is True
    assert len(delta.modified) == 1

    incr_ingested = ingest_repository(repo_dir, embedder, force_reindex=False)
    assert incr_ingested.num_files == 3

    # 6. Test Bug Localization & Automated Patch Engine
    patch_engine = PatchEngine(incr_ingested.store, embedder, llm=None, graph=incr_ingested.graph, repo_path=repo_dir)
    err_report = 'File "auth.py", line 4, in login\nValueError: Token missing'
    patch_rec = patch_engine.generate_patch(get_repo_id(repo_dir), err_report, target_file="auth.py")

    assert patch_rec["patch_id"] is not None
    assert patch_rec["target_file"] == "auth.py"
    assert "diff --git" in patch_rec["git_diff"]

    ok_app, msg_app = patch_engine.apply_patch(patch_rec)
    assert ok_app is True

    # 7. Test Multi-Turn QueryEngine with Personas & Memory
    q_engine = QueryEngine(incr_ingested.store, embedder, dep_graph=incr_ingested.graph)
    q_engine.set_persona("security")
    assert q_engine.active_persona == "security"

    res_q1 = q_engine.ask("How is user query handled?")
    assert len(q_engine.memory) == 1

    res_q2 = q_engine.ask("What imports does auth.py have?")
    assert len(q_engine.memory) == 2

    # 8. Test Git Hooks Generator Lifecycle
    ok_h, _ = install_git_hooks(repo_dir)
    assert ok_h is True
    st_h = check_git_hooks_status(repo_dir)
    assert st_h["post-commit"] is True

    ok_unh, _ = uninstall_git_hooks(repo_dir)
    assert ok_unh is True

    # 9. Test CLI Batch Query Mode
    with patch("sys.argv", ["cli.py", repo_dir, "-q", "authentication", "--backend", "tfidf"]):
        ret_cli = cli_main()
        assert ret_cli == 0

    # 10. Test Performance Benchmarking
    report = run_benchmark(repo_dir)
    assert report.num_files == 3
    assert report.speedup_factor >= 1.0
