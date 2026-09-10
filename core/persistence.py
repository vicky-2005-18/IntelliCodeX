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
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass

# Ensure repository root is on sys.path for direct script execution
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.parser import SourceFile
from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore

DEFAULT_DB_PATH = os.path.join(".storage", "metadata.db")



def compute_file_hash(content: str) -> str:
    """Computes SHA-256 hash of file content for fast change detection."""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates database directory if missing and returns a connected SQLite instance."""
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)
    
    conn = sqlite3.connect(db_path)
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
                last_indexed_at REAL NOT NULL
            );
        """)

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


def save_repo_metadata(
    conn: sqlite3.Connection,
    repo_id: str,
    repo_path: str,
    backend: str,
    source_files: List[SourceFile],
    chunks: List[CodeChunk]
):
    """Saves or updates repository metadata, file hashes, and code chunks in SQLite."""
    now = time.time()
    with conn:
        # 1. Update repos table
        conn.execute("""
            INSERT INTO repos (repo_id, repo_path, backend, total_files, total_chunks, last_indexed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_id) DO UPDATE SET
                repo_path=excluded.repo_path,
                backend=excluded.backend,
                total_files=excluded.total_files,
                total_chunks=excluded.total_chunks,
                last_indexed_at=excluded.last_indexed_at;
        """, (repo_id, os.path.abspath(repo_path), backend, len(source_files), len(chunks), now))

        # 2. Insert/Update files table
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
                INSERT INTO chunks (chunk_id, repo_id, file_path, language, kind, name, start_line, end_line, code, docstring, imports_json)
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
    path_hash = hashlib.md5(os.path.abspath(clean_path).encode("utf-8")).hexdigest()[:8]
    clean_base = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in base)
    return f"{clean_base}_{path_hash}"


def get_faiss_index_path(repo_id: str, storage_dir: str = ".storage") -> str:
    """Returns absolute file path for a repository's FAISS index (.storage/<repo_id>.faiss)."""
    os.makedirs(storage_dir, exist_ok=True)
    return os.path.abspath(os.path.join(storage_dir, f"{repo_id}.faiss"))


def save_faiss_index(store: FaissVectorStore, repo_id: str, storage_dir: str = ".storage") -> str:
    """Serializes the FAISS vector index to disk (.storage/<repo_id>.faiss)."""
    faiss_path = get_faiss_index_path(repo_id, storage_dir)
    return store.save(faiss_path)


def load_faiss_index(
    repo_id: str,
    chunks: Optional[List[CodeChunk]] = None,
    storage_dir: str = ".storage"
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
    db_path: str = DEFAULT_DB_PATH,
    storage_dir: str = ".storage"
) -> Tuple[str, str]:
    """
    Unified high-level save function:
    1. Saves repository metadata, file hashes, and chunks to SQLite (.storage/metadata.db).
    2. Serializes FAISS vector store index to disk (.storage/<repo_id>.faiss).
    Returns (db_path, faiss_path).
    """
    repo_id = get_repo_id(repo_path)
    conn = get_db_connection(db_path)
    try:
        save_repo_metadata(conn, repo_id, repo_path, backend, source_files, chunks)
    finally:
        conn.close()

    faiss_path = save_faiss_index(store, repo_id, storage_dir)
    return db_path, faiss_path


def load_index(
    repo_path: str,
    db_path: str = DEFAULT_DB_PATH,
    storage_dir: str = ".storage"
) -> Optional[Tuple[Dict[str, Any], List[CodeChunk], FaissVectorStore]]:
    """
    Unified high-level load function:
    1. Loads repository metadata and code chunks from SQLite.
    2. Loads corresponding FAISS vector store from disk.
    Returns (meta_dict, chunks_list, faiss_store) if found, else None.
    """
    repo_id = get_repo_id(repo_path)
    if not os.path.exists(db_path):
        return None

    conn = get_db_connection(db_path)
    try:
        meta = load_repo_metadata(conn, repo_id)
        if not meta:
            return None
        chunks = load_stored_chunks(conn, repo_id)
    finally:
        conn.close()

    store = load_faiss_index(repo_id, chunks=chunks, storage_dir=storage_dir)
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
    db_path: str = DEFAULT_DB_PATH
) -> RepositoryDelta:
    """
    Compares current repository source files against stored SHA-256 hashes in SQLite.
    Categorizes files into added, modified, deleted, and unchanged.
    """
    repo_id = get_repo_id(repo_path)
    if not os.path.exists(db_path):
        return RepositoryDelta(
            added=current_source_files,
            modified=[],
            deleted=[],
            unchanged=[],
            is_fresh_index=True
        )

    conn = get_db_connection(db_path)
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

