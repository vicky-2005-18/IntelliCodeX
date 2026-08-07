"""
IntelliCodeX Local AI Server (FastAPI Bridge)
Bridges baseline legacy endpoints (/ingest, /query, /localize_bug, /dependencies)
to the modular enterprise backend while mounting all new /api routes.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict

# Import new enterprise app
from backend.main import app as enterprise_app
from backend.api.repos import ACTIVE_REPOS, IngestRequest, ingest_repo
from backend.api.chat import QueryRequest, ask_assistant
from backend.api.bugs import BugReportRequest, localize_bug
from backend.api.patches import GeneratePatchRequest, generate_patch
from core.dependency_graph import files_likely_affected_by

app = enterprise_app


# Backward-compatible legacy endpoints expected by Phase 1 specification:

@app.post("/ingest")
def legacy_ingest(req: IngestRequest):
    return ingest_repo(req, current_user=None)


@app.post("/query")
def legacy_query(req: QueryRequest):
    return ask_assistant(req, current_user=None)


@app.post("/localize_bug")
def legacy_localize_bug(req: BugReportRequest):
    return localize_bug(req, current_user=None)


@app.post("/generate_patch")
def legacy_generate_patch(req: GeneratePatchRequest):
    return generate_patch(req, current_user=None)


@app.get("/dependencies/{repo_id}/{file_path:path}")
def legacy_dependencies(repo_id: str, file_path: str):
    if repo_id not in ACTIVE_REPOS:
        # try loading repo engine
        from backend.api.repos import get_repo_engine
        get_repo_engine(repo_id)
    graph = ACTIVE_REPOS[repo_id]["graph"]
    return {"file": file_path, "depended_on_by": files_likely_affected_by(graph, file_path)}
