"""
Repository-aware RAG query engine.
Ties together: VectorStore (retrieval) + LLM (reasoning) = grounded answers
with citations to real files/lines, not hallucinated code.
"""
from typing import List, Optional
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.chunker import CodeChunk

SYSTEM_PROMPT = """You are IntelliCodeX, an AI assistant with access to a specific \
software repository via retrieved code context. Answer using ONLY the provided \
context. Cite file paths and line numbers for every claim. If the context is \
insufficient, say so explicitly instead of guessing."""


def format_context(results: List[tuple]) -> str:
    blocks = []
    for chunk, score in results:
        header = f"### {chunk.file_path} :: {chunk.name} (lines {chunk.start_line}-{chunk.end_line}, relevance={score:.2f})"
        blocks.append(f"{header}\n```{chunk.language}\n{chunk.code}\n```")
    return "\n\n".join(blocks)


class QueryEngine:
    def __init__(self, store: FaissVectorStore, embedder: BaseEmbedder, llm=None):
        self.store = store
        self.embedder = embedder
        self.llm = llm  # OllamaLLM instance; None = retrieval-only mode

    def retrieve(self, query: str, top_k: int = 5):
        query_vec = self.embedder.embed([query])[0]
        return self.store.search(query_vec, top_k=top_k)

    def ask(self, question: str, top_k: int = 5) -> dict:
        results = self.retrieve(question, top_k=top_k)
        context = format_context(results)

        response = {
            "question": question,
            "retrieved_chunks": [
                {"file": c.file_path, "name": c.name, "lines": f"{c.start_line}-{c.end_line}", "score": s}
                for c, s in results
            ],
        }

        if self.llm is None:
            relevant_chunks = [(c, s) for c, s in results if s > 0.001]
            if not relevant_chunks:
                response["answer"] = (
                    f"[Offline Mode] TF-IDF search found no direct code symbol matches for '{question}'.\n"
                    f"Tip: Search for specific functions, classes, or code keywords (e.g., 'session', 'cookies', 'authenticate', 'request').\n"
                    f"To enable full natural language AI reasoning, switch backend via 'backend ollama'."
                )
            else:
                summary_lines = [f"[Offline Mode Summary] Found {len(relevant_chunks)} matching code references:"]
                for chunk, score in relevant_chunks:
                    desc = f"  • {chunk.file_path} :: {chunk.name} (lines {chunk.start_line}-{chunk.end_line}, score={score:.3f})"
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
        """Bug localization: treat the error/stack trace itself as the query."""
        return self.ask(
            f"Given this error report, identify the most likely root cause file(s) "
            f"and explain why:\n\n{error_report}",
            top_k=top_k,
        )
