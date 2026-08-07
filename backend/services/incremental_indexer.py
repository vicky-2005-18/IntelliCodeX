"""
Incremental Repository Indexing Engine (Phase 8)
Detects changed files via Git diff or content checksums, partially re-chunks,
and updates vector stores and metadata without requiring full repository re-indexing.
"""
import hashlib
import os
from typing import List, Dict, Any, Tuple
from core.parser import SourceFile, walk_repository
from core.chunker import chunk_file, CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from backend.services.git_service import GitService


def compute_file_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


class IncrementalIndexer:
    def __init__(self, embedder: BaseEmbedder):
        self.embedder = embedder
        self.git_service = GitService()

    def sync_repository(
        self,
        repo_path: str,
        existing_store: FaissVectorStore,
        previous_file_hashes: Dict[str, str]
    ) -> Tuple[FaissVectorStore, Dict[str, str], int]:
        
        current_files = walk_repository(repo_path)
        current_hashes: Dict[str, str] = {}
        changed_files: List[SourceFile] = []

        for sf in current_files:
            h = compute_file_hash(sf.content)
            current_hashes[sf.rel_path] = h
            if previous_file_hashes.get(sf.rel_path) != h:
                changed_files.append(sf)

        if not changed_files:
            return existing_store, current_hashes, 0

        # Remove old chunks of modified files from store
        changed_paths = {sf.rel_path for sf in changed_files}
        remaining_chunks = [c for c in existing_store.chunks if c.file_path not in changed_paths]

        # Re-chunk modified files
        new_chunks: List[CodeChunk] = []
        for sf in changed_files:
            new_chunks.extend(chunk_file(sf))

        all_chunks = remaining_chunks + new_chunks

        # Re-embed updated chunk corpus
        texts = [c.as_embedding_text() for c in all_chunks]
        vectors = self.embedder.embed(texts)

        new_store = FaissVectorStore(dim=vectors.shape[1])
        new_store.add(all_chunks, vectors)

        return new_store, current_hashes, len(changed_files)
