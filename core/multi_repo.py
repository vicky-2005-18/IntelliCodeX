"""
Multi-Repository Reasoning & Namespaced Indexing Engine (REQ-FUT-08)
Enables cross-repository intelligence, multi-repo workspaces, namespaced chunk indexing,
cross-service contract discovery (HTTP/REST APIs, shared data models), and federated RAG.
"""
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
    confidence: float = 0.9

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


class MultiRepoWorkspace:
    """
    Manages a federated multi-repository workspace.
    Maintains isolated namespaced indexes per repo and cross-repo contract graphs.
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
        }

        # Wrap chunks with repo namespace
        for c in rep_chunks:
            nc = NamespacedChunk(repo_id=repo_id, chunk=c)
            self.namespaced_chunks.append(nc)

        self._rebuild_federated_index()
        self.detect_cross_repo_contracts()

    def _rebuild_federated_index(self):
        """Builds a unified vector store across all namespaced repository chunks."""
        if not self.namespaced_chunks:
            dim = getattr(self.embedder, "dim", 32)
            self.federated_store = FaissVectorStore(dim=dim)
            return

        texts = [f"[{nc.repo_id}] {nc.chunk.as_embedding_text()}" for nc in self.namespaced_chunks]
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

        # 1. Discover producer endpoints: (repo_id, endpoint_path, file, line)
        producer_endpoints: List[Tuple[str, str, str, int]] = []
        route_pattern = re.compile(r"""@(?:app|router|blueprint)\.(?:get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]""", re.IGNORECASE)

        # 2. Discover consumer client invocations: (repo_id, endpoint_path, file, line)
        consumer_calls: List[Tuple[str, str, str, int]] = []
        client_pattern = re.compile(r"""(?:requests|http|client)\.(?:get|post|put|delete|patch)\(\s*f?['"]([^'"]+)['"]""", re.IGNORECASE)
        fetch_pattern = re.compile(r"""(?:fetch|axios(?:\.get|\.post)?)\(\s*f?['"]([^'"]+)['"]""", re.IGNORECASE)

        for repo_id, rdata in self.repos.items():
            for sf in rdata.get("source_files", []):
                for idx, line in enumerate(sf.content.splitlines(), start=1):
                    # Producer detection
                    for m in route_pattern.finditer(line):
                        ep = m.group(1).split("?")[0].rstrip("/")
                        if ep:
                            producer_endpoints.append((repo_id, ep, sf.rel_path, idx))

                    # Consumer detection
                    for pat in (client_pattern, fetch_pattern):
                        for m in pat.finditer(line):
                            raw_url = m.group(1).split("?")[0].rstrip("/")
                            # Normalize e.g. "http://auth-service/api/v1/login" -> "/api/v1/login"
                            normalized_ep = re.sub(r"^https?://[^/]+", "", raw_url)
                            if normalized_ep.startswith("/"):
                                consumer_calls.append((repo_id, normalized_ep, sf.rel_path, idx))

        # Match producer endpoints with consumer calls across different repos
        for prod_repo, prod_ep, prod_file, prod_line in producer_endpoints:
            for cons_repo, cons_ep, cons_file, cons_line in consumer_calls:
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
                        confidence=0.95,
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
    ) -> List[Tuple[NamespacedChunk, float]]:
        """Federated dense semantic search across namespaced repository chunks."""
        if not self.federated_store or not self.namespaced_chunks:
            return []

        q_vec = self.embedder.embed([query])[0]
        # Search a wider pool to allow repo filtering
        raw_results = self.federated_store.search(q_vec, top_k=top_k * 3)

        matched: List[Tuple[NamespacedChunk, float]] = []
        seen_ids = set()

        for chunk, score in raw_results:
            # Locate corresponding NamespacedChunk
            for nc in self.namespaced_chunks:
                if nc.chunk.chunk_id == chunk.chunk_id:
                    if repo_filter and nc.repo_id not in repo_filter:
                        continue
                    if nc.namespaced_id not in seen_ids:
                        seen_ids.add(nc.namespaced_id)
                        matched.append((nc, score))
                    break
            if len(matched) >= top_k:
                break

        return matched

    def ask(
        self,
        question: str,
        top_k: int = 5,
        repo_filter: Optional[List[str]] = None,
        llm: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Federated Cross-Repository RAG Q&A Engine.
        Synthesizes verified answers with explicit [repo_id:file_path:lines] citations.
        """
        retrieved = self.search(question, top_k=top_k, repo_filter=repo_filter)

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
            c.to_dict() for c in self.contracts
            if c.producer_repo in active_repos or c.consumer_repo in active_repos
        ]

        # Generate synthesized answer
        answer = ""
        if llm and hasattr(llm, "generate") and context_chunks:
            prompt_context = "\n\n".join(
                f"{c['citation']}\n{c['code']}" for c in context_chunks
            )
            contracts_summary = "\n".join(
                f"- Contract: `{c['consumer_repo']}` calls `{c['producer_repo']}` via `{c['endpoint_or_symbol']}`"
                for c in relevant_contracts
            )
            prompt = (
                f"You are IntelliCodeX Multi-Repository Reasoning Assistant.\n"
                f"Question: {question}\n\n"
                f"Cross-Repository Microservice Contracts:\n{contracts_summary or 'None detected.'}\n\n"
                f"Namespaced Multi-Repository Context:\n{prompt_context}\n\n"
                f"Provide a clear, precise explanation answering the question. "
                f"Always cite the exact repository and file in format [repo_id:file_path:lines]."
            )
            try:
                answer = llm.generate(prompt, temperature=0.1)
            except Exception as e:
                answer = f"Error generating cross-repo LLM answer: {e}"

        if not answer:
            # Deterministic fallback explanation
            participating_repos = sorted(list(set(c["repo_id"] for c in context_chunks)))
            contracts_desc = ""
            if relevant_contracts:
                contracts_desc = f" Verified {len(relevant_contracts)} shared microservice API contract(s)."

            answer = (
                f"Cross-repository analysis completed across {len(participating_repos)} repositories "
                f"({', '.join(participating_repos)}).{contracts_desc} "
                f"Retrieved {len(context_chunks)} relevant code contexts."
            )

        return {
            "workspace_id": self.workspace_id,
            "question": question,
            "answer": answer,
            "participating_repositories": list(self.repos.keys()),
            "retrieved_chunks": context_chunks,
            "cross_repo_contracts": relevant_contracts,
            "confidence_score": round(min(0.95, 0.6 + 0.1 * len(context_chunks)), 2),
        }
