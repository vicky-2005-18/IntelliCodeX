import os
import sys
import time
import subprocess
import hashlib
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SANDBOX_IMAGE = "intellicodex-sandbox:latest"

def run_java_task1():
    target_repo = os.path.abspath("error_in_this/java/task1")
    target_file = os.path.join(target_repo, "TextTransformer.java")
    
    # 1. Restore from frozen snapshot
    with open("qa_suite/snapshots/java_task1/TextTransformer.java", "rb") as sf:
        with open(target_file, "wb") as tf:
            tf.write(sf.read())
            
    with open(target_file, "rb") as f:
        hash_before = hashlib.sha256(f.read()).hexdigest()
    print(f"[*] Hash BEFORE Java Task 1 repair: {hash_before}")

    cmd = [
        sys.executable,
        "-u",
        "cli.py",
        target_repo,
        "--no-tui",
        "--sandbox", "docker",
        "--model", "qwen2.5-coder:7b",
        "--docker-image", SANDBOX_IMAGE,
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
        print(f"\n>>> USER INPUT: {line_str}", flush=True)
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

        if phase == "wait_start" and ">> " in buf and ("IntelliCodeX ready" in buf or "Type any natural" in buf):
            buf = ""
            phase = "sent_fix"
            time.sleep(0.5)
            send_line("fix:@TextTransformer.java Fix the identified errors while preserving existing public interfaces and unrelated behavior.")
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
    print(f"\n[*] Hash AFTER Java Task 1 repair: {hash_after}")

    os.makedirs("qa_suite/transcripts", exist_ok=True)
    with open("qa_suite/transcripts/java_task1_approval_transcript.log", "w", encoding="utf-8") as f:
        f.write("".join(transcript))

    # Independent Docker verification
    print("\n[*] Running INDEPENDENT acceptance verification in Docker sandbox...")
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{target_repo}:/app",
        "-w", "/app",
        SANDBOX_IMAGE,
        "bash", "-c", "javac -cp /usr/local/lib/junit-platform-console-standalone.jar -d build_classes *.java && java -jar /usr/local/lib/junit-platform-console-standalone.jar execute --disable-banner --class-path build_classes --scan-class-path"
    ]
    t_res = subprocess.run(docker_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"[*] Docker return code: {t_res.returncode}")
    print(t_res.stdout)
    if t_res.stderr:
        print(t_res.stderr)

    success = (hash_before != hash_after and t_res.returncode == 0)
    if success:
        print("[OK] JAVA TASK 1 REPAIR VERIFIED: Target file updated and all tests PASS in Docker.")
    else:
        print(f"[FAIL] JAVA TASK 1 REPAIR FAILED: hash_changed={hash_before != hash_after}, rc={t_res.returncode}")
    return success

if __name__ == "__main__":
    res = run_java_task1()
    sys.exit(0 if res else 1)
