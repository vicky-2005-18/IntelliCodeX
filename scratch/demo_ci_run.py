"""
Demonstration script for IntelliCodeX CI/CD Pipeline (REQ-FUT-04).

Demonstrates:
1. Passing Candidate Patch -> Exit Code 0, verified=True
2. Failing Candidate Patch -> Exit Code 1, verified=False (failed tests)
3. Zero-Test / Skipped Fixture -> Exit Code 1, verified=False (unverified repair rejected)
4. Configuration Error (missing patch) -> Exit Code 2, error diagnostic recorded
"""

import os
import shutil
import subprocess
import sys
import tempfile

PYTHON_EXE = sys.executable

def run_cmd(args):
    print(f"\n[DEMO EXEC] {' '.join(args)}")
    res = subprocess.run(args, capture_output=True, text=True)
    print(f"Exit Code: {res.returncode}")
    print(res.stdout)
    if res.stderr:
        print(f"[STDERR]: {res.stderr}")
    return res.returncode

def main():
    base_tmp = tempfile.mkdtemp(prefix="icx_ci_demo_")
    try:
        # 1. Setup passing repo
        pass_repo = os.path.join(base_tmp, "pass_repo")
        os.makedirs(os.path.join(pass_repo, "src"), exist_ok=True)
        os.makedirs(os.path.join(pass_repo, "tests"), exist_ok=True)
        with open(os.path.join(pass_repo, "src", "math_ops.py"), "w") as f:
            f.write("def multiply(a: int, b: int) -> int:\n    return a * b\n")
        with open(os.path.join(pass_repo, "tests", "test_ops.py"), "w") as f:
            f.write("from src.math_ops import multiply\ndef test_mult():\n    assert multiply(3, 4) == 12\n")

        # Case 1: Passing patch
        pass_json = os.path.abspath("scratch/ci_passing_demo.json")
        rc1 = run_cmd([
            PYTHON_EXE, "cli.py", pass_repo, "--backend", "tfidf", "--ci",
            "--target-file", "src/math_ops.py",
            "--patch", "def multiply(a: int, b: int) -> int:\n    \"\"\"Docstring.\"\"\"\n    return a * b\n",
            "--runtime", "python",
            "--sandbox", "docker",
            "--output-json", pass_json
        ])
        assert rc1 == 0, f"Expected 0, got {rc1}"

        # Case 2: Failing patch
        fail_json = os.path.abspath("scratch/ci_failing_demo.json")
        rc2 = run_cmd([
            PYTHON_EXE, "cli.py", pass_repo, "--backend", "tfidf", "--ci",
            "--target-file", "src/math_ops.py",
            "--patch", "def multiply(a: int, b: int) -> int:\n    return a + b\n",
            "--runtime", "python",
            "--sandbox", "docker",
            "--output-json", fail_json
        ])
        assert rc2 == 1, f"Expected 1, got {rc2}"

        # Case 3: Zero-test fixture
        zero_repo = os.path.join(base_tmp, "zero_repo")
        os.makedirs(os.path.join(zero_repo, "src"), exist_ok=True)
        with open(os.path.join(zero_repo, "src", "math_ops.py"), "w") as f:
            f.write("def multiply(a: int, b: int) -> int:\n    return a * b\n")

        zero_json = os.path.abspath("scratch/ci_zerotest_demo.json")
        rc3 = run_cmd([
            PYTHON_EXE, "cli.py", zero_repo, "--backend", "tfidf", "--ci",
            "--target-file", "src/math_ops.py",
            "--patch", "def multiply(a: int, b: int) -> int:\n    return a * b\n",
            "--runtime", "python",
            "--sandbox", "docker",
            "--output-json", zero_json
        ])
        assert rc3 == 1, f"Expected 1, got {rc3}"

        # Case 4: Configuration error
        err_json = os.path.abspath("scratch/ci_configerr_demo.json")
        rc4 = run_cmd([
            PYTHON_EXE, "cli.py", pass_repo, "--backend", "tfidf", "--ci",
            "--target-file", "src/math_ops.py",
            "--patch-file", "nonexistent_file.patch",
            "--runtime", "python",
            "--sandbox", "docker",
            "--output-json", err_json
        ])
        assert rc4 == 2, f"Expected 2, got {rc4}"

        print("\nAll 4 CI/CD Demonstration Cases Passed Successfully!")
    finally:
        shutil.rmtree(base_tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
