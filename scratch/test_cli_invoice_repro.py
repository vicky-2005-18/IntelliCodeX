import subprocess
import sys
import os

repo_path = os.path.abspath("scratch/demo_invoice_repo")
cli_path = os.path.abspath("cli.py")

input_text = "fix: AssertionError in test_invoice.py: assert 30 == 60 where 30 = invoice_total([10, 20, 30]) @invoice.py\nc\nexit\n"

env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

print("[*] Launching real CLI on disposable repo...")
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

stdout, _ = proc.communicate(input=input_text, timeout=180)

output_file = os.path.abspath("scratch/cli_repro_output.txt")
with open(output_file, "w", encoding="utf-8") as f:
    f.write(stdout or "")

print("[*] Done! Saved output to:", output_file)
