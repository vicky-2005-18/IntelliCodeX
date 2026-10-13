"""
Multi-Repository Workspace & Cross-Service Reasoning API Router (REQ-FUT-08).
Allows querying across multiple repositories simultaneously, namespaces code chunks,
and discovers microservice API contracts between independent repositories.
"""
import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user
from backend.api.repos import get_repo_for_user, ACTIVE_REPOS
from backend.database import db_manager
from core.multi_repo import MultiRepoWorkspace, CrossRepoContract

router = APIRouter(prefix="/multi-repo", tags=["Multi-Repository Reasoning"], dependencies=[Depends(get_current_user)])

# Active in-memory multi-repo workspace cache: workspace_id -> MultiRepoWorkspace
ACTIVE_WORKSPACES: Dict[str, MultiRepoWorkspace] = {}


class CreateWorkspaceRequest(BaseModel):
    workspace_id: str = Field(..., min_length=2, description="Unique workspace identifier")
    repo_ids: List[str] = Field(..., min_length=1, description="List of repository IDs to aggregate")
    name: Optional[str] = None


class MultiRepoQueryRequest(BaseModel):
    workspace_id: str
    question: str = Field(..., min_length=3, description="Cross-repository query")
    top_k: int = 5
    repo_filter: Optional[List[str]] = None


@router.post("/workspace")
def create_workspace(req: CreateWorkspaceRequest, current_user: User = Depends(get_current_user)):
    """Creates a federated multi-repository workspace by aggregating user-authorized repos."""
    workspace = MultiRepoWorkspace(workspace_id=req.workspace_id)

    loaded_repos = []
    for r_id in req.repo_ids:
        try:
            repo_data = get_repo_for_user(r_id, current_user)
            workspace.add_repository(
                repo_id=r_id,
                repo_path=repo_data.get("meta", {}).get("repo_path"),
                store=repo_data.get("store"),
                source_files=repo_data.get("source_files"),
                chunks=getattr(repo_data.get("store"), "chunks", None),
            )
            loaded_repos.append(r_id)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to attach repository '{r_id}' to workspace: {e}"
            )

    ACTIVE_WORKSPACES[req.workspace_id] = workspace

    db_record = {
        "workspace_id": req.workspace_id,
        "name": req.name or req.workspace_id,
        "user_id": current_user.id,
        "repo_ids": loaded_repos,
        "contracts_count": len(workspace.contracts),
        "total_chunks": len(workspace.namespaced_chunks),
        "created_at": time.time(),
    }
    db_manager.insert("multi_repo_workspaces", db_record)

    return {
        "workspace_id": req.workspace_id,
        "repositories": loaded_repos,
        "total_chunks": len(workspace.namespaced_chunks),
        "discovered_contracts": [c.to_dict() for c in workspace.contracts],
    }


@router.get("/workspaces")
def list_workspaces(current_user: User = Depends(get_current_user)):
    """Lists registered workspaces for the current user."""
    return db_manager.find("multi_repo_workspaces", {"user_id": current_user.id})


@router.get("/{workspace_id}/contracts")
def get_contracts(workspace_id: str, current_user: User = Depends(get_current_user)):
    """Retrieves discovered cross-service microservice contracts in a workspace."""
    if workspace_id not in ACTIVE_WORKSPACES:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found in active session.")

    workspace = ACTIVE_WORKSPACES[workspace_id]
    return {
        "workspace_id": workspace_id,
        "contracts_count": len(workspace.contracts),
        "contracts": [c.to_dict() for c in workspace.contracts],
    }


@router.post("/query")
def query_multi_repo(req: MultiRepoQueryRequest, current_user: User = Depends(get_current_user)):
    """Performs federated cross-repository RAG reasoning across all workspace repositories."""
    if req.workspace_id not in ACTIVE_WORKSPACES:
        raise HTTPException(status_code=404, detail=f"Workspace '{req.workspace_id}' not found in active session.")

    workspace = ACTIVE_WORKSPACES[req.workspace_id]
    result = workspace.ask(
        question=req.question,
        top_k=req.top_k,
        repo_filter=req.repo_filter,
    )
    return result
