"""
Repositories API Router (Phases 7, 8, 9)
Ingests, clones, lists, auto-reloads, and incrementally syncs software repositories.
"""
import os
import re
import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from core.pipeline import ingest_repository, IngestedRepository
from core.safe_paths import resolve_within
from backend.services.llm_factory import create_embedder, create_llm
from backend.auth import User, get_current_user
from backend.database import db_manager, save_vector_store, load_vector_store
from backend.services import GitService, IncrementalIndexer
from backend.config import settings

router = APIRouter(prefix="/repos", tags=["Repositories"], dependencies=[Depends(get_current_user)])

# Active repository cache: repo_id -> dict
ACTIVE_REPOS: Dict[str, Dict[str, Any]] = {}

REPO_ID_REGEX = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_repo_id(repo_id: str) -> str:
    """Restricts repo_id to alphanumeric characters, dots, underscores, and hyphens."""
    cleaned = repo_id.strip()
    if not REPO_ID_REGEX.match(cleaned):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid repository ID '{repo_id}'. ID must match ^[A-Za-z0-9._-]+$ and cannot be a path or contain special characters.",
        )
    return cleaned


def validate_ingest_path(repo_path: str) -> str:
    """Validates that repo_path exists, is a directory, and is within allowed directory boundaries."""
    if not repo_path or not repo_path.strip():
        raise HTTPException(status_code=400, detail="Repository path cannot be empty.")

    if not os.path.exists(repo_path):
        raise HTTPException(status_code=400, detail=f"Directory path '{repo_path}' does not exist.")

    real_target = os.path.realpath(repo_path)
    if not os.path.isdir(real_target):
        raise HTTPException(status_code=400, detail=f"Path '{repo_path}' is not a directory.")

    allowed_roots = [os.path.realpath(settings.REPOS_DIR)]
    for d in getattr(settings, "ALLOWED_INGEST_DIRS", []):
        allowed_roots.append(os.path.realpath(d))

    is_allowed = False
    for root in allowed_roots:
        try:
            if os.path.commonpath([root, real_target]) == root:
                is_allowed = True
                break
        except ValueError:
            continue

    if not is_allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Ingest path '{repo_path}' is outside permitted directory boundaries ({settings.REPOS_DIR}).",
        )
    return real_target


def validate_clone_url(git_url: str) -> str:
    """Validates that clone URL is https:// or git@ only, preventing flag injection or unauthorized protocols."""
    url = git_url.strip()
    if url.startswith("-"):
        raise HTTPException(status_code=400, detail="Invalid git clone URL.")
    if not (url.startswith("https://") or url.startswith("git@")):
        raise HTTPException(
            status_code=400,
            detail="Git clone URL must use https:// or git@ protocols only.",
        )
    return url


class IngestRequest(BaseModel):
    repo_id: str
    repo_path: str
    backend: str = settings.DEFAULT_EMBEDDER_BACKEND  # "ollama" | "tfidf"


class GitCloneRequest(BaseModel):
    repo_id: str
    git_url: str
    backend: str = settings.DEFAULT_EMBEDDER_BACKEND


