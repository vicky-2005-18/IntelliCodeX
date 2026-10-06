"""
End-to-End Integration Tests for Multi-Language Ingestion Pipeline
"""
import os
import tempfile
import pytest
from core.embedder import TfidfEmbedder
from core.pipeline import ingest_repository, IngestedRepository


def test_multi_language_pipeline_ingestion():
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Create Python file
        with open(os.path.join(tmpdir, "service.py"), "w", encoding="utf-8") as f:
            f.write("class UserService:\n    def get_user(self, user_id):\n        return {'id': user_id}\n")

        # 2. Create TypeScript file
        with open(os.path.join(tmpdir, "api.ts"), "w", encoding="utf-8") as f:
            f.write("export interface User {\n    id: number;\n    name: string;\n}\n\nexport function fetchUser(id: number): User {\n    return { id, name: 'Alice' };\n}\n")

        # 3. Create Go file
        with open(os.path.join(tmpdir, "server.go"), "w", encoding="utf-8") as f:
            f.write("package main\n\ntype Server struct {\n    Port int\n}\n\nfunc (s *Server) Start() {\n    println(\"Server running\")\n}\n")

        # 4. Create Markdown file
        with open(os.path.join(tmpdir, "README.md"), "w", encoding="utf-8") as f:
            f.write("# Project Docs\nWelcome to multi-lang ingestion.\n\n## Setup\nRun pip install.\n")

        embedder = TfidfEmbedder()
        ingested = ingest_repository(tmpdir, embedder)

        assert isinstance(ingested, IngestedRepository)
        assert ingested.num_files == 4
        assert ingested.num_chunks >= 4
        assert "python" in ingested.languages_found
        assert "typescript" in ingested.languages_found
        assert "go" in ingested.languages_found
        assert "markdown" in ingested.languages_found
        assert ingested.ast_chunks_count > 0

        # Verify FAISS store search works over multi-language chunks
        query_vec = embedder.embed(["fetch user user_id"])
        results = ingested.store.search(query_vec[0], top_k=3)
        assert len(results) > 0
        assert results[0][0].file_path in ("api.ts", "service.py", "README.md", "server.go")
