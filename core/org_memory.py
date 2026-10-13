"""
Distributed Organizational Memory Engine (REQ-FUT-09).
Mines historical Git commit logs, Architectural Decision Records (ADRs),
and pull request discussions to answer historical rationale queries
("Why was X chosen over Y?", "Who changed file Z and why?").
"""
import os
import re
import glob
import time
import subprocess
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple

from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder, TfidfEmbedder


@dataclass
class OrgMemoryItem:
    item_id: str                      # e.g., 'commit:a1b2c3d' or 'adr:0001-use-faiss.md'
    memory_type: str                  # 'commit' | 'adr' | 'pr'
    title: str
    author: str
    date_str: str
    content: str
    files_touched: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    citation: str = ""

    def __post_init__(self):
        if not self.citation:
            if self.memory_type == "commit":
                self.citation = f"[commit:{self.item_id.replace('commit:', '')[:8]}]"
            elif self.memory_type == "adr":
                self.citation = f"[adr:{self.metadata.get('file_path', self.title)}]"
            else:
                self.citation = f"[{self.memory_type}:{self.item_id}]"

    def as_embedding_text(self) -> str:
        parts = [
            f"Type: {self.memory_type.upper()}",
            f"Title: {self.title}",
            f"Author: {self.author}",
            f"Date: {self.date_str}",
        ]
        if self.files_touched:
            parts.append(f"Files: {', '.join(self.files_touched[:15])}")
        parts.append(f"Description:\n{self.content}")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GitHistoryMiner:
    """Mines Git repository commit messages, authors, dates, and touched files."""

    @staticmethod
    def mine_commits(repo_path: str, max_commits: int = 150) -> List[OrgMemoryItem]:
        items: List[OrgMemoryItem] = []
        if not os.path.isdir(repo_path) or not os.path.exists(os.path.join(repo_path, ".git")):
            return items

        # Format: Hash%x1fAuthor%x1fDate%x1fSubject%x1fBody%x1e
        # Followed by list of changed files
        cmd = [
            "git", "log",
            f"-n{max_commits}",
            "--date=short",
            "--pretty=format:%H%x1f%an%x1f%ad%x1f%s%x1f%b%x1e",
            "--name-only",
        ]

        try:
            res = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            if res.returncode != 0:
                return items
        except Exception:
            return items

        raw_output = res.stdout.strip()
        if not raw_output:
            return items

        raw_records = raw_output.split("\x1e")
        for rec in raw_records:
            rec = rec.strip()
            if not rec:
                continue
            parts = rec.split("\x1f")
            if len(parts) < 4:
                continue

            commit_hash = parts[0].strip()
            author = parts[1].strip()
            commit_date = parts[2].strip()
            subject = parts[3].strip()

            body_and_files = parts[4] if len(parts) > 4 else ""
            lines = [line.strip() for line in body_and_files.splitlines()]

            body_lines = []
            file_lines = []
            is_files = False
            for l in lines:
                if not l:
                    is_files = True
                    continue
                if is_files and (os.path.sep in l or "/" in l or "." in l):
                    file_lines.append(l)
                else:
                    body_lines.append(l)

            full_body = "\n".join(body_lines).strip()
            content = f"{subject}\n\n{full_body}".strip() if full_body else subject

            items.append(OrgMemoryItem(
                item_id=f"commit:{commit_hash}",
                memory_type="commit",
                title=subject,
                author=author,
                date_str=commit_date,
                content=content,
                files_touched=file_lines,
                metadata={
                    "commit_hash": commit_hash,
                    "short_hash": commit_hash[:8],
                },
            ))

        return items


