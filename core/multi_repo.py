"""
Multi-Repository Reasoning & Namespaced Indexing Engine (REQ-FUT-08)
Enables cross-repository intelligence, multi-repo workspaces, namespaced chunk indexing,
fair per-repository candidate retrieval, cross-service contract discovery (HTTP/REST APIs,
shared data models), and federated RAG with explicit [repo_id:file_path:lines] citations.
"""
import copy
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Set, Tuple
import networkx as nx

from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder, TfidfEmbedder
from core.parser import SourceFile, walk_repository


@dataclass
class CrossRepoContract:
    producer_repo: str
    consumer_repo: str
    contract_type: str  # 'http_api', 'shared_model', 'rpc'
    endpoint_or_symbol: str
    producer_file: str
    consumer_file: str
    producer_line: int = 1
    consumer_line: int = 1
    producer_symbol: Optional[str] = None
    consumer_symbol: Optional[str] = None
    confidence: float = 0.95
    basis: str = "inferred_by_route_and_client_pattern"
    producer_citation: str = ""
    consumer_citation: str = ""

    def __post_init__(self):
        if not self.producer_citation:
            self.producer_citation = f"[{self.producer_repo}:{self.producer_file}:{self.producer_line}]"
        if not self.consumer_citation:
            self.consumer_citation = f"[{self.consumer_repo}:{self.consumer_file}:{self.consumer_line}]"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NamespacedChunk:
    repo_id: str
    chunk: CodeChunk
    namespaced_id: str = ""

    def __post_init__(self):
        if not self.namespaced_id:
            self.namespaced_id = f"{self.repo_id}::{self.chunk.chunk_id}"

    @property
    def file_path(self) -> str:
        return self.chunk.file_path

    @property
    def code(self) -> str:
        return self.chunk.code

    @property
    def name(self) -> str:
        return self.chunk.name

    @property
    def start_line(self) -> int:
        return self.chunk.start_line

    @property
    def end_line(self) -> int:
        return self.chunk.end_line

    @property
    def citation(self) -> str:
        return f"[{self.repo_id}:{self.file_path}:{self.start_line}-{self.end_line}]"