def get_repo_engine(repo_id: str, user: Optional[User] = None):
    """
    Helper to retrieve or auto-reload repository query engine & graph from persistent storage.
    Resolves repos only by validated ID from the database or from REPOS_DIR/<validated id>.
    Runs ownership check before any loading or ingest.
    """
    valid_id = validate_repo_id(repo_id)
    backend = settings.DEFAULT_EMBEDDER_BACKEND

    if valid_id in ACTIVE_REPOS:
        repo_data = ACTIVE_REPOS[valid_id]
        if user and user.role != "admin":
            owner = repo_data.get("meta", {}).get("owner_id")
            if owner and owner != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: repository '{valid_id}' belongs to another user",
                )
        if repo_data["engine"].llm is None and backend == "ollama":
            repo_data["engine"].llm = create_llm("ollama")
        return repo_data

    # Check DB metadata first
    repo_meta = db_manager.find_one("repositories", {"repo_id": valid_id})
    if repo_meta:
        # Ownership check BEFORE loading vector store or parsing files
        if user and user.role != "admin":
            owner = repo_meta.get("owner_id")
            if owner and owner != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: repository '{valid_id}' belongs to another user",
                )

        store = load_vector_store(valid_id)
        embedder = create_embedder(backend)
        if store is None:
            dim = getattr(embedder, "dim", getattr(embedder, "dimension", 768))
            from core.vectorstore import FaissVectorStore
            store = FaissVectorStore(dim)

        llm = create_llm(backend)

        from backend.dependency_graph import EnhancedDependencyGraph
        from backend.parser import parse_repository_files
        repo_path = repo_meta.get("repo_path", valid_id)
        if not os.path.exists(repo_path):
            try:
                resolved_dir = resolve_within(settings.REPOS_DIR, valid_id)
                if os.path.exists(resolved_dir):
                    repo_path = resolved_dir
            except ValueError:
                pass

        source_files = parse_repository_files(repo_path) if os.path.exists(repo_path) else []
        enhanced_graph = EnhancedDependencyGraph().build(source_files) if source_files else EnhancedDependencyGraph().build([])

        from rag.query_engine import QueryEngine
        engine = QueryEngine(store, embedder, llm)

        ACTIVE_REPOS[valid_id] = {
            "engine": engine,
            "graph": enhanced_graph,
            "store": store,
            "meta": repo_meta,
            "source_files": source_files,
            "embedder": embedder,
        }
        return ACTIVE_REPOS[valid_id]

    # Check if directory exists in REPOS_DIR/<valid_id> safely
    try:
        target_path = resolve_within(settings.REPOS_DIR, valid_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid repository ID '{valid_id}'.")

    if os.path.isdir(target_path):
        embedder = create_embedder(backend)
        llm = create_llm(backend)
        result = ingest_repository(target_path, embedder)

        from backend.dependency_graph import EnhancedDependencyGraph
        from backend.parser import parse_repository_files
        source_files = parse_repository_files(target_path)
        enhanced_graph_engine = EnhancedDependencyGraph()
        enhanced_graph = enhanced_graph_engine.build(source_files)

        from rag.query_engine import QueryEngine
        engine = QueryEngine(result.store, embedder, llm)

        repo_record = {
            "repo_id": valid_id,
            "repo_path": target_path,
            "backend": backend,
            "owner_id": user.id if user else "system",
            "num_files": result.num_files,
            "num_chunks": result.num_chunks,
            "created_at": time.time(),
        }
        db_manager.update("repositories", {"repo_id": valid_id}, repo_record)
        save_vector_store(valid_id, result.store)

        ACTIVE_REPOS[valid_id] = {
            "engine": engine,
            "graph": enhanced_graph,
            "store": result.store,
            "meta": repo_record,
            "source_files": source_files,
            "embedder": embedder,
        }
        return ACTIVE_REPOS[valid_id]

    raise HTTPException(status_code=404, detail=f"Repository '{valid_id}' not found.")


def get_repo_for_user(repo_id: str, user: User) -> Dict[str, Any]:
    """
    Retrieve repository engine for a user, enforcing ownership check before loading.
    Non-admin users can only access their own repositories.
    """
    valid_id = validate_repo_id(repo_id)

    # Check DB metadata first
    repo_meta = db_manager.find_one("repositories", {"repo_id": valid_id})
    if repo_meta:
        owner_id = repo_meta.get("owner_id")
        if user.role != "admin" and owner_id and owner_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: repository '{valid_id}' belongs to another user",
            )

    return get_repo_engine(valid_id, user=user)


