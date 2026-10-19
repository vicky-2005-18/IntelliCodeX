"""
Distributed Organizational Memory Engine (REQ-FUT-09).
Mines historical Git commit logs, Architectural Decision Records (ADRs),
pull request discussions, verified repair experiences, and developer design decisions
to answer historical rationale queries ("Why was X chosen over Y?", "Who changed file Z and why?").

Enforces multi-tenant organization boundaries, repository-private access barriers,
lifecycle states (active, superseded, invalidated), atomic multi-process file locking,
and non-automatic verification of generated text.
"""
import os
import re
import glob
import time
import uuid
import json
import threading
import subprocess
import contextlib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple, Set

from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder, TfidfEmbedder


@contextlib.contextmanager
def file_process_lock(lock_path: str, timeout: float = 10.0):
    """
    Acquires an exclusive OS-level process lock for cross-process synchronization.
    Supports Windows (msvcrt) and Unix (fcntl) with timeout and cleanup.
    """
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    lock_file = None
    start = time.time()

    while True:
        try:
            lock_file = open(lock_path, "a+")
            if os.name == "nt":
                import msvcrt
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except (IOError, OSError):
            if lock_file:
                try:
                    lock_file.close()
                except Exception:
                    pass
                lock_file = None
            if time.time() - start >= timeout:
                raise TimeoutError(f"Could not acquire multi-process lock on '{lock_path}' within {timeout}s")
            time.sleep(0.05)

    try:
        yield
    finally:
        if lock_file:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                try:
                    lock_file.close()
                except Exception:
                    pass


