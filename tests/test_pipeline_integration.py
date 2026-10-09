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


def test_embedder_called_once_per_chunk_no_duplicates():
    """
    Asserts that repository ingestion calls the embedder exactly once per chunk,
    with no duplicate chunk embedding calls.
    """
    from typing import List
    import numpy as np
    from core.embedder import BaseEmbedder

    class FakeCountingEmbedder(BaseEmbedder):
        def __init__(self, dim: int = 16):
            self.dim = dim
            self.texts_embedded: List[str] = []
            self.call_count = 0

        def embed(self, texts: List[str]) -> np.ndarray:
            self.call_count += 1
            self.texts_embedded.extend(texts)
            return np.zeros((len(texts), self.dim), dtype="float32")

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(5):
            with open(os.path.join(tmpdir, f"module_{i}.py"), "w", encoding="utf-8") as f:
                f.write(f"def func_a_{i}():\n    return {i}\n\ndef func_b_{i}():\n    return {i} * 2\n")

        fake_embedder = FakeCountingEmbedder()
        ingested = ingest_repository(tmpdir, fake_embedder)

        assert ingested.num_chunks == 10
        # Exactly 10 chunks were passed to the embedder, matching num_chunks
        assert len(fake_embedder.texts_embedded) == ingested.num_chunks
        assert fake_embedder.call_count == 1
        # Assert no duplicated chunk texts
        assert len(set(fake_embedder.texts_embedded)) == ingested.num_chunks


def test_ollama_embedder_progress_not_overcounting(capsys, monkeypatch):
    """
    Simulates embedding 408 chunks with OllamaEmbedder and asserts
    that printed progress accurately reflects 408/408 (100.0%) and
    does not double-count (e.g. 792/408).
    """
    from unittest.mock import MagicMock
    from core.embedder import OllamaEmbedder

    with tempfile.TemporaryDirectory() as tmp_cache:
        embedder = OllamaEmbedder(host="http://fake-host", cache_dir=tmp_cache)
        texts = [f"chunk_code_{i}" for i in range(408)]

        # Mock Ollama batch /api/embed endpoint
        def fake_post(url, json=None, timeout=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            batch_input = json.get("input", [])
            mock_resp.json.return_value = {
                "embeddings": [[0.0] * 768 for _ in batch_input]
            }
            return mock_resp

        import requests
        monkeypatch.setattr(requests, "post", fake_post)

        vecs = embedder.embed(texts)
        assert vecs.shape == (408, 768)

        if embedder._db_conn:
            embedder._db_conn.close()

        captured = capsys.readouterr().out
        # Assert correct final progress was printed, not 792/408
        assert "408/408 chunks (100.0%)" in captured
        assert "792" not in captured


