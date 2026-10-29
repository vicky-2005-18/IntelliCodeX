"""
Comprehensive test suite verifying IntelliCodeX bug-analysis and repair pipeline generalization.

Validates:
1. Target isolation & call site grounding in a 100+ file repository with duplicate symbol names.
2. Rejection of newly introduced duplicate definitions across multiple languages (Python, Java, TS, Go, Rust).
3. Preservation of entry points (main) and existing public interfaces during patch assembly.
4. AST-based symbol reconciliation preventing duplicate functions and accidental deletions.
5. Asymmetric input generation and float vs floor division contract tests.
6. Protection against ungrounded approval on candidate validation failure.
7. Reproducibility of baseline and candidate execution metadata.
"""

import os
import tempfile
import ast
import pytest
from core.test_proposer import TestProposer
from core.patch_generator import validate_candidate_interface, replace_ast_symbols_in_python, evaluate_patch_approval_gate
from backend.patch_generator.patch_applier import merge_snippet_into_file


def test_100_plus_file_repo_target_isolation_and_call_site_grounding():
    """
    Simulates a repository with 105 files:
    - 1 target module ('engine_calc.py') with functions 'add', 'subtract', 'main'.
    - 100 unrelated files that contain same-name calls (e.g. set.add, sys.exit(main())) WITHOUT importing engine_calc.
    - 2 caller files that explicitly import engine_calc ('from engine_calc import add' and 'import engine_calc as ec').
    Verifies that _find_call_sites returns ONLY the 2 grounded call sites and 0 from the 100 unrelated files.
    """
    with tempfile.TemporaryDirectory(prefix="icx_100files_") as repo_dir:
        # 1. Target file
        target_code = (
            "def add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return b - a\n\n"
            "def main():\n    pass\n"
        )
        target_path = os.path.join(repo_dir, "engine_calc.py")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(target_code)

        # 2. 100 unrelated files with duplicate function names or calls without importing target
        for i in range(1, 101):
            unrelated_path = os.path.join(repo_dir, f"module_{i:03d}.py")
            content = (
                f"# Unrelated module {i}\n"
                f"class Container_{i}:\n"
                f"    def __init__(self):\n"
                f"        self.items = set()\n"
                f"    def add(self, x):\n"
                f"        self.items.add(x)\n\n"
                f"def main():\n"
                f"    c = Container_{i}()\n"
                f"    c.add({i})\n"
            )
            with open(unrelated_path, "w", encoding="utf-8") as f:
                f.write(content)

        # 3. Two grounded callers that actually import engine_calc
        caller1_path = os.path.join(repo_dir, "caller_from_import.py")
        with open(caller1_path, "w", encoding="utf-8") as f:
            f.write("from engine_calc import add\n\ndef run_step():\n    return add(5, 10)\n")

        caller2_path = os.path.join(repo_dir, "caller_module_import.py")
        with open(caller2_path, "w", encoding="utf-8") as f:
            f.write("import engine_calc as ec\n\ndef compute():\n    return ec.subtract(20, 5)\n")

        proposer = TestProposer()
        analysis = proposer.analyze_contract(repo_dir, "engine_calc.py")

        call_sites = analysis.call_sites
        assert len(call_sites) == 2, f"Expected exactly 2 grounded call sites, found {len(call_sites)}: {call_sites}"

        caller_files = {cs["caller_file"] for cs in call_sites}
        assert "caller_from_import.py" in caller_files
        assert "caller_module_import.py" in caller_files
        # Verify NONE of the 100 unrelated files were matched
        for i in range(1, 101):
            assert f"module_{i:03d}.py" not in caller_files


def test_duplicate_definition_rejection_python():
    """Verifies that validate_candidate_interface rejects candidates introducing duplicate top-level functions or classes."""
    orig = "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b\n"
    
    # Candidate defines 'add' twice
    dup_cand = (
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n\n"
        "def add(a, b):\n    return a + b  # duplicate\n"
    )
    ok, err = validate_candidate_interface(orig, dup_cand, language="python")
    assert not ok
    assert "duplicate definition" in err.lower()
    assert "'add'" in err


