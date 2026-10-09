"""
Repository-aware RAG query engine with Graph-Augmented Sub-Graph Context Expansion,
Multi-Turn Dialogue Memory, Token Budgeting, System Personas, and Token Streaming.
"""
import os
import time
from collections import defaultdict
from typing import List, Optional, Dict, Tuple, Set, Any, Generator
import networkx as nx
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder
from core.chunker import CodeChunk
from core.lexical_index import BM25Index
from core.static_checks import run_static_checks, run_static_checks_for_chunk

# Debug flag for prompt inspection
DEBUG_PROMPT = os.getenv("INTELLICODEX_DEBUG_PROMPT", "0") == "1"


PERSONAS: Dict[str, str] = {
    "general": (
        "You are IntelliCodeX, an AI code assistant with access to a specific software repository "
        "via retrieved code context and dependency graphs. Answer using ONLY the provided context. "
        "When asked about issues or bugs, identify ONLY actual bugs that exist in the code - do not hallucinate or invent issues. "
        "If no bugs are found, clearly state that the code has no issues. "
        "Cite file paths and line numbers for every claim. "
        "If the context is insufficient, say so explicitly."
    ),
    "security": (
        "You are IntelliCodeX Security Auditor. Analyze the provided repository context strictly for security "
        "vulnerabilities, injection risks, authentication flaws, and unsafe data practices. Highlight risks "
        "and recommend remediation with exact file paths and line references."
    ),
    "reviewer": (
        "You are IntelliCodeX Code Reviewer. Analyze code quality, readability, modularity, and clean code "
        "principles in the retrieved context. You MUST identify and list ALL issues found — do not stop at "
        "the first issue. Number each issue clearly (Issue 1, Issue 2, etc.) and provide constructive "
        "refactoring recommendations with exact file paths and line references for every issue found."
    ),
    "refactor": (
        "You are IntelliCodeX Architecture & Refactoring Specialist. Analyze module dependencies, caller-callee "
        "couplings, and suggest clean design pattern improvements for the retrieved code."
    ),
    "fixer": (
        "You are IntelliCodeX Automated Bug Fixer. Analyze error reports and code context to identify "
        "ONLY actual bugs that exist in the code - do not hallucinate or invent issues. "
        "If no bugs are found, clearly state that the code has no issues. "
        "Number each bug found (Bug 1, Bug 2, etc.), explain the root cause, and suggest a minimal correct fix."
    ),
}

DEFAULT_SYSTEM_PROMPT = PERSONAS["general"]
SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT

QA_SYSTEM_PROMPT = (
    "You are IntelliCodeX, an AI code assistant for software repositories. "
    "Answer the user's question accurately using ONLY the provided repository context. "
    "Cite relevant file paths and line numbers for your explanation. "
    "If the context does not contain enough information to answer, state that clearly."
)


def strip_qa_scaffolding(text: str) -> str:
    """Strips '### Function / Docstring/intent / Code' scaffolding from chunk text or history in Q&A mode."""
    if not text:
        return ""
    import re
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r'^###\s*Function\b', stripped, re.IGNORECASE):
            continue
        if re.match(r'^(?:\d+\.\s*)?Docstring/intent:\s*.*$', stripped, re.IGNORECASE):
            continue
        if re.match(r'^(?:\d+\.\s*)?Code:\s*$', stripped, re.IGNORECASE):
            continue
        if re.match(r'^(?:\d+\.\s*)?Analysis:\s*.*$', stripped, re.IGNORECASE):
            continue
        if re.match(r'^(?:\d+\.\s*)?Answer\s+(?:MATCH|MISMATCH)\b.*$', stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def partition_sources(answer: str, candidate_chunks: List[Any]) -> Tuple[List[Any], List[Any]]:
    """
    Partitions candidate chunks into:
    1. Relied-on chunks: chunks whose symbol, file:line, or distinctive code appears in the answer.
    2. Other retrieved context: the remaining chunks.
    """
    if not answer or not candidate_chunks:
        return [], candidate_chunks

    import re
    relied = []
    other = []

    answer_clean = answer.split("Sources:")[0] if "Sources:" in answer else answer

    for item in candidate_chunks:
        chunk = item[0] if isinstance(item, tuple) else (item.get("chunk") if isinstance(item, dict) else item)
        if not chunk or not getattr(chunk, "file_path", None):
            continue

        is_relied = False
        # 1. Symbol name appears in answer (symbol length >= 2)
        symbol = getattr(chunk, "name", "") or ""
        if symbol and symbol != "—" and len(symbol) >= 2:
            if re.search(rf"\b{re.escape(symbol)}\b", answer_clean):
                is_relied = True

        # 2. File:line appears in answer
        if not is_relied:
            fp = chunk.file_path
            base_fp = os.path.basename(fp)
            s_line = str(chunk.start_line)
            e_line = str(chunk.end_line)
            if f"{fp}:{s_line}" in answer_clean or f"{base_fp}:{s_line}" in answer_clean:
                is_relied = True
            elif f"{s_line}-{e_line}" in answer_clean and (fp in answer_clean or base_fp in answer_clean):
                is_relied = True
            elif fp in answer_clean or base_fp in answer_clean:
                for l_num in (s_line, e_line):
                    if re.search(rf"\bline\s+{l_num}\b", answer_clean, re.IGNORECASE):
                        is_relied = True
                        break

        # 3. Distinctive code from chunk appears in answer
        if not is_relied and getattr(chunk, "code", None):
            code_lines = [line.strip() for line in chunk.code.splitlines()]
            for line in code_lines:
                if len(line) >= 12 and not line.startswith(("#", "//", "/*", "*", "import ", "from ", "def ", "class ", "return None")):
                    if line in answer_clean:
                        is_relied = True
                        break

        if is_relied:
            relied.append(item)
        else:
            other.append(item)

    return relied, other


class ConversationMemory:
    """Manages multi-turn conversation dialogue history for RAG queries."""

    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self.turns: List[Tuple[str, str]] = []  # [(user_query, assistant_response)]
        self.turn_files: List[Set[str]] = []

    def add_turn(self, query: str, response: str, files: Optional[Set[str]] = None):
        self.turns.append((query, response))
        self.turn_files.append(set(files) if files else set())
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]
            self.turn_files = self.turn_files[-self.max_turns:]

    def clear(self):
        self.turns.clear()
        self.turn_files.clear()

    def is_topic_shifted(self, current_files: Set[str]) -> bool:
        """Detect if the newly retrieved context diverged completely from recent turns."""
        if not self.turns or not current_files:
            return False
        for prev_files in reversed(self.turn_files):
            if prev_files:
                if not (current_files & prev_files):
                    return True
                return False
        return False

    def is_code_analysis_question(self, query: str) -> bool:
        """Detect if the query is a code analysis/bug-finding question."""
        code_analysis_keywords = [
            "issue", "bug", "error", "problem", "fix", "debug",
            "wrong", "incorrect", "mistake", "analyze", "analyse", "review",
            "explain", "check", "find", "look", "inspect",
        ]
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in code_analysis_keywords)

    def format_history(self, is_analysis: bool = False) -> str:
        """Format conversation history. For analysis questions, only include user queries."""
        if not self.turns:
            return ""
        
        if is_analysis:
            # For code analysis, only include user questions to avoid contamination
            history_lines = ["--- Previous Questions ---"]
            for idx, (q, _) in enumerate(self.turns, start=1):
                history_lines.append(f"Q{idx}: {q}")
        else:
            # Normal conversation: include both user and assistant
            history_lines = [
                "--- Conversation History (Context only — never let history outweigh or override the retrieved code context below) ---"
            ]
            for idx, (q, r) in enumerate(self.turns, start=1):
                history_lines.append(f"Turn {idx} User: {q}")
                r_clean = strip_qa_scaffolding(r)
                r_snippet = r_clean[:250].replace("\n", " ") + ("..." if len(r_clean) > 250 else "")
                history_lines.append(f"Turn {idx} Assistant: {r_snippet}")
        
        return "\n".join(history_lines)

    def __len__(self):
        return len(self.turns)


