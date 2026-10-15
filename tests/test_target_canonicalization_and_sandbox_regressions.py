"""
Regression tests for Canonical Target Resolution, Ambiguity Disambiguation,
Nested Sandbox Patching, and Execution/Model Separation.
"""
import os
import sys
import tempfile
import pytest

from core.canonical_path import (
    resolve_canonical_target_path,
    find_matching_repository_files,
    normalize_repo_relative_path,
)
from core.sandbox_runner import SandboxRunner, SandboxTestResult
from core.code_review import display_review_screen


def test_normalize_repo_relative_path():
    assert normalize_repo_relative_path(r"foo\bar\baz.py") == "foo/bar/baz.py"
    assert normalize_repo_relative_path("./foo/bar.py") == "foo/bar.py"
    assert normalize_repo_relative_path("foo/bar.py") == "foo/bar.py"


def test_nested_target_canonical_resolution():
    with tempfile.TemporaryDirectory() as tmpdir:
        nested_dir = os.path.join(tmpdir, "IntelliCodeX_Practice_24_Files", "IntelliCodeX_Practice", "Python", "01_easy")
        os.makedirs(nested_dir, exist_ok=True)
        target_file = os.path.join(nested_dir, "invoice.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def invoice_total(p): return sum(p)\n")

        # 1. Resolve via bare basename
        canon, err = resolve_canonical_target_path(tmpdir, "invoice.py")
        assert err is None
        assert canon == "IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py"

        # 2. Resolve via partial directory suffix
        canon, err = resolve_canonical_target_path(tmpdir, "01_easy/invoice.py")
        assert err is None
        assert canon == "IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py"

        # 3. Resolve via Windows backslashed path
        canon, err = resolve_canonical_target_path(tmpdir, r"Python\01_easy\invoice.py")
        assert err is None
        assert canon == "IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py"

        # 4. Resolve via full absolute path
        canon, err = resolve_canonical_target_path(tmpdir, target_file)
        assert err is None
        assert canon == "IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py"


def test_duplicate_basenames_require_disambiguation():
    with tempfile.TemporaryDirectory() as tmpdir:
        dir_a = os.path.join(tmpdir, "pkg_a", "core")
        dir_b = os.path.join(tmpdir, "pkg_b", "core")
        os.makedirs(dir_a, exist_ok=True)
        os.makedirs(dir_b, exist_ok=True)

        with open(os.path.join(dir_a, "invoice.py"), "w", encoding="utf-8") as f:
            f.write("# pkg_a\n")
        with open(os.path.join(dir_b, "invoice.py"), "w", encoding="utf-8") as f:
            f.write("# pkg_b\n")

        # Ambiguous resolution with bare basename
        canon, err = resolve_canonical_target_path(tmpdir, "invoice.py")
        assert canon is None
        assert err is not None
        assert "Ambiguous target filename 'invoice.py' matches 2 files" in err
        assert "pkg_a/core/invoice.py" in err
        assert "pkg_b/core/invoice.py" in err
        assert "Disambiguation required" in err

        # Disambiguated resolution with partial directory
        canon_a, err_a = resolve_canonical_target_path(tmpdir, "pkg_a/core/invoice.py")
        assert err_a is None
        assert canon_a == "pkg_a/core/invoice.py"

        canon_b, err_b = resolve_canonical_target_path(tmpdir, "pkg_b/core/invoice.py")
        assert err_b is None
        assert canon_b == "pkg_b/core/invoice.py"


