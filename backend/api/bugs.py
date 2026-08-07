"""
Bug Localization API Router (Phase 2)
Submits stack traces or error logs to pinpoint root causes, file locations, line numbers, and confidence ratings.
"""
import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from backend.api.repos import get_repo_engine
from backend.bug_localizer import AdvancedBugLocalizer
from backend.auth import User, get_current_user
from backend.database import db_manager

router = APIRouter(prefix="/bugs", tags=["Bug Localization"])


class BugReportRequest(BaseModel):
    repo_id: str
    error_report: str
    top_k: int = 5


@router.post("/localize")
def localize_bug(req: BugReportRequest, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(req.repo_id)
    store = repo_data["store"]
    embedder = repo_data["embedder"]
    graph = repo_data["graph"]

    localizer = AdvancedBugLocalizer(store=store, embedder=embedder, graph=graph)
    result = localizer.localize(req.error_report, top_k=req.top_k)

    result["repo_id"] = req.repo_id

    # Store bug report audit
    db_manager.insert("bug_reports", {
        "repo_id": req.repo_id,
        "user_id": current_user.id,
        "error_report": req.error_report,
        "error_type": result.get("error_type"),
        "top_candidate": result.get("recommended_focus"),
        "created_at": time.time(),
    })

    return result


@router.get("/history/{repo_id}")
def get_bug_reports(repo_id: str, current_user: User = Depends(get_current_user)):
    return db_manager.find("bug_reports", {"repo_id": repo_id})
