import sys
import os
sys.path.insert(0, ".")

from core.sandbox_runner import SandboxRunner

repo_path = r"C:\Users\vikas\Downloads\error"
runner = SandboxRunner(sandbox_mode="docker", docker_image="intellicodex-sandbox:latest", is_admin=True)

# Candidate patch that fixes range(len(prices))
fixed_code = """def invoice_total(prices):
    total = 0
    for price in prices:
        total += price
    return total

if __name__ == '__main__':
    print(invoice_total([120, 80, 50]))
"""

print("=== Test 1: target_file='invoice.py' (incorrect root target) ===")
res1 = runner.run_tests_with_patch(
    repo_path=repo_path,
    target_file="invoice.py",
    patched_code=fixed_code,
    runtime="python"
)
print("Res1 success:", res1.success)
print("Res1 exit_code:", res1.exit_code)
print("Res1 passed_count:", res1.passed_count)
print("Res1 failed_count:", res1.failed_count)
print("Res1 stdout excerpt:\n", res1.stdout[-400:] if res1.stdout else "")

print("\n=== Test 2: target_file='IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py' (canonical path) ===")
res2 = runner.run_tests_with_patch(
    repo_path=repo_path,
    target_file="IntelliCodeX_Practice_24_Files/IntelliCodeX_Practice/Python/01_easy/invoice.py",
    patched_code=fixed_code,
    runtime="python"
)
print("Res2 success:", res2.success)
print("Res2 exit_code:", res2.exit_code)
print("Res2 passed_count:", res2.passed_count)
print("Res2 failed_count:", res2.failed_count)
print("Res2 stdout excerpt:\n", res2.stdout[-400:] if res2.stdout else "")
