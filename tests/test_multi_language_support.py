"""
Comprehensive End-to-End Verification of Multi-Language Repository Support (REQ-FUT-01).

Exercises:
1. Multi-language ingestion (Python, JavaScript, TypeScript, Java).
2. Syntax-aware AST chunking with function/class boundaries, line numbers, and extracted imports.
3. Disambiguation of identical symbol names across different files/languages.
4. Offline Hybrid / Vector Retrieval with exact language, file, symbol, and line references.
5. Ingestion boundaries: exclusion of ignored folders (node_modules, target, .git).
6. Syntax error resilience: non-fatal diagnostic warning, partial extraction/fallback, valid files preserved.
7. Incremental update: refreshing changed files without reindexing everything.
8. Application-level repository isolation & RBAC authorization boundary.
9. Knowledge graph entity extraction across multi-language source files.
"""
import os
import shutil
import tempfile
import pytest
import logging
from core.embedder import TfidfEmbedder
from core.pipeline import ingest_repository, IngestedRepository
from core.parser import walk_repository
from core.chunker import chunk_file
from rag.query_engine import QueryEngine
from backend.dependency_graph.enhanced_graph import EnhancedDependencyGraph
from backend.auth import User
from backend.api.repos import ACTIVE_REPOS, get_repo_engine
from fastapi import HTTPException


