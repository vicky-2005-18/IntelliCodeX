"""
Repository AI Assistant Router (Phase 3)
Handles structural queries, JWT verification lookups, unused code scans,
and architecture questions with confidence scoring and chat history persistence.
"""
import time
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from backend.api.repos import get_repo_engine
from backend.services.assistant_engine import AssistantEngine
from backend.auth import User, get_current_user
from backend.database import db_manager

router = APIRouter(prefix="/chat", tags=["Repository Assistant"])


class QueryRequest(BaseModel):
    repo_id: str
    question: str
    top_k: int = 5


@router.post("/ask")
def ask_assistant(req: QueryRequest, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(req.repo_id)

    assistant = AssistantEngine(
        store=repo_data["store"],
        embedder=repo_data["embedder"],
        llm=repo_data["engine"].llm,
        graph=repo_data["graph"],
    )
    response = assistant.ask(req.question, top_k=req.top_k)

    result = {
        "repo_id": req.repo_id,
        "question": req.question,
        "answer": response.get("answer", ""),
        "intent": response.get("intent", "general"),
        "retrieved_chunks": response.get("retrieved_chunks", []),
        "relevant_files": response.get("relevant_files", []),
        "functions": response.get("functions", []),
        "code_snippets": response.get("code_snippets", []),
        "dependency_relationships": response.get("dependency_relationships", []),
        "confidence_score": response.get("confidence_score", 0.0),
        "unused_files_detected": response.get("unused_files_detected", []),
        "architecture_summary": response.get("architecture_summary"),
        "timestamp": time.time(),
    }

    db_manager.insert("chat_history", {
        "repo_id": req.repo_id,
        "user_id": current_user.id,
        "question": req.question,
        "answer": response.get("answer", ""),
        "intent": response.get("intent"),
        "confidence_score": result["confidence_score"],
        "timestamp": time.time(),
    })

    return result


@router.get("/history/{repo_id}")
def get_chat_history(repo_id: str, current_user: User = Depends(get_current_user)):
    return db_manager.find("chat_history", {"repo_id": repo_id})