def test_duplicate_definition_rejection_multi_language():
    """Verifies duplicate definition detection for Java, TypeScript, Go, and Rust."""
    # Java duplicate method
    java_dup = (
        "public class Calculator {\n"
        "    public int add(int a, int b) { return a + b; }\n"
        "    public int add(int a, int b) { return a + b; }\n"
        "}\n"
    )
    ok, err = validate_candidate_interface("", java_dup, language="java")
    assert not ok
    assert "duplicate definition" in err.lower()

    # TypeScript duplicate function
    ts_dup = (
        "export function calculateTotal(items: number[]): number { return 0; }\n"
        "export function calculateTotal(items: number[]): number { return 1; }\n"
    )
    ok, err = validate_candidate_interface("", ts_dup, language="typescript")
    assert not ok
    assert "duplicate definition" in err.lower()

    # Go duplicate function
    go_dup = (
        "package calc\n"
        "func Add(a, b int) int { return a + b }\n"
        "func Add(a, b int) int { return a + b }\n"
    )
    ok, err = validate_candidate_interface("", go_dup, language="go")
    assert not ok
    assert "duplicate definition" in err.lower()

    # Rust duplicate function
    rust_dup = (
        "pub fn compute_hash(data: &[u8]) -> u64 { 0 }\n"
        "pub fn compute_hash(data: &[u8]) -> u64 { 1 }\n"
    )
    ok_r, err_r = validate_candidate_interface("", rust_dup, language="rust")
    assert not ok_r
    assert "duplicate definition" in err_r.lower()


def test_duplicate_detection_preserves_valid_scopes_and_overloads():
    """Verifies that duplicate detection preserves valid Java overloads, same-name methods in different classes, and Rust separate impl blocks."""
    # 1. Java valid method overloads with distinct signatures
    java_valid_overloads = (
        "public class Calculator {\n"
        "    public int add(int a, int b) { return a + b; }\n"
        "    public double add(double a, double b) { return a + b; }\n"
        "}\n"
    )
    ok_j_ov, err_j_ov = validate_candidate_interface("", java_valid_overloads, language="java")
    assert ok_j_ov is True, f"Valid Java overloads were rejected: {err_j_ov}"

    # 2. Java same-name methods across different classes
    java_diff_classes = (
        "public class ServiceA {\n"
        "    public void execute() {}\n"
        "}\n"
        "class ServiceB {\n"
        "    public void execute() {}\n"
        "}\n"
    )
    ok_j_cls, err_j_cls = validate_candidate_interface("", java_diff_classes, language="java")
    assert ok_j_cls is True, f"Same-name methods in different classes were rejected: {err_j_cls}"

    # 3. Rust same-name methods in separate impl blocks
    rust_separate_impls = (
        "struct Foo;\n"
        "struct Baz;\n"
        "impl Foo {\n"
        "    pub fn calculate(&self) -> i32 { 1 }\n"
        "}\n"
        "impl Baz {\n"
        "    pub fn calculate(&self) -> i32 { 2 }\n"
        "}\n"
    )
    ok_r, err_r = validate_candidate_interface("", rust_separate_impls, language="rust")
    assert ok_r is True, f"Rust methods in separate impl blocks were rejected: {err_r}"

    # 4. Go same-name methods on separate receiver types
    go_separate_receivers = (
        "package main\n"
        "type Foo struct{}\n"
        "type Bar struct{}\n"
        "func (f *Foo) Process() error { return nil }\n"
        "func (b *Bar) Process() error { return nil }\n"
    )
    ok_g, err_g = validate_candidate_interface("", go_separate_receivers, language="go")
    assert ok_g is True, f"Go methods on separate receivers were rejected: {err_g}"

    # 5. TypeScript overloads and different classes
    ts_valid = (
        "function parse(x: string): string;\n"
        "function parse(x: number): number;\n"
        "function parse(x: any): any { return x; }\n"
        "class A { run(): void {} }\n"
        "class B { run(): void {} }\n"
    )
    ok_ts, err_ts = validate_candidate_interface("", ts_valid, language="typescript")
    assert ok_ts is True, f"TypeScript overloads and classes were rejected: {err_ts}"


def test_entry_point_preservation_enforced():
    """Verifies that validate_candidate_interface rejects candidates that drop 'main' or public entry points."""
    orig = (
        "def calculate(x, y):\n    return x * y\n\n"
        "def main():\n    print(calculate(2, 3))\n"
    )
    # Candidate dropped main()
    cand_without_main = "def calculate(x, y):\n    return x * y\n"
    ok, err = validate_candidate_interface(orig, cand_without_main, language="python")
    assert not ok
    assert "dropped required public interface" in err
    assert "'main'" in err