class ADRMiner:
    """Discovers and parses Architectural Decision Records (ADRs) and design documents."""

    ADR_GLOBS = [
        "**/adr/*.md",
        "**/ADR/*.md",
        "**/decisions/*.md",
        "**/docs/architecture/*.md",
        "**/architecture/*.md",
        "*ADR*.md",
        "*DECISION*.md",
    ]

    @classmethod
    def mine_adrs(cls, repo_path: str) -> List[OrgMemoryItem]:
        items: List[OrgMemoryItem] = []
        if not os.path.isdir(repo_path):
            return items

        matched_files = set()
        for pattern in cls.ADR_GLOBS:
            full_pattern = os.path.join(repo_path, pattern)
            for f in glob.glob(full_pattern, recursive=True):
                if os.path.isfile(f) and not any(ign in f for ign in [".git", "node_modules", ".venv", "venv"]):
                    matched_files.add(os.path.realpath(f))

        for filepath in sorted(matched_files):
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
            except Exception:
                continue

            rel_path = os.path.relpath(filepath, repo_path).replace("\\", "/")
            title, status, context, decision, consequences = cls._parse_adr_content(text, rel_path)

            content_parts = []
            if status:
                content_parts.append(f"Status: {status}")
            if context:
                content_parts.append(f"Context & Rationale:\n{context}")
            if decision:
                content_parts.append(f"Decision:\n{decision}")
            if consequences:
                content_parts.append(f"Consequences:\n{consequences}")

            full_content = "\n\n".join(content_parts) if content_parts else text[:1200]

            item = OrgMemoryItem(
                item_id=f"adr:{rel_path}",
                memory_type="adr",
                title=title,
                author="Architectural Committee / Lead",
                date_str=time.strftime("%Y-%m-%d", time.gmtime(os.path.getmtime(filepath))),
                content=full_content,
                files_touched=[],
                metadata={
                    "file_path": rel_path,
                    "status": status or "Accepted",
                },
            )
            items.append(item)

        return items

    @staticmethod
    def _parse_adr_content(content: str, fallback_title: str) -> Tuple[str, str, str, str, str]:
        lines = content.splitlines()
        title = fallback_title
        status = ""
        context = ""
        decision = ""
        consequences = ""

        # Find title (# Title)
        for line in lines:
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

        # Extract sections using regex
        status_match = re.search(r"(?:##\s*Status\s*\n+)(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
        if status_match:
            status = status_match.group(1).strip()

        context_match = re.search(r"(?:##\s*(?:Context|Rationale|Background)\s*\n+)(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
        if context_match:
            context = context_match.group(1).strip()

        decision_match = re.search(r"(?:##\s*(?:Decision|Choice)\s*\n+)(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
        if decision_match:
            decision = decision_match.group(1).strip()

        consequences_match = re.search(r"(?:##\s*(?:Consequences|Impact)\s*\n+)(.*?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
        if consequences_match:
            consequences = consequences_match.group(1).strip()

        return title, status, context, decision, consequences


class OrgMemoryStore:
    """
    Manages vector index and retrieval for organizational memory items
    (Git commits, ADRs, PR decisions).
    """

    def __init__(self, repo_id: str, embedder: Optional[BaseEmbedder] = None):
        self.repo_id = repo_id
        self.embedder = embedder or TfidfEmbedder(dim=32)
        self.items: List[OrgMemoryItem] = []
        self.vector_store: Optional[FaissVectorStore] = None

    def _rebuild_index(self):
        """Builds or rebuilds unified vector index across all memory items."""
        if not self.items:
            dim = getattr(self.embedder, "dim", 32)
            self.vector_store = FaissVectorStore(dim=dim)
            return

        if isinstance(self.embedder, TfidfEmbedder):
            self.embedder = TfidfEmbedder(dim=self.embedder.dim)

        chunks: List[CodeChunk] = []
        texts: List[str] = []
        for item in self.items:
            c = CodeChunk(
                chunk_id=item.item_id,
                file_path=item.metadata.get("file_path", item.item_id),
                language="markdown" if item.memory_type == "adr" else "git-commit",
                kind=item.memory_type,
                name=item.title,
                start_line=1,
                end_line=max(1, len(item.content.splitlines())),
                code=item.content,
            )
            chunks.append(c)
            texts.append(item.as_embedding_text())

        vectors = self.embedder.embed(texts)
        dim = vectors.shape[1]
        self.vector_store = FaissVectorStore(dim=dim)
        self.vector_store.add(chunks, vectors)

    def ingest_repository(self, repo_path: str, max_commits: int = 150) -> Dict[str, Any]:
        """Scans Git commits and ADR documents, then builds organizational vector index."""
        commits = GitHistoryMiner.mine_commits(repo_path, max_commits=max_commits)
        adrs = ADRMiner.mine_adrs(repo_path)

        all_items = adrs + commits
        self.items = all_items
        self._rebuild_index()

        return {
            "repo_id": self.repo_id,
            "total_items": len(self.items),
            "commits_count": len(commits),
            "adrs_count": len(adrs),
        }

    def add_custom_item(self, item: OrgMemoryItem):
        """Allows programmatic addition of PR discussions or design memos."""
        self.items.append(item)
        self._rebuild_index()

    def search(
        self,
        query: str,
        top_k: int = 5,
        memory_type_filter: Optional[str] = None,
    ) -> List[Tuple[OrgMemoryItem, float]]:
        """Hybrid semantic + lexical keyword search over organizational memory items."""
        if not self.items:
            return []

        q_tokens = set(re.findall(r"\w+", query.lower()))

        dense_scores: Dict[str, float] = {}
        if self.vector_store and self.vector_store.index and self.vector_store.index.ntotal > 0:
            try:
                q_vec = self.embedder.embed([query])[0]
                raw_results = self.vector_store.search(q_vec, top_k=min(len(self.items), top_k * 3))
                for chunk, score in raw_results:
                    dense_scores[chunk.chunk_id] = float(score)
            except Exception:
                pass

        scored_items: List[Tuple[OrgMemoryItem, float]] = []
        for item in self.items:
            if memory_type_filter and item.memory_type != memory_type_filter:
                continue

            item_text = f"{item.title} {item.content}".lower()
            item_tokens = set(re.findall(r"\w+", item_text))
            overlap = len(q_tokens.intersection(item_tokens))
            lex_score = overlap / max(1, len(q_tokens))

            d_score = dense_scores.get(item.item_id, 0.0)
            composite_score = d_score + (2.0 * lex_score)
            scored_items.append((item, composite_score))

        scored_items.sort(key=lambda x: x[1], reverse=True)
        return scored_items[:top_k]

    def ask(
        self,
        question: str,
        top_k: int = 5,
        memory_type_filter: Optional[str] = None,
        llm: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Answers historical design, architecture, and change rationale queries
        synthesizing retrieved commits, ADRs, and decisions with citations.
        """
        results = self.search(question, top_k=top_k, memory_type_filter=memory_type_filter)

        context_items = []
        citations = []
        for item, score in results:
            citations.append(item.citation)
            context_items.append({
                "item_id": item.item_id,
                "type": item.memory_type,
                "title": item.title,
                "author": item.author,
                "date": item.date_str,
                "citation": item.citation,
                "score": round(float(score), 3),
                "summary": item.content[:400],
                "files_touched": item.files_touched,
            })

        answer = ""
        if llm and hasattr(llm, "generate") and context_items:
            prompt_context = "\n\n".join(
                f"[{it['citation']}] {it['type'].upper()} by {it['author']} on {it['date']}: {it['title']}\n{it['summary']}"
                for it in context_items
            )
            prompt = (
                f"You are the IntelliCodeX Organizational Memory Assistant.\n"
                f"Answer the developer's question regarding historical architectural decisions and code changes.\n"
                f"Question: {question}\n\n"
                f"Historical Records Context:\n{prompt_context}\n\n"
                f"Explain clearly WHY decisions were made, referencing the citations in brackets."
            )
            try:
                answer = llm.generate(prompt, temperature=0.1)
            except Exception as e:
                answer = f"Error generating historical rationale answer: {e}"

        if not answer:
            # Deterministic fallback summary
            if context_items:
                top = context_items[0]
                lines = [
                    f"Historical memory search found {len(context_items)} relevant record(s).",
                    f"Most relevant record: {top['citation']} - '{top['title']}' by {top['author']} ({top['date']}).",
                ]
                if top["summary"]:
                    lines.append(f"Summary: {top['summary'].splitlines()[0]}")
                answer = " ".join(lines)
            else:
                answer = "No historical commits, ADRs, or architectural decisions matched your query."

        return {
            "repo_id": self.repo_id,
            "question": question,
            "answer": answer,
            "citations": citations,
            "retrieved_records": context_items,
            "confidence_score": round(min(0.95, 0.5 + 0.1 * len(context_items)), 2),
        }