def test_sandbox_patches_nested_target_and_preserves_unrelated():
    with tempfile.TemporaryDirectory() as tmpdir:
        nested_pkg = os.path.join(tmpdir, "services", "billing")
        unrelated_dir = os.path.join(tmpdir, "services", "auth")
        os.makedirs(nested_pkg, exist_ok=True)
        os.makedirs(unrelated_dir, exist_ok=True)

        calc_file = os.path.join(nested_pkg, "calculator.py")
        with open(calc_file, "w", encoding="utf-8") as f:
            f.write("def calc(a, b): return a + b\n")

        test_file = os.path.join(nested_pkg, "test_calculator.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("from calculator import calc\ndef test_calc(): assert calc(10, 4) == 6\n")

        unrelated_file = os.path.join(unrelated_dir, "token.py")
        unrelated_original_content = "SECRET_KEY = 'do_not_touch'\n"
        with open(unrelated_file, "w", encoding="utf-8") as f:
            f.write(unrelated_original_content)

        # Patch calculator.py to subtract
        patched_code = "def calc(a, b): return a - b\n"
        canonical_target = "services/billing/calculator.py"

        runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
        result = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file=canonical_target,
            patched_code=patched_code,
            runtime="python"
        )

        assert result.success is True
        assert result.exit_code == 0
        assert result.passed_count == 1
        assert result.failed_count == 0
        assert result.patched_file_path == canonical_target
        assert result.working_dir is not None

        # Verify host files were completely untouched
        with open(calc_file, "r", encoding="utf-8") as f:
            assert f.read() == "def calc(a, b): return a + b\n"
        with open(unrelated_file, "r", encoding="utf-8") as f:
            assert f.read() == unrelated_original_content


def test_display_review_screen_separates_verdict_and_model_claims(capsys):
    filename = "services/billing/invoice.py"
    orig = "def total(p): return p[0]\n"
    patch = "def total(p): return sum(p)\n"

    # Case 1: Failed verification
    failed_info = {
        "test_status": "failed",
        "verified": False,
        "test_result": {
            "exit_code": 1,
            "passed_count": 1,
            "failed_count": 2,
        }
    }
    model_false_claim = "All tests now pass and invoice calculation is verified."

    display_review_screen(
        filename=filename,
        original_code=orig,
        patched_code=patch,
        explanation=model_false_claim,
        mode="unified",
        verification_info=failed_info,
    )
    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    # Model claim must not disguise test failure
    assert "FAILED" in combined_output
    assert "UNVERIFIED" in combined_output or "failed" in combined_output
    assert "Model advisory claims cannot override" in combined_output

    # Case 2: Passed verification
    passed_info = {
        "test_status": "passed",
        "verified": True,
        "test_result": {
            "exit_code": 0,
            "passed_count": 3,
            "failed_count": 0,
        }
    }
    display_review_screen(
        filename=filename,
        original_code=orig,
        patched_code=patch,
        explanation="Iterates through all prices.",
        mode="unified",
        verification_info=passed_info,
    )
    captured_pass = capsys.readouterr()
    pass_out = captured_pass.out + captured_pass.err
    assert "PASSED" in pass_out or "VERIFIED" in pass_out


def test_automatic_test_discovery_for_file_target():
    from core.canonical_path import discover_relevant_tests
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a project structure
        pkg_dir = os.path.join(tmpdir, "IntelliCodeX_Practice_24_Files", "IntelliCodeX_Practice", "Python", "02_medium")
        os.makedirs(pkg_dir, exist_ok=True)
        target_file = os.path.join(pkg_dir, "schedule.py")
        test_file = os.path.join(pkg_dir, "test_schedule.py")

        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def merge_intervals(intervals): return intervals\n")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_merge(): pass\n")

        canon_target = "IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/02_medium/schedule.py"
        discovered = discover_relevant_tests(tmpdir, canon_target)
        assert len(discovered) == 1
        assert discovered[0] == "IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/02_medium/test_schedule.py"


def test_explicit_boundary_when_no_tests_exist():
    from core.canonical_path import discover_relevant_tests
    with tempfile.TemporaryDirectory() as tmpdir:
        orphan_dir = os.path.join(tmpdir, "orphan_pkg")
        os.makedirs(orphan_dir, exist_ok=True)
        target_file = os.path.join(orphan_dir, "untested_module.py")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("def worker(): return 42\n")

        canon_target = "orphan_pkg/untested_module.py"
        discovered = discover_relevant_tests(tmpdir, canon_target)
        assert discovered == []

        # SandboxRunner must report skipped=True, success=False without fabricating verification
        runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
        res = runner.run_tests_with_patch(tmpdir, canon_target, "def worker(): return 42\n")
        assert res.success is False
        assert res.skipped is True
        assert any(msg in (res.error_message or "") for msg in ("Zero tests executed", "No automated test suite discovered"))


