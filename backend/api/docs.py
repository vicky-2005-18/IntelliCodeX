"""
Documentation Generator API Router (Phase 6)
Auto-generates Markdown READMEs, API docs, folder structures, and HTML/PDF formatted content.
"""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from backend.api.repos import get_repo_engine
from backend.documentation import DocumentationGenerator
from backend.auth import User, get_current_user

router = APIRouter(prefix="/docs", tags=["Documentation Generator"])


class DocGenRequest(BaseModel):
    repo_id: str
    format: str = "markdown"  # "markdown" | "html" | "pdf"


@router.post("/generate")
def generate_documentation(req: DocGenRequest, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(req.repo_id)
    source_files = repo_data["source_files"]
    chunks = repo_data["store"].chunks

    generator = DocumentationGenerator()
    readme_md = generator.generate_readme(req.repo_id, source_files, chunks)
    api_md = generator.generate_api_docs(chunks)

    full_md = f"{readme_md}\n\n---\n\n{api_md}"

    if req.format.lower() in ("html", "pdf"):
        html_doc = generator.export_to_pdf_html(full_md, title=f"{req.repo_id} Documentation")
        return Response(content=html_doc, media_type="text/html")

    return {
        "repo_id": req.repo_id,
        "format": "markdown",
        "readme": readme_md,
        "api_docs": api_md,
        "combined_markdown": full_md,
    }
