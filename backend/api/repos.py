"""
Repositories API Router (Phases 7, 8, 9)
Ingests, clones, lists, auto-reloads, and incrementally syncs software repositories.
"""
import os
import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from core.pipeline import ingest_repository, IngestedRepository
from backend.services.llm_factory import create_embedder, create_llm
from backend.auth import User, get_current_user
from backend.database import db_manager, save_vector_store, load_vector_store
from backend.services import GitService, IncrementalIndexer
from backend.config import settings

router = APIRouter(prefix="/repos", tags=["Repositories"])

# Active repository cache: repo_id -> dict
ACTIVE_REPOS: Dict[str, Dict[str, Any]] = {}


class IngestRequest(BaseModel):
    repo_id: str
    repo_path: str
    backend: str = settings.DEFAULT_EMBEDDER_BACKEND  # "ollama" | "tfidf"


class GitCloneRequest(BaseModel):
    repo_id: str
    git_url: str
    backend: str = settings.DEFAULT_EMBEDDER_BACKEND


def get_repo_engine(repo_id: str):
    """Helper to retrieve or auto-reload repository query engine & graph from persistent storage."""
    import urllib.parse
    repo_id = urllib.parse.unquote(repo_id).strip()

    if repo_id in ACTIVE_REPOS:
        return ACTIVE_REPOS[repo_id]

    # Attempt FAISS store & DB metadata auto-reload
    store = load_vector_store(repo_id)
    repo_meta = db_manager.find_one("repositories", {"repo_id": repo_id})

    if not store or not repo_meta:
        # If repo_id points to an existing local directory (e.g. sample_repo), auto-ingest it!
        if os.path.exists(repo_id):
            backend = settings.DEFAULT_EMBEDDER_BACKEND
            embedder = create_embedder(backend)
            llm = create_llm(backend)
            result = ingest_repository(repo_id, embedder)

            from backend.dependency_graph import EnhancedDependencyGraph
            from backend.parser import parse_repository_files
            source_files = parse_repository_files(repo_id)
            enhanced_graph_engine = EnhancedDependencyGraph()
            enhanced_graph = enhanced_graph_engine.build(source_files)

            from rag.query_engine import QueryEngine
            engine = QueryEngine(result.store, embedder, llm)

            repo_record = {
                "repo_id": repo_id,
                "repo_path": repo_id,
                "backend": backend,
                "owner_id": "default",
                "num_files": result.num_files,
                "num_chunks": result.num_chunks,
                "created_at": time.time(),
            }
            db_manager.update("repositories", {"repo_id": repo_id}, repo_record)
            save_vector_store(repo_id, result.store)

            ACTIVE_REPOS[repo_id] = {
                "engine": engine,
                "graph": enhanced_graph,
                "store": result.store,
                "meta": repo_record,
                "source_files": source_files,
                "embedder": embedder,
            }
            return ACTIVE_REPOS[repo_id]

        raise HTTPException(status_code=404, detail=f"Repository '{repo_id}' not found or not ingested.")



@router.post("/ingest")
def ingest_repo(req: IngestRequest, current_user: User = Depends(get_current_user)):
    embedder = create_embedder(req.backend)
    llm = create_llm(req.backend)

    if not os.path.exists(req.repo_path):
        raise HTTPException(status_code=400, detail=f"Directory path '{req.repo_path}' does not exist.")

    result = ingest_repository(req.repo_path, embedder)

    from backend.dependency_graph import EnhancedDependencyGraph
    from backend.parser import parse_repository_files
    source_files = parse_repository_files(req.repo_path)
    enhanced_graph_engine = EnhancedDependencyGraph()
    enhanced_graph = enhanced_graph_engine.build(source_files)

    from rag.query_engine import QueryEngine
    engine = QueryEngine(result.store, embedder, llm)

    repo_record = {
        "repo_id": req.repo_id,
        "repo_path": req.repo_path,
        "backend": req.backend,
        "owner_id": current_user.id,
        "num_files": result.num_files,
        "num_chunks": result.num_chunks,
        "created_at": time.time(),
    }

    # Save metadata & FAISS index
    db_manager.update("repositories", {"repo_id": req.repo_id}, repo_record)
    save_vector_store(req.repo_id, result.store)

    ACTIVE_REPOS[req.repo_id] = {
        "engine": engine,
        "graph": enhanced_graph,
        "store": result.store,
        "meta": repo_record,
        "source_files": source_files,
        "embedder": embedder,
    }

    return {
        "message": f"Repository '{req.repo_id}' ingested successfully",
        "repo_id": req.repo_id,
        "files_indexed": result.num_files,
        "chunks_indexed": result.num_chunks,
        "graph_nodes": enhanced_graph.number_of_nodes(),
    }


@router.post("/clone")
def clone_repo(req: GitCloneRequest, current_user: User = Depends(get_current_user)):
    git_service = GitService()
    try:
        local_path = git_service.clone_repository(req.git_url, req.repo_id)
        ingest_req = IngestRequest(repo_id=req.repo_id, repo_path=local_path, backend=req.backend)
        return ingest_repo(ingest_req, current_user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
def list_repos(current_user: User = Depends(get_current_user)):
    return db_manager.find("repositories")


@router.post("/{repo_id}/sync")
def sync_incremental(repo_id: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(repo_id)
    embedder = repo_data["embedder"]
    store = repo_data["store"]
    repo_path = repo_data["meta"]["repo_path"]

    indexer = IncrementalIndexer(embedder)
    prev_hashes = repo_data.get("file_hashes", {})

    new_store, new_hashes, count = indexer.sync_repository(repo_path, store, prev_hashes)

    if count > 0:
        save_vector_store(repo_id, new_store)
        repo_data["store"] = new_store
        repo_data["file_hashes"] = new_hashes

    return {
        "repo_id": repo_id,
        "files_reindexed": count,
        "total_chunks": len(new_store.chunks),
    }
