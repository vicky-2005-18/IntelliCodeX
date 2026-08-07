"""
Repository Analytics API Router (Phase 5)
Provides high-level stats, language distribution, health score, and component counts.
"""
from fastapi import APIRouter, Depends
from backend.api.repos import get_repo_engine
from backend.analytics import RepositoryAnalyticsEngine
from backend.auth import User, get_current_user
from backend.database import db_manager

router = APIRouter(prefix="/analytics", tags=["Repository Analytics"])


@router.get("/{repo_id:path}")
def get_analytics(repo_id: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(repo_id)
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