class MultiRepoWorkspace:
    """
    Manages a federated multi-repository workspace.
    Maintains isolated namespaced indexes per repo, prevents cross-repo chunk collisions,
    ensures fair per-repository candidate retrieval, discovers cross-repo contracts,
    and conducts grounded cross-repository impact analysis.
    """
    def __init__(self, workspace_id: str, embedder: Optional[BaseEmbedder] = None):
        self.workspace_id = workspace_id
        self.embedder = embedder or TfidfEmbedder(dim=32)
        self.repos: Dict[str, Dict[str, Any]] = {}
        self.federated_store: Optional[FaissVectorStore] = None
        self.namespaced_chunks: List[NamespacedChunk] = []
        self.contract_graph = nx.DiGraph()
        self.contracts: List[CrossRepoContract] = []

    def add_repository(
        self,
        repo_id: str,
        repo_path: Optional[str] = None,
        store: Optional[FaissVectorStore] = None,
        source_files: Optional[List[SourceFile]] = None,
        chunks: Optional[List[CodeChunk]] = None,
        snapshot_id: str = "current",
        is_stale: bool = False,
        stale_warning: Optional[str] = None,
    ):
        """Registers a repository into the multi-repo workspace."""
        if repo_path and not source_files:
            source_files = walk_repository(repo_path)

        rep_chunks: List[CodeChunk] = []
        if chunks:
            rep_chunks = chunks
        elif store and hasattr(store, "chunks"):
            rep_chunks = store.chunks
        elif source_files:
            from core.chunker import chunk_file
            for sf in source_files:
                rep_chunks.extend(chunk_file(sf))

        self.repos[repo_id] = {
            "repo_id": repo_id,
            "repo_path": repo_path,
            "store": store,
            "source_files": source_files or [],
            "chunks": rep_chunks,
            "snapshot_id": snapshot_id,
            "is_stale": is_stale,
            "stale_warning": stale_warning,
        }

        # Wrap chunks with repo namespace and guarantee unique namespaced chunk IDs
        for c in rep_chunks:
            # Clone chunk to avoid modifying original in single-repo cache
            cloned = copy.copy(c)
            nc = NamespacedChunk(repo_id=repo_id, chunk=cloned)
            # Ensure the underlying CodeChunk object also has the uniquely namespaced chunk_id
            cloned.chunk_id = nc.namespaced_id
            self.namespaced_chunks.append(nc)

        self._rebuild_federated_index()
        self.detect_cross_repo_contracts()

    def _rebuild_federated_index(self):
        """Builds a unified vector store across all namespaced repository chunks."""
        if not self.namespaced_chunks:
            dim = getattr(self.embedder, "dim", 32)
            self.federated_store = FaissVectorStore(dim=dim)
            return

        texts = [
            f"[{nc.repo_id}] {nc.chunk.file_path} {nc.chunk.name}\n{nc.chunk.as_embedding_text()}"
            for nc in self.namespaced_chunks
        ]
        underlying_chunks = [nc.chunk for nc in self.namespaced_chunks]
        vectors = self.embedder.embed(texts)
        dim = vectors.shape[1]
        self.federated_store = FaissVectorStore(dim=dim)
        self.federated_store.add(underlying_chunks, vectors)

    def detect_cross_repo_contracts(self) -> List[CrossRepoContract]:
        """
        Discovers cross-service contracts across repositories.
        Matches producer route definitions (@app.get('/api/...'), @router.post)
        against consumer HTTP client calls (requests.get('/api/...'), fetch, axios).
        """
        self.contracts.clear()
        self.contract_graph.clear()

        # 1. Discover producer endpoints: (repo_id, endpoint_path, file, line, symbol)
        producer_endpoints: List[Tuple[str, str, str, int, Optional[str]]] = []
        route_pattern = re.compile(
            r"""@(?:app|router|blueprint)\.(?:get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]""",
            re.IGNORECASE,
        )

        # 2. Discover consumer client invocations: (repo_id, endpoint_path, file, line, symbol)
        consumer_calls: List[Tuple[str, str, str, int, Optional[str]]] = []
        client_pattern = re.compile(
            r"""(?:requests|http|client)\.(?:get|post|put|delete|patch)\(\s*f?['"]([^'"]+)['"]""",
            re.IGNORECASE,
        )
        fetch_pattern = re.compile(
            r"""(?:fetch|axios(?:\.get|\.post)?)\(\s*f?['"]([^'"]+)['"]""",
            re.IGNORECASE,
        )

        for repo_id, rdata in self.repos.items():
            for sf in rdata.get("source_files", []):
                lines = sf.content.splitlines() if sf.content else []
                current_fn: Optional[str] = None
                for idx, line in enumerate(lines, start=1):
                    fn_match = re.match(r"""(?:def|async\s+def|function)\s+([a-zA-Z_]\w*)""", line.strip())
                    if fn_match:
                        current_fn = fn_match.group(1)

                    # Producer detection
                    for m in route_pattern.finditer(line):
                        ep = m.group(1).split("?")[0].rstrip("/")
                        if ep:
                            producer_endpoints.append((repo_id, ep, sf.rel_path, idx, current_fn))

                    # Consumer detection
                    for pat in (client_pattern, fetch_pattern):
                        for m in pat.finditer(line):
                            raw_url = m.group(1).split("?")[0].rstrip("/")
                            # Normalize e.g. "http://auth-service/api/v1/login" -> "/api/v1/login"
                            normalized_ep = re.sub(r"^https?://[^/]+", "", raw_url)
                            if normalized_ep.startswith("/"):
                                consumer_calls.append((repo_id, normalized_ep, sf.rel_path, idx, current_fn))

        # Match producer endpoints with consumer calls across different repos
        for prod_repo, prod_ep, prod_file, prod_line, prod_sym in producer_endpoints:
            for cons_repo, cons_ep, cons_file, cons_line, cons_sym in consumer_calls:
                if prod_repo != cons_repo and prod_ep == cons_ep:
                    contract = CrossRepoContract(
                        producer_repo=prod_repo,
                        consumer_repo=cons_repo,
                        contract_type="http_api",
                        endpoint_or_symbol=prod_ep,
                        producer_file=prod_file,
                        consumer_file=cons_file,
                        producer_line=prod_line,
                        consumer_line=cons_line,
                        producer_symbol=prod_sym,
                        consumer_symbol=cons_sym,
                        confidence=0.95,
                        basis="inferred_by_route_and_client_pattern",
                    )
                    self.contracts.append(contract)
                    self.contract_graph.add_edge(
                        cons_repo,
                        prod_repo,
                        endpoint=prod_ep,
                        consumer_file=cons_file,
                        producer_file=prod_file,
                    )

        return self.contracts

    def search(
        self,
        query: str,
        top_k: int = 5,
        repo_filter: Optional[List[str]] = None,
        balanced_across_repos: bool = True,
    ) -> List[Tuple[NamespacedChunk, float]]:
        """
        Federated dense semantic search across namespaced repository chunks.
        Prevents large repositories from starving smaller selected repositories
        by implementing balanced fair-share candidate allocation.
        """
        if not self.federated_store or not self.namespaced_chunks:
            return []

        # Determine target repositories
        target_repos = set(repo_filter) if repo_filter else set(self.repos.keys())
        if not target_repos:
            return []

        q_vec = self.embedder.embed([query])[0]
        # Query a larger pool from federated index to enable fair multi-repo allocation
        pool_size = max(top_k * 4, 20)
        raw_results = self.federated_store.search(q_vec, top_k=pool_size)

        # Build mapping of namespaced_id -> NamespacedChunk
        id_to_nc = {nc.namespaced_id: nc for nc in self.namespaced_chunks}

        # Filter by requested repositories
        scoped_matches: List[Tuple[NamespacedChunk, float]] = []
        repo_buckets: Dict[str, List[Tuple[NamespacedChunk, float]]] = {r: [] for r in target_repos}

        for chunk, score in raw_results:
            nc = id_to_nc.get(chunk.chunk_id)
            if nc and nc.repo_id in target_repos:
                scoped_matches.append((nc, score))
                repo_buckets[nc.repo_id].append((nc, score))

        if not balanced_across_repos or len(target_repos) <= 1:
            return scoped_matches[:top_k]

        # Fair Allocation: Ensure each target repository gets up to its fair share
        # of top slots if it has relevant chunks, preventing one large repo from starving others
        active_target_count = len([r for r, b in repo_buckets.items() if b])
        if active_target_count <= 1:
            return scoped_matches[:top_k]

        fair_quota = max(1, top_k // active_target_count)
        selected: List[Tuple[NamespacedChunk, float]] = []
        selected_ids: Set[str] = set()

        # Step 1: Guarantee fair representation from each target repository
        for r_id in target_repos:
            bucket = repo_buckets.get(r_id, [])
            for nc, score in bucket[:fair_quota]:
                if nc.namespaced_id not in selected_ids and len(selected) < top_k:
                    selected.append((nc, score))
                    selected_ids.add(nc.namespaced_id)

        # Step 2: Fill remaining capacity with globally highest-scoring unselected candidates
        if len(selected) < top_k:
            for nc, score in scoped_matches:
                if nc.namespaced_id not in selected_ids:
                    selected.append((nc, score))
                    selected_ids.add(nc.namespaced_id)
                    if len(selected) >= top_k:
                        break

        # Final sort by relevance score descending
        selected.sort(key=lambda x: x[1], reverse=True)
        return selected

    def analyze_endpoint_impact(self, query: str) -> Dict[str, Any]:
        """
        Analyzes cross-repository endpoint definitions, client invocations,
        and candidate files needing review if response fields change.
        """
        # Look for endpoint path in query or match discovered contracts
        matched_contracts = []
        for c in self.contracts:
            if c.endpoint_or_symbol.lower() in query.lower() or any(
                part in query.lower() for part in c.endpoint_or_symbol.strip("/").split("/") if len(part) > 2
            ):
                matched_contracts.append(c)

        # If no specific endpoint in query, consider all contracts in active repos
        if not matched_contracts and self.contracts:
            matched_contracts = list(self.contracts)

        producer_files = list(set(c.producer_file for c in matched_contracts))
        consumer_files = list(set(c.consumer_file for c in matched_contracts))
        candidate_review_files = sorted(list(set(producer_files + consumer_files)))

        disclaimer = (
            "Candidate impact analysis is based on static HTTP client URL and route pattern matches. "
            "Matching symbol names or endpoints alone do not prove runtime dependency, "
            "and this does not claim complete dynamic impact analysis."
        )

        return {
            "matched_contracts": [c.to_dict() for c in matched_contracts],
            "producer_files": producer_files,
            "consumer_files": consumer_files,
            "candidate_review_files": candidate_review_files,
            "disclaimer": disclaimer,
        }

    def ask(
        self,
        question: str,
        top_k: int = 5,
        repo_filter: Optional[List[str]] = None,
        llm: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Federated Cross-Repository RAG Q&A Engine.
        Synthesizes answers with explicit [repo_id:file_path:lines] citations,
        differentiates observed code facts from inferred contracts,
        and provides candidate impact analysis.
        """
        target_repos = list(repo_filter) if repo_filter else list(self.repos.keys())

        # Check for empty or unavailable repositories in target scope
        notices: List[str] = []
        for r_id in target_repos:
            r_data = self.repos.get(r_id)
            if not r_data or not r_data.get("chunks"):
                notices.append(f"Notice: Repository '{r_id}' has an empty index or yielded no indexed chunks.")

        retrieved = self.search(question, top_k=top_k, repo_filter=repo_filter, balanced_across_repos=True)

        # Context assembly across repositories
        context_chunks = []
        for nc, score in retrieved:
            citation = f"[{nc.repo_id}:{nc.file_path}:{nc.start_line}-{nc.end_line}]"
            context_chunks.append({
                "repo_id": nc.repo_id,
                "file": nc.file_path,
                "lines": f"{nc.start_line}-{nc.end_line}",
                "name": nc.name,
                "score": round(float(score), 3),
                "citation": citation,
                "code": nc.code,
            })

        # Relevant cross-repo contracts
        active_repos = set(nc.repo_id for nc, _ in retrieved)
        relevant_contracts = [
            c for c in self.contracts
            if (c.producer_repo in active_repos or c.consumer_repo in active_repos)
            or (c.producer_repo in target_repos and c.consumer_repo in target_repos)
        ]

        # Extract Observed Code Facts (Declarations and Call Sites)
        observed_endpoints = []
        observed_call_sites = []
        for c in relevant_contracts:
            observed_endpoints.append({
                "repo_id": c.producer_repo,
                "file": c.producer_file,
                "line": c.producer_line,
                "endpoint": c.endpoint_or_symbol,
                "symbol": c.producer_symbol,
                "citation": c.producer_citation,
            })
            observed_call_sites.append({
                "repo_id": c.consumer_repo,
                "file": c.consumer_file,
                "line": c.consumer_line,
                "endpoint": c.endpoint_or_symbol,
                "symbol": c.consumer_symbol,
                "citation": c.consumer_citation,
            })

        # Candidate Impact Analysis
        impact_info = self.analyze_endpoint_impact(question)

        # Per-Repository Snapshot Information
        snapshot_info = {}
        for r_id in target_repos:
            r_meta = self.repos.get(r_id, {})
            snapshot_info[r_id] = {
                "snapshot_id": r_meta.get("snapshot_id", "current"),
                "is_stale": r_meta.get("is_stale", False),
                "stale_warning": r_meta.get("stale_warning"),
            }

        # Deterministic Context Assembly (LLM-independent)
        assembled_context_lines = [
            f"=== Multi-Repository Scope ({len(target_repos)} repositories: {', '.join(target_repos)}) ===",
            "",
            "--- Observed Code Facts (Exact Static Citations) ---",
        ]
        if observed_endpoints:
            assembled_context_lines.append("Endpoint Definitions:")
            for ep in observed_endpoints:
                assembled_context_lines.append(f"  - Endpoint '{ep['endpoint']}' defined in {ep['citation']}")
        if observed_call_sites:
            assembled_context_lines.append("Client Call Sites:")
            for cs in observed_call_sites:
                assembled_context_lines.append(f"  - Client call to '{cs['endpoint']}' in {cs['citation']}")

        assembled_context_lines.append("")
        assembled_context_lines.append("--- Inferred Cross-Repository Relationships ---")
        if relevant_contracts:
            for c in relevant_contracts:
                assembled_context_lines.append(
                    f"  - Inferred HTTP API Contract: [{c.consumer_repo}] calls [{c.producer_repo}] via '{c.endpoint_or_symbol}' "
                    f"(Producer: {c.producer_citation}, Consumer: {c.consumer_citation}, Basis: {c.basis})"
                )
        else:
            assembled_context_lines.append("  - No matching cross-repository contracts detected.")

        assembled_context_lines.append("")
        assembled_context_lines.append("--- Candidate Review Files (Impact Boundary) ---")
        if impact_info["candidate_review_files"]:
            assembled_context_lines.append(f"  - Candidate files for review: {', '.join(impact_info['candidate_review_files'])}")
        assembled_context_lines.append(f"  - Caveat: {impact_info['disclaimer']}")

        assembled_context_lines.append("")
        assembled_context_lines.append("--- Retrieved Code Chunks ---")
        for chunk in context_chunks:
            assembled_context_lines.append(f"Citation: {chunk['citation']} (Score: {chunk['score']})")
            assembled_context_lines.append(chunk["code"])
            assembled_context_lines.append("")

        assembled_context = "\n".join(assembled_context_lines)

        # Generate or Synthesize Answer
        llm_status = "unavailable"
        answer = ""

        if llm and context_chunks:
            prompt = (
                "You are IntelliCodeX Multi-Repository Reasoning Assistant.\n"
                f"Question: {question}\n\n"
                f"{assembled_context}\n\n"
                "Provide a clear, factual answer to the question using the evidence above.\n"
                "Rules:\n"
                "1. State where the endpoint is defined with exact citation [repo_id:file_path:lines].\n"
                "2. State which client code uses it with exact citation [repo_id:file_path:lines].\n"
                "3. List candidate files that may need review if the response field changes.\n"
                "4. Explicitly distinguish observed code facts from inferred cross-repository relationships.\n"
                "5. Do NOT treat matching symbol names alone as proof of runtime dependency."
            )
            try:
                if hasattr(llm, "generate"):
                    answer = llm.generate(prompt, temperature=0.1)
                elif hasattr(llm, "ask"):
                    res_llm = llm.ask(prompt)
                    answer = res_llm if isinstance(res_llm, str) else res_llm.get("answer", str(res_llm))
                else:
                    answer = str(llm(prompt))
                llm_status = "generated"
            except Exception as e:
                notices.append(f"LLM inference encountered error ({e}); using deterministic synthesis.")
                llm_status = "deterministic_fallback"

        if not answer:
            # Deterministic structured synthesis directly answering the workflow questions
            def_lines = [f"{ep['citation']}" for ep in observed_endpoints]
            call_lines = [f"{cs['citation']}" for cs in observed_call_sites]
            review_files = impact_info.get("candidate_review_files", [])

            ans_parts = [
                f"### Cross-Repository Reasoning Findings",
                f"",
                f"**1. Endpoint Definition (Observed Code Fact)**:",
                f"- Defined in: {', '.join(def_lines) if def_lines else 'No exact producer definition found in queried repositories.'}",
                f"",
                f"**2. Consuming Client Code (Observed Code Fact)**:",
                f"- Invoked in: {', '.join(call_lines) if call_lines else 'No exact client invocations found in queried repositories.'}",
                f"",
                f"**3. Inferred Cross-Repository Relationship**:",
                f"- Relationship: Inferred HTTP API contract between consumer and producer based on matching route pattern (`basis: inferred_by_route_and_client_pattern`).",
                f"- Notice: Matching endpoint paths or symbol names represent candidate relationships, not static compilation facts.",
                f"",
                f"**4. Candidate Review Files If Response Field Changes**:",
                f"- Candidate files for review: {', '.join(f'`{f}`' for f in review_files) if review_files else 'None'}",
                f"- Boundary Notice: {impact_info['disclaimer']}",
            ]
            answer = "\n".join(ans_parts)

        return {
            "workspace_id": self.workspace_id,
            "question": question,
            "answer": answer,
            "participating_repositories": target_repos,
            "snapshot_info": snapshot_info,
            "observed_facts": {
                "endpoint_definitions": observed_endpoints,
                "client_call_sites": observed_call_sites,
                "retrieved_chunks": context_chunks,
            },
            "inferred_relationships": {
                "contracts": [c.to_dict() for c in relevant_contracts],
                "relationship_type": "inferred_http_contract",
            },
            "candidate_impact_analysis": impact_info,
            "notices": notices,
            "retrieved_chunks": context_chunks,
            "cross_repo_contracts": [c.to_dict() for c in relevant_contracts],
            "assembled_context": assembled_context,
            "confidence_score": round(min(0.95, 0.6 + 0.1 * len(context_chunks)), 2),
            "llm_status": llm_status,
        }