@dataclass
class OrgMemoryItem:
    item_id: str                      # e.g., 'commit:a1b2c3d', 'adr:0001-use-faiss.md', 'decision:d-01'
    memory_type: str                  # 'decision' | 'adr' | 'commit' | 'repair' | 'summary' | 'pr'
    title: str
    author: str
    date_str: str
    content: str
    org_id: str = "default_org"       # Tenant / organization boundary
    repo_id: Optional[str] = None     # Repository scope (None for org-wide)
    scope: str = "repo_private"       # 'repo_private' (default) | 'org_shared'
    verification_status: str = "unverified" # 'verified' | 'unverified' | 'developer_approved' | 'rejected'
    security_policy: str = "unscanned" # 'strict' | 'secrets_only' | 'unscanned'
    state: str = "active"             # 'active' | 'superseded' | 'invalidated'
    superseded_by: Optional[str] = None
    invalidation_reason: Optional[str] = None
    source_references: List[str] = field(default_factory=list)
    files_touched: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    citation: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def memory_id(self) -> str:
        return self.item_id

    def __post_init__(self):
        if not self.citation:
            if self.memory_type == "commit":
                clean_id = self.item_id.replace("commit:", "")
                self.citation = f"[commit:{clean_id[:8]}]"
            elif self.memory_type == "adr":
                self.citation = f"[adr:{self.metadata.get('file_path', self.title)}]"
            elif self.memory_type == "decision":
                prefix = f"{self.repo_id}:" if self.repo_id else ""
                clean_id = self.item_id.replace("decision:", "")
                self.citation = f"[decision:{prefix}{clean_id[:10]}]"
            elif self.memory_type == "repair":
                clean_id = self.item_id.replace("repair:", "")
                self.citation = f"[repair:{clean_id[:12]}]"
            elif self.memory_type == "summary":
                clean_id = self.item_id.replace("summary:", "")
                self.citation = f"[summary:{clean_id[:10]}]"
            else:
                self.citation = f"[{self.memory_type}:{self.item_id}]"

    def is_accessible(
        self,
        user_id: str,
        user_role: str,
        user_org_id: str,
        accessible_repos: Optional[Set[str]] = None,
        include_inactive: bool = False,
    ) -> bool:
        """
        Enforces tenant, repository, scope, and lifecycle boundaries.
        """
        # Inactive check
        if not include_inactive and self.state != "active":
            return False

        # Tenant boundary: different organizations can NEVER access each other's memories
        if self.org_id != user_org_id:
            return False

        # Admin role within same organization has access
        if user_role == "admin":
            return True

        # Scope: org_shared is accessible to all verified members of the organization
        if self.scope == "org_shared":
            return True

        # Scope: repo_private requires explicit repository access
        if self.scope == "repo_private":
            if self.repo_id:
                if accessible_repos and self.repo_id in accessible_repos:
                    return True
                if self.author == user_id:
                    return True
                return False
            # Unbound repo_private item is restricted to author
            return self.author == user_id

        return False

    def as_embedding_text(self) -> str:
        parts = [
            f"Type: {self.memory_type.upper()}",
            f"Scope: {self.scope}",
            f"Title: {self.title}",
            f"Author: {self.author}",
            f"Status: {self.verification_status}",
            f"Date: {self.date_str}",
        ]
        if self.files_touched:
            parts.append(f"Files: {', '.join(self.files_touched[:15])}")
        if self.source_references:
            parts.append(f"Sources: {', '.join(self.source_references[:10])}")
        parts.append(f"Description:\n{self.content}")
        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrgMemoryItem":
        valid_keys = {
            "item_id", "memory_type", "title", "author", "date_str", "content",
            "org_id", "repo_id", "scope", "verification_status", "security_policy",
            "state", "superseded_by", "invalidation_reason", "source_references",
            "files_touched", "metadata", "citation", "created_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        # Backward compatibility fallbacks
        if "item_id" not in filtered and "memory_id" in data:
            filtered["item_id"] = data["memory_id"]
        if "org_id" not in filtered:
            filtered["org_id"] = "default_org"
        if "scope" not in filtered:
            filtered["scope"] = "repo_private"
        if "verification_status" not in filtered:
            filtered["verification_status"] = "unverified"
        if "security_policy" not in filtered:
            filtered["security_policy"] = "unscanned"
        if "state" not in filtered:
            filtered["state"] = "active"
        if "source_references" not in filtered:
            filtered["source_references"] = []
        return cls(**filtered)


class GitHistoryMiner:
    """Mines Git repository commit messages, authors, dates, and touched files."""

    @staticmethod
    def mine_commits(repo_path: str, max_commits: int = 150) -> List[OrgMemoryItem]:
        items: List[OrgMemoryItem] = []
        if not os.path.isdir(repo_path) or not os.path.exists(os.path.join(repo_path, ".git")):
            return items

        # Format: Hash%x1fAuthor%x1fDate%x1fSubject%x1fBody%x1e
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
                scope="repo_private",
                verification_status="verified",
                state="active",
                files_touched=file_lines,
                source_references=[f"git:{commit_hash[:8]}"],
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
                scope="org_shared",
                verification_status="verified",
                state="active",
                source_references=[rel_path],
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

        for line in lines:
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                break

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
    Thread-safe, multi-process safe, file-backed repository of organizational knowledge.
    Enforces distinct memory types, tenant boundaries, repository scopes,
    multi-process file locking, and vector retrieval.
    """

    def __init__(
        self,
        repo_id: Optional[str] = None,
        org_id: str = "default_org",
        storage_dir: Optional[str] = None,
        embedder: Optional[BaseEmbedder] = None,
    ):
        self.repo_id = repo_id
        self.org_id = org_id
        self.embedder = embedder or TfidfEmbedder(dim=32)
        self.items: List[OrgMemoryItem] = []
        self.vector_store: Optional[FaissVectorStore] = None
        self._thread_lock = threading.Lock()

        # Disk storage configuration
        if storage_dir:
            self.storage_dir = storage_dir
        else:
            repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            base_storage = os.environ.get("STORAGE_DIR") or os.path.join(repo_root, ".storage")
            self.storage_dir = os.path.join(base_storage, "org_memory")
        os.makedirs(self.storage_dir, exist_ok=True)
        store_key = f"{org_id}_{repo_id}" if repo_id else f"{org_id}_org_shared"
        safe_key = re.sub(r"[^\w\-.]", "_", store_key)
        self.storage_path = os.path.join(self.storage_dir, f"{safe_key}.json")
        self.lock_path = os.path.join(self.storage_dir, f"{safe_key}.lock")

        # Load persisted items from disk
        self._load()

    def _load(self):
        with self._thread_lock:
            with file_process_lock(self.lock_path):
                if os.path.isfile(self.storage_path):
                    try:
                        with open(self.storage_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        self.items = [OrgMemoryItem.from_dict(d) for d in data]
                    except Exception:
                        pass
        self._rebuild_index()

    def _persist(self):
        """
        Atomic multi-process safe persistence using process file lock and temporary replacement.
        Guarantees that a failed write cannot corrupt the existing storage file.
        """
        with self._thread_lock:
            with file_process_lock(self.lock_path):
                temp_path = os.path.join(self.storage_dir, f".tmp_{uuid.uuid4().hex[:8]}.tmp")
                try:
                    with open(temp_path, "w", encoding="utf-8") as f:
                        json.dump([item.to_dict() for item in self.items], f, indent=2)
                    os.replace(temp_path, self.storage_path)
                except Exception:
                    if os.path.exists(temp_path):
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                    raise

    def _rebuild_index(self):
        """Builds or rebuilds unified vector index across all active memory items."""
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
                language="markdown" if item.memory_type == "adr" else "text",
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
        """Scans Git commits and ADR documents, stores them, and rebuilds vector index."""
        commits = GitHistoryMiner.mine_commits(repo_path, max_commits=max_commits)
        adrs = ADRMiner.mine_adrs(repo_path)

        for c in commits:
            c.org_id = self.org_id
            c.repo_id = self.repo_id
        for a in adrs:
            a.org_id = self.org_id
            a.repo_id = self.repo_id

        # Merge with existing, deduplicating by item_id
        existing_ids = {it.item_id for it in self.items}
        for item in adrs + commits:
            if item.item_id not in existing_ids:
                self.items.append(item)
                existing_ids.add(item.item_id)

        self._persist()
        self._rebuild_index()

        return {
            "repo_id": self.repo_id,
            "total_items": len(self.items),
            "commits_count": len([i for i in self.items if i.memory_type == "commit"]),
            "adrs_count": len([i for i in self.items if i.memory_type == "adr"]),
        }

    def add_custom_item(self, item: OrgMemoryItem):
        """Allows programmatic addition of custom memory items."""
        # Ensure org_id is aligned if default
        if item.org_id == "default_org" and self.org_id != "default_org":
            item.org_id = self.org_id
        if item.repo_id is None and self.repo_id is not None:
            item.repo_id = self.repo_id

        # Replace existing or append
        existing_idx = next((i for i, it in enumerate(self.items) if it.item_id == item.item_id), None)
        if existing_idx is not None:
            self.items[existing_idx] = item
        else:
            self.items.append(item)

        self._persist()
        self._rebuild_index()

    def record_decision(
        self,
        title: str,
        content: str,
        author: str,
        repo_id: Optional[str] = None,
        scope: str = "repo_private",
        source_references: Optional[List[str]] = None,
        files_touched: Optional[List[str]] = None,
        item_id: Optional[str] = None,
    ) -> OrgMemoryItem:
        """
        Records a developer-authored architectural or code design decision.
        Tagged with verification_status='developer_approved'.
        """
        effective_repo = repo_id or self.repo_id
        item = OrgMemoryItem(
            item_id=item_id or f"decision:{uuid.uuid4().hex[:8]}",
            memory_type="decision",
            title=title,
            author=author,
            date_str=time.strftime("%Y-%m-%d"),
            content=content,
            org_id=self.org_id,
            repo_id=effective_repo,
            scope=scope,
            verification_status="developer_approved",
            security_policy="unscanned",
            state="active",
            source_references=source_references or [],
            files_touched=files_touched or [],
        )
        self.add_custom_item(item)
        return item

    def record_repair(
        self,
        title: str,
        content: str,
        author: str,
        security_policy: str = "strict",
        test_verified: bool = True,
        developer_approved: bool = True,
        repo_id: Optional[str] = None,
        scope: str = "repo_private",
        source_references: Optional[List[str]] = None,
        item_id: Optional[str] = None,
    ) -> OrgMemoryItem:
        """
        Records a verified repair experience, preserving security policy provenance.
        """
        effective_repo = repo_id or self.repo_id
        is_verified = test_verified and developer_approved
        item = OrgMemoryItem(
            item_id=item_id or f"repair:{uuid.uuid4().hex[:8]}",
            memory_type="repair",
            title=title,
            author=author,
            date_str=time.strftime("%Y-%m-%d"),
            content=content,
            org_id=self.org_id,
            repo_id=effective_repo,
            scope=scope,
            verification_status="verified" if is_verified else "unverified",
            security_policy=security_policy,
            state="active",
            source_references=source_references or [],
        )
        self.add_custom_item(item)
        return item

    def record_summary(
        self,
        title: str,
        content: str,
        author: str = "ai_doc_generator",
        repo_id: Optional[str] = None,
        scope: str = "repo_private",
        source_references: Optional[List[str]] = None,
        item_id: Optional[str] = None,
    ) -> OrgMemoryItem:
        """
        Records an automated or AI-generated summary.
        Generated text MUST NOT become verified knowledge automatically.
        Always tagged with verification_status='unverified'.
        """
        effective_repo = repo_id or self.repo_id
        item = OrgMemoryItem(
            item_id=item_id or f"summary:{uuid.uuid4().hex[:8]}",
            memory_type="summary",
            title=title,
            author=author,
            date_str=time.strftime("%Y-%m-%d"),
            content=content,
            org_id=self.org_id,
            repo_id=effective_repo,
            scope=scope,
            verification_status="unverified",  # Invariant: generated summaries are never auto-verified
            security_policy="unscanned",
            state="active",
            source_references=source_references or [],
        )
        self.add_custom_item(item)
        return item

    def invalidate_record(self, item_id: str, reason: str, user_id: str) -> bool:
        """
        Invalidates a record and excludes it from active retrieval.
        """
        found = False
        for it in self.items:
            if it.item_id == item_id or it.memory_id == item_id:
                it.state = "invalidated"
                it.invalidation_reason = f"{reason} (by {user_id})"
                found = True
                break
        if found:
            self._persist()
            self._rebuild_index()
        return found

    def supersede_record(self, old_item_id: str, new_item: OrgMemoryItem) -> bool:
        """
        Supersedes an old record with a newly approved version.
        """
        found = False
        for it in self.items:
            if it.item_id == old_item_id or it.memory_id == old_item_id:
                it.state = "superseded"
                it.superseded_by = new_item.item_id
                found = True
                break
        if found:
            new_item.state = "active"
            self.items.append(new_item)
            self._persist()
            self._rebuild_index()
        return found

    def sync_from_repair_bank(
        self,
        experience_bank: Any,
        repo_id: Optional[str] = None,
        scope: str = "repo_private",
    ) -> int:
        """
        Reuses existing RepairExperienceBank records without creating duplicate storage.
        Preserves test_verified, developer_approved, and security_policy provenance.
        """
        target_repo = repo_id or self.repo_id
        if hasattr(experience_bank, "experiences"):
            candidates = list(experience_bank.experiences.values())
            experiences = [
                exp for exp in candidates
                if exp.is_active and (target_repo is None or exp.repo_id == target_repo or not exp.repo_id)
            ]
        elif hasattr(experience_bank, "get_experiences"):
            experiences = experience_bank.get_experiences(
                repo_id=target_repo,
                include_public=False,
                strict_security_only=False,
            )
        else:
            experiences = []

        existing_ids = {it.item_id for it in self.items}
        added = 0
        for exp in experiences:
            exp_item_id = f"repair:{exp.experience_id}"
            if exp_item_id in existing_ids:
                continue
            item = OrgMemoryItem(
                item_id=exp_item_id,
                memory_type="repair",
                title=f"Repair for {exp.error_type}: {exp.error_description[:60]}",
                author=exp.source,
                date_str=time.strftime("%Y-%m-%d", time.gmtime(exp.created_at)),
                content=f"Error: {exp.error_description}\nExplanation: {exp.explanation}\nFixed Code:\n{exp.fixed_code}",
                org_id=self.org_id,
                repo_id=exp.repo_id or target_repo,
                scope=scope,
                verification_status="verified" if (exp.test_verified and exp.developer_approved) else "unverified",
                security_policy=exp.security_policy,
                state="active" if exp.is_active else "invalidated",
                files_touched=exp.tags,
                source_references=[f"experience:{exp.experience_id}"],
            )
            self.items.append(item)
            existing_ids.add(exp_item_id)
            added += 1

        if added > 0:
            self._persist()
            self._rebuild_index()
        return added

    def search(
        self,
        query: str,
        top_k: int = 5,
        memory_type_filter: Optional[str] = None,
        user_id: Optional[str] = None,
        user_role: str = "developer",
        user_org_id: Optional[str] = None,
        accessible_repos: Optional[Set[str]] = None,
        include_inactive: bool = False,
        security_policy_filter: Optional[str] = None,
    ) -> List[Tuple[OrgMemoryItem, float]]:
        """
        Hybrid semantic + lexical keyword search over organizational memory items.
        Applies tenant authorization, repository scope, lifecycle filtering, and
        security policy verification before calculating relevance.
        """
        if not self.items:
            return []

        # Default authorization context for backward compatibility
        effective_user_id = user_id or "anonymous"
        effective_org_id = user_org_id or self.org_id
        effective_role = user_role if user_id is not None else "admin"

        # 1. Authorize and filter items
        authorized_items: List[OrgMemoryItem] = []
        for it in self.items:
            if not it.is_accessible(
                user_id=effective_user_id,
                user_role=effective_role,
                user_org_id=effective_org_id,
                accessible_repos=accessible_repos,
                include_inactive=include_inactive,
            ):
                continue

            if memory_type_filter and it.memory_type != memory_type_filter:
                continue

            if security_policy_filter == "strict":
                if it.memory_type == "repair" and it.security_policy != "strict":
                    continue

            authorized_items.append(it)

        if not authorized_items:
            return []

        q_tokens = set(re.findall(r"\w+", query.lower()))

        dense_scores: Dict[str, float] = {}
        if self.vector_store and self.vector_store.index and self.vector_store.index.ntotal > 0:
            try:
                q_vec = self.embedder.embed([query])[0]
                raw_results = self.vector_store.search(q_vec, top_k=min(len(self.items), top_k * 4))
                for chunk, score in raw_results:
                    dense_scores[chunk.chunk_id] = float(score)
            except Exception:
                pass

        scored_items: List[Tuple[OrgMemoryItem, float]] = []
        for item in authorized_items:
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
        user_id: Optional[str] = None,
        user_role: str = "developer",
        user_org_id: Optional[str] = None,
        accessible_repos: Optional[Set[str]] = None,
        include_inactive: bool = False,
        security_policy_filter: Optional[str] = None,
        llm: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Answers historical design, architecture, and change rationale queries
        synthesizing authorized commits, ADRs, decisions, and repairs with citations.
        """
        results = self.search(
            question,
            top_k=top_k,
            memory_type_filter=memory_type_filter,
            user_id=user_id,
            user_role=user_role,
            user_org_id=user_org_id,
            accessible_repos=accessible_repos,
            include_inactive=include_inactive,
            security_policy_filter=security_policy_filter,
        )

        context_items = []
        citations = []
        for item, score in results:
            citations.append(item.citation)
            context_items.append({
                "item_id": item.item_id,
                "memory_id": item.memory_id,
                "type": item.memory_type,
                "title": item.title,
                "author": item.author,
                "date": item.date_str,
                "scope": item.scope,
                "verification_status": item.verification_status,
                "security_policy": item.security_policy,
                "state": item.state,
                "citation": item.citation,
                "score": round(float(score), 3),
                "summary": item.content[:400],
                "source_references": item.source_references,
                "files_touched": item.files_touched,
            })

        answer = ""
        if llm and hasattr(llm, "generate") and context_items:
            prompt_context = "\n\n".join(
                f"[{it['citation']}] {it['type'].upper()} ({it['verification_status']}) by {it['author']} on {it['date']}: {it['title']}\n{it['summary']}"
                for it in context_items
            )
            prompt = (
                f"You are the IntelliCodeX Organizational Memory Assistant.\n"
                f"Answer the developer's question regarding historical architectural decisions and code changes.\n"
                f"Question: {question}\n\n"
                f"Authorized Historical Records Context:\n{prompt_context}\n\n"
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
                    f"Historical memory search found {len(context_items)} authorized record(s).",
                    f"Most relevant record: {top['citation']} - '{top['title']}' [{top['type']}, status: {top['verification_status']}] by {top['author']} ({top['date']}).",
                ]
                if top["summary"]:
                    lines.append(f"Summary: {top['summary'].splitlines()[0]}")
                answer = " ".join(lines)
            else:
                answer = "No authorized historical commits, ADRs, or architectural decisions matched your query."

        return {
            "repo_id": self.repo_id,
            "org_id": user_org_id or self.org_id,
            "question": question,
            "answer": answer,
            "citations": citations,
            "retrieved_records": context_items,
            "confidence_score": round(min(0.95, 0.5 + 0.1 * len(context_items)), 2),
        }
