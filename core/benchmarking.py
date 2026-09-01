"""
Benchmarking Engine for IntelliCodeX Repository Parsing & Ingestion
Measures file parsing speed, chunking granularity, AST chunk ratio, FAISS build latency, and RAM footprint.
"""
import time
import os
import sys

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Ensure repository root is on sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from dataclasses import dataclass
from typing import Dict, Any
from core.embedder import BaseEmbedder, TfidfEmbedder
from core.pipeline import ingest_repository, IngestedRepository


@dataclass
class BenchmarkReport:
    repo_path: str
    num_files: int
    num_chunks: int
    ast_chunks_count: int
    ast_ratio_percent: float
    total_time_seconds: float
    files_per_second: float
    avg_lines_per_chunk: float
    memory_used_mb: float
    languages_found: Dict[str, int]


def run_benchmark(repo_path: str, embedder: BaseEmbedder = None) -> BenchmarkReport:
    """Runs performance benchmarking on the specified target repository."""
    if embedder is None:
        embedder = TfidfEmbedder()

    mem_before = 0.0
    if HAS_PSUTIL:
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / (1024 * 1024)

    start_time = time.perf_counter()
    ingested = ingest_repository(repo_path, embedder)
    end_time = time.perf_counter()

    mem_used = 0.0
    if HAS_PSUTIL:
        mem_after = process.memory_info().rss / (1024 * 1024)
        mem_used = round(max(0.0, mem_after - mem_before), 2)
    total_time = max(0.0001, end_time - start_time)

    num_files = ingested.num_files
    num_chunks = ingested.num_chunks
    ast_count = ingested.ast_chunks_count

    ast_ratio = (ast_count / num_chunks * 100.0) if num_chunks > 0 else 0.0
    fps = num_files / total_time

    total_lines = sum(sf.line_count for sf in ingested.files)
    avg_lines = (total_lines / num_chunks) if num_chunks > 0 else 0.0

    return BenchmarkReport(
        repo_path=os.path.abspath(repo_path),
        num_files=num_files,
        num_chunks=num_chunks,
        ast_chunks_count=ast_count,
        ast_ratio_percent=round(ast_ratio, 2),
        total_time_seconds=round(total_time, 4),
        files_per_second=round(fps, 2),
        avg_lines_per_chunk=round(avg_lines, 2),
        memory_used_mb=mem_used,
        languages_found=ingested.languages_found
    )


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "sample_repo"
    print(f"Running benchmark on '{target}'...")
    report = run_benchmark(target)
    print("=" * 60)
    print(f"Benchmark Target       : {report.repo_path}")
    print(f"Total Files Ingested   : {report.num_files}")
    print(f"Total Chunks Extracted : {report.num_chunks}")
    print(f"AST Chunks Count       : {report.ast_chunks_count} ({report.ast_ratio_percent}%)")
    print(f"Ingestion Time         : {report.total_time_seconds}s ({report.files_per_second} files/sec)")
    print(f"Avg Lines / Chunk      : {report.avg_lines_per_chunk}")
    print(f"RAM Memory Impact      : {report.memory_used_mb} MB")
    print(f"Languages Breakdown    : {report.languages_found}")
    print("=" * 60)
