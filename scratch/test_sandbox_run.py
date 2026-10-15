import sys
import os
sys.path.insert(0, ".")

from core.sandbox_runner import SandboxRunner

with open("scratch/demo_calculator_repo/calculator.py") as f:
    orig = f.read()

fixed = orig.replace(
    "# Intentional arithmetic bug: uses addition instead of subtraction\n    return a + b",
    "return a - b"
)

runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest", allow_local_sandbox=True, is_admin=True)
res = runner.run_tests_with_patch(
    repo_path=os.path.abspath("scratch/demo_calculator_repo"),
    target_file="calculator.py",
    patched_code=fixed,
    runtime="python",
)

print("Sandbox test result:")
print("Success:", res.success)
print("Skipped:", res.skipped)
print("Passed count:", res.passed_count)
print("Failed count:", res.failed_count)
print("Error message:", res.error_message)
print("Stdout:\n", res.stdout)
