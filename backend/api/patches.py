"""
Patch Generator API Router (Phase 1)
Generates AI context-aware code patches, outputs Git diffs, confidence scores,
validates patches, and handles developer approval / application workflows.
"""
import re
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from backend.api.repos import get_repo_engine, get_repo_for_user
from backend.patch_generator import PatchEngine
from backend.auth import User, get_current_user, require_role
from backend.database import db_manager

router = APIRouter(prefix="/patches", tags=["Patch Generation Engine"], dependencies=[Depends(get_current_user)])


class GeneratePatchRequest(BaseModel):
    repo_id: str
    error_report: str = Field(..., min_length=3, description="Bug report or stack trace")
    target_file: Optional[str] = None
    verify_in_sandbox: bool = False
    test_command: Optional[str] = None
    max_iterations: int = Field(3, ge=1, le=5, description="Max repair loop iterations")


class PatchApprovalRequest(BaseModel):
    patch_id: str
    status: str = Field(..., description="'approved' | 'rejected' | 'applied'")
    manual_edit: Optional[str] = Field(None, description="Developer-edited patch content")
    security_policy: Optional[str] = Field(None, description="'strict' | 'secrets_only'")


@router.post("/generate")
def generate_patch(req: GeneratePatchRequest, current_user: User = Depends(get_current_user)):
    """
    Generate an AI-powered patch from a bug report or stack trace.
    Returns original code, suggested patch, git diff, explanation, and confidence score.
    Supports autonomous multi-turn repair loop in sandbox when verify_in_sandbox is True.
    """
    repo_data = get_repo_for_user(req.repo_id, current_user)
    is_admin = (current_user.role == "admin")

    engine = PatchEngine(
        store=repo_data["store"],
        embedder=repo_data["embedder"],
        llm=repo_data["engine"].llm,
        graph=repo_data.get("graph"),
        repo_path=repo_data["meta"].get("repo_path"),
        is_admin=is_admin,
        allow_local_sandbox=is_admin,  # Admin can run local sandbox if configured
    )
    return engine.generate_patch(
        repo_id=req.repo_id,
        error_report=req.error_report,
        target_file=req.target_file,
        verify_in_sandbox=req.verify_in_sandbox,
        test_command=req.test_command,
        max_iterations=req.max_iterations,
        owner_id=current_user.id,
    )


@router.post("/approve")
@router.post("/apply")
def approve_patch(req: PatchApprovalRequest, current_user: User = Depends(get_current_user)):
    """Approve, reject, or apply a generated patch. Requires patch owner, repo owner, or admin."""
    if req.status not in ("approved", "rejected", "applied"):
        raise HTTPException(
            status_code=400,
            detail="Status must be 'approved', 'rejected', or 'applied'.",
        )

    record = db_manager.find_one("generated_patches", {"patch_id": req.patch_id})
    if not record:
        raise HTTPException(status_code=404, detail=f"Patch ID '{req.patch_id}' not found.")

    # Check authorization: patch owner, repository owner, or admin
    repo_meta = db_manager.find_one("repositories", {"repo_id": record["repo_id"]})
    patch_owner = record.get("owner_id")
    repo_owner = repo_meta.get("owner_id") if repo_meta else None

    if current_user.role != "admin":
        if current_user.id != patch_owner and current_user.id != repo_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the repository owner, patch owner, or an administrator can approve or apply patches.",
            )

    repo_data = get_repo_engine(record["repo_id"], user=current_user)
    engine = PatchEngine(
        store=repo_data["store"],
        embedder=repo_data["embedder"],
        llm=repo_data["engine"].llm,
        graph=repo_data.get("graph"),
        repo_path=repo_data["meta"].get("repo_path"),
        is_admin=(current_user.role == "admin"),
        allow_local_sandbox=False  # API mode: local sandbox disabled by default
    )

    updated = engine.update_patch_status(
        req.patch_id,
        req.status,
        req.manual_edit,
        user=current_user.id,
        security_policy=req.security_policy,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Patch ID '{req.patch_id}' not found.")

    if req.status == "applied" and updated.get("apply_result", {}).get("success") is False:
        err_msg = updated["apply_result"].get("message") or updated["apply_result"].get("error") or "Unknown error"
        raise HTTPException(
            status_code=400,
            detail=f"Patch application failed: {err_msg}",
        )

    return updated


@router.get("/list/{repo_id}")
def list_patches(repo_id: str, current_user: User = Depends(get_current_user)):
    """List all generated patches for a repository, newest first."""
    get_repo_for_user(repo_id, current_user)
    if current_user.role == "admin":
        patches = db_manager.find("generated_patches", {"repo_id": repo_id})
    else:
        patches = db_manager.find("generated_patches", {"repo_id": repo_id, "owner_id": current_user.id})
    return sorted(patches, key=lambda p: p.get("created_at", 0), reverse=True)


from core.self_improving import global_experience_bank


class IngestExperienceRequest(BaseModel):
    error_type: str = Field(default="UnknownError", max_length=64)
    error_description: str = Field(default="", max_length=1000)
    original_code: str = Field(default="", max_length=5000)
    fixed_code: str = Field(default="", max_length=5000)
    explanation: str = Field(default="", max_length=1500)
    source: str = "manual"
    language: str = "python"
    repo_id: Optional[str] = None


@router.get("/experiences")
def get_repair_experiences(error_type: Optional[str] = None, repo_id: Optional[str] = None, current_user: User = Depends(get_current_user)):
    """Retrieves learned self-improving repair patterns and memory bank analytics (REQ-FUT-10)."""
    if repo_id:
        get_repo_for_user(repo_id, current_user)
    stats = global_experience_bank.get_stats(repo_id=repo_id)
    shots = global_experience_bank.retrieve_few_shots(error_type=error_type, repo_id=repo_id, limit=20)
    return {
        "stats": stats,
        "experiences": [s.to_dict() for s in shots],
    }


@router.post("/experiences")
def record_repair_experience(req: IngestExperienceRequest, current_user: User = Depends(get_current_user)):
    """Ingests a verified bug-fix pattern into the self-improving experience bank (REQ-FUT-10)."""
    # 1. Authorization check: must be active registered user
    if not current_user or not current_user.id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    # 2. Check repo authorization if repo_id provided
    if req.repo_id:
        get_repo_for_user(req.repo_id, current_user)

    # 3. Identifier validation
    if not re.match(r"^[A-Za-z0-9_.-]+$", req.error_type):
        raise HTTPException(status_code=400, detail="Invalid error_type identifier format.")

    # 4. Content validation
    if not req.original_code or not req.fixed_code:
        raise HTTPException(status_code=400, detail="original_code and fixed_code are required.")

    # 5. Syntax validation for python code
    if req.language.lower() == "python":
        import ast
        try:
            ast.parse(req.fixed_code)
        except SyntaxError as e:
            raise HTTPException(status_code=400, detail=f"Fixed code contains syntax errors: {e}")

    exp = global_experience_bank.record_success(
        error_type=req.error_type,
        error_description=req.error_description,
        original_code=req.original_code,
        fixed_code=req.fixed_code,
        explanation=req.explanation,
        source=req.source,
        language=req.language,
        test_verified=False,
        developer_approved=True,
        repo_id=req.repo_id,
        is_public=False if req.repo_id else True,
        event_id=f"manual:{current_user.id}:{uuid.uuid4().hex[:6]}",
    )
    return exp.to_dict()
