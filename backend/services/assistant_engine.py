"""
Repository AI Assistant Engine (Phase 3)
Enhances RAG chat with query intent classification, keyword boosting,
dependency relationship extraction, and structured response formatting.
"""
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx

from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.chunker import CodeChunk
from rag.query_engine import format_context, SYSTEM_PROMPT


class QueryIntent(str, Enum):
    AUTH_FLOW = "auth_flow"
    JWT = "jwt_verification"
    LOGIN = "login"
    ARCHITECTURE = "architecture"
    FUNCTION_EXPLAIN = "function_explain"
    UNUSED_CODE = "unused_code"
    GENERAL = "general"


INTENT_KEYWORDS: Dict[QueryIntent, List[str]] = {
    QueryIntent.AUTH_FLOW: ["authentication", "auth flow", "auth mechanism", "how does auth"],
    QueryIntent.JWT: ["jwt", "token verification", "bearer token", "json web token"],
    QueryIntent.LOGIN: ["login", "sign in", "signin", "log in"],
    QueryIntent.ARCHITECTURE: ["architecture", "structure", "overview", "how is the project organized"],
    QueryIntent.FUNCTION_EXPLAIN: ["explain this function", "what does", "how does this function", "explain function"],
    QueryIntent.UNUSED_CODE: ["unused", "dead code", "unreferenced", "not imported"],
}