def test_baseline_test_execution_captures_failures_and_passes():
    with tempfile.TemporaryDirectory() as tmpdir:
        calc_file = os.path.join(tmpdir, "calc.py")
        test_file = os.path.join(tmpdir, "test_calc.py")

        with open(calc_file, "w", encoding="utf-8") as f:
            # Buggy: passes add, fails sub
            f.write("def add(a, b): return a + b\ndef sub(a, b): return a + b\n")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(
                "from calc import add, sub\n"
                "def test_add(): assert add(2, 3) == 5\n"
                "def test_sub(): assert sub(5, 3) == 2\n"
            )

        runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
        baseline = runner.run_baseline_tests(tmpdir, "calc.py")
        assert baseline.success is False
        assert baseline.passed_count == 1
        assert baseline.failed_count == 1
        assert any("test_add" in t for t in baseline.passed_tests)
        assert any("test_sub" in t for t in baseline.failed_tests)
        assert len(baseline.assertion_errors) > 0


def test_refinement_feedback_propagation_and_requirements():
    from core.patch_generator import PatchEngine
    engine = PatchEngine(store=None, embedder=None, llm=None, repo_path="/dummy")

    test_res = SandboxTestResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="AssertionError: assert [[8, 10], [1, 6]] == [[8, 10], [1, 4]]",
        duration_seconds=0.5,
        framework="pytest",
        passed_count=4,
        failed_count=1,
        total_count=5,
        passed_tests=["test_overlapping_intervals", "test_nested_intervals", "test_shared_endpoint", "test_empty_input"],
        failed_tests=["test_input_unchanged"],
        assertion_errors=["AssertionError: assert [[8, 10], [1, 6]] == [[8, 10], [1, 4]]"],
        traceback_summary="AssertionError in test_input_unchanged",
    )

    prompt = engine._build_refinement_prompt(
        error_report="Baseline test failure",
        file_path="schedule.py",
        snippet="def merge_intervals(intervals): ...",
        current_patch="def merge_intervals(intervals): merged[-1][1] = 6",
        test_result=test_res,
        rag_context="RAG_CONTEXT",
    )

    # 1. Failing tests present
    assert "test_input_unchanged" in prompt
    # 2. Passing tests to preserve present
    assert "Passing Tests (MUST PRESERVE - DO NOT BREAK):" in prompt
    assert "test_overlapping_intervals" in prompt
    assert "test_empty_input" in prompt
    # 3. Assertion details present
    assert "assert [[8, 10], [1, 6]] == [[8, 10], [1, 4]]" in prompt
    # 4. Critical requirement present (extracted dynamically from test_input_unchanged)
    assert "Input Preservation:" in prompt
    assert "Avoid mutating input parameters in-place" in prompt
    # 5. Previous candidate present
    assert "merged[-1][1] = 6" in prompt


def test_refinement_feedback_intentional_mutation_preserved():
    """Verifies that intentional in-place mutation is preserved when specified by docstring/spec."""
    from core.patch_generator import PatchEngine
    engine = PatchEngine(store=None, embedder=None, llm=None, repo_path="/dummy")

    test_res = SandboxTestResult(
        success=False,
        exit_code=1,
        stdout="",
        stderr="AssertionError: values not sorted",
        duration_seconds=0.5,
        framework="pytest",
        passed_count=2,
        failed_count=1,
        total_count=3,
        passed_tests=["test_empty", "test_single"],
        failed_tests=["test_sort_elements"],
        assertion_errors=["AssertionError: values not sorted"],
        traceback_summary="AssertionError in test_sort_elements",
    )

    prompt = engine._build_refinement_prompt(
        error_report="Sorting test failure",
        file_path="sorter.py",
        snippet="def in_place_sort(items):\n    '''Sorts items in-place using bubble sort.'''\n    pass",
        current_patch="def in_place_sort(items): return sorted(items)",
        test_result=test_res,
        rag_context="RAG_CONTEXT",
    )

    # Universal immutability must NOT be assumed
    assert "Input Preservation:" not in prompt
    # Intentional mutation must be explicitly propagated
    assert "Intentional Mutation:" in prompt
    assert "Preserve intentional in-place mutation" in prompt


