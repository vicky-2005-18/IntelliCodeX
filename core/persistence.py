"""
Index Persistence & Metadata Database Manager
Uses SQLite (.storage/metadata.db) to store file hashes, modification times, language metadata,
and extracted code chunks for instant CLI startup and incremental re-indexing.
"""
import os
import sys
import json
import sqlite3
import hashlib
import time
from typing import List, Dict, Optional, Tuple, Any, Set
from dataclasses import dataclass

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.parser import SourceFile
from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore


def get_storage_dir() -> str:
    """Returns the intended application storage directory (.storage), respecting STORAGE_DIR or project root."""
    env_dir = os.environ.get("STORAGE_DIR")
    if env_dir:
        return os.path.abspath(env_dir)
    return os.path.join(repo_root, ".storage")


def get_default_db_path() -> str:
    """Returns the default SQLite database path (.storage/metadata.db)."""
    return os.path.join(get_storage_dir(), "metadata.db")


DEFAULT_DB_PATH = get_default_db_path()
GRAPH_FORMAT_VERSION: int = 3


def compute_file_hash(content: str) -> str:
    """Computes SHA-256 hash of file content for fast change detection."""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Creates database directory if missing and returns a connected SQLite instance."""
    eff_db_path = db_path if db_path is not None else get_default_db_path()
    db_dir = os.path.dirname(os.path.abspath(eff_db_path))
    os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(eff_db_path)
    conn.row_factory = sqlite3.Row
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection):
    """Initializes SQLite database tables for repos, files, and code chunks."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS repos (
                repo_id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                backend TEXT DEFAULT 'tfidf',
                total_files INTEGER DEFAULT 0,
                total_chunks INTEGER DEFAULT 0,
                last_indexed_at REAL NOT NULL,
                graph_version INTEGER DEFAULT 1,
                skip_overloads INTEGER DEFAULT 1
            );
        """)
        try:
            conn.execute("ALTER TABLE repos ADD COLUMN graph_version INTEGER DEFAULT 1;")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE repos ADD COLUMN skip_overloads INTEGER DEFAULT 1;")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE repos ADD COLUMN embedding_dim INTEGER DEFAULT 0;")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE repos ADD COLUMN model_name TEXT DEFAULT '';")
        except Exception:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                repo_id TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                mtime REAL NOT NULL,
                size_bytes INTEGER DEFAULT 0,
                line_count INTEGER DEFAULT 0,
                language TEXT NOT NULL,
                has_tree_sitter INTEGER DEFAULT 0,
                PRIMARY KEY (repo_id, rel_path)
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                repo_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                language TEXT NOT NULL,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                code TEXT NOT NULL,
                docstring TEXT,
                imports_json TEXT,
                FOREIGN KEY (repo_id, file_path) REFERENCES files (repo_id, rel_path) ON DELETE CASCADE
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS unregistered_repos (
                repo_path TEXT PRIMARY KEY,
                unregistered_at REAL NOT NULL
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id TEXT NOT NULL,
                turn_index INTEGER NOT NULL,
                query TEXT NOT NULL,
                response TEXT NOT NULL,
                files_json TEXT,
                timestamp REAL NOT NULL
            );
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                target_file TEXT NOT NULL,
                proposal_id TEXT NOT NULL,
                verification_outcome TEXT NOT NULL,
                save_outcome TEXT NOT NULL,
                summary TEXT,
                details_json TEXT,
                timestamp REAL NOT NULL
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_repo ON conversation_turns(repo_id, id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_act_repo ON activity_records(repo_id, id);")



def save_repo_metadata(
    conn: sqlite3.Connection,
    repo_id: str,
    repo_path: str,
    backend: str,
    source_files: List[SourceFile],
    chunks: List[CodeChunk],
    graph_version: int = GRAPH_FORMAT_VERSION,
    skip_overload_stubs: bool = True,
    embedding_dim: int = 0,
    model_name: str = "",
):
    """Saves or updates repository metadata, file hashes, and code chunks in SQLite."""
    now = time.time()
    with conn:
        # Clear unregistered status if this repository path was previously unregistered
        try:
            norm_p = os.path.normcase(os.path.abspath(repo_path))
            conn.execute("DELETE FROM unregistered_repos WHERE repo_path = ?", (norm_p,))
            conn.execute("DELETE FROM unregistered_repos WHERE repo_path = ?", (os.path.abspath(repo_path),))
        except Exception:
            pass

        # 1. Update repos table
        conn.execute("""
            INSERT INTO repos (repo_id, repo_path, backend, total_files, total_chunks, last_indexed_at, graph_version, skip_overloads, embedding_dim, model_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET
                repo_path=excluded.repo_path,
                backend=excluded.backend,
                total_files=excluded.total_files,
                total_chunks=excluded.total_chunks,
                last_indexed_at=excluded.last_indexed_at,
                graph_version=excluded.graph_version,
                skip_overloads=excluded.skip_overloads,
                embedding_dim=excluded.embedding_dim,
                model_name=excluded.model_name;
        """, (
            repo_id,
            os.path.abspath(repo_path),
            backend,
            len(source_files),
            len(chunks),
            now,
            graph_version,
            1 if skip_overload_stubs else 0,
            embedding_dim,
            model_name,
        ))

        # 2. Synchronize files table (remove deleted files, upsert current files)
        current_rel_paths = {sf.rel_path for sf in source_files}
        cursor = conn.execute("SELECT rel_path FROM files WHERE repo_id = ?", (repo_id,))
        existing_stored_paths = {row["rel_path"] for row in cursor.fetchall()}
        deleted_stored_paths = list(existing_stored_paths - current_rel_paths)
        if deleted_stored_paths:
            delete_files_from_db(conn, repo_id, deleted_stored_paths)

        for sf in source_files:
            f_hash = compute_file_hash(sf.content)
            mtime = os.path.getmtime(sf.path) if os.path.exists(sf.path) else now
            conn.execute("""
                INSERT INTO files (repo_id, rel_path, file_hash, mtime, size_bytes, line_count, language, has_tree_sitter)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id, rel_path) DO UPDATE SET
                    file_hash=excluded.file_hash,
                    mtime=excluded.mtime,
                    size_bytes=excluded.size_bytes,
                    line_count=excluded.line_count,
                    language=excluded.language,
                    has_tree_sitter=excluded.has_tree_sitter;
            """, (repo_id, sf.rel_path, f_hash, mtime, sf.size_bytes, sf.line_count, sf.language, 1 if sf.has_tree_sitter else 0))

        # 3. Clear old chunks for repo and insert new chunks
        conn.execute("DELETE FROM chunks WHERE repo_id = ?", (repo_id,))
        for c in chunks:
            imports_str = json.dumps(c.imports) if c.imports else "[]"
            conn.execute("""
                INSERT OR REPLACE INTO chunks (chunk_id, repo_id, file_path, language, kind, name, start_line, end_line, code, docstring, imports_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (c.chunk_id, repo_id, c.file_path, c.language, c.kind, c.name, c.start_line, c.end_line, c.code, c.docstring, imports_str))


