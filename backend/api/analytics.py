"""
Repository Analytics API Router (Phase 5 & REQ-FUT-05)
Provides high-level stats, language distribution, health score, and security vulnerability scanning.
"""
import os
from fastapi import APIRouter, Depends, HTTPException
from backend.api.repos import get_repo_for_user
from backend.analytics import RepositoryAnalyticsEngine
from backend.auth import User, get_current_user
from backend.database import db_manager

router = APIRouter(prefix="/analytics", tags=["Repository Analytics"], dependencies=[Depends(get_current_user)])


@router.get("/{repo_id}/security")
@router.post("/{repo_id}/security")
def scan_repository_security(
    repo_id: str,
    threshold: str = "HIGH",
    policy: str = "strict",
    current_user: User = Depends(get_current_user),
):
    """
    Scans repository for static security vulnerabilities and hardcoded secrets (REQ-FUT-05).
    Enforces repository authorization & multi-tenant isolation via get_repo_for_user.
    Supports explicit policy: 'strict' (default) or 'secrets_only'.
    """
    repo_data = get_repo_for_user(repo_id, current_user)
    repo_dir = repo_data.get("repo_path") or repo_data.get("meta", {}).get("repo_path")
    if not repo_dir or not os.path.isdir(repo_dir):
        raise HTTPException(
            status_code=404,
            detail=f"Repository filesystem directory not found for '{repo_id}'",
        )

    from core.security_scanner import run_security_scan
    scan_result = run_security_scan(
        repo_dir,
        repo_root=repo_dir,
        severity_threshold=threshold.upper(),
        security_policy=policy,
    )
    return {
        "repo_id": repo_id,
        "scan_result": scan_result,
    }


@router.get("/{repo_id:path}")
def get_analytics(repo_id: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_for_user(repo_id, current_user)
    source_files = repo_data["source_files"]
    chunks = repo_data["store"].chunks
    graph = repo_data["graph"]

    bugs_count = len(db_manager.find("bug_reports", {"repo_id": repo_id}))
    query_count = len(db_manager.find("chat_history", {"repo_id": repo_id}))

    analytics_engine = RepositoryAnalyticsEngine()
    metrics = analytics_engine.compute_analytics(
        repo_id=repo_id,
        source_files=source_files,
        chunks=chunks,
        graph=graph,
        bugs_count=bugs_count,
        query_count=query_count,
    )

    return metrics
