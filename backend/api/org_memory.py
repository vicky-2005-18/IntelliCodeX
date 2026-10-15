"""
Distributed Organizational Memory API Router (REQ-FUT-09).
Exposes historical Git commit and ADR mining, architectural rationale search,
decision timeline tracking, scoped record creation, lifecycle invalidation/superseding,
and multi-tenant repository access boundaries.
"""
from typing import List, Dict, Any, Optional, Set
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user
from backend.api.repos import get_repo_for_user, ACTIVE_REPOS
from backend.database import db_manager
from core.org_memory import OrgMemoryStore, OrgMemoryItem

router = APIRouter(prefix="/org-memory", tags=["Organizational Memory"], dependencies=[Depends(get_current_user)])

# In-memory store cache: (org_id, repo_id) -> OrgMemoryStore
ACTIVE_ORG_MEMORIES: Dict[str, OrgMemoryStore] = {}


def get_cached_org_memory_store(repo_id: Optional[str], org_id: str) -> OrgMemoryStore:
    """Helper to retrieve or initialize an OrgMemoryStore instance."""
    cache_key = f"{org_id}::{repo_id}" if repo_id else f"{org_id}::shared"
    if cache_key not in ACTIVE_ORG_MEMORIES:
        ACTIVE_ORG_MEMORIES[cache_key] = OrgMemoryStore(repo_id=repo_id, org_id=org_id)
    return ACTIVE_ORG_MEMORIES[cache_key]


def get_user_accessible_repos(user: User) -> Set[str]:
    """Finds all repositories accessible to the user based on tenant ownership and active state."""
    accessible: Set[str] = set()
    if user.role == "admin":
        # Admin can access all repositories within organization
        for r_id, r_data in ACTIVE_REPOS.items():
            accessible.add(r_id)
        db_repos = db_manager.find("repositories", {})
        for r in db_repos:
            accessible.add(r.get("repo_id"))
        return accessible

    # Normal developer: own repos
    for r_id, r_data in ACTIVE_REPOS.items():
        owner = r_data.get("meta", {}).get("owner_id") or r_data.get("meta", {}).get("user_id")
        if owner == user.id:
            accessible.add(r_id)

    db_repos = db_manager.find("repositories", {"owner_id": user.id})
    for r in db_repos:
        accessible.add(r.get("repo_id"))

    return accessible


class OrgMemoryCreateRecordRequest(BaseModel):
    title: str = Field(default="", description="Decision or knowledge record title")
    content: str = Field(default="", description="Rationale, context, decision body, or summary")
    memory_type: str = Field("decision", description="'decision' | 'repair' | 'summary' | 'adr'")
    scope: str = Field("repo_private", description="'repo_private' (default) | 'org_shared'")
    repo_id: Optional[str] = Field(None, description="Repository identifier if scoped to a repository")
    source_references: List[str] = Field(default_factory=list, description="Referenced files, tickets, or URLs")
    files_touched: List[str] = Field(default_factory=list, description="Source files impacted by this record")
    security_policy: str = Field("unscanned", description="'strict' | 'secrets_only' | 'unscanned'")
    verification_status: Optional[str] = Field(None, description="Optional override; summaries are always unverified")


class OrgMemoryInvalidateRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Reason for invalidating or superseding this record")


class OrgMemoryQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Historical architectural rationale question")
    top_k: int = 5
    memory_type_filter: Optional[str] = Field(None, description="Optional filter: 'commit', 'adr', 'decision', 'repair', 'summary'")
    scope_filter: Optional[str] = Field(None, description="Optional filter: 'repo_private' or 'org_shared'")
    security_policy_filter: Optional[str] = Field(None, description="Optional security filter: e.g. 'strict'")
    include_inactive: bool = False


