"""
Comprehensive automated tests for Dynamic Execution Coverage Matrix and SBFL (Ochiai, Tarantula, DStar).
Tests mathematical formulas, dynamic matrix ingestion, pytest-cov integration, and BugLocalizer ranking.
"""
import os
import tempfile
import json
import pytest

from core.bug_localizer import (
    calculate_ochiai_score,
    calculate_tarantula_score,
    calculate_dstar_score,
    DynamicCoverageMatrix,
    ElementCoverageMetrics,
    CoverageRecord,
    BugLocalizer,
)
from core.vectorstore import FaissVectorStore
from core.embedder import TfidfEmbedder
from core.chunker import CodeChunk


def test_sbfl_metric_formulas_against_ground_truth():
    """
    Verifies Ochiai, Tarantula, and DStar mathematical formulas.
    Scenario:
      ef = 3 (failing executions covering element)
      ep = 1 (passing executions covering element)
      nf = 3 (total failing tests)
      np = 9 (total passing tests)
    """
    # Ochiai: ef / sqrt(nf * (ef + ep)) = 3 / sqrt(3 * (3 + 1)) = 3 / sqrt(12) = 3 / 3.4641 = 0.8660
    ochiai = calculate_ochiai_score(ef=3, ep=1, nf=3, np=9)
    assert ochiai == 0.866

    # Tarantula: (ef / nf) / ((ef / nf) + (ep / np)) = (3/3) / ((3/3) + (1/9)) = 1 / (1 + 0.1111) = 0.9000
    tarantula = calculate_tarantula_score(ef=3, ep=1, nf=3, np=9)
    assert tarantula == 0.90

    # DStar: (ef ** 2) / (ep + (nf - ef)) = (3 ** 2) / (1 + (3 - 3)) = 9 / 1 = 9.0
    dstar = calculate_dstar_score(ef=3, ep=1, nf=3, np=9, star_power=2)
    assert dstar == 9.0


def test_sbfl_boundary_conditions_and_zero_division():
    """Verifies that all formulas handle edge cases (zero failing tests, zero covered executions) safely."""
    assert calculate_ochiai_score(0, 0, 0, 0) == 0.0
    assert calculate_ochiai_score(0, 5, 0, 5) == 0.0
    assert calculate_ochiai_score(0, 5, 2, 5) == 0.0
    assert calculate_tarantula_score(0, 5, 2, 5) == 0.0
    assert calculate_tarantula_score(0, 0, 0, 0) == 0.0
    assert calculate_dstar_score(0, 5, 2, 5) == 0.0
    assert calculate_dstar_score(0, 0, 0, 0) == 0.0


def test_dynamic_coverage_matrix_record_and_metrics():
    """Verifies DynamicCoverageMatrix test tracking and metric generation."""
    matrix = DynamicCoverageMatrix()

    # Test 1 (Passing): covers common.py and auth.py:login
    matrix.record_test("test_auth_success", passed=True, covered_elements=[
        "common.py", "auth.py", "auth.py:10", "auth.py:11", "auth.py:12"
    ])
    # Test 2 (Passing): covers common.py and billing.py
    matrix.record_test("test_billing_success", passed=True, covered_elements=[
        "common.py", "billing.py", "billing.py:5"
    ])
    # Test 3 (Failing): covers common.py and auth.py:12 (bug location)
    matrix.record_test("test_auth_failure", passed=False, covered_elements=[
        "common.py", "auth.py", "auth.py:12"
    ])

    summary = matrix.summary()
    assert summary["total_tests"] == 3
    assert summary["total_failing"] == 1
    assert summary["total_passing"] == 2

    # auth.py:12 is covered by 1 failing and 1 passing test out of (nf=1, np=2)
    # ef=1, ep=1, nf=1, np=2
    # Ochiai: 1 / sqrt(1 * (1 + 1)) = 1 / sqrt(2) = 0.7071
    m_12 = matrix.get_metrics("auth.py:12")
    assert m_12 is not None
    assert m_12.ef == 1
    assert m_12.ep == 1
    assert m_12.ochiai == 0.7071

    # billing.py is only covered by passing tests (ef=0) -> Ochiai = 0.0
    m_bill = matrix.get_metrics("billing.py")
    assert m_bill is not None
    assert m_bill.ef == 0
    assert m_bill.ochiai == 0.0

    # Top suspicious elements should rank auth.py:12 and auth.py above common.py and billing.py
    top_el = matrix.get_top_suspicious_elements("ochiai", top_k=2)
    assert top_el[0]["element_id"] in ("auth.py:12", "auth.py")
    assert top_el[0]["ochiai"] > 0.5