def reciprocal_rank_fusion(
    ranked_lists: List[List[Any]],
    weights: Optional[List[float]] = None,
    k: int = 60,
    top_k: int = 5,
    list_names: Optional[List[str]] = None,
    include_reason: bool = False,
    trace: Optional[Any] = None,
) -> List[Any]:
    """
    Combines multiple ranked search results using Reciprocal Rank Fusion (RRF):
    RRF_score(d) = sum_{m in M} (w_m / (k + rank_m(d)))

    where rank_m(d) is the 1-based rank of document d in ranking m.
    Documents appearing across multiple retrieval algorithms receive additive boosts.
    """
    if not ranked_lists:
        return []

    if weights is None:
        weights = [1.0] * len(ranked_lists)
    if list_names is None:
        list_names = [f"Ranker_{i+1}" for i in range(len(ranked_lists))]

    chunk_map: Dict[str, CodeChunk] = {}
    scores: Dict[str, float] = defaultdict(float)
    matched_sources: Dict[str, Set[str]] = defaultdict(set)
    rank_by_source: Dict[str, Dict[str, int]] = defaultdict(dict)

    for rank_idx, r_list in enumerate(ranked_lists):
        w = weights[rank_idx] if rank_idx < len(weights) else 1.0
        name = list_names[rank_idx] if rank_idx < len(list_names) else f"Ranker_{rank_idx+1}"
        for rank, item in enumerate(r_list, start=1):
            chunk = item[0]
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            scores[cid] += w / (k + rank)
            matched_sources[cid].add(name)
            rank_by_source[name][cid] = rank

    # Sort descending by fused RRF score
    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    if trace is not None:
        from core.retrieval_trace import FusedHit
        for cid, score in sorted_items:
            chunk = chunk_map[cid]
            bm25_r = rank_by_source.get("BM25", {}).get(cid)
            dense_r = rank_by_source.get("Dense", {}).get(cid)
            trace.fused_hits.append(
                FusedHit(
                    chunk.chunk_id,
                    chunk.file_path,
                    chunk.name or "",
                    chunk.start_line,
                    chunk.end_line,
                    round(score, 5),
                    bm25_r,
                    dense_r,
                    round(score, 5),
                )
            )
            trace.chunk_codes[chunk.chunk_id] = chunk.code

    fused_results = []
    for cid, score in sorted_items:
        chunk = chunk_map[cid]
        sources = matched_sources[cid]
        if len(sources) > 1:
            reason = f"Hybrid ({' + '.join(sorted(sources))} Match)"
        elif "BM25" in sources:
            reason = "BM25 Lexical Match"
        elif "Dense" in sources:
            reason = "Direct Vector Match"
        else:
            reason = f"{next(iter(sources))} Match"

        if include_reason:
            fused_results.append((chunk, round(score, 5), reason))
        else:
            fused_results.append((chunk, round(score, 5)))

    return fused_results


def expand_retrieved_context(
    results: List[Any],
    dep_graph: Optional[nx.DiGraph] = None,
    call_graph: Optional[nx.DiGraph] = None,
    store_chunks: Optional[List[CodeChunk]] = None,
    trace: Optional[Any] = None,
) -> List[Dict]:
    """
    Graph-Augmented Sub-Graph Expansion:
    Enriches top-K search results by expanding caller/callee relations from the Call Graph
    and file import links from the Dependency Graph.
    """
    t_exp_start = time.perf_counter()
    seen_chunk_ids: Set[str] = {item[0].chunk_id for item in results}
    expanded_list: List[Dict] = []

    # Map chunk IDs to CodeChunk objects for fast O(1) lookup
    chunk_map: Dict[str, CodeChunk] = {}
    # Fix 3: Pre-build file→chunks index for O(1) dep expansion (replaces O(n) inner scan)
    file_to_chunks: Dict[str, List[CodeChunk]] = {}
    if store_chunks:
        for c in store_chunks:
            chunk_map[c.chunk_id] = c
            key = c.file_path.replace("\\", "/")
            file_to_chunks.setdefault(key, []).append(c)

    # 1. Add direct search results
    for item in results:
        chunk = item[0]
        score = item[1]
        reason = item[2] if len(item) > 2 else "Direct Match"
        expanded_list.append({
            "chunk": chunk,
            "score": score,
            "reason": reason,
            "is_expanded": False
        })

    # 2. Expand Call Graph relations (callers and callees of top-K chunks)
    if call_graph is not None:
        for item in results:
            chunk, score = item[0], item[1]
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
                    if trace is not None:
                        from core.retrieval_trace import GraphAddition
                        trace.graph_additions.append(GraphAddition(caller_id, "caller", chunk.chunk_id))
                        trace.chunk_codes[caller_id] = chunk_map[caller_id].code

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
                    if trace is not None:
                        from core.retrieval_trace import GraphAddition
                        trace.graph_additions.append(GraphAddition(callee_id, "callee", chunk.chunk_id))
                        trace.chunk_codes[callee_id] = chunk_map[callee_id].code

    # 3. Expand Dependency Graph relations — O(1) per imported file via pre-built index
    if dep_graph is not None:
        for item in results:
            chunk, score = item[0], item[1]
            rel_file = chunk.file_path.replace("\\", "/")
            if rel_file in dep_graph:
                imported_files = [
                    v for u, v, data in dep_graph.out_edges(rel_file, data=True)
                    if data.get("internal", False)
                ]
                for imp_file in imported_files[:2]:
                    for c in file_to_chunks.get(imp_file, []):
                        if c.chunk_id not in seen_chunk_ids:
                            seen_chunk_ids.add(c.chunk_id)
                            expanded_list.append({
                                "chunk": c,
                                "score": score * 0.7,
                                "reason": f"Imported by {chunk.file_path}",
                                "is_expanded": True
                            })
                            if trace is not None:
                                from core.retrieval_trace import GraphAddition
                                trace.graph_additions.append(GraphAddition(c.chunk_id, "import", chunk.chunk_id))
                                trace.chunk_codes[c.chunk_id] = c.code
                            break

    if trace is not None:
        trace.timings_ms["expand"] = round((time.perf_counter() - t_exp_start) * 1000, 2)

    return expanded_list