@router.post("/records")
def create_org_memory_record(req: OrgMemoryCreateRecordRequest, current_user: User = Depends(get_current_user)):
    """
    Stores a developer-authored decision, repair record, or generated summary.
    Enforces authorization, tenant boundaries, and non-automatic verification for generated text.
    """
    user_org_id = getattr(current_user, "org_id", "default_org")

    # Authorize repository access if scoped to a repository
    if req.repo_id:
        # Raises 403 / 404 if unauthorized
        get_repo_for_user(req.repo_id, current_user)

    if not req.title or len(req.title.strip()) < 3 or not req.content or len(req.content.strip()) < 5:
        raise HTTPException(status_code=400, detail="Fields 'title' (min 3 chars) and 'content' (min 5 chars) are required.")

    store = get_cached_org_memory_store(req.repo_id, user_org_id)

    # Invariant: generated summaries NEVER become verified knowledge automatically
    if req.memory_type == "summary":
        item = store.record_summary(
            title=req.title,
            content=req.content,
            author=current_user.id,
            repo_id=req.repo_id,
            scope=req.scope,
            source_references=req.source_references,
        )
    elif req.memory_type == "repair":
        item = store.record_repair(
            title=req.title,
            content=req.content,
            author=current_user.id,
            security_policy=req.security_policy,
            test_verified=True,
            developer_approved=True,
            repo_id=req.repo_id,
            scope=req.scope,
            source_references=req.source_references,
        )
    else:  # 'decision' or custom
        item = store.record_decision(
            title=req.title,
            content=req.content,
            author=current_user.id,
            repo_id=req.repo_id,
            scope=req.scope,
            source_references=req.source_references,
            files_touched=req.files_touched,
        )

    return {
        "status": "created",
        "memory_id": item.memory_id,
        "citation": item.citation,
        "scope": item.scope,
        "verification_status": item.verification_status,
        "security_policy": item.security_policy,
        "org_id": item.org_id,
        "repo_id": item.repo_id,
    }


@router.post("/records/{item_id}/invalidate")
def invalidate_org_memory_record(
    item_id: str,
    req: OrgMemoryInvalidateRequest,
    repo_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    Invalidates an obsolete or erroneous memory item.
    Excludes it from subsequent default retrieval.
    """
    user_org_id = getattr(current_user, "org_id", "default_org")
    if repo_id:
        get_repo_for_user(repo_id, current_user)

    store = get_cached_org_memory_store(repo_id, user_org_id)
    success = store.invalidate_record(item_id, reason=req.reason, user_id=current_user.id)
    if not success:
        # Also check shared store
        shared_store = get_cached_org_memory_store(None, user_org_id)
        success = shared_store.invalidate_record(item_id, reason=req.reason, user_id=current_user.id)

    if not success:
        raise HTTPException(status_code=404, detail=f"Memory record '{item_id}' not found in organization.")

    return {
        "status": "invalidated",
        "memory_id": item_id,
        "reason": req.reason,
        "invalidated_by": current_user.id,
    }


@router.post("/query")
def query_all_org_memory(req: OrgMemoryQueryRequest, current_user: User = Depends(get_current_user)):
    """
    Cross-repository organization-wide memory query.
    Retrieves authorized org_shared records and repo_private records for accessible repositories only.
    """
    user_org_id = getattr(current_user, "org_id", "default_org")
    accessible_repos = get_user_accessible_repos(current_user)

    # Search in shared store and all accessible repo stores
    stores_to_search: List[OrgMemoryStore] = [get_cached_org_memory_store(None, user_org_id)]
    for r_id in accessible_repos:
        stores_to_search.append(get_cached_org_memory_store(r_id, user_org_id))

    all_scored_items = []
    seen_ids = set()
    for s in stores_to_search:
        results = s.search(
            query=req.question,
            top_k=req.top_k,
            memory_type_filter=req.memory_type_filter,
            user_id=current_user.id,
            user_role=current_user.role,
            user_org_id=user_org_id,
            accessible_repos=accessible_repos,
            include_inactive=req.include_inactive,
            security_policy_filter=req.security_policy_filter,
        )
        for item, score in results:
            if item.item_id not in seen_ids:
                if req.scope_filter and item.scope != req.scope_filter:
                    continue
                all_scored_items.append((item, score))
                seen_ids.add(item.item_id)

    all_scored_items.sort(key=lambda x: x[1], reverse=True)
    top_items = all_scored_items[:req.top_k]

    context_items = []
    citations = []
    for item, score in top_items:
        citations.append(item.citation)
        context_items.append({
            "item_id": item.item_id,
            "memory_id": item.memory_id,
            "type": item.memory_type,
            "title": item.title,
            "author": item.author,
            "date": item.date_str,
            "scope": item.scope,
            "verification_status": item.verification_status,
            "security_policy": item.security_policy,
            "state": item.state,
            "citation": item.citation,
            "score": round(float(score), 3),
            "summary": item.content[:400],
            "source_references": item.source_references,
            "files_touched": item.files_touched,
        })

    # Fallback answer
    if context_items:
        top = context_items[0]
        answer = (
            f"Found {len(context_items)} authorized organizational memory record(s). "
            f"Top match: {top['citation']} - '{top['title']}' [{top['type']}, verification: {top['verification_status']}] "
            f"by {top['author']}. Rationale: {top['summary'].splitlines()[0]}"
        )
    else:
        answer = "No authorized organizational memory records matched your query."

    return {
        "org_id": user_org_id,
        "question": req.question,
        "answer": answer,
        "citations": citations,
        "retrieved_records": context_items,
        "confidence_score": round(min(0.95, 0.5 + 0.1 * len(context_items)), 2),
    }


@router.post("/{repo_id}/ingest")
def ingest_org_memory(repo_id: str, max_commits: int = 150, current_user: User = Depends(get_current_user)):
    """Mines Git history and Architectural Decision Records for a repository."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")
    user_org_id = getattr(current_user, "org_id", "default_org")

    if not repo_path:
        raise HTTPException(status_code=400, detail=f"No local path found for repository '{repo_id}'")

    mem_store = get_cached_org_memory_store(repo_id, user_org_id)
    stats = mem_store.ingest_repository(repo_path, max_commits=max_commits)

    db_manager.insert("org_memory_index", {
        "repo_id": repo_id,
        "org_id": user_org_id,
        "user_id": current_user.id,
        "total_items": stats["total_items"],
        "commits_count": stats["commits_count"],
        "adrs_count": stats["adrs_count"],
    })

    return {
        "repo_id": repo_id,
        "org_id": user_org_id,
        "status": "success",
        "total_items": stats["total_items"],
        "commits_count": stats["commits_count"],
        "adrs_count": stats["adrs_count"],
    }