def test_rejection_of_failed_candidate_approval():
    from core.patch_generator import PatchEngine
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "app.py")
        original_content = "def run(): return 'original'\n"
        with open(target, "w", encoding="utf-8") as f:
            f.write(original_content)

        engine = PatchEngine(store=None, embedder=None, llm=None, repo_path=tmpdir)

        failed_patch_rec = {
            "patch_id": "test-fail-1",
            "target_file": "app.py",
            "original_code": original_content,
            "suggested_patch": "def run(): return 'broken_candidate'\n",
            "file_read_from_disk": True,
            "status": "pending",
            "sandbox_validation": {
                "verified": False,
                "test_status": "failed",
                "iterations_count": 3,
            }
        }

        # 1. Normal approval attempt without force MUST be rejected
        ok, msg = engine.apply_patch(failed_patch_rec, force=False)
        assert ok is False
        assert "Approval rejected" in msg
        assert "failed test verification" in msg

        # Ensure file on disk was NOT touched
        with open(target, "r", encoding="utf-8") as f:
            assert f.read() == original_content

        # 2. Verified patch CAN be applied
        verified_patch_rec = {
            "patch_id": "test-pass-1",
            "target_file": "app.py",
            "original_code": original_content,
            "suggested_patch": "def run(): return 'verified_fix'\n",
            "file_read_from_disk": True,
            "status": "verified",
            "sandbox_validation": {
                "verified": True,
                "test_status": "passed",
                "iterations_count": 1,
            }
        }
        ok_v, msg_v = engine.apply_patch(verified_patch_rec, force=False)
        assert ok_v is True
        with open(target, "r", encoding="utf-8") as f:
            assert f.read() == "def run(): return 'verified_fix'\n"


def test_contract_analysis_extracts_explicit_and_inferred_behaviors():
    """Verifies that TestProposer extracts docstrings, call sites, and classifies explicit vs inferred contracts."""
    from core.test_proposer import TestProposer
    with tempfile.TemporaryDirectory() as tmpdir:
        mod_file = os.path.join(tmpdir, "formatter.py")
        with open(mod_file, "w", encoding="utf-8") as f:
            f.write(
                '"""Module string formatting utilities."""\n'
                'def format_title(title: str) -> str:\n'
                '    """Capitalizes words in title and trims whitespace."""\n'
                '    return title.title()\n'
                'def unstated_helper(x):\n'
                '    return x * 2\n'
            )

        caller_file = os.path.join(tmpdir, "main.py")
        with open(caller_file, "w", encoding="utf-8") as f:
            f.write(
                'from formatter import format_title\n'
                'val = format_title("hello world")\n'
            )

        proposer = TestProposer()
        analysis = proposer.analyze_contract(tmpdir, "formatter.py")

        assert "format_title" in analysis.docstrings
        assert any("Capitalizes words" in eb for eb in analysis.explicit_behaviors)
        assert any("unstated_helper" in ib for ib in analysis.inferred_behaviors)
        assert len(analysis.call_sites) >= 1
        assert analysis.call_sites[0]["caller_file"] == "main.py"
        assert analysis.is_ambiguous is False


def test_ambiguity_detection_generates_focused_clarification_question():
    """Verifies that contradictory/ambiguous docstrings produce a single focused question with options."""
    from core.test_proposer import TestProposer
    with tempfile.TemporaryDirectory() as tmpdir:
        mod_file = os.path.join(tmpdir, "pricing.py")
        with open(mod_file, "w", encoding="utf-8") as f:
            f.write(
                'def calculate_discount(price, rate):\n'
                '    """Calculates discount amount or final price based on rate."""\n'
                '    return price * rate\n'
            )

        proposer = TestProposer()
        analysis = proposer.analyze_contract(tmpdir, "pricing.py")

        assert analysis.is_ambiguous is True
        assert "calculate_discount" in analysis.ambiguity_reason
        assert analysis.clarification_question is not None
        assert "discount amount or final price" in analysis.clarification_question.lower()
        assert len(analysis.clarification_options) == 2

        # Clarifying resolves ambiguity
        clarified = proposer.analyze_contract(
            tmpdir, "pricing.py", user_clarification="Option A: Discount amount"
        )
        assert clarified.is_ambiguous is False
        assert any("User Clarification:" in eb for eb in clarified.explicit_behaviors)