def format_context(expanded_results: List[Any], max_token_budget: int = 3000, trace: Optional[Any] = None) -> str:
    """Formats expanded code chunks into contiguous line-numbered blocks per file."""
    from collections import defaultdict
    
    # Candidate chunk list for budget accounting
    all_candidates: List[CodeChunk] = []
    seen_cand_ids: Set[str] = set()
    for item in expanded_results:
        chunk_obj = item[0] if isinstance(item, tuple) else (item.get("chunk") if isinstance(item, dict) else None)
        if chunk_obj and chunk_obj.chunk_id not in seen_cand_ids:
            seen_cand_ids.add(chunk_obj.chunk_id)
            all_candidates.append(chunk_obj)
            if trace is not None:
                trace.chunk_codes[chunk_obj.chunk_id] = chunk_obj.code

    # Group chunks by file, tracking highest retrieval score per file
    file_chunks = defaultdict(list)
    file_max_score = defaultdict(float)
    for item in expanded_results:
        if isinstance(item, tuple):
            chunk, score = item[0], item[1]
        elif isinstance(item, dict):
            chunk = item["chunk"]
            score = item.get("score", 0.0)
        else:
            continue
        file_chunks[chunk.file_path].append(chunk)
        if score > file_max_score[chunk.file_path]:
            file_max_score[chunk.file_path] = score
    
    # For each file, merge chunks into contiguous line-numbered blocks
    blocks = []
    char_budget = max_token_budget * 4
    current_chars = 0
    included_chunk_ids: List[str] = []
    
    # Sort files by relevance score descending so top-ranked chunks get precedence in token budget
    for file_path in sorted(file_chunks.keys(), key=lambda fp: file_max_score[fp], reverse=True):
        chunks = file_chunks[file_path]
        
        # Sort chunks by start line
        chunks.sort(key=lambda c: c.start_line)
        
        # Merge overlapping/adjacent chunks
        merged_lines = {}
        for chunk in chunks:
            lines = chunk.code.splitlines()
            for offset, line in enumerate(lines):
                actual_line_num = chunk.start_line + offset
                if actual_line_num not in merged_lines:
                    merged_lines[actual_line_num] = line
        
        # Build line-numbered block
        code_lines = []
        for line_num in sorted(merged_lines.keys()):
            line = merged_lines[line_num]
            code_lines.append(f"  {line_num:3d} | {line}")
        
        if not code_lines:
            continue
        
        block_text = f"### File: {file_path}\n```python\n" + "\n".join(code_lines) + "\n```"
        
        if current_chars + len(block_text) > char_budget:
            remaining_chars = max(200, char_budget - current_chars)
            truncated = block_text[:remaining_chars] + "\n... [truncated due to token budget]"
            blocks.append(truncated)
            break
        
        for c in chunks:
            if c.chunk_id not in included_chunk_ids:
                included_chunk_ids.append(c.chunk_id)
        blocks.append(block_text)
        current_chars += len(block_text)
    
    final_context = "\n\n".join(blocks)

    if trace is not None:
        dropped_chunk_ids = [c.chunk_id for c in all_candidates if c.chunk_id not in included_chunk_ids]
        used_tokens = min(max_token_budget, max(0, len(final_context) // 4))
        trace.budget.max_tokens = max_token_budget
        trace.budget.used_tokens = used_tokens
        trace.budget.included_chunk_ids = list(included_chunk_ids)
        trace.budget.dropped_chunk_ids = list(dropped_chunk_ids)

    return final_context



class QueryEngine:
    """
    Multi-Turn Repository-Aware Query Engine with Hybrid RRF Search.
    """

    def __init__(
        self,
        store: FaissVectorStore,
        embedder: BaseEmbedder,
        llm=None,
        dep_graph: Optional[nx.DiGraph] = None,
        call_graph: Optional[nx.DiGraph] = None,
        max_turns: int = 5,
        lexical_index: Optional[BM25Index] = None,
        hybrid_search: bool = True,
        rrf_k: int = 60,
        repo_path: Optional[str] = None,
    ):
        self.store = store
        self.embedder = embedder
        self.llm = llm
        self.dep_graph = dep_graph
        self.call_graph = call_graph
        self.repo_path = repo_path
        self.memory = ConversationMemory(max_turns=max_turns)
        self.active_persona = "general"
        self.system_prompt = PERSONAS["general"]
        self.hybrid_search = hybrid_search
        self.rrf_k = rrf_k
        self.runtime_findings = []  # Store runtime findings for merging

        if lexical_index is not None:
            self.lexical_index = lexical_index
        elif hasattr(store, "chunks") and store.chunks:
            self.lexical_index = BM25Index(store.chunks)
        else:
            self.lexical_index = None

    def toggle_hybrid(self, enabled: Optional[bool] = None) -> bool:
        """Toggles or explicitly sets the active hybrid search state."""
        if enabled is not None:
            self.hybrid_search = bool(enabled)
        else:
            self.hybrid_search = not self.hybrid_search
        return self.hybrid_search

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

    def retrieve(self, query: str, top_k: int = 5, file_filter: Optional[str] = None, trace: Optional[Any] = None) -> List[Tuple[CodeChunk, float]]:
        """Retrieves top-K matches using Hybrid Search (RRF) or pure Dense Vector Search."""
        import re
        mention_match = re.search(r'@([\w\-.\/]+)', query)
        if mention_match and not file_filter:
            file_filter = mention_match.group(1)

        clean_query = re.sub(r'@[\w\-.\/]+', ' ', query).strip()
        clean_query = re.sub(r'\s+', ' ', clean_query)
        effective_query = clean_query if clean_query else query

        store_chunks = getattr(self.store, "chunks", [])
        allowed_chunks = None
        if file_filter:
            f = file_filter.replace("\\", "/").lower()
            allowed_chunks = [c for c in store_chunks if f in c.file_path.replace("\\", "/").lower() or f in os.path.basename(c.file_path).lower()]
            if not allowed_chunks:
                return []
            allowed_ids = {c.chunk_id for c in allowed_chunks}
        else:
            allowed_ids = None

        if self.hybrid_search and self.lexical_index is not None and len(self.lexical_index) > 0:
            candidate_k = max(top_k * 4, 20, len(store_chunks) if allowed_ids else 20)
            t0 = time.perf_counter()
            query_vec = self.embedder.embed([effective_query])[0]
            t_embed = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            dense_results = self.store.search(query_vec, top_k=candidate_k)
            if allowed_ids is not None:
                dense_results = [(c, s) for c, s in dense_results if c.chunk_id in allowed_ids]
            t_dense = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            bm25_results = self.lexical_index.search(effective_query, top_k=candidate_k)
            if allowed_ids is not None:
                bm25_results = [(c, s) for c, s in bm25_results if c.chunk_id in allowed_ids]
            t_bm25 = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            if dense_results or bm25_results:
                results = reciprocal_rank_fusion(
                    [dense_results, bm25_results],
                    list_names=["Dense", "BM25"],
                    k=self.rrf_k,
                    top_k=top_k,
                    include_reason=False,
                    trace=trace,
                )
            elif allowed_chunks:
                results = [(c, 1.0) for c in allowed_chunks[:top_k]]
            else:
                results = []
            t_fuse = (time.perf_counter() - t0) * 1000

            if trace is not None:
                from core.retrieval_trace import RetrievalHit
                trace.timings_ms["embed"] = round(t_embed, 2)
                trace.timings_ms["dense"] = round(t_dense, 2)
                trace.timings_ms["bm25"] = round(t_bm25, 2)
                trace.timings_ms["fuse"] = round(t_fuse, 2)
                trace.bm25_hits = [
                    RetrievalHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s))
                    for c, s in bm25_results[:top_k]
                ]
                trace.dense_hits = [
                    RetrievalHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s))
                    for c, s in dense_results[:top_k]
                ]
                for c, _ in bm25_results[:top_k]:
                    trace.chunk_codes[c.chunk_id] = c.code
                for c, _ in dense_results[:top_k]:
                    trace.chunk_codes[c.chunk_id] = c.code
        else:
            candidate_k = max(top_k, len(store_chunks) if allowed_ids else top_k)
            t0 = time.perf_counter()
            query_vec = self.embedder.embed([effective_query])[0]
            t_embed = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            dense_results = self.store.search(query_vec, top_k=candidate_k)
            if allowed_ids is not None:
                dense_results = [(c, s) for c, s in dense_results if c.chunk_id in allowed_ids]
            t_dense = (time.perf_counter() - t0) * 1000

            if dense_results:
                results = dense_results[:top_k]
            elif allowed_chunks:
                results = [(c, 1.0) for c in allowed_chunks[:top_k]]
            else:
                results = []

            if trace is not None:
                from core.retrieval_trace import RetrievalHit, FusedHit
                trace.timings_ms["embed"] = round(t_embed, 2)
                trace.timings_ms["dense"] = round(t_dense, 2)
                trace.dense_hits = [
                    RetrievalHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s))
                    for c, s in results[:top_k]
                ]
                trace.fused_hits = [
                    FusedHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s), None, idx, float(s))
                    for idx, (c, s) in enumerate(results[:top_k], start=1)
                ]
                for c, _ in results[:top_k]:
                    trace.chunk_codes[c.chunk_id] = c.code

        return results

    def retrieve_with_reasons(self, query: str, top_k: int = 5, file_filter: Optional[str] = None, trace: Optional[Any] = None) -> List[Tuple[CodeChunk, float, str]]:
        """Retrieves top-K matches with reason annotations for context expansion."""
        import re
        mention_match = re.search(r'@([\w\-.\/]+)', query)
        if mention_match and not file_filter:
            file_filter = mention_match.group(1)

        clean_query = re.sub(r'@[\w\-.\/]+', ' ', query).strip()
        clean_query = re.sub(r'\s+', ' ', clean_query)
        effective_query = clean_query if clean_query else query

        store_chunks = getattr(self.store, "chunks", [])
        allowed_chunks = None
        if file_filter:
            f = file_filter.replace("\\", "/").lower()
            allowed_chunks = [c for c in store_chunks if f in c.file_path.replace("\\", "/").lower() or f in os.path.basename(c.file_path).lower()]
            if not allowed_chunks:
                return []
            allowed_ids = {c.chunk_id for c in allowed_chunks}
        else:
            allowed_ids = None

        if self.hybrid_search and self.lexical_index is not None and len(self.lexical_index) > 0:
            candidate_k = max(top_k * 4, 20, len(store_chunks) if allowed_ids else 20)
            t0 = time.perf_counter()
            query_vec = self.embedder.embed([effective_query])[0]
            t_embed = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            dense_results = self.store.search(query_vec, top_k=candidate_k)
            if allowed_ids is not None:
                dense_results = [(c, s) for c, s in dense_results if c.chunk_id in allowed_ids]
            t_dense = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            bm25_results = self.lexical_index.search(effective_query, top_k=candidate_k)
            if allowed_ids is not None:
                bm25_results = [(c, s) for c, s in bm25_results if c.chunk_id in allowed_ids]
            t_bm25 = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            if dense_results or bm25_results:
                results = reciprocal_rank_fusion(
                    [dense_results, bm25_results],
                    list_names=["Dense", "BM25"],
                    k=self.rrf_k,
                    top_k=top_k,
                    include_reason=True,
                    trace=trace,
                )
            elif allowed_chunks:
                results = [(c, 1.0, "File Scoping") for c in allowed_chunks[:top_k]]
            else:
                results = []
            t_fuse = (time.perf_counter() - t0) * 1000

            if trace is not None:
                from core.retrieval_trace import RetrievalHit, FusedHit
                trace.timings_ms["embed"] = round(t_embed, 2)
                trace.timings_ms["dense"] = round(t_dense, 2)
                trace.timings_ms["bm25"] = round(t_bm25, 2)
                trace.timings_ms["fuse"] = round(t_fuse, 2)
                trace.bm25_hits = [
                    RetrievalHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s))
                    for c, s in bm25_results[:top_k]
                ]
                trace.dense_hits = [
                    RetrievalHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s))
                    for c, s in dense_results[:top_k]
                ]
                if not dense_results and not bm25_results and allowed_chunks:
                    trace.fused_hits = [
                        FusedHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, 1.0, None, None, 1.0)
                        for c in allowed_chunks[:top_k]
                    ]
                for c, _ in bm25_results[:top_k]:
                    trace.chunk_codes[c.chunk_id] = c.code
                for c, _ in dense_results[:top_k]:
                    trace.chunk_codes[c.chunk_id] = c.code
                for c in allowed_chunks or []:
                    trace.chunk_codes[c.chunk_id] = c.code
        else:
            candidate_k = max(top_k, len(store_chunks) if allowed_ids else top_k)
            t0 = time.perf_counter()
            query_vec = self.embedder.embed([effective_query])[0]
            t_embed = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            dense_results = self.store.search(query_vec, top_k=candidate_k)
            if allowed_ids is not None:
                dense_results = [(c, s) for c, s in dense_results if c.chunk_id in allowed_ids]
            t_dense = (time.perf_counter() - t0) * 1000

            if dense_results:
                results = [(c, s, "Direct Vector Match") for c, s in dense_results[:top_k]]
            elif allowed_chunks:
                results = [(c, 1.0, "File Scoping") for c in allowed_chunks[:top_k]]
            else:
                results = []

            if trace is not None:
                from core.retrieval_trace import RetrievalHit, FusedHit
                trace.timings_ms["embed"] = round(t_embed, 2)
                trace.timings_ms["dense"] = round(t_dense, 2)
                trace.dense_hits = [
                    RetrievalHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s))
                    for c, s in dense_results[:top_k]
                ]
                trace.fused_hits = [
                    FusedHit(c.chunk_id, c.file_path, c.name or "", c.start_line, c.end_line, float(s), None, idx, float(s))
                    for idx, (c, s, _) in enumerate(results[:top_k], start=1)
                ]
                for c, _, _ in results[:top_k]:
                    trace.chunk_codes[c.chunk_id] = c.code

        return results

    def retrieve_expanded(self, query: str, top_k: int = 5, file_filter: Optional[str] = None, trace: Optional[Any] = None) -> List[Dict]:
        """Retrieves top-K matches and applies graph-augmented context expansion."""
        import re
        mention_match = re.search(r'@([\w\-.\/]+)', query)
        if mention_match and not file_filter:
            file_filter = mention_match.group(1)

        detailed_results = self.retrieve_with_reasons(query, top_k=top_k, file_filter=file_filter, trace=trace)
        store_chunks = getattr(self.store, "chunks", [])
        if file_filter:
            f = file_filter.replace("\\", "/").lower()
            store_chunks = [c for c in store_chunks if f in c.file_path.replace("\\", "/").lower() or f in os.path.basename(c.file_path).lower()]
        return expand_retrieved_context(
            detailed_results,
            dep_graph=self.dep_graph,
            call_graph=self.call_graph,
            store_chunks=store_chunks,
            trace=trace,
        )

    def ask(
        self,
        question: str,
        top_k: int = 5,
        use_memory: bool = True,
        max_token_budget: int = 3000,
        file_filter: Optional[str] = None,
        trace: Optional[Any] = None,
        no_answer: bool = False,
        append_sources: bool = False,
    ) -> dict:
        """Performs RAG query answering with context expansion, conversation history, and persona reasoning."""
        t_start = time.perf_counter()

        import re
        mention_match = re.search(r'@([\w\-.\/]+)', question)
        effective_filter = file_filter
        if mention_match and not effective_filter:
            effective_filter = mention_match.group(1)

        search_query = re.sub(r'@[\w\-.\/]+', ' ', question).strip()
        search_query = re.sub(r'\s+', ' ', search_query)
        if not search_query:
            search_query = question

        if trace is not None:
            from core.lexical_index import tokenize_query
            from core.embedder import TfidfEmbedder
            trace.question = question
            trace.query_terms = tokenize_query(question, remove_stopwords=True)
            embed_name = "tfidf" if isinstance(self.embedder, TfidfEmbedder) else "ollama"
            trace.embedder = embed_name
            trace.embedder_name = embed_name

        expanded_results = self.retrieve_expanded(search_query, top_k=top_k, file_filter=effective_filter, trace=trace)
        t_retrieval = time.perf_counter() - t_start
        context = format_context(expanded_results, max_token_budget=max_token_budget, trace=trace)

        # Sources
        inc_cids = set(trace.budget.included_chunk_ids) if (trace and trace.budget.included_chunk_ids) else set()
        sources = []
        for item in expanded_results:
            c = item[0] if isinstance(item, tuple) else (item.get("chunk") if isinstance(item, dict) else None)
            if c and (not inc_cids or c.chunk_id in inc_cids):
                src = f"{c.file_path}:{c.start_line}-{c.end_line}"
                if src not in sources:
                    sources.append(src)
        if trace is not None:
            trace.sources = sources

        retrieved_chunks = []
        for item in expanded_results:
            if isinstance(item, dict):
                c = item["chunk"]
                retrieved_chunks.append({
                    "file": c.file_path,
                    "name": c.name,
                    "lines": f"{c.start_line}-{c.end_line}",
                    "score": item.get("score", 0.0),
                    "reason": item.get("reason", "retrieved")
                })
            elif isinstance(item, tuple):
                c, score = item[0], item[1]
                retrieved_chunks.append({
                    "file": c.file_path,
                    "name": c.name,
                    "lines": f"{c.start_line}-{c.end_line}",
                    "score": score,
                    "reason": "direct_match"
                })

        response = {
            "question": question,
            "persona": self.active_persona,
            "retrieved_chunks": retrieved_chunks,
            "sources": sources,
        }

        # Extract files in current retrieved context for topic-shift tracking
        current_files = {
            c.file_path
            for item in expanded_results
            for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
            if c and getattr(c, "file_path", None)
        }
        if use_memory and self.memory.is_topic_shifted(current_files):
            self.memory.clear()

        # Build prompt and capture augmented prompt & prompt_sections
        is_analysis = self.memory.is_code_analysis_question(question)
        history_str = self.memory.format_history(is_analysis=is_analysis) if (use_memory and len(self.memory) > 0) else ""
        file_scope_note = ""
        if effective_filter:
            file_scope_note = (
                f"SCOPE: Focus your answer on '{effective_filter}'. "
                f"The context below is scoped to this file. Answer the user's question using this context.\n\n"
            )

        is_bug_query = self._classify_query_intent(question, file_filter=effective_filter)

        if is_bug_query:
            anti_hallucination = (
                "You are analyzing code for bugs, syntax errors, and logic flaws.\n"
                "IMPORTANT: You MUST analyze and output a separate section for EVERY function, method, and block in the context (including main!). Do NOT stop after the first function.\n\n"
                "For EVERY function/method found in the context:\n"
                "1. Name: [function/method name]\n"
                "2. Docstring/intent: [what the code should do based on name/docstring]\n"
                "3. Code: [the implementation]\n"
                "4. Analysis: Check both docstring/name contract and potential runtime failures:\n"
                "   - Syntax & compile errors (missing colons, missing brackets, unbalanced quotes)\n"
                "   - Type mismatch errors (e.g. str + int operations, NoneType operations)\n"
                "   - Logic mistakes & operand order (e.g., 'return b - a' instead of 'a - b')\n"
                "   - Operator bugs & precision loss (e.g., '//' instead of '/')\n"
                "   - Boolean logic and quantifier errors (e.g. 'any()' vs 'all()')\n"
                "5. Answer MATCH or MISMATCH (do NOT assume MATCH if docstring is missing; evaluate function name and arguments)\n"
                "6. If MISMATCH, quote the exact line with the bug\n"
                "7. Explain in one sentence why it is a bug and provide the fix\n\n"
                "CRITICAL: Only report bugs that exist in the code. Quote the exact line from the code.\n\n"
            )
            system_prompt_to_use = self.system_prompt
        else:
            anti_hallucination = (
                "Answer the question directly based on the provided repository context. "
                "Cite file paths and line numbers accurately. Do not invent or assume behavior not shown in the context.\n\n"
            )
            system_prompt_to_use = QA_SYSTEM_PROMPT
            context = strip_qa_scaffolding(context)

        prompt_parts = []
        if history_str:
            prompt_parts.append(history_str)
        prompt_parts.append(anti_hallucination + file_scope_note + f"Repository context:\n\n{context}")
        prompt_parts.append(f"Question: {question}\n\nAnswer:")
        prompt = "\n\n".join(prompt_parts)

        # Context chunks metadata for prompt_sections
        included_chunks_list = []
        for item in expanded_results:
            c = item[0] if isinstance(item, tuple) else (item.get("chunk") if isinstance(item, dict) else None)
            if c and (not inc_cids or c.chunk_id in inc_cids):
                included_chunks_list.append({
                    "file": c.file_path,
                    "lines": f"{c.start_line}-{c.end_line}",
                    "symbol": c.name or "—",
                    "code": c.code,
                    "chunk_id": c.chunk_id,
                })

        instruction_block = (system_prompt_to_use + "\n\n" + anti_hallucination + file_scope_note).strip() if system_prompt_to_use else (anti_hallucination + file_scope_note).strip()

        if trace is not None:
            trace.augmented_prompt = prompt
            trace.prompt_sections = {
                "instructions": instruction_block,
                "context_chunks": included_chunks_list,
                "question": question,
                "memory": history_str,
            }

        if no_answer:
            if trace is not None:
                trace.answer = None
                trace.timings_ms["llm"] = 0.0
            response["answer"] = None
            response["elapsed_seconds"] = round(time.perf_counter() - t_start, 3)
            response["retrieval_seconds"] = round(t_retrieval, 3)
            response["llm_seconds"] = 0.0
            if trace is not None:
                response["trace"] = trace
            return response

        if self.llm is None:
            relevant_items = [
                item for item in expanded_results
                if (item.get("score", 0) if isinstance(item, dict) else item[1]) > 0.001
            ]
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

            t_total = time.perf_counter() - t_start
            response["answer"] = ans
            response["elapsed_seconds"] = round(t_total, 3)
            response["retrieval_seconds"] = round(t_retrieval, 3)
            response["llm_seconds"] = round(max(0.0, t_total - t_retrieval), 3)
            if trace is not None:
                trace.answer = ans
                trace.timings_ms["llm"] = 0.0
                response["trace"] = trace
            if use_memory:
                self.memory.add_turn(question, ans)
            return response

        if is_bug_query:
            # Deterministic Static Analysis Pass (syntax, undefined variables, missing imports)
            static_findings = []
            files_seen = set()
            for item in expanded_results:
                chunk = item[0] if isinstance(item, tuple) else (item.get("chunk") if isinstance(item, dict) else None)
                if chunk and chunk.file_path and chunk.file_path not in files_seen:
                    files_seen.add(chunk.file_path)
                    try:
                        checks = run_static_checks_for_chunk(chunk, repo_path=self.repo_path)
                        static_findings.extend(checks)
                    except Exception as e:
                        if DEBUG_PROMPT:
                            print(f"[DEBUG_PROMPT] Static check exception on {chunk.file_path}: {e}")

            # If static syntax error exists, report immediately and bypass expensive logic pass
            has_syntax_error = any(f.get("type") == "SyntaxError" for f in static_findings)
            if has_syntax_error:
                answer = self._format_merged_findings(static_findings)
                answer, unverified_files, unverified_symbols = self._post_process_answer(answer, sources, append_to_answer=append_sources)
                t_total = time.perf_counter() - t_start
                response["answer"] = answer
                response["unverified_files"] = unverified_files
                response["unverified_symbols"] = unverified_symbols
                response["elapsed_seconds"] = round(t_total, 3)
                response["retrieval_seconds"] = round(t_retrieval, 3)
                response["llm_seconds"] = 0.0
                if trace is not None:
                    trace.answer = answer
                    trace.timings_ms["llm"] = 0.0
                    response["trace"] = trace
                if use_memory:
                    self.memory.add_turn(question, answer)
                return response

            # First LLM pass: Runtime errors on whole line-numbered file at temperature 0.0
            runtime_errors_prompt = (
                "This file is supposed to run. List every error that would stop it from running "
                "(syntax errors, undefined names, missing imports, type errors). "
                "For each error, provide: line number, the exact line, and the error type. "
                "If there are none, say NONE.\n\n"
            )
            runtime_context = file_scope_note + f"Repository context:\n\n{context}"
            runtime_prompt = "\n\n".join([history_str, runtime_errors_prompt, runtime_context, f"Question: {question}\n\nAnswer:"])
            
            if DEBUG_PROMPT:
                from backend.config import settings
                debug_path = os.path.join(settings.STORAGE_DIR, "last_runtime_prompt.txt")
                estimated_tokens = int(len(runtime_prompt) / 3.5)
                debug_content = f"=== RUNTIME ERRORS PROMPT ===\n{runtime_prompt}\n\n=== ESTIMATED TOKENS ===\n{estimated_tokens}\n"
                os.makedirs(settings.STORAGE_DIR, exist_ok=True)
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(debug_content)
                print(f"[DEBUG] Runtime prompt written to {debug_path} (estimated {estimated_tokens} tokens)")
            
            t_llm0 = time.perf_counter()
            runtime_answer = self.llm.generate(runtime_prompt, system=self.system_prompt, temperature=0.0)
            
            if DEBUG_PROMPT:
                runtime_debug_path = os.path.join(settings.STORAGE_DIR, "last_runtime_llm_output.txt")
                with open(runtime_debug_path, "w", encoding="utf-8") as f:
                    f.write(f"=== RAW LLM OUTPUT ===\n{runtime_answer}\n")
                print(f"[DEBUG] LLM output written to {runtime_debug_path}")
            
            # Parse runtime errors from LLM response
            runtime_findings = self._parse_runtime_errors(runtime_answer, expanded_results)
            
            # Second pass: Per-function analysis for semantic bugs and logic flaws
            anti_hallucination = (
                "You are analyzing code for bugs, syntax errors, and logic flaws.\n"
                "IMPORTANT: You MUST analyze and output a separate section for EVERY function, method, and block in the context (including main!). Do NOT stop after the first function.\n\n"
                "For EVERY function/method found in the context:\n"
                "1. Name: [function/method name]\n"
                "2. Docstring/intent: [what the code should do based on name/docstring]\n"
                "3. Code: [the implementation]\n"
                "4. Analysis: Check both docstring/name contract and potential runtime failures:\n"
                "   - Syntax & compile errors (missing colons, missing brackets, unbalanced quotes)\n"
                "   - Type mismatch errors (e.g. str + int operations, NoneType operations)\n"
                "   - Logic mistakes & operand order (e.g., 'return b - a' instead of 'a - b')\n"
                "   - Operator bugs & precision loss (e.g., '//' instead of '/')\n"
                "   - Boolean logic and quantifier errors (e.g. 'any()' vs 'all()')\n"
                "5. Answer MATCH or MISMATCH (do NOT assume MATCH if docstring is missing; evaluate function name and arguments)\n"
                "6. If MISMATCH, quote the exact line with the bug\n"
                "7. Explain in one sentence why it is a bug and provide the fix\n\n"
                "CRITICAL: Only report bugs that exist in the code. Quote the exact line from the code.\n\n"
            )
        else:
            anti_hallucination = (
                "Answer the question directly based on the provided repository context. "
                "Cite file paths and line numbers accurately. Do not invent or assume behavior not shown in the context.\n\n"
            )
            system_prompt_to_use = QA_SYSTEM_PROMPT
            context = strip_qa_scaffolding(context)
            t_llm0 = time.perf_counter()

        prompt_parts = []
        if history_str:
            prompt_parts.append(history_str)
        prompt_parts.append(anti_hallucination + file_scope_note + f"Repository context:\n\n{context}")
        prompt_parts.append(f"Question: {question}\n\nAnswer:")

        prompt = "\n\n".join(prompt_parts)
        if trace is not None:
            trace.augmented_prompt = prompt
        
        # Debug: write prompt to file if debug flag is set
        if DEBUG_PROMPT:
            from backend.config import settings
            debug_path = os.path.join(settings.STORAGE_DIR, "last_prompt.txt")
            estimated_tokens = int(len(prompt) / 3.5)
            debug_content = f"=== SYSTEM PROMPT ===\n{system_prompt_to_use}\n\n=== USER PROMPT ===\n{prompt}\n\n=== ESTIMATED TOKENS ===\n{estimated_tokens}\n"
            os.makedirs(settings.STORAGE_DIR, exist_ok=True)
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(debug_content)
            print(f"[DEBUG] Prompt written to {debug_path} (estimated {estimated_tokens} tokens)")
        
        answer = self.llm.generate(prompt, system=system_prompt_to_use, temperature=0.0)

        # Anti-hallucination filter for bug queries
        if is_bug_query:
            answer = self._filter_hallucinated_claims(answer, expanded_results)
            
            # Merge deterministic static findings, LLM runtime findings, and semantic findings
            semantic_findings = self._parse_semantic_findings(answer)
            merged = self._merge_findings(static_findings + runtime_findings, semantic_findings)
            if merged:
                answer = self._format_merged_findings(merged)
        else:
            # Guard against Q&A drift: stop generation if "### Analysis" or "MATCH" appears
            import re
            drift_match = re.search(r'(?:###\s*Analysis|\bMATCH\b|\bMISMATCH\b)', answer)
            if drift_match:
                answer = answer[:drift_match.start()].rstrip()

        t_total = time.perf_counter() - t_start
        t_llm = max(0.0, time.perf_counter() - t_llm0)

        # Partition sources into relied-on chunks vs unused retrieved context
        relied_items, other_items = partition_sources(answer, expanded_results)
        relied_sources = [
            f"{c.file_path}:{c.start_line}-{c.end_line}"
            for item in relied_items
            for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
            if c and getattr(c, "file_path", None)
        ]
        relied_sources = list(dict.fromkeys(relied_sources))

        other_sources = [
            f"{c.file_path}:{c.start_line}-{c.end_line}"
            for item in other_items
            for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
            if c and getattr(c, "file_path", None)
        ]
        other_sources = list(dict.fromkeys(other_sources))

        answer, unverified_files, unverified_symbols = self._post_process_answer(
            answer,
            sources=relied_sources,
            append_to_answer=append_sources,
            retrieved_context=other_sources,
        )

        response["sources"] = relied_sources
        response["retrieved_context"] = other_sources
        response["answer"] = answer
        response["unverified_files"] = unverified_files
        response["unverified_symbols"] = unverified_symbols
        response["elapsed_seconds"] = round(t_total, 3)
        response["retrieval_seconds"] = round(t_retrieval, 3)
        response["llm_seconds"] = round(t_llm, 3)
        if trace is not None:
            trace.answer = answer
            trace.timings_ms["llm"] = round(t_llm * 1000, 2)
            response["trace"] = trace
        if use_memory:
            self.memory.add_turn(question, answer, files=current_files)
        return response

    def stream_ask(
        self,
        question: str,
        top_k: int = 5,
        use_memory: bool = True,
        max_token_budget: int = 3000,
        file_filter: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """Streams AI response tokens in real-time while updating conversation memory."""
        expanded_results = self.retrieve_expanded(question, top_k=top_k, file_filter=file_filter)
        context = format_context(expanded_results, max_token_budget=max_token_budget)

        if self.llm is None or not hasattr(self.llm, "stream_generate"):
            resp = self.ask(question, top_k=top_k, use_memory=use_memory, max_token_budget=max_token_budget, file_filter=file_filter)
            yield resp["answer"]
            return

        current_files = {
            c.file_path
            for item in expanded_results
            for c in [item[0] if isinstance(item, tuple) else item.get("chunk")]
            if c and getattr(c, "file_path", None)
        }
        if use_memory and self.memory.is_topic_shifted(current_files):
            self.memory.clear()

        is_analysis = self.memory.is_code_analysis_question(question)
        history_str = self.memory.format_history(is_analysis=is_analysis) if (use_memory and len(self.memory) > 0) else ""
        file_scope_note = ""
        if file_filter:
            file_scope_note = (
                f"SCOPE: Focus your answer on '{file_filter}'. "
                f"The context below is scoped to this file. Answer the user's question using this context.\n\n"
            )
        
        is_bug_query = self._classify_query_intent(question, file_filter=file_filter)
        runtime_findings = []
        
        if is_bug_query:
            # Deterministic static analysis pass first
            static_findings = []
            files_seen = set()
            for item in expanded_results:
                chunk = item[0] if isinstance(item, tuple) else (item.get("chunk") if isinstance(item, dict) else None)
                if chunk and chunk.file_path and chunk.file_path not in files_seen:
                    files_seen.add(chunk.file_path)
                    try:
                        file_code = chunk.code
                        if os.path.isfile(chunk.file_path):
                            with open(chunk.file_path, "r", encoding="utf-8", errors="replace") as f:
                                file_code = f.read()
                        checks = run_static_checks(file_code, chunk.file_path, chunk.language)
                        static_findings.extend(checks)
                    except Exception as e:
                        if DEBUG_PROMPT:
                            print(f"[DEBUG_PROMPT] Static check exception in stream_ask on {chunk.file_path}: {e}")

            # If syntax error exists, return static findings directly
            has_syntax_error = any(f.get("type") == "SyntaxError" for f in static_findings)
            if has_syntax_error:
                formatted = self._format_merged_findings(static_findings)
                if use_memory:
                    self.memory.add_turn(question, formatted, files=current_files)
                yield formatted
                return
            # First pass: Runtime errors (syntax, undefined names, missing imports, type errors)
            runtime_errors_prompt = (
                "This file is supposed to run. List every error that would stop it from running "
                "(syntax errors, undefined names, missing imports, type errors). "
                "For each error, provide: line number, the exact line, and the error type. "
                "If there are none, say NONE.\n\n"
            )
            runtime_context = file_scope_note + f"Repository context:\n\n{context}"
            runtime_prompt = "\n\n".join([history_str, runtime_errors_prompt, runtime_context, f"Question: {question}\n\nAnswer:"])
            
            runtime_answer = self.llm.generate(runtime_prompt, system=self.system_prompt, temperature=0.0)
            runtime_findings = self._parse_runtime_errors(runtime_answer, expanded_results)
            
            # Second pass: Per-function analysis for semantic bugs
            anti_hallucination = (
                "You are analyzing code for bugs. Process each function/class separately:\n\n"
                "For each function/class found in the context:\n"
                "1. Name: [function/class name]\n"
                "2. Docstring/intent: [what the code should do based on name/docstring]\n"
                "3. Code: [the implementation]\n"
                "4. Analysis: Does the implementation do what the name and docstring say?\n"
                "5. Answer MATCH or MISMATCH\n"
                "6. Quote the exact line with the bug (e.g., 'return b - a')\n"
                "7. Explain in one sentence why it's a bug\n\n"
                "CRITICAL: Only report bugs that exist in the code. Quote the exact line from the code. "
                "Do not invent bugs. If no bugs found, say 'No bugs found'.\n\n"
            )
            system_prompt_to_use = self.system_prompt
        else:
            anti_hallucination = (
                "Answer the question directly based on the provided repository context. "
                "Cite file paths and line numbers accurately. Do not invent or assume behavior not shown in the context.\n\n"
            )
            system_prompt_to_use = QA_SYSTEM_PROMPT
            context = strip_qa_scaffolding(context)

        prompt_parts = []
        if history_str:
            prompt_parts.append(history_str)
        prompt_parts.append(anti_hallucination + file_scope_note + f"Repository context:\n\n{context}")
        prompt_parts.append(f"Question: {question}\n\nAnswer:")

        prompt = "\n\n".join(prompt_parts)
        accumulated_tokens = []

        import re
        for token in self.llm.stream_generate(prompt, system=system_prompt_to_use, temperature=0.0):
            if not is_bug_query:
                curr_text = "".join(accumulated_tokens) + token
                drift_match = re.search(r'(?:###\s*Analysis|\bMATCH\b|\bMISMATCH\b)', curr_text)
                if drift_match:
                    # Halt token streaming on drift
                    break
            accumulated_tokens.append(token)
            yield token

        full_answer = "".join(accumulated_tokens)
        
        # Anti-hallucination filter for bug queries
        if is_bug_query:
            full_answer = self._filter_hallucinated_claims(full_answer, expanded_results)
        
        if use_memory:
            self.memory.add_turn(question, full_answer, files=current_files)

    def _filter_hallucinated_claims(self, answer: str, expanded_results: List[Any]) -> str:
        """Filter out hallucinated claims by verifying quoted lines exist in files."""
        import re
        
        # Extract all quoted code from the answer (look for patterns like 'return b - a' or "return b - a")
        quoted_patterns = re.findall(r'["\']([^"\']{5,100})["\']', answer)
        
        if not quoted_patterns:
            return answer
        
        # Build a set of all actual code lines from the context
        actual_lines = set()
        for item in expanded_results:
            if isinstance(item, tuple):
                chunk = item[0]
            elif isinstance(item, dict):
                chunk = item["chunk"]
            else:
                continue
            
            # Normalize whitespace and add lines
            for line in chunk.code.splitlines():
                # Strip potential line number prefixes like "  1 | " if present
                clean_line = re.sub(r'^\s*\d+\s*\|\s*', '', line)
                normalized = ' '.join(clean_line.split())
                if normalized:
                    actual_lines.add(normalized)
        
        # Filter claims
        removed_count = 0
        filtered_answer = answer
        
        for quote in quoted_patterns:
            # Strip line number prefixes, code fences, and whitespace
            clean_quote = re.sub(r'^\s*\d+\s*\|\s*', '', quote)
            clean_quote = clean_quote.strip('`').strip()
            normalized_quote = ' '.join(clean_quote.split())
            if not normalized_quote or normalized_quote not in actual_lines:
                # Remove this claim or mark it
                removed_count += 1
                if DEBUG_PROMPT:
                    print(f"[DEBUG_PROMPT] Removed hallucinated quote: {quote!r} (normalized: {normalized_quote!r})")
                # Replace the quoted part with a marker
                filtered_answer = filtered_answer.replace(f'"{quote}"', '[QUOTED CODE NOT FOUND IN FILE]')
                filtered_answer = filtered_answer.replace(f"'{quote}'", '[QUOTED CODE NOT FOUND IN FILE]')
        
        if removed_count > 0:
            notice = f"\n\n[Anti-hallucination filter: {removed_count} claim(s) removed - quoted code not found in file]"
            filtered_answer += notice
        
        return filtered_answer

    def localize_bug(self, error_report: str, top_k: int = 5) -> dict:
        """Bug localization: treat error/stack trace as query and expand caller context graph."""
        return self.ask(
            f"Given this error report, identify the most likely root cause file(s) "
            f"and explain why:\n\n{error_report}",
            top_k=top_k,
        )

    def _parse_runtime_errors(self, answer: str, expanded_results: List[Any]) -> List[Dict]:
        """Parse runtime errors from LLM response and verify quotes."""
        import re
        
        findings = []
        
        # Extract error findings (look for patterns like "Line X: ... error")
        # The LLM should respond with format: "Line 5: return a + b + math.sqrt(a) - NameError"
        lines = answer.split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.lower() in ['none', 'no errors found']:
                continue
            
            # Try to extract line number and quote - more flexible pattern
            line_match = re.search(r'Line\s*(\d+):\s*(.+?)(?:\s*[-–]\s*(?:NameError|SyntaxError|TypeError|ImportError|AttributeError|ValueError|RuntimeError).*)?$', line, re.IGNORECASE)
            if line_match:
                line_num = int(line_match.group(1))
                code_snippet = line_match.group(2).strip()
                
                # Verify the quote exists in the file
                if self._verify_quote_exists(code_snippet, expanded_results, line_num):
                    findings.append({
                        'line': line_num,
                        'code': code_snippet,
                        'source': 'llm',
                        'type': 'runtime'
                    })
        
        return findings
    
    def _parse_semantic_findings(self, answer: str) -> List[Dict]:
        """Parse semantic bugs from per-function analysis."""
        import re
        
        findings = []
        lines = answer.split('\n')
        
        for line in lines:
            # Look for quoted lines in semantic analysis
            quoted_match = re.search(r'["\']([^"\']{5,100})["\']', line)
            if quoted_match:
                findings.append({
                    'code': quoted_match.group(1),
                    'source': 'semantic',
                    'type': 'semantic'
                })
        
        return findings
    
    def _merge_findings(self, runtime_findings: List[Dict], semantic_findings: List[Dict]) -> List[Dict]:
        """Merge runtime and semantic findings, deduplicating by line + kind."""
        merged = []
        seen = set()
        
        for finding in runtime_findings:
            key = (finding.get('line'), finding.get('type'))
            if key not in seen:
                seen.add(key)
                merged.append(finding)
        
        for finding in semantic_findings:
            # For semantic findings, we don't have line numbers yet, so add all
            merged.append(finding)
        
        return merged
    
    def _format_merged_findings(self, findings: List[Dict]) -> str:
        """Format merged findings into readable output."""
        if not findings:
            return "No bugs found."
        
        output = []
        
        # 1. Deterministic Static findings first (labelled [STATIC])
        static_errs = [f for f in findings if f.get('source') == 'static']
        if static_errs:
            output.append("**Static Analysis Findings:**")
            for f in static_errs:
                loc = f"Line {f.get('line')}" if f.get('line') else ""
                col = f", Col {f.get('column')}" if f.get('column') else ""
                coord = f" ({loc}{col})" if loc else ""
                err_type = f" [{f.get('type')}]" if f.get('type') else ""
                code_snippet = f": `{f['code']}`" if f.get('code') else ""
                output.append(f"- [STATIC]{err_type}{coord} {f.get('message', '')}{code_snippet}")

        # 2. Runtime findings second
        runtime = [f for f in findings if f.get('source') == 'llm']
        if runtime:
            if static_errs:
                output.append("\n**Runtime Errors:**")
            for f in runtime:
                output.append(f"**Runtime Error (Line {f['line']}):** {f['code']}")
        
        # 3. Semantic findings third
        semantic = [f for f in findings if f.get('source') not in ('static', 'llm')]
        if semantic:
            output.append("\n**Semantic Analysis Findings:**")
            for f in semantic:
                output.append(f"- {f['code']}")
        
        return "\n".join(output)
    
    def _verify_quote_exists(self, quote: str, expanded_results: List[Any], claimed_line: int) -> bool:
        """Verify a quoted line exists in the file at or near the claimed line number."""
        # Normalize quote
        normalized_quote = ' '.join(quote.split())
        
        for item in expanded_results:
            if isinstance(item, tuple):
                chunk = item[0]
            elif isinstance(item, dict):
                chunk = item["chunk"]
            else:
                continue
            
            lines = chunk.code.splitlines()
            for offset, line in enumerate(lines, start=chunk.start_line):
                normalized_line = ' '.join(line.split())
                if normalized_quote in normalized_line:
                    # Check if it's close to the claimed line number (within 5 lines)
                    if abs(offset - claimed_line) <= 5:
                        return True
        
        return False

    def _classify_query_intent(self, question: str, file_filter: Optional[str] = None) -> bool:
        """Classifies whether a query has explicit bug-finding / crash-localization intent.

        Precedence rules:
        1. Explicit bug-intent words (bug, bugs, issue, issues, wrong with, review, @file with find/check),
           stack traces / tracebacks, or crash keywords WIN over leading how/what/where/why.
        2. Informational questions without explicit bug-intent (e.g. 'How does Flask handle an error raised in a view?')
           route strictly to normal Q&A.
        """
        import re
        q_lower = question.lower()

        # Stack trace / traceback detection -> crash localization
        has_stack_trace = (
            "traceback (most recent call last)" in q_lower
            or "\n  file " in q_lower
            or bool(re.search(r'\b(why does this crash|where does it crash|crash(?:ed|es|ing)?)\b', q_lower))
        )
        if has_stack_trace:
            return True

        # Explicit bug-intent words (standalone regex matching)
        has_explicit_bug_words = bool(re.search(
            r'\b(bug|bugs|issue|issues|wrong with|syntax error|syntax errors|type error|runtime error|static check|static analysis|code review|audit code)\b',
            q_lower
        ))

        # @file / scoped inspection with action verbs
        has_scoped_inspection = bool(file_filter) and bool(re.search(r'\b(find|check|inspect|review|audit|fix)\b', q_lower))

        if self.active_persona in ("fixer", "reviewer", "audit") or has_explicit_bug_words or has_scoped_inspection:
            return True

        return False

    def _post_process_answer(
        self,
        answer: str,
        sources: List[str],
        append_to_answer: bool = False,
        retrieved_context: Optional[List[str]] = None,
    ) -> Tuple[str, List[str], List[str]]:
        """Verifies mentioned file paths and checks for unverified symbol names, optionally appending to answer."""
        if not answer:
            return answer, [], []

        # 1. Sources line
        sources_str = ", ".join(sources) if sources else ""
        retrieved_str = ", ".join(retrieved_context) if retrieved_context else ""

        # 2. Check mentioned file paths against the repository index
        indexed_files = set()
        indexed_basenames = set()
        store_chunks = getattr(self.store, "chunks", []) or []
        for c in store_chunks:
            if getattr(c, "file_path", None):
                np = c.file_path.replace("\\", "/").lower()
                indexed_files.add(np)
                indexed_basenames.add(os.path.basename(np))

        # Extract file paths from answer (excluding Sources line itself)
        answer_body = answer.split("Sources:")[0] if "Sources:" in answer else answer
        import re
        raw_paths = re.findall(r'\b([a-zA-Z0-9_\-\.\/\\]+\.(?:py|js|ts|tsx|jsx|java|c|cpp|h|go|rs|json|yaml|yml|md))\b', answer_body)
        unverified_files = set()
        for cand in raw_paths:
            cand_norm = cand.replace("\\", "/").lower()
            if cand_norm not in indexed_files and os.path.basename(cand_norm) not in indexed_basenames:
                if cand_norm not in ("readme.md", "setup.py", "requirements.txt", "pyproject.toml", "license.txt", "license.md", "conftest.py"):
                    unverified_files.add(cand)

        # 3. Check unverified symbol names against builtins, stdlib, imports, and index
        import builtins, keyword, sys
        builtins_set = set(dir(builtins)) | set(keyword.kwlist) | {
            "def", "class", "self", "cls", "return", "import", "from", "as", "if", "else", "elif",
            "try", "except", "finally", "with", "raise", "pass", "None", "True", "False", "str",
            "int", "float", "bool", "dict", "list", "set", "tuple", "len", "print", "open", "type",
            "range", "isinstance", "issubclass", "getattr", "setattr", "hasattr", "Exception",
            "ValueError", "KeyError", "TypeError", "AttributeError", "RuntimeError", "SyntaxError",
            "NameError", "args", "kwargs", "app", "request", "session", "response", "g", "config"
        }

        stdlib_modules = set(getattr(sys, "stdlib_module_names", set())) | {
            "os", "sys", "re", "json", "math", "typing", "datetime", "pathlib", "collections",
            "itertools", "functools", "logging", "unittest", "hashlib", "time", "sqlite3",
            "dataclasses", "abc", "typing_extensions"
        }

        imported_names = set()
        known_symbols = set()
        for c in store_chunks:
            if getattr(c, "imports", None):
                for imp in c.imports:
                    imported_names.add(imp)
                    if "." in imp:
                        imported_names.add(imp.split(".")[0])
                        imported_names.add(imp.split(".")[-1])
            if getattr(c, "name", None):
                known_symbols.add(c.name)
                if "." in c.name:
                    known_symbols.add(c.name.split(".")[-1])

        raw_symbols = re.findall(r'`([a-zA-Z_][a-zA-Z0-9_]*)`', answer_body)
        unverified_symbols = set()
        for sym in raw_symbols:
            if (sym not in builtins_set and
                sym not in stdlib_modules and
                sym not in imported_names and
                sym not in known_symbols):
                found = any(sym in c.code for c in store_chunks) if store_chunks else False
                if not found:
                    unverified_symbols.add(sym)

        processed_answer = answer
        if append_to_answer:
            if sources_str and "Sources:" not in processed_answer:
                processed_answer = processed_answer.rstrip() + f"\n\nSources: {sources_str}"
            if retrieved_str and "Retrieved context:" not in processed_answer:
                processed_answer = processed_answer.rstrip() + f"\n\nRetrieved context: {retrieved_str}"
            if unverified_files:
                processed_answer = processed_answer.rstrip() + f"\n\n[Unverified file path(s): {', '.join(sorted(unverified_files))}]"
            if unverified_symbols:
                processed_answer = processed_answer.rstrip() + f"\n\n[Unverified names: {', '.join(sorted(unverified_symbols))}]"

        return processed_answer, sorted(list(unverified_files)), sorted(list(unverified_symbols))
