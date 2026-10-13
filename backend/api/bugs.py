"""
Bug Localization API Router (Phase 2)
Submits stack traces or error logs to pinpoint root causes, file locations, line numbers, and confidence ratings.
"""
import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from backend.api.repos import get_repo_for_user
from backend.bug_localizer import AdvancedBugLocalizer
from backend.auth import User, get_current_user
from backend.database import db_manager

router = APIRouter(prefix="/bugs", tags=["Bug Localization"], dependencies=[Depends(get_current_user)])


class BugReportRequest(BaseModel):
    repo_id: str
    error_report: str
    top_k: int = 5
    spectrum_scores: Optional[Dict[str, float]] = None
    coverage_records: Optional[List[Dict[str, Any]]] = None
    total_failing: Optional[int] = 0
    total_passing: Optional[int] = 0


@router.post("/localize")
def localize_bug(req: BugReportRequest, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_for_user(req.repo_id, current_user)
    store = repo_data["store"]
    embedder = repo_data["embedder"]
    graph = repo_data["graph"]

    cov_records = None
    if req.coverage_records:
        from core.bug_localizer import CoverageRecord
        cov_records = [
            CoverageRecord(
                element_id=r.get("element_id", ""),
                failing_exec_count=r.get("failing_exec_count", 0),
                passing_exec_count=r.get("passing_exec_count", 0),
            )
            for r in req.coverage_records
            if "element_id" in r
        ]

    localizer = AdvancedBugLocalizer(
        store=store,
        embedder=embedder,
        graph=graph,
        spectrum_scores=req.spectrum_scores,
        coverage_records=cov_records,
        total_failing=req.total_failing or 0,
        total_passing=req.total_passing or 0,
    )
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
    get_repo_for_user(repo_id, current_user)
    if current_user.role == "admin":
        return db_manager.find("bug_reports", {"repo_id": repo_id})
    return db_manager.find("bug_reports", {"repo_id": repo_id, "user_id": current_user.id})