def test_test_proposer_generates_grounded_candidate_tests_with_ai_banner():
    """Verifies candidate test proposal produces pytest code with AI banner and citations in disposable storage."""
    from core.test_proposer import TestProposer, AI_TEST_HEADER_BANNER
    with tempfile.TemporaryDirectory() as tmpdir:
        mod_file = os.path.join(tmpdir, "math_tool.py")
        with open(mod_file, "w", encoding="utf-8") as f:
            f.write(
                'def add_tax(amount, rate):\n'
                '    """Calculates total amount including tax rate."""\n'
                '    return amount + (amount * rate)\n'
            )

        proposer = TestProposer()
        analysis = proposer.analyze_contract(tmpdir, "math_tool.py")
        proposal = proposer.generate_candidate_tests(tmpdir, "math_tool.py", analysis, llm=None)

        assert AI_TEST_HEADER_BANNER in proposal.test_code
        assert "def test_add_tax_contract_happy_path" in proposal.test_code
        assert "# Grounded in:" in proposal.test_code
        assert os.path.isfile(proposal.disposable_path)
        assert not os.path.exists(os.path.join(tmpdir, "test_math_tool.py"))  # Repo untouched!


def test_test_proposal_docker_validation_distinguishes_harness_from_behavioral_errors():
    """Verifies that Docker validation flags broken syntax/imports as harness errors, while assertions are behavioral."""
    from core.test_proposer import TestProposer, TestProposal, ContractAnalysis
    from core.sandbox_runner import SandboxRunner, SandboxTestResult

    with tempfile.TemporaryDirectory() as tmpdir:
        proposer = TestProposer()

        # 1. Syntax Error proposal
        analysis = ContractAnalysis(target_file="sample.py")
        bad_syntax_proposal = TestProposal(
            target_file="sample.py",
            contract_analysis=analysis,
            test_code="def broken syntax(): pass",
            disposable_path=os.path.join(tmpdir, "test_syntax.py")
        )
        mock_runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
        val_syn = proposer.validate_proposed_tests_in_docker(mock_runner, tmpdir, bad_syntax_proposal)
        assert val_syn.syntax_valid is False
        assert val_syn.is_runnable is False
        assert any("SyntaxError" in he for he in val_syn.harness_errors)

        # 2. Behavioral assertion failure (valid harness discovering defect on untouched code)
        code_file = os.path.join(tmpdir, "calc.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write("def double(x):\n    return x + 1  # buggy implementation\n")

        valid_test_code = (
            "import pytest\n"
            "from calc import double\n"
            "def test_double_contract():\n"
            "    assert double(5) == 10\n"
        )
        valid_proposal = TestProposal(
            target_file="calc.py",
            contract_analysis=analysis,
            test_code=valid_test_code,
            disposable_path=os.path.join(tmpdir, "test_calc.py")
        )
        val_valid = proposer.validate_proposed_tests_in_docker(mock_runner, tmpdir, valid_proposal)
        assert val_valid.syntax_valid is True
        assert val_valid.imports_valid is True
        assert val_valid.tests_collected == 1
        assert val_valid.is_runnable is True
        assert len(val_valid.harness_errors) == 0
        assert len(val_valid.behavioral_failures) >= 1  # Caught the defect!


def test_test_freezing_and_extra_files_sandbox_execution():
    """Verifies that an accepted test is frozen in extra_files and executed in sandbox without modifying disk."""
    from core.sandbox_runner import SandboxRunner
    with tempfile.TemporaryDirectory() as tmpdir:
        code_file = os.path.join(tmpdir, "greet.py")
        with open(code_file, "w", encoding="utf-8") as f:
            f.write("def greet(name):\n    return f'Hello, {name}'\n")

        # Proposed test is NOT in tmpdir
        assert not os.path.exists(os.path.join(tmpdir, "test_greet.py"))

        frozen_test = (
            "from greet import greet\n"
            "def test_greet():\n"
            "    assert greet('Alice') == 'Hello, Alice'\n"
        )

        runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)
        res = runner.run_baseline_tests(
            repo_path=tmpdir,
            target_file="greet.py",
            extra_files={"test_greet.py": frozen_test}
        )

        assert res.success is True
        assert res.passed_count == 1
        assert res.failed_count == 0
        # User's repo remains untouched
        assert not os.path.exists(os.path.join(tmpdir, "test_greet.py"))


