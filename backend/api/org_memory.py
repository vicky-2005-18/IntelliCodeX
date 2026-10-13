"""
Distributed Organizational Memory API Router (REQ-FUT-09).
Exposes historical Git commit and ADR mining, architectural rationale search,
and decision timeline tracking.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user
from backend.api.repos import get_repo_for_user
from backend.database import db_manager
from core.org_memory import OrgMemoryStore

router = APIRouter(prefix="/org-memory", tags=["Organizational Memory"], dependencies=[Depends(get_current_user)])

# In-memory store cache: repo_id -> OrgMemoryStore
ACTIVE_ORG_MEMORIES: Dict[str, OrgMemoryStore] = {}


class OrgMemoryQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Historical architectural rationale question")
    top_k: int = 5
    memory_type_filter: Optional[str] = Field(None, description="Optional filter: 'commit' or 'adr'")


@router.post("/{repo_id}/ingest")
def ingest_org_memory(repo_id: str, max_commits: int = 150, current_user: User = Depends(get_current_user)):
    """Mines Git history and Architectural Decision Records for a repository."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")

    if not repo_path:
        raise HTTPException(status_code=400, detail=f"No local path found for repository '{repo_id}'")

    mem_store = OrgMemoryStore(repo_id=repo_id)
    stats = mem_store.ingest_repository(repo_path, max_commits=max_commits)
    ACTIVE_ORG_MEMORIES[repo_id] = mem_store

    db_manager.insert("org_memory_index", {
        "repo_id": repo_id,
        "user_id": current_user.id,
        "total_items": stats["total_items"],
        "commits_count": stats["commits_count"],
        "adrs_count": stats["adrs_count"],
    })

    return {
        "repo_id": repo_id,
        "status": "success",
        "total_items": stats["total_items"],
        "commits_count": stats["commits_count"],
        "adrs_count": stats["adrs_count"],
    }


@router.post("/{repo_id}/query")
def query_org_memory(repo_id: str, req: OrgMemoryQueryRequest, current_user: User = Depends(get_current_user)):
    """Answers historical design and change rationale questions with citations."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")

    mem_store = ACTIVE_ORG_MEMORIES.get(repo_id)
    if not mem_store:
        # Auto-ingest if not cached
        mem_store = OrgMemoryStore(repo_id=repo_id)
        if repo_path:
            mem_store.ingest_repository(repo_path)
        ACTIVE_ORG_MEMORIES[repo_id] = mem_store

    llm = getattr(repo_data.get("engine"), "llm", None)
    result = mem_store.ask(
        question=req.question,
        top_k=req.top_k,
        memory_type_filter=req.memory_type_filter,
        llm=llm,
    )
    return result


@router.get("/{repo_id}/adrs")
def get_repository_adrs(repo_id: str, current_user: User = Depends(get_current_user)):
    """Retrieves all discovered Architectural Decision Records for a repository."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")

    mem_store = ACTIVE_ORG_MEMORIES.get(repo_id)
    if not mem_store:
        mem_store = OrgMemoryStore(repo_id=repo_id)
        if repo_path:
            mem_store.ingest_repository(repo_path)
        ACTIVE_ORG_MEMORIES[repo_id] = mem_store

    adrs = [item.to_dict() for item in mem_store.items if item.memory_type == "adr"]
    return {
        "repo_id": repo_id,
        "count": len(adrs),
        "adrs": adrs,
    }


@router.get("/{repo_id}/timeline")
def get_decision_timeline(repo_id: str, limit: int = 50, current_user: User = Depends(get_current_user)):
    """Returns a chronological timeline of repository architectural decisions and commits."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")

    mem_store = ACTIVE_ORG_MEMORIES.get(repo_id)
    if not mem_store:
        mem_store = OrgMemoryStore(repo_id=repo_id)
        if repo_path:
            mem_store.ingest_repository(repo_path)
        ACTIVE_ORG_MEMORIES[repo_id] = mem_store

    # Sort items by date descending if possible
    sorted_items = sorted(mem_store.items, key=lambda x: x.date_str or "", reverse=True)
    return {
        "repo_id": repo_id,
        "total_records": len(sorted_items),
        "timeline": [it.to_dict() for it in sorted_items[:limit]],
    }
