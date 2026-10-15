import sys
sys.path.insert(0, ".")
import time, os
from core.pipeline import ingest_repository, IngestedRepository, BM25Index, detect_repository_changes
from core.parser import walk_repository
from core.chunker import chunk_repository
from core.dependency_graph import build_dependency_graph
from core.call_graph import build_call_graph
from core.embedder import TfidfEmbedder
from core.vectorstore import FaissVectorStore
from core.persistence import save_index, load_index

repo_path = 'sample_repo'
embedder = TfidfEmbedder()
backend_name = "tfidf"

# --- FRESH INDEXING STAGES ---
# Stage 1: Walk repository
t0 = time.perf_counter()
source_files = walk_repository(repo_path)
t_walk = (time.perf_counter() - t0) * 1000

# Stage 2: Chunking (AST parsing & chunk extraction)
t0 = time.perf_counter()
chunks = chunk_repository(source_files, skip_overload_stubs=True)
t_chunk = (time.perf_counter() - t0) * 1000

# Stage 3: Dependency Graph
t0 = time.perf_counter()
dep_graph = build_dependency_graph(source_files)
t_dep = (time.perf_counter() - t0) * 1000

# Stage 4: Call Graph
t0 = time.perf_counter()
call_graph = build_call_graph(chunks, source_files)
t_call = (time.perf_counter() - t0) * 1000

# Stage 5: TF-IDF vector fitting & embedding
t0 = time.perf_counter()
texts = [c.as_embedding_text() for c in chunks]
vectors = embedder.embed(texts)
t_embed = (time.perf_counter() - t0) * 1000

# Stage 6: Faiss Index creation and vector ingestion
t0 = time.perf_counter()
store = FaissVectorStore(dim=vectors.shape[1])
store.add(chunks, vectors)
t_faiss = (time.perf_counter() - t0) * 1000

# Stage 7: BM25 Lexical Index
t0 = time.perf_counter()
lex_idx = BM25Index(chunks)
t_bm25 = (time.perf_counter() - t0) * 1000

# Stage 8: Disk Persistence (.storage/ SQLite metadata + Faiss index file)
t0 = time.perf_counter()
save_index(
    repo_path,
    backend_name,
    source_files,
    chunks,
    store,
    embedding_dim=embedder.dim,
    model_name="tfidf",
)
t_persist = (time.perf_counter() - t0) * 1000

t_total_fresh = t_walk + t_chunk + t_dep + t_call + t_embed + t_faiss + t_bm25 + t_persist

# --- CACHED LOADING STAGES ---
# Cache Stage 1: File integrity / Delta detection
t0 = time.perf_counter()
delta = detect_repository_changes(repo_path, source_files)
t_cache_check = (time.perf_counter() - t0) * 1000

# Cache Stage 2: Load Faiss index and SQLite metadata
t0 = time.perf_counter()
meta, cached_chunks, cached_store = load_index(repo_path)
t_load_store = (time.perf_counter() - t0) * 1000

# Cache Stage 3: Graph and BM25 rebuild from memory
t0 = time.perf_counter()
c_dep = build_dependency_graph(source_files)
c_call = build_call_graph(cached_chunks, source_files)
c_bm25 = BM25Index(cached_chunks)
t_rebuild = (time.perf_counter() - t0) * 1000

t_total_cached = t_cache_check + t_load_store + t_rebuild

print("="*60)
print("STAGE-BY-STAGE TIMING BREAKDOWN (sample_repo)")
print(f"Embedding Backend: TfidfEmbedder")
print(f"Embedding Model:   scikit-learn TfidfVectorizer (dimension={embedder.dim})")
print("="*60)
print(f"Stage 1: Walk Repository:               {t_walk:6.2f} ms")
print(f"Stage 2: AST Chunking:                  {t_chunk:6.2f} ms")
print(f"Stage 3: Build Dependency Graph:        {t_dep:6.2f} ms")
print(f"Stage 4: Build Call Graph:              {t_call:6.2f} ms")
print(f"Stage 5: TF-IDF Text Embedding:         {t_embed:6.2f} ms")
print(f"Stage 6: Faiss Index Construction:      {t_faiss:6.2f} ms")
print(f"Stage 7: BM25 Lexical Index:            {t_bm25:6.2f} ms")
print(f"Stage 8: SQLite & Faiss Disk Save:      {t_persist:6.2f} ms")
print("-"*60)
print(f"TOTAL FRESH INDEXING TIME:              {t_total_fresh:6.2f} ms")
print("="*60)
print(f"Cache Stage 1: Delta / Freshness Check: {t_cache_check:6.2f} ms")
print(f"Cache Stage 2: Deserialization:         {t_load_store:6.2f} ms")
print(f"Cache Stage 3: In-Memory Graph/BM25:    {t_rebuild:6.2f} ms")
print("-"*60)
print(f"TOTAL CACHED LOADING TIME:              {t_total_cached:6.2f} ms")
print("="*60)

print(f"\n=== ALL {dep_graph.number_of_nodes()} DEPENDENCY GRAPH NODES ===")
for n in sorted(list(dep_graph.nodes())):
    in_deg = dep_graph.in_degree(n)
    out_deg = dep_graph.out_degree(n)
    is_iso = (in_deg == 0 and out_deg == 0)
    print(f"  - Node: '{n}' (in-degree={in_deg}, out-degree={out_deg}, isolated={is_iso})")

print(f"\n=== ALL {call_graph.number_of_nodes()} CALL GRAPH NODES ===")
for n in sorted(list(call_graph.nodes())):
    in_deg = call_graph.in_degree(n)
    out_deg = call_graph.out_degree(n)
    is_iso = (in_deg == 0 and out_deg == 0)
    print(f"  - Node: '{n}' (in-degree={in_deg}, out-degree={out_deg}, isolated={is_iso})")
