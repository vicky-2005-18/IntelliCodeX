"""
Repository-aware RAG query engine with Graph-Augmented Sub-Graph Context Expansion.
Ties together: VectorStore (retrieval) + Dependency & Call Graphs (structural expansion) + LLM (reasoning).
"""
from typing import List, Optional, Dict, Tuple, Set, Any
import networkx as nx
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.chunker import CodeChunk

SYSTEM_PROMPT = """You are IntelliCodeX, an AI assistant with access to a specific \
software repository via retrieved code context and dependency graphs. Answer using ONLY \
the provided context. Cite file paths and line numbers for every claim. If the context is \
insufficient, say so explicitly instead of guessing."""


def expand_retrieved_context(
    results: List[Tuple[CodeChunk, float]],
    dep_graph: Optional[nx.DiGraph] = None,
    call_graph: Optional[nx.DiGraph] = None,
    store_chunks: Optional[List[CodeChunk]] = None
) -> List[Dict]:
    """
    Graph-Augmented Sub-Graph Expansion:
    Enriches top-K vector search results by expanding caller/callee relations from the Call Graph
    and file import links from the Dependency Graph.
    """
    seen_chunk_ids: Set[str] = {chunk.chunk_id for chunk, _ in results}
    expanded_list: List[Dict] = []

    # Map chunk IDs to CodeChunk objects for fast lookup
    chunk_map: Dict[str, CodeChunk] = {}
    if store_chunks:
        for c in store_chunks:
            chunk_map[c.chunk_id] = c

    # 1. Add direct vector search results
    for chunk, score in results:
        expanded_list.append({
            "chunk": chunk,
            "score": score,
            "reason": "Direct Vector Match",
            "is_expanded": False
        })

    # 2. Expand Call Graph relations (callers and callees of top-K chunks)
    if call_graph is not None:
        for chunk, score in results:
            if chunk.chunk_id not in call_graph:
                continue

            # Add caller function chunks
            predecessors = list(call_graph.predecessors(chunk.chunk_id))
            for caller_id in predecessors[:2]:  # Limit top 2 callers
                if caller_id not in seen_chunk_ids and caller_id in chunk_map:
                    seen_chunk_ids.add(caller_id)
                    expanded_list.append({
                        "chunk": chunk_map[caller_id],
                        "score": score * 0.8,
                        "reason": f"Caller of {chunk.name}",
                        "is_expanded": True
                    })

            # Add callee target chunks
            successors = list(call_graph.successors(chunk.chunk_id))
            for callee_id in successors[:2]:  # Limit top 2 callees
                if callee_id not in seen_chunk_ids and callee_id in chunk_map:
                    seen_chunk_ids.add(callee_id)
                    expanded_list.append({
                        "chunk": chunk_map[callee_id],
                        "score": score * 0.75,
                        "reason": f"Called by {chunk.name}",
                        "is_expanded": True
                    })

    # 3. Expand Dependency Graph relations (files imported by top-K files)
    if dep_graph is not None:
        for chunk, score in results:
            rel_file = chunk.file_path.replace("\\", "/")
            if rel_file in dep_graph:
                imported_files = [
                    v for u, v, data in dep_graph.out_edges(rel_file, data=True)
                    if data.get("internal", False)
                ]
                for imp_file in imported_files[:2]:
                    # Find first chunk in imported file
                    for c in chunk_map.values():
                        if c.file_path.replace("\\", "/") == imp_file and c.chunk_id not in seen_chunk_ids:
                            seen_chunk_ids.add(c.chunk_id)
                            expanded_list.append({
                                "chunk": c,
                                "score": score * 0.7,
                                "reason": f"Imported by {chunk.file_path}",
                                "is_expanded": True
                            })
                            break

    return expanded_list


def format_context(expanded_results: List[Any]) -> str:
    """Formats expanded code chunks into markdown code blocks for LLM prompt context."""
    blocks = []
    for item in expanded_results:
        if isinstance(item, tuple):
            chunk, score = item[0], item[1]
            reason = "Direct Match"
        elif isinstance(item, dict):
            chunk = item["chunk"]
            score = item.get("score", 0.0)
            reason = item.get("reason", "Context")
        else:
            continue

        header = f"### {chunk.file_path} :: {chunk.name} (lines {chunk.start_line}-{chunk.end_line}, relevance={score:.2f}, context={reason})"
        blocks.append(f"{header}\n```{chunk.language}\n{chunk.code}\n```")
    return "\n\n".join(blocks)


class QueryEngine:
    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm=None,
        dep_graph: Optional[nx.DiGraph] = None,
        call_graph: Optional[nx.DiGraph] = None
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.dep_graph = dep_graph
        self.call_graph = call_graph

    def retrieve(self, query: str, top_k: int = 5):
        query_vec = self.embedder.embed([query])[0]
        return self.store.search(query_vec, top_k=top_k)

    def retrieve_expanded(self, query: str, top_k: int = 5) -> List[Dict]:
        """Retrieves top-K vector matches and applies graph-augmented context expansion."""
        results = self.retrieve(query, top_k=top_k)
        store_chunks = getattr(self.store, "chunks", [])
        return expand_retrieved_context(
            results,
            dep_graph=self.dep_graph,
            call_graph=self.call_graph,
            store_chunks=store_chunks
        )

    def ask(self, question: str, top_k: int = 5) -> dict:
        expanded_results = self.retrieve_expanded(question, top_k=top_k)
        context = format_context(expanded_results)

        response = {
            "question": question,
            "retrieved_chunks": [
                {
                    "file": item["chunk"].file_path,
                    "name": item["chunk"].name,
                    "lines": f"{item['chunk'].start_line}-{item['chunk'].end_line}",
                    "score": item["score"],
                    "reason": item["reason"]
                }
                for item in expanded_results
            ],
        }

        if self.llm is None:
            relevant_items = [item for item in expanded_results if item["score"] > 0.001]
            if not relevant_items:
                response["answer"] = (
                    f"[Offline Mode] TF-IDF search found no direct code symbol matches for '{question}'.\n"
                    f"Tip: Search for specific functions, classes, or code keywords.\n"
                    f"To enable full natural language AI reasoning, switch backend via 'backend ollama'."
                )
            else:
                summary_lines = [f"[Offline Mode Summary] Found {len(relevant_items)} matching code references (with graph expansion):"]
                for item in relevant_items:
                    chunk = item["chunk"]
                    score = item["score"]
                    reason = item["reason"]
                    desc = f"  • {chunk.file_path} :: {chunk.name} (lines {chunk.start_line}-{chunk.end_line}, score={score:.3f}, context={reason})"
                    if chunk.docstring:
                        first_line = chunk.docstring.strip().splitlines()[0]
                        desc += f"\n    \"{first_line[:80]}\""
                    summary_lines.append(desc)
                summary_lines.append("\n(Switch to 'backend ollama' for AI-synthesized natural language explanations).")
                response["answer"] = "\n".join(summary_lines)
            return response

        prompt = f"Repository context:\n\n{context}\n\nQuestion: {question}\n\nAnswer:"
        response["answer"] = self.llm.generate(prompt, system=SYSTEM_PROMPT)
        return response

    def localize_bug(self, error_report: str, top_k: int = 5) -> dict:
        """Bug localization: treat error/stack trace as query and expand caller context graph."""
        return self.ask(
            f"Given this error report, identify the most likely root cause file(s) "
            f"and explain why:\n\n{error_report}",
            top_k=top_k,
        )