def test_pytest_output_parser_separates_collection_errors_and_rejects_banners():
    """Confirms pytest banner separators never become test names and collection errors are properly isolated."""
    runner = SandboxRunner()
    raw_pytest_error_output = """
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.3.4, pluggy-1.5.0
rootdir: /work
collected 0 items / 1 error

==================================== ERRORS ====================================
_______________________ ERROR collecting test_schedule.py _______________________
ImportError while importing test module '/work/test_schedule.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/local/lib/python3.11/importlib/__init__.py:126: in import_module
    return _bootstrap._gcd_import(name, package, level)
test_schedule.py:2: in <module>
    from schedule import merge_intervals
E   ImportError: cannot import name 'merge_intervals' from 'schedule' (/work/schedule.py)
=========================== short test summary info ============================
ERROR test_schedule.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.05s ===============================
"""
    parsed = runner._parse_pytest_output(raw_pytest_error_output, "", exit_code=2)
    # 1. No banner separators or punctuation in failed_tests or passed_tests
    for t in parsed["failed_tests"]:
        assert not t.startswith("=")
        assert not t.startswith("_")
        assert not t.startswith("!")
    for t in parsed["passed_tests"]:
        assert not t.startswith("=")
        assert not t.startswith("_")

    # 2. Collection error is isolated
    assert len(parsed["collection_errors"]) >= 1
    assert any("ImportError" in ce and "merge_intervals" in ce for ce in parsed["collection_errors"])

    # 3. Executed test counts are 0, collected count is 0
    assert parsed["passed_count"] == 0
    assert parsed["failed_count"] == 0
    assert parsed["total_count"] == 0
    assert parsed["collected_count"] == 0


def test_validate_candidate_interface_preserves_public_interfaces_and_rejects_test_substitution():
    """Confirms validate_candidate_interface catches dropped public symbols and test substitution."""
    from core.patch_generator import validate_candidate_interface

    original_code = (
        "def merge_intervals(intervals):\n"
        "    intervals.sort(key=lambda x: x[0])\n"
        "    return intervals\n"
    )

    # 1. Malformed test substitution candidate
    test_substitution_candidate = (
        "def test_input_unchanged():\n"
        "    intervals = [[1, 3], [2, 6]]\n"
        "    original = [[1, 3], [2, 6]]\n"
        "    merged = merge_intervals(intervals.copy())\n"
        "    assert intervals == original\n"
    )
    is_valid, err = validate_candidate_interface(original_code, test_substitution_candidate, "python")
    assert is_valid is False
    assert "substitutes test suite functions" in err or "dropped required public interface" in err
    assert "merge_intervals" in err

    # 2. Syntax error candidate
    syntax_err_candidate = "def merge_intervals(intervals: return intervals\n"
    is_valid, err = validate_candidate_interface(original_code, syntax_err_candidate, "python")
    assert is_valid is False
    assert "syntax error" in err.lower()

    # 3. Legitimate implementation patch preserving interface
    legit_candidate = (
        "def merge_intervals(intervals):\n"
        "    if not intervals:\n"
        "        return []\n"
        "    copy_ints = list(intervals)\n"
        "    copy_ints.sort(key=lambda x: x[0])\n"
        "    return copy_ints\n"
    )
    is_valid, err = validate_candidate_interface(original_code, legit_candidate, "python")
    assert is_valid is True
    assert err is None


