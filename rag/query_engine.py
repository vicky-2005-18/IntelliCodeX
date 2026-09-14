"""
Repository-aware RAG query engine with Graph-Augmented Sub-Graph Context Expansion,
Multi-Turn Dialogue Memory, Token Budgeting, System Personas, and Token Streaming.
"""
from typing import List, Optional, Dict, Tuple, Set, Any, Generator
import networkx as nx
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.chunker import CodeChunk


PERSONAS: Dict[str, str] = {
    "general": (
        "You are IntelliCodeX, an AI code assistant with access to a specific software repository "
        "via retrieved code context and dependency graphs. Answer using ONLY the provided context. "
        "Cite file paths and line numbers for every claim. If the context is insufficient, say so explicitly."
    ),
    "security": (
        "You are IntelliCodeX Security Auditor. Analyze the provided repository context strictly for security "
        "vulnerabilities, injection risks, authentication flaws, and unsafe data practices. Highlight risks "
        "and recommend remediation with exact file paths and line references."
    ),
    "reviewer": (
        "You are IntelliCodeX Code Reviewer. Analyze code quality, readability, modularity, and clean code "
        "principles in the retrieved context. Provide constructive refactoring recommendations with file citations."
    ),
    "refactor": (
        "You are IntelliCodeX Architecture & Refactoring Specialist. Analyze module dependencies, caller-callee "
        "couplings, and suggest clean design pattern improvements for the retrieved code."
    ),
    "fixer": (
        "You are IntelliCodeX Automated Bug Fixer. Analyze error reports and code context to identify "
        "root causes and suggest minimal, correct code fixes."
    ),
}

DEFAULT_SYSTEM_PROMPT = PERSONAS["general"]


class ConversationMemory:
    """Manages multi-turn conversation dialogue history for RAG queries."""

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.turns: List[Tuple[str, str]] = []  # [(user_query, assistant_response)]

    def add_turn(self, query: str, response: str):
        self.turns.append((query, response))
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def clear(self):
        self.turns.clear()

    def format_history(self) -> str:
        if not self.turns:
            return ""
        history_lines = ["--- Conversation History ---"]
        for idx, (q, r) in enumerate(self.turns, start=1):
            history_lines.append(f"Turn {idx} User: {q}")
            r_snippet = r[:250].replace("\n", " ") + ("..." if len(r) > 250 else "")
            history_lines.append(f"Turn {idx} Assistant: {r_snippet}")
        return "\n".join(history_lines)

    def __len__(self):
        return len(self.turns)


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


def format_context(expanded_results: List[Any], max_token_budget: int = 3000) -> str:
    """Formats expanded code chunks into markdown code blocks with dynamic token budgeting."""
    blocks = []
    char_budget = max_token_budget * 4
    current_chars = 0

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
        block = f"{header}\n```{chunk.language}\n{chunk.code}\n```"

        if current_chars + len(block) > char_budget:
            remaining_chars = max(200, char_budget - current_chars)
            truncated_code = chunk.code[:remaining_chars] + "\n... [truncated due to token budget]"
            block = f"{header}\n```{chunk.language}\n{truncated_code}\n```"
            blocks.append(block)
            break

        blocks.append(block)
        current_chars += len(block)

    return "\n\n".join(blocks)


class QueryEngine:
    """
    Multi-Turn Repository-Aware Query Engine.
    """

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm=None,
        dep_graph: Optional[nx.DiGraph] = None,
        call_graph: Optional[nx.DiGraph] = None,
        max_turns: int = 5,
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.dep_graph = dep_graph
        self.call_graph = call_graph
        self.memory = ConversationMemory(max_turns=max_turns)
        self.active_persona = "general"
        self.system_prompt = PERSONAS["general"]

    def set_persona(self, persona_name: str) -> str:
        """Sets the active AI persona and system prompt."""
        key = persona_name.lower().strip()
        if key not in PERSONAS:
            raise ValueError(f"Unknown persona '{persona_name}'. Available: {list(PERSONAS.keys())}")
        self.active_persona = key
        self.system_prompt = PERSONAS[key]
        return self.active_persona

    def set_model(self, model_name: str):
        """Switches the active LLM model if supported."""
        if self.llm and hasattr(self.llm, "set_model"):
            self.llm.set_model(model_name)

    def clear_memory(self):
        """Clears current conversation history."""
        self.memory.clear()

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

    def ask(
        self,
        question: str,
        top_k: int = 5,
        use_memory: bool = True,
        max_token_budget: int = 3000
    ) -> dict:
        """Performs RAG query answering with context expansion, conversation history, and persona reasoning."""
        expanded_results = self.retrieve_expanded(question, top_k=top_k)
        context = format_context(expanded_results, max_token_budget=max_token_budget)

        response = {
            "question": question,
            "persona": self.active_persona,
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
                ans = (
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
                ans = "\n".join(summary_lines)

            response["answer"] = ans
            if use_memory:
                self.memory.add_turn(question, ans)
            return response

        history_str = self.memory.format_history() if (use_memory and len(self.memory) > 0) else ""
        prompt_parts = []
        if history_str:
            prompt_parts.append(history_str)
        prompt_parts.append(f"Repository context:\n\n{context}")
        prompt_parts.append(f"Question: {question}\n\nAnswer:")

        prompt = "\n\n".join(prompt_parts)
        answer = self.llm.generate(prompt, system=self.system_prompt)

        response["answer"] = answer
        if use_memory:
            self.memory.add_turn(question, answer)
        return response

    def stream_ask(
        self,
        question: str,
        top_k: int = 5,
        use_memory: bool = True,
        max_token_budget: int = 3000
    ) -> Generator[str, None, None]:
        """Streams AI response tokens in real-time while updating conversation memory."""
        expanded_results = self.retrieve_expanded(question, top_k=top_k)
        context = format_context(expanded_results, max_token_budget=max_token_budget)

        if self.llm is None or not hasattr(self.llm, "stream_generate"):
            resp = self.ask(question, top_k=top_k, use_memory=use_memory, max_token_budget=max_token_budget)
            yield resp["answer"]
            return

        history_str = self.memory.format_history() if (use_memory and len(self.memory) > 0) else ""
        prompt_parts = []
        if history_str:
            prompt_parts.append(history_str)
        prompt_parts.append(f"Repository context:\n\n{context}")
        prompt_parts.append(f"Question: {question}\n\nAnswer:")

        prompt = "\n\n".join(prompt_parts)
        accumulated_tokens = []

        for token in self.llm.stream_generate(prompt, system=self.system_prompt):
            accumulated_tokens.append(token)
            yield token

        full_answer = "".join(accumulated_tokens)
        if use_memory:
            self.memory.add_turn(question, full_answer)

    def localize_bug(self, error_report: str, top_k: int = 5) -> dict:
        """Bug localization: treat error/stack trace as query and expand caller context graph."""
        return self.ask(
            f"Given this error report, identify the most likely root cause file(s) "
            f"and explain why:\n\n{error_report}",
            top_k=top_k,
        )