class AssistantEngine:
    """
    Enterprise repository assistant that combines:
    - Intent-aware retrieval boosting
    - RAG context assembly with citations
    - Dependency graph relationship extraction
    - Confidence scoring
    """

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm=None,
        graph: Optional[nx.DiGraph] = None,
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.graph = graph or nx.DiGraph()

    def ask(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        intent = self._classify_intent(question)
        results = self._retrieve_with_boosting(question, intent, top_k)
        context = format_context(results)

        relevant_files = list({c.file_path for c, _ in results})
        functions = [
            {"file": c.file_path, "name": c.name, "lines": f"{c.start_line}-{c.end_line}", "kind": c.kind}
            for c, _ in results
        ]
        code_snippets = [
            {
                "file": c.file_path,
                "name": c.name,
                "lines": f"{c.start_line}-{c.end_line}",
                "code": c.code,
                "score": round(float(s), 3),
            }
            for c, s in results
        ]
        dependency_relationships = self._extract_dependencies(relevant_files)
        confidence_score = self._compute_confidence(results, intent)

        response: Dict[str, Any] = {
            "question": question,
            "intent": intent.value,
            "retrieved_chunks": [
                {
                    "file": c.file_path,
                    "name": c.name,
                    "lines": f"{c.start_line}-{c.end_line}",
                    "score": round(float(s), 3),
                }
                for c, s in results
            ],
            "relevant_files": relevant_files,
            "functions": functions,
            "code_snippets": code_snippets,
            "dependency_relationships": dependency_relationships,
            "confidence_score": confidence_score,
        }

        # Intent-specific enrichments
        if intent == QueryIntent.UNUSED_CODE:
            unused = self._find_unused_files()
            response["unused_files_detected"] = unused[:15]
            response["answer"] = self._format_unused_answer(unused)
            return response

        if intent == QueryIntent.ARCHITECTURE:
            response["architecture_summary"] = self._architecture_summary()
            if self.llm is None:
                response["answer"] = response["architecture_summary"]
                return response

        if self.llm is None:
            response["answer"] = (
                "(No LLM configured — retrieval-only mode. "
                "See code_snippets and retrieved_chunks for context.)"
            )
            return response

        prompt = self._build_prompt(question, context, intent, dependency_relationships)
        response["answer"] = self.llm.generate(prompt, system=SYSTEM_PROMPT)
        return response

    def _classify_intent(self, question: str) -> QueryIntent:
        q_lower = question.lower()
        for intent, keywords in INTENT_KEYWORDS.items():
            if any(kw in q_lower for kw in keywords):
                return intent
        if re.search(r"explain\s+\w+", q_lower):
            return QueryIntent.FUNCTION_EXPLAIN
        return QueryIntent.GENERAL

    def _retrieve_with_boosting(
        self, question: str, intent: QueryIntent, top_k: int
    ) -> List[Tuple[CodeChunk, float]]:
        query_vec = self.embedder.embed([question])[0]
        raw_results = self.store.search(query_vec, top_k=top_k * 3)

        boost_terms = self._boost_terms_for_intent(intent, question)
        scored: List[Tuple[CodeChunk, float]] = []

        for chunk, score in raw_results:
            boosted = float(score)
            chunk_text = f"{chunk.file_path} {chunk.name} {chunk.code}".lower()
            for term in boost_terms:
                if term in chunk_text:
                    boosted = min(1.0, boosted + 0.08)
            scored.append((chunk, boosted))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _boost_terms_for_intent(self, intent: QueryIntent, question: str) -> List[str]:
        base = {
            QueryIntent.AUTH_FLOW: ["auth", "authenticate", "session", "middleware"],
            QueryIntent.JWT: ["jwt", "token", "decode", "verify", "bearer"],
            QueryIntent.LOGIN: ["login", "password", "credential", "signin"],
            QueryIntent.ARCHITECTURE: ["main", "router", "config", "app", "service"],
            QueryIntent.FUNCTION_EXPLAIN: [],
            QueryIntent.UNUSED_CODE: [],
            QueryIntent.GENERAL: [],
        }.get(intent, [])

        # Extract quoted identifiers from question for function explain queries
        quoted = re.findall(r"`([^`]+)`|'([^']+)'|\"([^\"]+)\"", question)
        identifiers = [g for group in quoted for g in group if g]
        return base + [i.lower() for i in identifiers]

    def _extract_dependencies(self, files: List[str]) -> List[Dict[str, str]]:
        relationships: List[Dict[str, str]] = []
        seen: set = set()

        for file_path in files:
            if file_path not in self.graph:
                continue
            for succ in self.graph.successors(file_path):
                rel = self.graph.edges.get((file_path, succ), {})
                relationship = rel.get("relationship", "depends_on")
                key = (file_path, str(succ), relationship)
                if key not in seen:
                    seen.add(key)
                    relationships.append({
                        "source": file_path,
                        "target": str(succ),
                        "relationship": relationship,
                    })
            for pred in self.graph.predecessors(file_path):
                rel = self.graph.edges.get((pred, file_path), {})
                relationship = rel.get("relationship", "referenced_by")
                key = (str(pred), file_path, relationship)
                if key not in seen:
                    seen.add(key)
                    relationships.append({
                        "source": str(pred),
                        "target": file_path,
                        "relationship": relationship,
                    })

        return relationships[:20]

    def _find_unused_files(self) -> List[str]:
        in_degrees = dict(self.graph.in_degree())
        return [
            node for node, deg in in_degrees.items()
            if deg == 0
            and self.graph.nodes.get(node, {}).get("type") == "file"
            and not str(node).startswith("ext:")
        ]

    def _format_unused_answer(self, unused: List[str]) -> str:
        if not unused:
            return "No unreferenced files detected in the dependency graph."
        preview = ", ".join(unused[:8])
        suffix = f" (and {len(unused) - 8} more)" if len(unused) > 8 else ""
        return (
            f"Found {len(unused)} file(s) with zero inbound import references: "
            f"{preview}{suffix}. These may be entry points, tests, or genuinely unused code."
        )

    def _architecture_summary(self) -> str:
        file_nodes = [
            n for n, d in self.graph.nodes(data=True) if d.get("type") == "file"
        ]
        ext_nodes = [
            n for n, d in self.graph.nodes(data=True) if d.get("external")
        ]
        languages: Dict[str, int] = {}
        for n in file_nodes:
            lang = self.graph.nodes[n].get("language", "unknown")
            languages[lang] = languages.get(lang, 0) + 1

        lang_summary = ", ".join(f"{k}: {v}" for k, v in sorted(languages.items()))
        return (
            f"Repository contains {len(file_nodes)} source files across "
            f"{len(languages)} language(s) ({lang_summary}). "
            f"External dependencies: {len(ext_nodes)}. "
            f"Total graph edges: {self.graph.number_of_edges()}."
        )

    def _compute_confidence(
        self, results: List[Tuple[CodeChunk, float]], intent: QueryIntent
    ) -> float:
        if not results:
            return 0.2
        avg_score = sum(s for _, s in results) / len(results)
        intent_bonus = 0.1 if intent != QueryIntent.GENERAL else 0.0
        return round(min(0.98, max(0.35, avg_score + 0.12 + intent_bonus)), 3)

    def _build_prompt(
        self,
        question: str,
        context: str,
        intent: QueryIntent,
        dependencies: List[Dict[str, str]],
    ) -> str:
        dep_text = ""
        if dependencies:
            dep_lines = [
                f"  - {d['source']} --[{d['relationship']}]--> {d['target']}"
                for d in dependencies[:10]
            ]
            dep_text = "\nDependency relationships:\n" + "\n".join(dep_lines) + "\n"

        intent_hint = {
            QueryIntent.AUTH_FLOW: "Focus on the authentication flow step-by-step.",
            QueryIntent.JWT: "Identify where JWT tokens are created, verified, and decoded.",
            QueryIntent.LOGIN: "Explain the login endpoint, validation, and session handling.",
            QueryIntent.ARCHITECTURE: "Provide a high-level architecture overview.",
            QueryIntent.FUNCTION_EXPLAIN: "Explain the function logic line-by-line with citations.",
            QueryIntent.UNUSED_CODE: "List potentially unused files and why.",
            QueryIntent.GENERAL: "",
        }.get(intent, "")

        return (
            f"Repository context:\n\n{context}\n"
            f"{dep_text}\n"
            f"Question: {question}\n"
            f"{intent_hint}\n"
            f"Answer with file paths, line numbers, and code references:"
        )
