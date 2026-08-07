"""
Code Review & Commit Message API Router (Phases 14 & 15)
Performs automated code smell, security, complexity analysis, and generates commit messages.
"""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from backend.services import CodeReviewAssistant
from backend.auth import User, get_current_user

router = APIRouter(prefix="/review", tags=["Code Review Assistant"])


class FileReviewRequest(BaseModel):
    code_content: str
    file_path: str = "code.py"


class CommitMsgRequest(BaseModel):
    git_diff: str


@router.post("/analyze")
def analyze_code(req: FileReviewRequest, current_user: User = Depends(get_current_user)):
    assistant = CodeReviewAssistant()
    return assistant.analyze_file(req.code_content, req.file_path)


@router.post("/commit_message")
def generate_commit_message(req: CommitMsgRequest, current_user: User = Depends(get_current_user)):
    assistant = CodeReviewAssistant()
    message = assistant.generate_commit_message(req.git_diff)
    return {"commit_message": message, "git_diff": req.git_diff}