@router.post("/ingest")
def ingest_repo(req: IngestRequest, current_user: User = Depends(get_current_user)):
    """Ingest a repository. Developers can ingest their own repositories within allowed directories."""
    valid_id = validate_repo_id(req.repo_id)
    valid_path = validate_ingest_path(req.repo_path)

    existing = db_manager.find_one("repositories", {"repo_id": valid_id})
    if existing and current_user.role != "admin" and existing.get("owner_id") != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot overwrite repository owned by another user.",
        )

    embedder = create_embedder(req.backend)
    llm = create_llm(req.backend)

    result = ingest_repository(valid_path, embedder)

    from backend.dependency_graph import EnhancedDependencyGraph
    from backend.parser import parse_repository_files
    source_files = parse_repository_files(valid_path)
    enhanced_graph_engine = EnhancedDependencyGraph()
    enhanced_graph = enhanced_graph_engine.build(source_files)

    from rag.query_engine import QueryEngine
    engine = QueryEngine(result.store, embedder, llm)

    repo_record = {
        "repo_id": valid_id,
        "repo_path": valid_path,
        "backend": req.backend,
        "owner_id": current_user.id,
        "num_files": result.num_files,
        "num_chunks": result.num_chunks,
        "created_at": time.time(),
    }

    # Save metadata & FAISS index
    db_manager.update("repositories", {"repo_id": valid_id}, repo_record)
    save_vector_store(valid_id, result.store)

    ACTIVE_REPOS[valid_id] = {
        "engine": engine,
        "graph": enhanced_graph,
        "store": result.store,
        "meta": repo_record,
        "source_files": source_files,
        "embedder": embedder,
    }

    return {
        "message": f"Repository '{valid_id}' ingested successfully",
        "repo_id": valid_id,
        "files_indexed": result.num_files,
        "chunks_indexed": result.num_chunks,
        "graph_nodes": enhanced_graph.number_of_nodes(),
    }


@router.post("/clone")
def clone_repo(req: GitCloneRequest, current_user: User = Depends(get_current_user)):
    """Clone and ingest a remote repository into .repos."""
    valid_id = validate_repo_id(req.repo_id)
    valid_url = validate_clone_url(req.git_url)

    # Check ownership BEFORE cloning: cannot overwrite another user's repo
    existing = db_manager.find_one("repositories", {"repo_id": valid_id})
    if existing and current_user.role != "admin" and existing.get("owner_id") != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot overwrite repository owned by another user.",
        )

    git_service = GitService()
    try:
        local_path = git_service.clone_repository(valid_url, valid_id)
        ingest_req = IngestRequest(repo_id=valid_id, repo_path=local_path, backend=req.backend)
        return ingest_repo(ingest_req, current_user)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{repo_id}")
def delete_repo(repo_id: str, current_user: User = Depends(get_current_user)):
    """Delete a repository. Users can delete their own; admins can delete any repository."""
    valid_id = validate_repo_id(repo_id)
    repo_meta = db_manager.find_one("repositories", {"repo_id": valid_id})
    if not repo_meta and valid_id not in ACTIVE_REPOS:
        raise HTTPException(status_code=404, detail=f"Repository '{valid_id}' not found.")

    owner_id = repo_meta.get("owner_id") if repo_meta else ACTIVE_REPOS.get(valid_id, {}).get("meta", {}).get("owner_id")
    if current_user.role != "admin" and owner_id and owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete other users' repositories.",
        )

    ACTIVE_REPOS.pop(valid_id, None)
    db_manager.delete("repositories", {"repo_id": valid_id})
    return {"message": f"Repository '{valid_id}' deleted successfully", "repo_id": valid_id}


@router.get("/")
def list_repos(current_user: User = Depends(get_current_user)):
    """List repositories: admins see all, developers only see their own."""
    if current_user.role == "admin":
        return db_manager.find("repositories")
    return db_manager.find("repositories", {"owner_id": current_user.id})


@router.post("/{repo_id}/sync")
def sync_incremental(repo_id: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_for_user(repo_id, current_user)
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