def test_target_contents_authoritative_when_traceback_contains_test_code():
    """
    Regression: When error report contains a traceback from test_schedule.py pointing to
    def test_input_unchanged, target schedule.py must remain authoritative and diff must
    compare against schedule.py rather than substituting the test function.
    """
    import unittest.mock
    from core.patch_generator import PatchEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        sched_file = os.path.join(tmpdir, "schedule.py")
        test_file = os.path.join(tmpdir, "test_schedule.py")

        original_schedule = (
            "def merge_intervals(intervals):\n"
            "    if not intervals:\n"
            "        return []\n"
            "    intervals.sort(key=lambda x: x[0])\n"
            "    return intervals\n"
        )
        test_content = (
            "from schedule import merge_intervals\n"
            "def test_input_unchanged():\n"
            "    intervals = [[1, 3], [2, 6]]\n"
            "    original = [[1, 3], [2, 6]]\n"
            "    assert intervals == original\n"
        )
        with open(sched_file, "w", encoding="utf-8") as f:
            f.write(original_schedule)
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(test_content)

        # Mock vector store and localizer
        mock_store = unittest.mock.MagicMock()
        mock_store.chunks = []
        mock_store.search.return_value = []
        mock_embedder = unittest.mock.MagicMock()
        mock_embedder.embed.return_value = [[0.0] * 384]

        engine = PatchEngine(
            store=mock_store,
            embedder=mock_embedder,
            llm=None,
            repo_path=tmpdir,
            allow_heuristic_fallback=False,
        )

        # Localizer erroneously returned test_schedule.py because traceback came from test
        test_snippet = (
            "def test_input_unchanged():\n"
            "    intervals = [[1, 3], [2, 6]]\n"
            "    original = [[1, 3], [2, 6]]\n"
            "    assert intervals == original\n"
        )
        engine.localizer = unittest.mock.MagicMock()
        engine.localizer.localize.return_value = {
            "candidates": [
                {
                    "file_path": "test_schedule.py",
                    "snippet": test_snippet,
                    "confidence_score": 0.9,
                }
            ],
            "root_cause_explanation": "Test input changed",
            "parsed_frames": [],
        }

        # Request patch for schedule.py
        patch_rec = engine.generate_patch(
            repo_id="test_repo",
            error_report="Traceback: File test_schedule.py, line 28, in test_input_unchanged",
            target_file="schedule.py",
        )

        # Target file content must be schedule.py, NOT test_schedule.py
        assert patch_rec["target_file"] == "schedule.py"
        assert "def merge_intervals" in patch_rec["original_code"]
        assert "def test_input_unchanged" not in patch_rec["original_code"]
        assert "--- a/schedule.py" in patch_rec["git_diff"]
        assert "+++ b/schedule.py" in patch_rec["git_diff"]
        assert "def test_input_unchanged" not in patch_rec["git_diff"]


def test_test_file_immutability_enforced_in_sandbox():
    """Confirms test files cannot be modified or overwritten during sandbox repair."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sched_file = os.path.join(tmpdir, "schedule.py")
        test_file = os.path.join(tmpdir, "test_schedule.py")

        with open(sched_file, "w", encoding="utf-8") as f:
            f.write("def merge_intervals(i): return i\n")
        initial_test_bytes = b"from schedule import merge_intervals\ndef test_pass(): assert merge_intervals([1]) == [1]\n"
        with open(test_file, "wb") as f:
            f.write(initial_test_bytes)

        runner = SandboxRunner(sandbox_mode="local", allow_local_sandbox=True, is_admin=True)

        # 1. Normal patch to schedule.py preserves test_schedule.py byte-for-byte
        res = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="schedule.py",
            patched_code="def merge_intervals(i): return list(i)\n",
            runtime="python"
        )
        assert res.success is True

        # 2. If test_schedule.py was mutated during execution, immutability verification catches it
        script = "open('test_schedule.py', 'w').write('# corrupted')\nimport pytest\nraise SystemExit(pytest.main(['test_schedule.py']))"
        malicious_cmd = [sys.executable, "-c", script]
        res_mut = runner.run_tests_with_patch(
            repo_path=tmpdir,
            target_file="schedule.py",
            patched_code="def merge_intervals(i): return list(i)\n",
            test_command=malicious_cmd,
            runtime="python"
        )
        assert res_mut.success is False
        assert "immutability violation" in res_mut.error_message.lower()

        # 3. User's test file on host disk is completely unchanged byte-for-byte
        with open(test_file, "rb") as f:
            assert f.read() == initial_test_bytes