def test_dynamic_coverage_matrix_from_pytest_cov_json():
    """Verifies parsing of standard pytest-cov / coverage.py JSON report."""
    fake_cov_json = {
        "meta": {"version": "7.4.0", "timestamp": "2026-10-29T10:00:00"},
        "files": {
            "core/auth.py": {
                "executed_lines": [10, 11, 12, 14, 15],
                "missing_lines": [20, 21],
                "summary": {"covered_lines": 5, "num_statements": 7}
            },
            "core/utils.py": {
                "executed_lines": [1, 2, 3],
                "missing_lines": [],
                "summary": {"covered_lines": 3, "num_statements": 3}
            }
        }
    }

    test_outcomes = {
        "test_login_valid": True,
        "test_login_invalid_password": False,
        "test_utils_format": True,
    }

    matrix = DynamicCoverageMatrix.from_pytest_cov_json(
        report_data=fake_cov_json,
        test_results=test_outcomes,
        failing_files=["core/auth.py"],
    )

    summary = matrix.summary()
    assert summary["total_tests"] == 3
    assert summary["total_failing"] == 1
    assert summary["total_passing"] == 2

    # Line 12 in core/auth.py was executed in failing test
    metrics = matrix.get_metrics("core/auth.py:12")
    assert metrics is not None
    assert metrics.ef == 1
    assert metrics.ochiai > 0.5


def test_bug_localizer_with_dynamic_coverage_matrix():
    """Verifies BugLocalizer incorporates line-level dynamic coverage matrix into ranking."""
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="core/auth.py::authenticate",
        file_path="core/auth.py",
        language="python",
        kind="function",
        name="authenticate",
        start_line=10,
        end_line=20,
        code="def authenticate(user, token):\n    if not token:\n        return False\n    return verify(token)\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    matrix = DynamicCoverageMatrix()
    # 2 failing tests execute line 12, 0 passing tests execute line 12 (ef=2, ep=0, nf=2, np=5)
    # Ochiai = 2 / sqrt(2 * (2 + 0)) = 2 / 2 = 1.0 (maximal suspiciousness!)
    matrix.record_test("test_fail_1", passed=False, covered_elements=["core/auth.py", "core/auth.py:12"])
    matrix.record_test("test_fail_2", passed=False, covered_elements=["core/auth.py", "core/auth.py:12"])
    matrix.record_test("test_pass_1", passed=True, covered_elements=["core/utils.py"])
    matrix.record_test("test_pass_2", passed=True, covered_elements=["core/utils.py"])

    localizer = BugLocalizer(store=store, embedder=embedder, coverage_matrix=matrix)
    res = localizer.localize("Authentication failure token validation error")

    assert len(res["candidates"]) > 0
    top = res["candidates"][0]
    assert top["file_path"] == "core/auth.py"
    assert top["line_number"] == 12  # Pinpointed exact line via line-level Ochiai!
    assert top["ochiai_score"] == 1.0
    assert top["spectrum_analysis"] is not None
    assert top["spectrum_analysis"]["ef"] == 2
    assert top["spectrum_analysis"]["ochiai"] == 1.0
    assert "Dynamic line 12 executed in failing tests (Ochiai=1.00)" in top["explanation"]


def test_bug_localizer_load_pytest_cov_report_workflow():
    """Verifies dynamic runtime loading of pytest coverage JSON via load_pytest_cov_report."""
    embedder = TfidfEmbedder(dim=16)
    chunk = CodeChunk(
        chunk_id="services/order.py::create_order",
        file_path="services/order.py",
        language="python",
        kind="function",
        name="create_order",
        start_line=5,
        end_line=18,
        code="def create_order(cart):\n    validate(cart)\n    return db.save(cart)\n",
    )
    vecs = embedder.embed([chunk.as_embedding_text()])
    store = FaissVectorStore(dim=vecs.shape[1])
    store.add([chunk], vecs)

    localizer = BugLocalizer(store=store, embedder=embedder)

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({
            "files": {
                "services/order.py": {
                    "executed_lines": [5, 6, 7],
                    "missing_lines": [],
                    "summary": {"covered_lines": 3}
                }
            }
        }, f)
        temp_cov_path = f.name

    try:
        matrix = localizer.load_pytest_cov_report(
            report_data=temp_cov_path,
            test_results={"test_order_fail": False, "test_order_pass": True},
            failing_files=["services/order.py"],
        )
        assert matrix.total_failing == 1
        assert matrix.total_passing == 1

        res = localizer.localize("Order creation database save validation error")
        top = res["candidates"][0]
        assert top["file_path"] == "services/order.py"
        assert top["ochiai_score"] > 0.0
        assert top["spectrum_analysis"] is not None
    finally:
        if os.path.exists(temp_cov_path):
            os.remove(temp_cov_path)
