import subprocess
import sys
import os

def test():
    cmd = [
        sys.executable,
        "cli.py",
        ".",
        "--no-tui",
        "--sandbox", "docker",
        "--model", "qwen2.5-coder:7b",
        "--docker-image", "intellicodex-sandbox:latest",
    ]
    input_text = "fix:calculator_practice.py\n1\na\nc\nexit\n"
    env = os.environ.copy()
    env["INTELLICODEX_NO_TUI"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    
    print("[*] Running cli with communicate()...")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    
    out, _ = proc.communicate(input=input_text, timeout=300)
    print("\n--- COMPLETE CLI OUTPUT ---")
    print(out)
    with open("scratch/live_cli_transcript.log", "w", encoding="utf-8") as f:
        f.write(out)
    print("\n[✓] Saved to scratch/live_cli_transcript.log")

if __name__ == "__main__":
    test()
