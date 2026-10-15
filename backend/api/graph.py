"""
Knowledge Graph & Dependency API Router (Phase 4 / REQ-FUT-07)
Provides:
- Knowledge graph entity queries with line citations, direction filters, and depth
- Shortest path resolution between code symbols
- Indexed entity enumeration filtered by symbol type
- Knowledge graph schema metadata with supported and unsupported relationships
- Cytoscape.js export, circular dependencies, and reverse dependency blast-radius
"""
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from backend.api.repos import get_repo_for_user
from backend.dependency_graph import (
    EnhancedDependencyGraph,
    SUPPORTED_RELATIONSHIPS,
    UNSUPPORTED_RELATIONSHIPS,
)
from backend.auth import User, get_current_user
from core.dependency_graph import files_likely_affected_by

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"], dependencies=[Depends(get_current_user)])


def _get_or_build_enhanced_graph(repo_data: Dict[str, Any]) -> EnhancedDependencyGraph:
    """Retrieves cached EnhancedDependencyGraph engine or builds and caches it."""
    engine = repo_data.get("enhanced_graph_engine")
    if engine is None:
        engine = EnhancedDependencyGraph()
        engine.build(
            repo_data.get("source_files", []),
            call_graph=repo_data.get("call_graph"),
        )
        repo_data["enhanced_graph_engine"] = engine
    return engine


@router.get("/{repo_id}/query")
def query_knowledge_graph(
    repo_id: str,
    entity: str = "",
    relationship: Optional[str] = None,
    direction: str = Query(default="both", pattern="^(both|incoming|outgoing)$"),
    depth: int = Query(default=1, ge=1, le=5),
    current_user: User = Depends(get_current_user),
):
    """
    REQ-FUT-07: Query the repository knowledge graph for a specific entity
    (file, class, method, function, external package, or endpoint) and its relationships.
    Returns entity attributes, incident relationships with line citations,
    and documented supported/unsupported relationships.
    """
    repo_data = get_repo_for_user(repo_id, current_user)
    if not entity:
        raise HTTPException(status_code=400, detail="Query parameter 'entity' is required.")
    enhanced_engine = _get_or_build_enhanced_graph(repo_data)
    result = enhanced_engine.query_entity(
        entity_id_or_name=entity,
        relationship=relationship,
        direction=direction,
        depth=depth,
    )
    if not result.get("found"):
        raise HTTPException(
            status_code=404,
            detail=f"Entity '{entity}' not found in knowledge graph for repository '{repo_id}'.",
        )
    result["repo_id"] = repo_id
    return result


@router.get("/{repo_id}/entities")
def list_knowledge_graph_entities(
    repo_id: str,
    type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
):
    """
    REQ-FUT-07: Lists code entities indexed in the repository knowledge graph,
    optionally filtered by type (file, class, method, function, external, api, database)
    and substring search.
    """
    repo_data = get_repo_for_user(repo_id, current_user)
    enhanced_engine = _get_or_build_enhanced_graph(repo_data)
    entities = enhanced_engine.list_entities(entity_type=type, search=search, limit=limit)
    return {
        "repo_id": repo_id,
        "total_returned": len(entities),
        "entities": entities,
    }


@router.get("/{repo_id}/path")
def find_knowledge_graph_path(
    repo_id: str,
    source: str = "",
    target: str = "",
    directed: bool = False,
    current_user: User = Depends(get_current_user),
):
    """
    REQ-FUT-07: Computes the shortest dependency or call path between two entities
    in the repository knowledge graph.
    """
    repo_data = get_repo_for_user(repo_id, current_user)
    if not source or not target:
        raise HTTPException(status_code=400, detail="Query parameters 'source' and 'target' are required.")
    enhanced_engine = _get_or_build_enhanced_graph(repo_data)
    result = enhanced_engine.find_path(source=source, target=target, directed=directed)
    if not result.get("found"):
        raise HTTPException(
            status_code=404,
            detail=result.get("error", f"Entities '{source}' or '{target}' not found in repository '{repo_id}'."),
        )
    result["repo_id"] = repo_id
    return result


@router.get("/{repo_id}/metadata")
def get_knowledge_graph_metadata(
    repo_id: str,
    current_user: User = Depends(get_current_user),
):
    """
    REQ-FUT-07: Returns knowledge graph statistics, supported vs unsupported
    relationship schemas, and cache invalidation / stale-graph boundaries.
    """
    repo_data = get_repo_for_user(repo_id, current_user)
    enhanced_engine = _get_or_build_enhanced_graph(repo_data)
    metadata = enhanced_engine.get_metadata()
    metadata["repo_id"] = repo_id
    return metadata


@router.get("/{repo_id}/blast_radius/{file_path:path}")
def get_blast_radius(repo_id: str, file_path: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_for_user(repo_id, current_user)
    graph = repo_data["graph"]
    affected = files_likely_affected_by(graph, file_path)
    return {
        "repo_id": repo_id,
        "changed_file": file_path,
        "affected_files": affected,
        "total_affected": len(affected),
    }


@router.get("/{repo_id}/architecture-optimization")
@router.get("/{repo_id}/optimize")
def get_architecture_optimization(
    repo_id: str,
    high_coupling_threshold: int = Query(default=5, ge=2, le=50),
    complexity_threshold: int = Query(default=80, ge=10, le=500),
    include_llm_advisory: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
):
    """
    REQ-FUT-06: Architecture Optimization Endpoint.
    Analyzes dependency graph for circular dependencies, God-component bottlenecks,
    and complex components. Returns grounded refactoring recommendations and decoupling diffs.
    """
    repo_data = get_repo_for_user(repo_id, current_user)
    source_files = repo_data.get("source_files", [])

    enhanced_engine = _get_or_build_enhanced_graph(repo_data)

    meta = repo_data.get("meta", {})
    snapshot_id = meta.get("commit_hash") or meta.get("snapshot_id") or "live_working_copy"
    is_stale = repo_data.get("graph_is_stale", False)
    stale_warning = "Watched filesystem changes have occurred since this graph was built." if is_stale else None

    # LLM usage: only evaluate advisory if explicitly requested, otherwise remain strictly deterministic
    llm = None
    if include_llm_advisory:
        engine_obj = repo_data.get("engine")
        if engine_obj and hasattr(engine_obj, "llm"):
            llm = engine_obj.llm

    from core.architecture_optimizer import ArchitectureOptimizer
    optimizer = ArchitectureOptimizer(
        high_coupling_threshold=high_coupling_threshold,
        complexity_lines_threshold=complexity_threshold,
    )
    report = optimizer.analyze(
        dep_graph=enhanced_engine.graph,
        source_files=source_files,
        llm=llm,
        repo_id=repo_id,
        snapshot_id=snapshot_id,
        is_stale=is_stale,
        stale_warning=stale_warning,
    )
    res = report.to_dict()
    res["repo_id"] = repo_id
    return res


@router.get("/{repo_id:path}")
def get_graph(repo_id: str, current_user: User = Depends(get_current_user)):
    repo_data = get_repo_for_user(repo_id, current_user)
    enhanced_engine = _get_or_build_enhanced_graph(repo_data)

    cytoscape_data = enhanced_engine.export_cytoscape()
    circular_cycles = enhanced_engine.detect_circular_dependencies()

    return {
        "repo_id": repo_id,
        "nodes_count": len(cytoscape_data["nodes"]),
        "edges_count": len(cytoscape_data["edges"]),
        "circular_dependencies": circular_cycles,
        "cytoscape": cytoscape_data,
    }