def test_replace_ast_symbols_preserves_unrelated_code_and_entry_points():
    """Verifies that AST symbol replacement updates target function without deleting main or creating duplicate functions."""
    orig = (
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return b - a  # Buggy\n\n"
        "def multiply(a, b):\n    return a * b\n\n"
        "def main():\n"
        "    print('Interactive main loop')\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )

    # Candidate fixes subtract, and also re-outputs add
    cand = (
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n"
    )

    assembled = replace_ast_symbols_in_python(orig, cand)
    assert assembled is not None

    # Check 0 duplicates
    assert assembled.count("def add(") == 1
    assert assembled.count("def subtract(") == 1
    assert assembled.count("def multiply(") == 1
    assert assembled.count("def main(") == 1

    # Check bug fixed
    assert "return a - b" in assembled
    assert "return b - a" not in assembled

    # Check main and entry points preserved
    assert "Interactive main loop" in assembled
    assert "if __name__ == '__main__':" in assembled


def test_merge_snippet_into_file_guards_against_duplicate_injection():
    """Verifies that merge_snippet_into_file returns None if candidate snippet defines symbols outside the snippet."""
    full = (
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return b - a\n"
    )
    snip = "def subtract(a, b):\n    return b - a"
    # Patched snippet includes 'add', which already exists outside snip
    patched_snip = "def add(a, b):\n    return a + b\n\ndef subtract(a, b):\n    return a - b"

    result = merge_snippet_into_file(full, snip, patched_snip)
    # Must refuse blind string replace because it would duplicate 'add'
    assert result is None


def test_asymmetric_contract_test_generation():
    """Verifies that contract test generation respects documentation/clarification and does not universally infer ungrounded semantics."""
    calc_src = (
        "def add(a, b):\n    return a + b\n\n"
        "def subtract(a, b):\n    return a - b\n\n"
        "def divide(a, b):\n    return a / b\n\n"
        "def main():\n    choice = input('Option: ')\n"
    )
    proposer = TestProposer()

    # 1. Unclarified: subtract asymmetry is tested, but unstated division semantics are not universally guessed
    analysis_unclarified = proposer.analyze_contract(".", "calculator_practice.py")
    test_code_unclarified = proposer._generate_ast_contract_tests("calculator_practice.py", calc_src, analysis_unclarified)
    assert "test_subtract_contract_asymmetry" in test_code_unclarified
    assert "assert subtract(10, 3) == 7" in test_code_unclarified
    assert "test_divide_contract_happy_path" in test_code_unclarified
    assert "test_divide_contract_true_division" not in test_code_unclarified

    # 2. User-clarified semantics: true float division and ZeroDivisionError
    analysis_clarified = proposer.analyze_contract(
        ".", "calculator_practice.py", user_clarification="True float division (a / b), raising ZeroDivisionError on 0"
    )
    test_code_clarified = proposer._generate_ast_contract_tests("calculator_practice.py", calc_src, analysis_clarified)
    assert "test_divide_contract_true_division" in test_code_clarified
    assert "assert divide(10, 4) == 2.5" in test_code_clarified
    assert "ZeroDivisionError" in test_code_clarified

    # 3. Main entry point protection (must not invoke input() bare)
    assert "test_main_is_callable" in test_code_clarified
    assert "assert callable(main)" in test_code_clarified
    assert "main()" not in test_code_clarified


def test_central_gate_blocks_approval_when_verification_fails():
    """Verifies that evaluate_patch_approval_gate strictly blocks approval when verification fails."""
    canonical_id = "test-repo_1234abcd"
    unverified_patch = {
        "patch_id": "test-unverified-1",
        "repo_id": canonical_id,
        "target_file": "calculator_practice.py",
        "suggested_patch": "def add(a, b): return a + b\n",
        "sandbox_validation": {
            "verified": False,
            "test_status": "failed",
            "test_result": {
                "success": False,
                "passed_count": 0,
                "failed_count": 1,
            }
        }
    }
    ok, msg = evaluate_patch_approval_gate(unverified_patch, target_repo_id=canonical_id)
    assert not ok
    assert "candidate patch failed test verification" in msg

