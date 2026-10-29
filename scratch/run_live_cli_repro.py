import subprocess
import sys
import time
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_cli_session():
    py_exe = sys.executable

    cmd = [
        py_exe,
        "-u",
        "cli.py",
        ".",
        "--no-tui",
        "--sandbox", "docker",
        "--model", "qwen2.5-coder:7b",
        "--docker-image", "intellicodex-sandbox:latest",
    ]
    
    env = os.environ.copy()
    env["INTELLICODEX_NO_TUI"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    
    print(f"[*] Launching CLI: {' '.join(cmd)}")
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

    # Step 1: Wait for prompt >>
    buf = ""
    start_time = time.time()
    phase = "wait_start"
    
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
        
        # Check triggers
        if phase == "wait_start" and ">> " in buf:
            buf = ""
            phase = "sent_fix"
            time.sleep(0.5)
            send_line("fix:calculator_practice.py")
        elif phase == "sent_fix" and "enter clarification:" in buf:
            buf = ""
            phase = "sent_clarif"
            time.sleep(0.5)
            send_line("1") # Select Option 1: True float division raising ZeroDivisionError
        elif phase in ("sent_fix", "sent_clarif") and "Candidate Test Action" in buf and "):" in buf:
            buf = ""
            phase = "sent_accept_tests"
            time.sleep(0.5)
            send_line("a") # Accept candidate test contract
        elif phase == "sent_accept_tests" and "Choose action" in buf and "):" in buf:
            buf = ""
            phase = "in_review"
            time.sleep(1)
            send_line("c") # Cancel review to leave files untouched
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

    full_log = "".join(transcript)
    with open("scratch/live_cli_transcript.log", "w", encoding="utf-8") as f:
        f.write(full_log)
    print("\n\n[✓] Transcript saved to scratch/live_cli_transcript.log")

if __name__ == "__main__":
    run_cli_session()
