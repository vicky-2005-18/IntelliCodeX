import subprocess
import sys
import time
import os
import hashlib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_approval_test():
    target_repo = os.path.abspath("error_in_this/python/task1")
    target_file = os.path.join(target_repo, "stats_calculator.py")
    
    with open(target_file, "rb") as f:
        hash_before = hashlib.sha256(f.read()).hexdigest()
    print(f"[*] Hash BEFORE approval test: {hash_before}")

    cmd = [
        sys.executable,
        "-u",
        "cli.py",
        target_repo,
        "--no-tui",
        "--sandbox", "docker",
        "--model", "qwen2.5-coder:7b",
        "--docker-image", "intellicodex-sandbox:latest",
    ]
    
    env = os.environ.copy()
    env["INTELLICODEX_NO_TUI"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    transcript = []
    
    def send_line(line_str):
        print(f"\n>>> USER INPUT: {line_str}")
        transcript.append(f">>> USER INPUT: {line_str}\n")
        proc.stdin.write(line_str + "\n")
        proc.stdin.flush()

    buf = ""
    start_time = time.time()
    phase = "wait_start"
    approved = False
    
    while True:
        if proc.poll() is not None:
            break
        char = proc.stdout.read(1)
        if not char:
            break
        buf += char
        sys.stdout.write(char)
        sys.stdout.flush()
        transcript.append(char)
        
        if phase == "wait_start" and ">> " in buf:
            buf = ""
            phase = "sent_fix"
            time.sleep(0.5)
            send_line("fix:stats_calculator.py Fix the identified errors while preserving existing public interfaces and unrelated behavior.")
        elif phase == "sent_fix" and "Choose action" in buf and "):" in buf:
            buf = ""
            phase = "in_review"
            time.sleep(1)
            send_line("a") # Approve & commit
            approved = True
        elif phase == "in_review" and ">> " in buf:
            buf = ""
            phase = "exiting"
            send_line("exit")
            break
            
        if time.time() - start_time > 600:
            print("\n[!] Timeout after 600s")
            proc.kill()
            break

    try:
        proc.stdin.close()
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    with open(target_file, "rb") as f:
        hash_after = hashlib.sha256(f.read()).hexdigest()
    print(f"\n[*] Hash AFTER approval test: {hash_after}")

    with open("qa_suite/transcripts/approval_transcript.log", "w", encoding="utf-8") as f:
        f.write("".join(transcript))

    # Independent Docker test execution to verify updated code passes acceptance tests
    print("\n[*] Running INDEPENDENT acceptance verification in Docker sandbox...")
    from core.sandbox_runner import SandboxRunner
    sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
    res = sb.run_tests(target_repo, test_command=["python", "-m", "pytest", "test_stats_calculator.py"])
    print(f"[*] Independent Docker Test Result: success={res.success}, passed={res.passed_count}, failed={res.failed_count}")
    print(res.stdout)

    if hash_before != hash_after and res.success and res.passed_count > 0 and res.failed_count == 0:
        print("[OK] APPROVAL & INDEPENDENT REPAIR VERIFIED: Target file updated and all tests PASS in Docker.")
        return True
    else:
        print(f"[FAIL] APPROVAL REPAIR FAILED: hash_changed={hash_before != hash_after}, tests_passed={res.success}")
        return False

if __name__ == "__main__":
    success = run_approval_test()
    sys.exit(0 if success else 1)