def load_stored_file_hashes(conn: sqlite3.Connection, repo_id: str) -> Dict[str, str]:
    """Returns a dict mapping rel_path -> file_hash for the specified repo_id."""
    cursor = conn.execute("SELECT rel_path, file_hash FROM files WHERE repo_id = ?", (repo_id,))
    return {row["rel_path"]: row["file_hash"] for row in cursor.fetchall()}


def load_stored_chunks(conn: sqlite3.Connection, repo_id: str) -> List[CodeChunk]:
    """Loads all stored CodeChunk objects for the specified repo_id from SQLite."""
    cursor = conn.execute("""
        SELECT chunk_id, file_path, language, kind, name, start_line, end_line, code, docstring, imports_json
        FROM chunks WHERE repo_id = ?
    """, (repo_id,))

    chunks: List[CodeChunk] = []
    for row in cursor.fetchall():
        imports = json.loads(row["imports_json"]) if row["imports_json"] else []
        chunks.append(CodeChunk(
            chunk_id=row["chunk_id"],
            file_path=row["file_path"],
            language=row["language"],
            kind=row["kind"],
            name=row["name"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            code=row["code"],
            docstring=row["docstring"],
            imports=imports,
        ))
    return chunks


def load_repo_metadata(conn: sqlite3.Connection, repo_id: str) -> Optional[Dict[str, Any]]:
    """Loads top-level repository metadata from SQLite."""
    cursor = conn.execute("SELECT * FROM repos WHERE repo_id = ?", (repo_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return dict(row)


def get_repo_id(repo_path: str) -> str:
    """Generates a canonical, filesystem-friendly repository ID from a local path or Git URL."""
    clean_path = repo_path.strip().replace("\\", "/").rstrip("/")
    base = os.path.basename(clean_path) or "repo"
    if base.endswith(".git"):
        base = base[:-4]
    path_hash = hashlib.md5(os.path.abspath(clean_path).encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

    clean_base = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in base)
    return f"{clean_base}_{path_hash}"


def is_canonical_repo_id(repo_id: Optional[str]) -> bool:
    """
    Checks whether a repository ID is a canonical, path-hashed identity
    (i.e., formatted as '<base>_<8-char-hex-hash>'), rejecting missing,
    empty, or legacy basename-only identifiers.
    """
    if not repo_id or not isinstance(repo_id, str):
        return False
    parts = repo_id.rsplit("_", 1)
    if len(parts) != 2:
        return False
    base, hash_part = parts
    if not base or len(hash_part) != 8:
        return False
    try:
        int(hash_part, 16)
        return True
    except ValueError:
        return False


def unregister_repo(repo_path: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Removes a repository's registration from the persistent registry without deleting source files, Git history, or cache."""
    abs_p = os.path.abspath(repo_path)
    norm_p = os.path.normcase(abs_p)
    repo_id = get_repo_id(abs_p)
    conn = get_db_connection(db_path)
    try:
        init_schema(conn)
        with conn:
            # Delete from repos table matching either repo_id or normalized path
            rows = conn.execute("SELECT repo_id, repo_path FROM repos").fetchall()
            for r in rows:
                r_id = r["repo_id"] if isinstance(r, sqlite3.Row) else r[0]
                r_p = r["repo_path"] if isinstance(r, sqlite3.Row) else r[1]
                if r_id == repo_id or (r_p and os.path.normcase(os.path.abspath(r_p)) == norm_p):
                    conn.execute("DELETE FROM repos WHERE repo_id = ?", (r_id,))
            
            # Record in unregistered_repos table so scanning mechanisms (like .repos/ or sample_repo) also omit it
            conn.execute(
                "INSERT OR REPLACE INTO unregistered_repos (repo_path, unregistered_at) VALUES (?, ?)",
                (norm_p, time.time()),
            )
        return True
    finally:
        conn.close()


def clear_unregistered_repo(repo_path: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Clears a repository's unregistered state so that re-adding/indexing it will register it again."""
    abs_p = os.path.abspath(repo_path)
    norm_p = os.path.normcase(abs_p)
    conn = get_db_connection(db_path)
    try:
        init_schema(conn)
        with conn:
            conn.execute("DELETE FROM unregistered_repos WHERE repo_path = ?", (norm_p,))
            conn.execute("DELETE FROM unregistered_repos WHERE repo_path = ?", (abs_p,))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_unregistered_repos(db_path: str = DEFAULT_DB_PATH) -> set:
    """Returns a set of normalized absolute paths of unregistered repositories."""
    conn = get_db_connection(db_path)
    unregistered = set()
    try:
        init_schema(conn)
        rows = conn.execute("SELECT repo_path FROM unregistered_repos").fetchall()
        for r in rows:
            p = r["repo_path"] if isinstance(r, sqlite3.Row) else r[0]
            if p:
                unregistered.add(os.path.normcase(os.path.abspath(p)))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return unregistered


def is_repo_unregistered(repo_path: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Checks if a repository path has been explicitly unregistered."""
    if not os.path.exists(db_path):
        return False
    abs_p = os.path.abspath(repo_path)
    norm_p = os.path.normcase(abs_p)
    conn = get_db_connection(db_path)
    try:
        init_schema(conn)
        row = conn.execute(
            "SELECT 1 FROM unregistered_repos WHERE repo_path = ? OR repo_path = ?",
            (norm_p, abs_p),
        ).fetchone()
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()



def get_faiss_index_path(repo_id: str, storage_dir: Optional[str] = None) -> str:
    """Returns absolute file path for a repository's FAISS index (.storage/<repo_id>.faiss)."""
    target_dir = storage_dir if (storage_dir is not None and storage_dir != ".storage") else get_storage_dir()
    os.makedirs(target_dir, exist_ok=True)
    return os.path.abspath(os.path.join(target_dir, f"{repo_id}.faiss"))


def save_faiss_index(store: FaissVectorStore, repo_id: str, storage_dir: Optional[str] = None) -> str:
    """Serializes the FAISS vector index to disk (.storage/<repo_id>.faiss)."""
    faiss_path = get_faiss_index_path(repo_id, storage_dir)
    return store.save(faiss_path)


def load_faiss_index(
    repo_id: str,
    chunks: Optional[List[CodeChunk]] = None,
    storage_dir: Optional[str] = None
) -> Optional[FaissVectorStore]:
    """Deserializes a FAISS vector index from disk if it exists."""
    faiss_path = get_faiss_index_path(repo_id, storage_dir)
    if not os.path.exists(faiss_path):
        return None
    try:
        return FaissVectorStore.load(faiss_path, chunks=chunks)
    except Exception as e:
        print(f"[!] Warning: Failed to load FAISS index from '{faiss_path}': {e}")
        return None


def save_index(
    repo_path: str,
    backend: str,
    source_files: List[SourceFile],
    chunks: List[CodeChunk],
    store: FaissVectorStore,
    db_path: Optional[str] = None,
    storage_dir: Optional[str] = None,
    graph_version: int = GRAPH_FORMAT_VERSION,
    skip_overload_stubs: bool = True,
    embedding_dim: Optional[int] = None,
    model_name: str = "",
) -> Tuple[str, str]:
    """
    Unified high-level save function:
    1. Saves repository metadata, file hashes, and chunks to SQLite (.storage/metadata.db).
    2. Serializes FAISS vector store index to disk (.storage/<repo_id>.faiss).
    3. Validates invariants: unique chunk IDs, SQLite rows == FAISS ntotal == in-memory chunks.
    Returns (db_path, faiss_path).
    """
    eff_db = db_path if db_path is not None else get_default_db_path()
    eff_storage = storage_dir if (storage_dir is not None and storage_dir != ".storage") else (
        os.path.dirname(os.path.abspath(eff_db)) if eff_db else get_storage_dir()
    )
    repo_id = get_repo_id(repo_path)
    eff_dim = embedding_dim if embedding_dim is not None else (store.dim if (store and hasattr(store, "dim")) else 0)
    conn = get_db_connection(eff_db)
    try:
        save_repo_metadata(
            conn,
            repo_id,
            repo_path,
            backend,
            source_files,
            chunks,
            graph_version=graph_version,
            skip_overload_stubs=skip_overload_stubs,
            embedding_dim=eff_dim,
            model_name=model_name,
        )
        sqlite_row_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE repo_id = ?", (repo_id,)).fetchone()[0]
    finally:
        conn.close()

    faiss_path = save_faiss_index(store, repo_id, eff_storage)

    faiss_ntotal = store.index.ntotal if (store and hasattr(store, "index")) else len(chunks)
    in_mem_count = len(chunks)
    unique_ids_count = len(set(c.chunk_id for c in chunks))

    if not (unique_ids_count == in_mem_count == sqlite_row_count == faiss_ntotal):
        msg = (
            f"[!] Invariant violation at ingest for repo '{repo_id}': "
            f"unique_chunk_ids={unique_ids_count}, in-memory chunks={in_mem_count}, "
            f"SQLite chunk rows={sqlite_row_count}, FAISS ntotal={faiss_ntotal}."
        )
        raise ValueError(msg)

    return eff_db, faiss_path


def load_index(
    repo_path: str,
    db_path: Optional[str] = None,
    storage_dir: Optional[str] = None
) -> Optional[Tuple[Dict[str, Any], List[CodeChunk], FaissVectorStore]]:
    """
    Unified high-level load function:
    1. Loads repository metadata and code chunks from SQLite.
    2. Loads corresponding FAISS vector store from disk.
    Returns (meta_dict, chunks_list, faiss_store) if found, else None.
    """
    eff_db = db_path if db_path is not None else get_default_db_path()
    eff_storage = storage_dir if (storage_dir is not None and storage_dir != ".storage") else (
        os.path.dirname(os.path.abspath(eff_db)) if eff_db else get_storage_dir()
    )
    repo_id = get_repo_id(repo_path)
    if not os.path.exists(eff_db):
        return None

    conn = get_db_connection(eff_db)
    try:
        meta = load_repo_metadata(conn, repo_id)
        if not meta:
            return None
        chunks = load_stored_chunks(conn, repo_id)
    finally:
        conn.close()

    store = load_faiss_index(repo_id, chunks=chunks, storage_dir=eff_storage)
    if not store:
        return None

    return meta, chunks, store


@dataclass
class RepositoryDelta:
    added: List[SourceFile]
    modified: List[SourceFile]
    deleted: List[str]  # list of relative file paths
    unchanged: List[SourceFile]
    is_fresh_index: bool = False

    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    @property
    def total_changed_files(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)


def detect_repository_changes(
    repo_path: str,
    current_source_files: List[SourceFile],
    db_path: Optional[str] = None
) -> RepositoryDelta:
    """
    Compares current repository source files against stored SHA-256 hashes in SQLite.
    Categorizes files into added, modified, deleted, and unchanged.
    """
    eff_db = db_path if db_path is not None else get_default_db_path()
    repo_id = get_repo_id(repo_path)
    if not os.path.exists(eff_db):
        return RepositoryDelta(
            added=current_source_files,
            modified=[],
            deleted=[],
            unchanged=[],
            is_fresh_index=True
        )

    conn = get_db_connection(eff_db)
    try:
        stored_hashes = load_stored_file_hashes(conn, repo_id)
    finally:
        conn.close()

    if not stored_hashes:
        return RepositoryDelta(
            added=current_source_files,
            modified=[],
            deleted=[],
            unchanged=[],
            is_fresh_index=True
        )

    added: List[SourceFile] = []
    modified: List[SourceFile] = []
    unchanged: List[SourceFile] = []
    current_rel_paths = set()

    for sf in current_source_files:
        current_rel_paths.add(sf.rel_path)
        curr_hash = compute_file_hash(sf.content)

        if sf.rel_path not in stored_hashes:
            added.append(sf)
        elif stored_hashes[sf.rel_path] != curr_hash:
            modified.append(sf)
        else:
            unchanged.append(sf)

    deleted = [rel_path for rel_path in stored_hashes if rel_path not in current_rel_paths]

    return RepositoryDelta(
        added=added,
        modified=modified,
        deleted=deleted,
        unchanged=unchanged,
        is_fresh_index=False
    )


def delete_files_from_db(conn: sqlite3.Connection, repo_id: str, rel_paths: List[str]):
    """Removes deleted files and their associated code chunks from SQLite DB."""
    if not rel_paths:
        return
    with conn:
        placeholders = ",".join("?" for _ in rel_paths)
        conn.execute(f"DELETE FROM chunks WHERE repo_id = ? AND file_path IN ({placeholders})", [repo_id] + rel_paths)
        conn.execute(f"DELETE FROM files WHERE repo_id = ? AND rel_path IN ({placeholders})", [repo_id] + rel_paths)


def save_repo_turn(
    repo_id: str,
    query: str,
    response: str,
    files: Optional[List[str]] = None,
    max_stored_turns: int = 50,
    db_path: Optional[str] = None,
):
    """Persists a Q&A conversation turn scoped to a canonical repo_id."""
    conn = get_db_connection(db_path)
    now = time.time()
    files_json = json.dumps(files or [])
    try:
        with conn:
            cursor = conn.execute("SELECT COUNT(*) FROM conversation_turns WHERE repo_id = ?", (repo_id,))
            cnt = cursor.fetchone()[0]
            turn_idx = cnt + 1
            conn.execute(
                """
                INSERT INTO conversation_turns (repo_id, turn_index, query, response, files_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (repo_id, turn_idx, query, response, files_json, now),
            )
            # Prune oldest turns if exceeding max_stored_turns
            if cnt + 1 > max_stored_turns:
                excess = (cnt + 1) - max_stored_turns
                conn.execute(
                    """
                    DELETE FROM conversation_turns WHERE id IN (
                        SELECT id FROM conversation_turns WHERE repo_id = ? ORDER BY id ASC LIMIT ?
                    );
                    """,
                    (repo_id, excess),
                )
    finally:
        conn.close()

    # Mirror to db_manager for compatibility
    try:
        from backend.database.mongo import db_manager
        db_manager.insert("chat_history", {
            "repo_id": repo_id,
            "question": query,
            "answer": response,
            "files": files or [],
            "timestamp": now,
        })
    except Exception:
        pass


def save_repo_activity(
    repo_id: str,
    activity: Dict[str, Any],
    max_stored_activities: int = 100,
    db_path: Optional[str] = None,
):
    """Persists a creation or repair activity record scoped to a canonical repo_id."""
    conn = get_db_connection(db_path)
    now = activity.get("timestamp") or time.time()
    act_type = activity.get("activity_type", "activity")
    tgt = activity.get("target_file", "unknown")
    pid = activity.get("proposal_id", "unknown")
    v_out = activity.get("verification_outcome", "unknown")
    s_out = activity.get("save_outcome", "unknown")
    summary = activity.get("summary", "")
    details_json = json.dumps(activity.get("details") or {})
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO activity_records (repo_id, activity_type, target_file, proposal_id, verification_outcome, save_outcome, summary, details_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (repo_id, act_type, tgt, pid, v_out, s_out, summary, details_json, now),
            )
            cursor = conn.execute("SELECT COUNT(*) FROM activity_records WHERE repo_id = ?", (repo_id,))
            cnt = cursor.fetchone()[0]
            if cnt > max_stored_activities:
                excess = cnt - max_stored_activities
                conn.execute(
                    """
                    DELETE FROM activity_records WHERE id IN (
                        SELECT id FROM activity_records WHERE repo_id = ? ORDER BY id ASC LIMIT ?
                    );
                    """,
                    (repo_id, excess),
                )
    finally:
        conn.close()

    try:
        from backend.database.mongo import db_manager
        db_manager.insert("activity_history", {
            "repo_id": repo_id,
            "activity_type": act_type,
            "target_file": tgt,
            "proposal_id": pid,
            "verification_outcome": v_out,
            "save_outcome": s_out,
            "summary": summary,
            "timestamp": now,
        })
    except Exception:
        pass


def load_repo_conversation(
    repo_id: str,
    db_path: Optional[str] = None,
    max_turns: int = 10,
) -> Tuple[List[Tuple[str, str]], List[Set[str]], List[Dict[str, Any]]]:
    """Loads persisted turns and activity records for a canonical repo_id."""
    conn = get_db_connection(db_path)
    turns: List[Tuple[str, str]] = []
    turn_files: List[Set[str]] = []
    activities: List[Dict[str, Any]] = []
    try:
        cursor = conn.execute(
            """
            SELECT query, response, files_json FROM (
                SELECT id, query, response, files_json FROM conversation_turns
                WHERE repo_id = ? ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC;
            """,
            (repo_id, max_turns),
        )
        for row in cursor.fetchall():
            turns.append((row["query"], row["response"]))
            files_list = json.loads(row["files_json"]) if row["files_json"] else []
            turn_files.append(set(files_list))

        cur_act = conn.execute(
            """
            SELECT activity_type, target_file, proposal_id, verification_outcome, save_outcome, summary, details_json, timestamp
            FROM activity_records WHERE repo_id = ? ORDER BY id ASC;
            """,
            (repo_id,),
        )
        for row in cur_act.fetchall():
            details = json.loads(row["details_json"]) if row["details_json"] else {}
            activities.append({
                "activity_type": row["activity_type"],
                "target_file": row["target_file"],
                "proposal_id": row["proposal_id"],
                "verification_outcome": row["verification_outcome"],
                "save_outcome": row["save_outcome"],
                "summary": row["summary"],
                "details": details,
                "timestamp": row["timestamp"],
            })
    finally:
        conn.close()

    return turns, turn_files, activities


def clear_repo_conversation(
    repo_id: str,
    clear_activities: bool = False,
    db_path: Optional[str] = None,
):
    """Clears conversation turns (and optionally activity records) for a single canonical repo_id."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute("DELETE FROM conversation_turns WHERE repo_id = ?", (repo_id,))
            if clear_activities:
                conn.execute("DELETE FROM activity_records WHERE repo_id = ?", (repo_id,))
    finally:
        conn.close()


def load_conversation_memory(
    repo_id: str,
    memory_obj: Any,
    db_path: Optional[str] = None,
):
    """Populates an in-memory ConversationMemory instance from persistent storage."""
    max_turns = getattr(memory_obj, "max_turns", 10)
    turns, turn_files, activities = load_repo_conversation(repo_id, db_path=db_path, max_turns=max_turns)
    memory_obj.repo_id = repo_id
    memory_obj.turns = turns
    memory_obj.turn_files = turn_files
    memory_obj.activities = activities


if __name__ == "__main__":

    db_test_path = os.path.join(".storage", "test_metadata.db")
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

    conn = get_db_connection(db_test_path)
    print(f"SQLite Metadata Database initialized successfully at '{db_test_path}'!")
    
    # Verify tables created
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    print(f"Tables created: {tables}")
    conn.close()
    if os.path.exists(db_test_path):
        os.remove(db_test_path)

