import subprocess
import sys
import os
import hashlib

repo_path = os.path.abspath("scratch/nested_practice_disposable")
cli_path = os.path.abspath("cli.py")
test_file_path = os.path.join(repo_path, "IntelliCodeX_Practice", "Python", "02_medium", "test_schedule.py")

with open(test_file_path, "rb") as f:
    pre_test_hash = hashlib.sha256(f.read()).hexdigest()
print(f"[*] Pre-run test_schedule.py SHA256: {pre_test_hash}")

# Send 'fix: @schedule.py', attempt 'a' (approve), then 'c' (cancel), then 'exit'
input_text = "fix: @schedule.py\na\nc\nexit\n"

env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

print("[*] Launching real CLI workflow on nested practice disposable copy...")
proc = subprocess.Popen(
    [sys.executable, cli_path, repo_path, "--backend", "ollama", "--model", "qwen2.5-coder:3b", "--sandbox", "docker", "--no-tui"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
    cwd=os.path.dirname(cli_path),
    env=env,
)

stdout, _ = proc.communicate(input=input_text, timeout=300)

output_file = os.path.abspath("scratch/schedule_repro_output.txt")
with open(output_file, "w", encoding="utf-8") as f:
    f.write(stdout or "")

with open(test_file_path, "rb") as f:
    post_test_hash = hashlib.sha256(f.read()).hexdigest()
print(f"[*] Post-run test_schedule.py SHA256: {post_test_hash}")
assert pre_test_hash == post_test_hash, "test_schedule.py hash changed!"
print("[*] Verified: test_schedule.py remains byte-for-byte identical!")
print(f"[*] Complete CLI log written to: {output_file}")
