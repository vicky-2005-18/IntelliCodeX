import subprocess
import sys
import os
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

repo_path = os.path.abspath("scratch/nested_practice_disposable")
cli_path = os.path.abspath("cli.py")
log_path = os.path.abspath("scratch/cli_live_log.txt")

with open(log_path, "w", encoding="utf-8") as f:
    f.write("[*] Starting debug run\n")

env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

cmd = [
    sys.executable, "-u", cli_path, repo_path,
    "--backend", "ollama",
    "--model", "qwen2.5-coder:3b",
    "--sandbox", "docker",
    "--no-tui",
]

p = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
    bufsize=1,
    env=env,
    cwd=os.path.dirname(cli_path),
)

import threading

def reader():
    with open(log_path, "a", encoding="utf-8") as log_f:
        for line in iter(p.stdout.readline, ""):
            log_f.write(line)
            log_f.flush()

t = threading.Thread(target=reader, daemon=True)
t.start()

# Wait for startup
time.sleep(3)
print("[*] Sending fix: @schedule.py")
p.stdin.write("fix: @schedule.py\n")
p.stdin.flush()

# Monitor log for review screen or completion
deadline = time.time() + 180
sent_actions = False

while time.time() < deadline:
    if p.poll() is not None:
        break
    try:
        with open(log_path, "r", encoding="utf-8") as rf:
            content = rf.read()
    except Exception:
        content = ""
    
    # Check if review screen or rejection prompt appeared
    if not sent_actions and ("[A]pprove" in content or "Action [" in content or "Review Code Changes" in content):
        print("[*] Detected review screen! Testing approval block with 'a'...")
        time.sleep(2)
        try:
            p.stdin.write("a\n")
            p.stdin.flush()
            time.sleep(2)
            p.stdin.write("c\n")
            p.stdin.flush()
            time.sleep(2)
            p.stdin.write("exit\n")
            p.stdin.flush()
            sent_actions = True
        except Exception as e:
            print("[!] Write error:", e)
    time.sleep(2)

if not sent_actions and p.poll() is None:
    print("[*] Reached deadline without review screen, sending exit...")
    try:
        p.stdin.write("exit\n")
        p.stdin.flush()
    except Exception:
        pass

p.wait(timeout=15)
print(f"[*] Process finished with returncode: {p.returncode}")
