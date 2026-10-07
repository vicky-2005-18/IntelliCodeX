"""
Query & Retrieval Provenance API Router
Provides authenticated, owner-scoped endpoint for explaining RAG retrieval pipelines.
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from backend.api.repos import get_repo_for_user, validate_repo_id
from backend.auth import User, get_current_user
from core.retrieval_trace import RetrievalTrace

router = APIRouter(prefix="/query", tags=["Query"], dependencies=[Depends(get_current_user)])


class ExplainRequest(BaseModel):
    repo_id: str
    question: str
    top_k: int = 5
    file_filter: Optional[str] = None
    no_answer: bool = False
    max_token_budget: int = 3000


@router.post("/explain")
def explain_query(req: ExplainRequest, current_user: User = Depends(get_current_user)):
    """
    Explains the retrieval and answer pipeline for a given question.
    Returns the complete RetrievalTrace as a JSON dictionary.
    Enforces repository owner scoping and RBAC.
    """
    valid_id = validate_repo_id(req.repo_id)
    repo_data = get_repo_for_user(valid_id, current_user)
    engine = repo_data["engine"]

    trace = RetrievalTrace()
    engine.ask(
        req.question,
        top_k=req.top_k,
        file_filter=req.file_filter,
        max_token_budget=req.max_token_budget,
        trace=trace,
        no_answer=req.no_answer,
    )
    return trace.to_dict()