@router.post("/{repo_id}/query")
def query_org_memory(repo_id: str, req: OrgMemoryQueryRequest, current_user: User = Depends(get_current_user)):
    """Answers historical design and change rationale questions with citations for a repository."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")
    user_org_id = getattr(current_user, "org_id", "default_org")

    mem_store = get_cached_org_memory_store(repo_id, user_org_id)
    if not mem_store.items and repo_path:
        mem_store.ingest_repository(repo_path)

    llm = getattr(repo_data.get("engine"), "llm", None)
    result = mem_store.ask(
        question=req.question,
        top_k=req.top_k,
        memory_type_filter=req.memory_type_filter,
        user_id=current_user.id,
        user_role=current_user.role,
        user_org_id=user_org_id,
        accessible_repos={repo_id},
        include_inactive=req.include_inactive,
        security_policy_filter=req.security_policy_filter,
        llm=llm,
    )
    return result


@router.get("/{repo_id}/adrs")
def get_repository_adrs(repo_id: str, current_user: User = Depends(get_current_user)):
    """Retrieves all discovered Architectural Decision Records for a repository."""
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_path = repo_data.get("meta", {}).get("repo_path")
    user_org_id = getattr(current_user, "org_id", "default_org")

    mem_store = get_cached_org_memory_store(repo_id, user_org_id)
    if not mem_store.items and repo_path:
        mem_store.ingest_repository(repo_path)

    adrs = [item.to_dict() for item in mem_store.items if item.memory_type == "adr" and item.state == "active"]
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
    user_org_id = getattr(current_user, "org_id", "default_org")

    mem_store = get_cached_org_memory_store(repo_id, user_org_id)
    if not mem_store.items and repo_path:
        mem_store.ingest_repository(repo_path)

    active_items = [it for it in mem_store.items if it.state == "active"]
    sorted_items = sorted(active_items, key=lambda x: x.date_str or "", reverse=True)
    return {
        "repo_id": repo_id,
        "total_records": len(sorted_items),
        "timeline": [it.to_dict() for it in sorted_items[:limit]],
    }
