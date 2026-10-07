"""
Retrieval Trace Data Model for IntelliCodeX RAG Pipeline.
Captures end-to-end provenance: query tokens, BM25 hits, dense hits, RRF fusion,
graph context expansion, token budgeting, prompt context, and timings.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union


class RetrievalHit(tuple):
    """
    Hit tuple: (chunk_id, file, symbol, start_line, end_line, score)
    Supports both tuple indexing, attribute access, and dict conversion.
    """
    def __new__(cls, chunk_id: str, file: str, symbol: str, start_line: int, end_line: int, score: float):
        return super().__new__(cls, (chunk_id, file, symbol, int(start_line), int(end_line), float(score)))

    @property
    def chunk_id(self) -> str:
        return self[0]

    @property
    def file(self) -> str:
        return self[1]

    @property
    def symbol(self) -> str:
        return self[2]

    @property
    def start_line(self) -> int:
        return self[3]

    @property
    def end_line(self) -> int:
        return self[4]

    @property
    def score(self) -> float:
        return self[5]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self[0],
            "file": self[1],
            "symbol": self[2],
            "start_line": self[3],
            "end_line": self[4],
            "score": self[5],
        }


class FusedHit(tuple):
    """
    Fused hit tuple:
    (chunk_id, file, symbol, start_line, end_line, score, bm25_rank, dense_rank, rrf_score)
    where bm25_rank and dense_rank are 1-based (or None if absent).
    """
    def __new__(
        cls,
        chunk_id: str,
        file: str,
        symbol: str,
        start_line: int,
        end_line: int,
        score: float,
        bm25_rank: Optional[int],
        dense_rank: Optional[int],
        rrf_score: float,
    ):
        return super().__new__(
            cls,
            (
                chunk_id,
                file,
                symbol,
                int(start_line),
                int(end_line),
                float(score),
                int(bm25_rank) if bm25_rank is not None else None,
                int(dense_rank) if dense_rank is not None else None,
                float(rrf_score),
            ),
        )

    @property
    def chunk_id(self) -> str:
        return self[0]

    @property
    def file(self) -> str:
        return self[1]

    @property
    def symbol(self) -> str:
        return self[2]

    @property
    def start_line(self) -> int:
        return self[3]

    @property
    def end_line(self) -> int:
        return self[4]

    @property
    def score(self) -> float:
        return self[5]

    @property
    def bm25_rank(self) -> Optional[int]:
        return self[6]

    @property
    def dense_rank(self) -> Optional[int]:
        return self[7]

    @property
    def rrf_score(self) -> float:
        return self[8]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self[0],
            "file": self[1],
            "symbol": self[2],
            "start_line": self[3],
            "end_line": self[4],
            "score": self[5],
            "bm25_rank": self[6],
            "dense_rank": self[7],
            "rrf_score": self[8],
        }


class GraphAddition(tuple):
    """
    Graph addition tuple: (target, reason, caused_by)
    reason must be one of: "caller", "callee", "import".
    caused_by is the chunk_id of the hit that triggered this graph expansion.
    """
    def __new__(cls, target: str, reason: str, caused_by: Optional[str] = None):
        return super().__new__(cls, (str(target), str(reason), str(caused_by) if caused_by else None))

    @property
    def target(self) -> str:
        return self[0]

    @property
    def reason(self) -> str:
        return self[1]

    @property
    def caused_by(self) -> Optional[str]:
        return self[2]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self[0],
            "reason": self[1],
            "caused_by": self[2],
        }


class BudgetTrace:
    """
    Token budget tracking container supporting attribute access,
    dict-like subscripting, and JSON serialization.
    """
    def __init__(
        self,
        max_tokens: int = 0,
        used_tokens: int = 0,
        included_chunk_ids: Optional[List[str]] = None,
        dropped_chunk_ids: Optional[List[str]] = None,
    ):
        self.max_tokens: int = int(max_tokens)
        self.used_tokens: int = int(used_tokens)
        self.included_chunk_ids: List[str] = list(included_chunk_ids or [])
        self.dropped_chunk_ids: List[str] = list(dropped_chunk_ids or [])

    def __getitem__(self, item: str):
        if hasattr(self, item):
            return getattr(self, item)
        raise KeyError(item)

    def __setitem__(self, key: str, value: Any):
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "used_tokens": self.used_tokens,
            "included_chunk_ids": list(self.included_chunk_ids),
            "dropped_chunk_ids": list(self.dropped_chunk_ids),
        }


@dataclass
class RetrievalTrace:
    """
    Comprehensive provenance trace for QueryEngine retrieval and answering.
    """
    question: str = ""
    query_terms: List[str] = field(default_factory=list)
    bm25_hits: List[Union[RetrievalHit, Tuple[str, str, str, int, int, float]]] = field(default_factory=list)
    dense_hits: List[Union[RetrievalHit, Tuple[str, str, str, int, int, float]]] = field(default_factory=list)
    fused_hits: List[Union[FusedHit, Tuple[str, str, str, int, int, float, Optional[int], Optional[int], float]]] = field(default_factory=list)
    graph_additions: List[Union[GraphAddition, Tuple[str, str, Optional[str]]]] = field(default_factory=list)
    budget: BudgetTrace = field(default_factory=BudgetTrace)
    answer: Optional[str] = None
    sources: Optional[List[str]] = None
    timings_ms: Dict[str, float] = field(
        default_factory=lambda: {
            "embed": 0.0,
            "bm25": 0.0,
            "dense": 0.0,
            "fuse": 0.0,
            "expand": 0.0,
            "llm": 0.0,
        }
    )
    embedder: Optional[str] = None
    chunk_codes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes trace to standard JSON-compatible dictionary."""
        return {
            "question": self.question,
            "query_terms": list(self.query_terms),
            "bm25_hits": [
                h.to_dict() if hasattr(h, "to_dict") else {
                    "chunk_id": h[0],
                    "file": h[1],
                    "symbol": h[2],
                    "start_line": h[3],
                    "end_line": h[4],
                    "score": h[5],
                }
                for h in self.bm25_hits
            ],
            "dense_hits": [
                h.to_dict() if hasattr(h, "to_dict") else {
                    "chunk_id": h[0],
                    "file": h[1],
                    "symbol": h[2],
                    "start_line": h[3],
                    "end_line": h[4],
                    "score": h[5],
                }
                for h in self.dense_hits
            ],
            "fused_hits": [
                h.to_dict() if hasattr(h, "to_dict") else {
                    "chunk_id": h[0],
                    "file": h[1],
                    "symbol": h[2],
                    "start_line": h[3],
                    "end_line": h[4],
                    "score": h[5],
                    "bm25_rank": h[6],
                    "dense_rank": h[7],
                    "rrf_score": h[8],
                }
                for h in self.fused_hits
            ],
            "graph_additions": [
                g.to_dict() if hasattr(g, "to_dict") else {
                    "target": g[0],
                    "reason": g[1],
                    "caused_by": g[2] if len(g) > 2 else None,
                }
                for g in self.graph_additions
            ],
            "budget": self.budget.to_dict() if hasattr(self.budget, "to_dict") else dict(self.budget),
            "answer": self.answer,
            "sources": list(self.sources) if self.sources is not None else None,
            "timings_ms": {k: float(v) for k, v in self.timings_ms.items()},
            "embedder": self.embedder,
            "chunk_codes": dict(self.chunk_codes),
        }
