"""
Tests for Benchmarking Engine
"""
import pytest
from core.benchmarking import run_benchmark, BenchmarkReport


def test_benchmarking_sample_repo():
    report = run_benchmark("sample_repo")
    assert isinstance(report, BenchmarkReport)
    assert report.num_files > 0
    assert report.num_chunks > 0
    assert report.total_time_seconds > 0
    assert report.files_per_second >= 0
    assert report.ast_ratio_percent >= 0
    assert "python" in report.languages_found