@pytest.fixture
def mixed_language_repo():
    """Creates a deterministic multi-language repository with Python, JS, TS, and Java."""
    tmpdir = tempfile.mkdtemp(prefix="intellicodex_multilang_")

    # 1. Python backend service
    os.makedirs(os.path.join(tmpdir, "backend"), exist_ok=True)
    with open(os.path.join(tmpdir, "backend", "orders.py"), "w", encoding="utf-8") as f:
        f.write(
            "import json\n"
            "import datetime\n\n"
            "class OrderManager:\n"
            "    def __init__(self):\n"
            "        self.orders = []\n\n"
            "    def validate(self, order_data):\n"
            "        \"\"\"Validates python order dictionary structure.\"\"\"\n"
            "        if not order_data or 'id' not in order_data:\n"
            "            return False\n"
            "        return True\n\n"
            "    def calculate_total(self, items):\n"
            "        \"\"\"Calculates sum of item subtotals with sales tax.\"\"\"\n"
            "        return sum(item.get('price', 0) for item in items) * 1.08\n"
        )

    # 2. JavaScript UI component
    os.makedirs(os.path.join(tmpdir, "frontend", "components"), exist_ok=True)
    with open(os.path.join(tmpdir, "frontend", "components", "OrderView.js"), "w", encoding="utf-8") as f:
        f.write(
            "import React from 'react';\n"
            "import _ from 'lodash';\n\n"
            "function formatCurrency(amount) {\n"
            "    return '$' + amount.toFixed(2);\n"
            "}\n\n"
            "function validate(formData) {\n"
            "    // JavaScript client-side form validation\n"
            "    return formData != null && formData.length > 0;\n"
            "}\n\n"
            "class OrderView {\n"
            "    render() {\n"
            "        return '<div>Order Summary</div>';\n"
            "    }\n"
            "}\n"
        )

    # 3. TypeScript API client
    os.makedirs(os.path.join(tmpdir, "frontend", "services"), exist_ok=True)
    with open(os.path.join(tmpdir, "frontend", "services", "types.ts"), "w", encoding="utf-8") as f:
        f.write(
            "export interface OrderPayload {\n"
            "    id: string;\n"
            "    amount: number;\n"
            "}\n"
        )
    with open(os.path.join(tmpdir, "frontend", "services", "orderClient.ts"), "w", encoding="utf-8") as f:
        f.write(
            "import { OrderPayload } from './types';\n\n"
            "export class OrderClient {\n"
            "    private endpoint: string;\n"
            "    constructor(endpoint: string) {\n"
            "        this.endpoint = endpoint;\n"
            "    }\n\n"
            "    async submitOrder(payload: OrderPayload): Promise<boolean> {\n"
            "        return payload.amount > 0;\n"
            "    }\n"
            "}\n\n"
            "export function validate(payload: OrderPayload): boolean {\n"
            "    return payload.id.length > 0 && payload.amount > 0;\n"
            "}\n"
        )

    # 4. Java backend processing service
    os.makedirs(os.path.join(tmpdir, "services"), exist_ok=True)
    with open(os.path.join(tmpdir, "services", "OrderProcessor.java"), "w", encoding="utf-8") as f:
        f.write(
            "package com.orders;\n\n"
            "import java.util.List;\n"
            "import java.util.ArrayList;\n\n"
            "public class OrderProcessor {\n"
            "    private List<String> processedIds = new ArrayList<>();\n\n"
            "    public boolean validate(String orderToken) {\n"
            "        // Java token authentication\n"
            "        return orderToken != null && orderToken.startsWith(\"ORD-\");\n"
            "    }\n\n"
            "    public void processPayment(String orderToken, double amount) {\n"
            "        if (validate(orderToken)) {\n"
            "            processedIds.add(orderToken);\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

    # 5. Ignored folders & files (must be excluded by ingestion rules)
    os.makedirs(os.path.join(tmpdir, "node_modules", "package_mock"), exist_ok=True)
    with open(os.path.join(tmpdir, "node_modules", "package_mock", "index.js"), "w", encoding="utf-8") as f:
        f.write("module.exports = { mock: true };\n")

    os.makedirs(os.path.join(tmpdir, "target", "classes"), exist_ok=True)
    with open(os.path.join(tmpdir, "target", "classes", "Dummy.class"), "wb") as f:
        f.write(b"\xca\xfe\xba\xbe\x00\x00\x00\x34")

    os.makedirs(os.path.join(tmpdir, ".git"), exist_ok=True)
    with open(os.path.join(tmpdir, ".git", "config"), "w", encoding="utf-8") as f:
        f.write("[core]\nrepositoryformatversion = 0\n")

    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_mixed_language_ingestion_and_symbol_extraction(mixed_language_repo):
    """
    Verifies that Python, JS, TS, and Java files are discovered,
    parsed with syntax-aware tree-sitter/AST parsers, and have line references and imports.
    """
    embedder = TfidfEmbedder()
    ingested = ingest_repository(mixed_language_repo, embedder)

    assert isinstance(ingested, IngestedRepository)
    # 5 valid files: backend/orders.py, frontend/components/OrderView.js,
    # frontend/services/types.ts, frontend/services/orderClient.ts, services/OrderProcessor.java
    assert ingested.num_files == 5

    # Verify discovered languages
    expected_langs = {"python", "javascript", "typescript", "java"}
    assert expected_langs.issubset(set(ingested.languages_found))

    # Verify ignored directories were NOT ingested
    indexed_paths = [c.file_path.replace("\\", "/") for c in ingested.store.chunks]
    for p in indexed_paths:
        assert "node_modules" not in p
        assert "target" not in p
        assert ".git" not in p

    # Verify syntax-aware chunk types and line references for each language
    chunks_by_file = {}
    for c in ingested.store.chunks:
        norm_path = c.file_path.replace("\\", "/")
        chunks_by_file.setdefault(norm_path, []).append(c)

    # Python: backend/orders.py
    py_chunks = chunks_by_file["backend/orders.py"]
    py_symbols = {c.name: c for c in py_chunks}
    assert "OrderManager" in py_symbols
    assert "OrderManager.validate" in py_symbols
    assert "OrderManager.calculate_total" in py_symbols
    val_py = py_symbols["OrderManager.validate"]
    assert val_py.language == "python"
    assert val_py.start_line >= 8 and val_py.end_line <= 13
    assert val_py.kind in ("method", "function")
    assert "json" in val_py.imports

    # JavaScript: frontend/components/OrderView.js
    js_chunks = chunks_by_file["frontend/components/OrderView.js"]
    js_symbols = {c.name: c for c in js_chunks}
    assert "formatCurrency" in js_symbols
    assert "validate" in js_symbols
    assert "OrderView" in js_symbols
    fc_js = js_symbols["formatCurrency"]
    assert fc_js.language == "javascript"
    assert fc_js.start_line == 4 and fc_js.end_line == 6
    assert "React" in fc_js.imports or "lodash" in fc_js.imports

    # TypeScript: frontend/services/orderClient.ts
    ts_chunks = chunks_by_file["frontend/services/orderClient.ts"]
    ts_symbols = {c.name: c for c in ts_chunks}
    assert "OrderClient" in ts_symbols
    assert "OrderClient.submitOrder" in ts_symbols
    assert "validate" in ts_symbols
    so_ts = ts_symbols["OrderClient.submitOrder"]
    assert so_ts.language == "typescript"
    assert so_ts.start_line >= 9 and so_ts.end_line <= 11
    assert "./types" in so_ts.imports

    # Java: services/OrderProcessor.java
    java_chunks = chunks_by_file["services/OrderProcessor.java"]
    java_symbols = {c.name: c for c in java_chunks}
    assert "OrderProcessor" in java_symbols
    assert "OrderProcessor.validate" in java_symbols
    assert "OrderProcessor.processPayment" in java_symbols
    pp_java = java_symbols["OrderProcessor.processPayment"]
    assert pp_java.language == "java"
    assert pp_java.start_line >= 14 and pp_java.end_line <= 18
    assert "java.util.List" in pp_java.imports


def test_symbol_disambiguation_across_languages(mixed_language_repo):
    """
    Verifies that identical symbol names ('validate') in Python, JS, TS, and Java
    receive distinct chunk_ids, source coordinates, and language identifiers.
    """
    embedder = TfidfEmbedder()
    ingested = ingest_repository(mixed_language_repo, embedder)

    validate_chunks = [c for c in ingested.store.chunks if "validate" in c.name]
    assert len(validate_chunks) == 4

    chunk_ids = {c.chunk_id for c in validate_chunks}
    assert len(chunk_ids) == 4, "Each language chunk must have a distinct unique chunk_id"

    languages = {c.language for c in validate_chunks}
    assert languages == {"python", "javascript", "typescript", "java"}

    file_paths = {c.file_path.replace("\\", "/") for c in validate_chunks}
    assert file_paths == {
        "backend/orders.py",
        "frontend/components/OrderView.js",
        "frontend/services/orderClient.ts",
        "services/OrderProcessor.java"
    }


def test_offline_retrieval_with_exact_citations(mixed_language_repo):
    """
    Verifies that QueryEngine offline hybrid/dense retrieval resolves domain terms
    to the correct file, language, and line ranges.
    """
    embedder = TfidfEmbedder()
    ingested = ingest_repository(mixed_language_repo, embedder)

    engine = QueryEngine(
        store=ingested.store,
        embedder=embedder,
        dep_graph=ingested.graph,
        call_graph=getattr(ingested, "call_graph", None),
        lexical_index=getattr(ingested, "lexical_index", None),
        hybrid_search=True,
    )

    # 1. Query distinct JavaScript function 'formatCurrency'
    results_js = engine.retrieve("formatCurrency", top_k=3)
    assert len(results_js) > 0
    top_chunk, score = results_js[0]
    assert top_chunk.file_path.replace("\\", "/").endswith("OrderView.js")
    assert top_chunk.language == "javascript"
    assert top_chunk.name == "formatCurrency"
    assert top_chunk.start_line == 4

    # 2. Query distinct TypeScript method 'submitOrder'
    results_ts = engine.retrieve("submitOrder", top_k=3)
    assert len(results_ts) > 0
    top_chunk_ts, _ = results_ts[0]
    assert top_chunk_ts.file_path.replace("\\", "/").endswith("orderClient.ts")
    assert top_chunk_ts.language == "typescript"
    assert "submitOrder" in top_chunk_ts.name

    # 3. Query distinct Java method 'processPayment'
    results_java = engine.retrieve("processPayment", top_k=3)
    assert len(results_java) > 0
    top_chunk_java, _ = results_java[0]
    assert top_chunk_java.file_path.replace("\\", "/").endswith("OrderProcessor.java")
    assert top_chunk_java.language == "java"
    assert "processPayment" in top_chunk_java.name

    # 4. Query distinct Python method 'calculate_total'
    results_py = engine.retrieve("calculate_total", top_k=3)
    assert len(results_py) > 0
    top_chunk_py, _ = results_py[0]
    assert top_chunk_py.file_path.replace("\\", "/").endswith("orders.py")
    assert top_chunk_py.language == "python"
    assert "calculate_total" in top_chunk_py.name

    # 5. Query ambiguous symbol 'validate' with file scoping (@backend/orders.py)
    results_scoped = engine.retrieve("validate @backend/orders.py", top_k=5)
    assert len(results_scoped) > 0
    for chunk, _ in results_scoped:
        assert chunk.file_path.replace("\\", "/").endswith("orders.py")
        assert chunk.language == "python"


def test_syntax_error_diagnostic_and_file_preservation(mixed_language_repo, caplog):
    """
    Verifies that a syntax error in one file (e.g., broken TS) produces a clear
    diagnostic warning and does NOT cause ingestion to fail or drop unrelated valid files.
    """
    broken_ts_path = os.path.join(mixed_language_repo, "frontend", "services", "broken.ts")
    with open(broken_ts_path, "w", encoding="utf-8") as f:
        f.write(
            "function brokenFunction( {\n"
            "    const x = ;;\n"
            "    return\n"
        )

    broken_py_path = os.path.join(mixed_language_repo, "backend", "broken.py")
    with open(broken_py_path, "w", encoding="utf-8") as f:
        f.write("def broken_py(:\n  return\n")

    embedder = TfidfEmbedder()
    with caplog.at_level(logging.WARNING):
        ingested = ingest_repository(mixed_language_repo, embedder)

    # Total files = 5 valid + 2 broken = 7
    assert ingested.num_files == 7

    # Check that diagnostic warnings were produced for both broken files
    warnings = [rec.message for rec in caplog.records if rec.levelno >= logging.WARNING]
    ts_warn = [w for w in warnings if "broken.ts" in w]
    py_warn = [w for w in warnings if "broken.py" in w]
    assert len(ts_warn) > 0, "Expected Tree-Sitter syntax warning for broken.ts"
    assert len(py_warn) > 0, "Expected AST syntax error warning for broken.py"

    # Verify that valid files are still fully present in the index
    indexed_files = {c.file_path.replace("\\", "/") for c in ingested.store.chunks}
    assert "backend/orders.py" in indexed_files
    assert "frontend/components/OrderView.js" in indexed_files
    assert "services/OrderProcessor.java" in indexed_files
    assert "frontend/services/orderClient.ts" in indexed_files


def test_incremental_update_on_mixed_language_repository(mixed_language_repo):
    """
    Verifies that editing a multi-language file updates the index incrementally
    without corrupting other files.
    """
    embedder = TfidfEmbedder()
    # 1. Initial ingestion
    ingested = ingest_repository(mixed_language_repo, embedder, force_reindex=True)
    assert ingested.indexing_mode.lower() in ("fresh", "cached")

    # 2. Modify Python file with a new method
    py_path = os.path.join(mixed_language_repo, "backend", "orders.py")
    with open(py_path, "a", encoding="utf-8") as f:
        f.write(
            "\n    def cancel_order(self, order_id):\n"
            "        \"\"\"Cancels an order by ID.\"\"\"\n"
            "        return f'Cancelled {order_id}'\n"
        )

    # 3. Incremental re-ingestion
    re_ingested = ingest_repository(mixed_language_repo, embedder, force_reindex=False)
    assert re_ingested.indexing_mode.lower() == "incremental"

    # 4. Verify new method is in store and retrievable
    engine = QueryEngine(
        store=re_ingested.store,
        embedder=embedder,
        dep_graph=re_ingested.graph,
        call_graph=getattr(re_ingested, "call_graph", None),
        lexical_index=getattr(re_ingested, "lexical_index", None),
        hybrid_search=True,
    )
    results = engine.retrieve("cancel_order", top_k=3)
    assert len(results) > 0
    assert any("cancel_order" in c.name for c, _ in results)


def test_multi_language_knowledge_graph_extraction(mixed_language_repo):
    """
    Verifies that EnhancedKnowledgeGraph extracts symbol entities and import relationships
    across Python, JS, TS, and Java files.
    """
    source_files = walk_repository(mixed_language_repo)
    kg = EnhancedDependencyGraph()
    kg.build(source_files)

    # Check entities in graph
    nodes = set(kg.graph.nodes())
    # Should contain files
    assert "backend/orders.py" in nodes
    assert "frontend/components/OrderView.js" in nodes
    assert "frontend/services/orderClient.ts" in nodes
    assert "services/OrderProcessor.java" in nodes

    # Should contain classes and methods across languages with qualified node IDs
    assert "backend/orders.py::OrderManager" in nodes
    assert "frontend/components/OrderView.js::OrderView" in nodes
    assert "frontend/services/orderClient.ts::OrderClient" in nodes
    assert "services/OrderProcessor.java::OrderProcessor" in nodes

    # Check entity resolution via resolve_entity
    assert len(kg.resolve_entity("OrderManager")) > 0
    assert len(kg.resolve_entity("OrderView")) > 0
    assert len(kg.resolve_entity("OrderClient")) > 0
    assert len(kg.resolve_entity("OrderProcessor")) > 0

    # Check source line references on nodes
    order_mgr_node = kg.graph.nodes["backend/orders.py::OrderManager"]
    assert order_mgr_node.get("file_path", "").replace("\\", "/").endswith("orders.py")
    assert order_mgr_node.get("start_line") is not None

    order_proc_node = kg.graph.nodes["services/OrderProcessor.java::OrderProcessor"]
    assert order_proc_node.get("file_path", "").replace("\\", "/").endswith("OrderProcessor.java")
    assert order_proc_node.get("start_line") is not None

    # Check internal import resolution edge in TypeScript (orderClient -> types)
    assert kg.graph.has_edge("frontend/services/orderClient.ts", "frontend/services/types.ts")


def test_repository_isolation_and_authorization(mixed_language_repo):
    """
    Verifies multi-tenant repository isolation and access control boundaries.
    """
    user_alice = User(id="user_alice", username="alice", email="alice@example.com", role="developer")
    user_bob = User(id="user_bob", username="bob", email="bob@example.com", role="developer")

    # Ingest repo into ACTIVE_REPOS cache scoped to Alice
    embedder = TfidfEmbedder()
    ingested = ingest_repository(mixed_language_repo, embedder)
    repo_id = "test-multilang-repo"

    ACTIVE_REPOS[repo_id] = {
        "engine": QueryEngine(ingested.store, embedder, dep_graph=ingested.graph),
        "graph": ingested.graph,
        "meta": {"repo_id": repo_id, "owner_id": user_alice.id, "path": mixed_language_repo}
    }

    try:
        # Alice should have access
        repo_alice = get_repo_engine(repo_id, user_alice)
        assert repo_alice is not None
        assert repo_alice["meta"]["owner_id"] == "user_alice"

        # Bob should be denied with HTTP 403
        with pytest.raises(HTTPException) as exc_info:
            get_repo_engine(repo_id, user_bob)
        assert exc_info.value.status_code == 403
        assert "belongs to another user" in exc_info.value.detail
    finally:
        ACTIVE_REPOS.pop(repo_id, None)
