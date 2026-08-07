"""
Dependency Graph API Router (Phase 4)
Returns Cytoscape.js visual graph elements, circular dependencies, and reverse dependency blast-radius.
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from backend.api.repos import get_repo_engine
from backend.dependency_graph import EnhancedDependencyGraph
from backend.auth import User, get_current_user
from core.dependency_graph import files_likely_affected_by

router = APIRouter(prefix="/graph", tags=["Dependency Graph"])


@router.get("/{repo_id:path}")
def get_graph(repo_id: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(repo_id)
    source_files = repo_data["source_files"]

    enhanced_engine = EnhancedDependencyGraph()
    enhanced_engine.build(source_files)

    cytoscape_data = enhanced_engine.export_cytoscape()
    circular_cycles = enhanced_engine.detect_circular_dependencies()

    return {
        "repo_id": repo_id,
        "nodes_count": len(cytoscape_data["nodes"]),
        "edges_count": len(cytoscape_data["edges"]),
        "circular_dependencies": circular_cycles,
        "cytoscape": cytoscape_data,
    }


@router.get("/{repo_id}/blast_radius/{file_path:path}")
def get_blast_radius(repo_id: str, file_path: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_engine(repo_id)
    graph = repo_data["graph"]
    affected = files_likely_affected_by(graph, file_path)
    return {
        "repo_id": repo_id,
        "changed_file": file_path,
        "affected_files": affected,
        "total_affected": len(affected),
    }
