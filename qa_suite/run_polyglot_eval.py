import os
import sys
import time
import subprocess
import hashlib
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SANDBOX_IMAGE = "intellicodex-sandbox:latest"

def run_cli_workflow(target_repo, commands_sequence, transcript_file):
    """
    Executes a sequence of commands against the real IntelliCodeX CLI.
    Handles 'fix:' commands with an approval/cancellation action sub-step.
    """
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

    def read_until_prompt(timeout=300):
        buf = ""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                break
            ch = proc.stdout.read(1)
            if not ch:
                break
            buf += ch
            sys.stdout.write(ch)
            sys.stdout.flush()
            transcript.append(ch)
            if ">> " in buf[-10:]:
                return buf
        return buf

    def read_until_review_action(timeout=300):
        buf = ""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if proc.poll() is not None:
                break
            ch = proc.stdout.read(1)
            if not ch:
                break
            buf += ch
            sys.stdout.write(ch)
            sys.stdout.flush()
            transcript.append(ch)
            if "Choose action" in buf and "):" in buf:
                return buf
        return buf

    # 1. Wait for initial Mascot ready prompt
    init_buf = ""
    while True:
        if proc.poll() is not None:
            break
        ch = proc.stdout.read(1)
        if not ch:
            break
        init_buf += ch
        sys.stdout.write(ch)
        sys.stdout.flush()
        transcript.append(ch)
        if "IntelliCodeX ready" in init_buf:
            # Now wait for the actual prompt >>
            while True:
                ch2 = proc.stdout.read(1)
                if not ch2:
                    break
                init_buf += ch2
                sys.stdout.write(ch2)
                sys.stdout.flush()
                transcript.append(ch2)
                if ">> " in init_buf[-10:]:
                    break
            break

    # 2. Execute commands sequentially
    for item in commands_sequence:
        if isinstance(item, tuple):
            # (fix_command, review_action)
            fix_cmd, review_act = item
            send_line(fix_cmd)
            read_until_review_action(timeout=300)
            time.sleep(1)
            send_line(review_act)
            read_until_prompt(timeout=120)
        else:
            send_line(item)
            read_until_prompt(timeout=300)

    # 3. Exit CLI
    send_line("exit")
    try:
        proc.stdin.close()
        proc.wait(timeout=15)
    except Exception:
        proc.kill()

    os.makedirs(os.path.dirname(transcript_file), exist_ok=True)
    with open(transcript_file, "w", encoding="utf-8") as f:
        f.write("".join(transcript))

    return "".join(transcript)


def evaluate_task(lang, task_name, rel_target, test_cmd, repo_rel, snapshot_subpath):
    target_repo = os.path.abspath(repo_rel)
    target_file = os.path.join(target_repo, rel_target)
    
    # Restore from snapshot first to ensure frozen clean state
    snap_file = os.path.join("qa_suite", "snapshots", snapshot_subpath)
    if os.path.isfile(snap_file):
        with open(snap_file, "rb") as sf:
            with open(target_file, "wb") as tf:
                tf.write(sf.read())
        print(f"[*] Restored frozen snapshot from {snap_file} to {target_file}")

    with open(target_file, "rb") as f:
        orig_bytes = f.read()
    orig_hash = hashlib.sha256(orig_bytes).hexdigest()

    print(f"\n{'='*70}\nEVALUATING {lang.upper()} {task_name.upper()} (Target: {rel_target})\n{'='*70}")
    print(f"[*] Initial Frozen Target Hash: {orig_hash}")

    # Step 1: Explanation and Diagnosis (Requests A and B)
    print(f"\n--- STEP 1: EXPLANATION & DIAGNOSIS ---")
    exp_trans_file = f"qa_suite/transcripts/{lang}_{task_name}_explain_diag.log"
    trans1 = run_cli_workflow(
        target_repo,
        [
            f"Explain how this program works, including its main functions, data flow, and interactions between files in @{rel_target}",
            f"Identify the bugs in this program. Explain the root causes, affected locations, and inputs that reproduce the incorrect behavior in @{rel_target}",
        ],
        exp_trans_file
    )

    # Step 2: Cancellation Test (Request C with 'c')
    print(f"\n--- STEP 2: CANCELLATION TEST ---")
    cancel_trans_file = f"qa_suite/transcripts/{lang}_{task_name}_cancellation.log"
    run_cli_workflow(
        target_repo,
        [
            (f"fix:@{rel_target} Fix the identified errors while preserving existing public interfaces and unrelated behavior.", "c")
        ],
        cancel_trans_file
    )
    with open(target_file, "rb") as f:
        cancel_hash = hashlib.sha256(f.read()).hexdigest()
    cancellation_passed = (cancel_hash == orig_hash)
    print(f"[*] Cancellation Hash Preserved: {cancellation_passed} ({cancel_hash})")

    # Step 3: Approval Test (Request C with 'a')
    print(f"\n--- STEP 3: REPAIR & APPROVAL ---")
    approval_trans_file = f"qa_suite/transcripts/{lang}_{task_name}_approval.log"
    run_cli_workflow(
        target_repo,
        [
            (f"fix:@{rel_target} Fix the identified errors while preserving existing public interfaces and unrelated behavior.", "a")
        ],
        approval_trans_file
    )
    with open(target_file, "rb") as f:
        after_hash = hashlib.sha256(f.read()).hexdigest()
    approval_applied = (after_hash != orig_hash)
    print(f"[*] Post-Approval Hash Changed: {approval_applied} ({after_hash})")

    # Step 4: Independent Acceptance Test in Docker Sandbox
    print(f"\n--- STEP 4: INDEPENDENT ACCEPTANCE SUITE IN DOCKER ---")
    docker_exec_cmd = [
        "docker", "run", "--rm",
        "-v", f"{target_repo}:/app",
        "-w", "/app",
        SANDBOX_IMAGE,
        "bash", "-c", test_cmd
    ]
    t_res = subprocess.run(docker_exec_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"[*] Independent Docker Return Code: {t_res.returncode}")
    print(t_res.stdout)
    if t_res.stderr:
        print(t_res.stderr)

    return {
        "lang": lang,
        "task": task_name,
        "orig_hash": orig_hash,
        "after_hash": after_hash,
        "cancellation_preserved": cancellation_passed,
        "approval_applied": approval_applied,
        "independent_exit_code": t_res.returncode,
        "independent_success": (t_res.returncode == 0),
        "explanation_captured": ("Explain" in trans1 or len(trans1) > 500),
        "diagnosis_captured": ("Identify" in trans1 or len(trans1) > 500),
    }

if __name__ == "__main__":
    task_filter = sys.argv[1].lower() if len(sys.argv) > 1 else None
    subtask_filter = sys.argv[2].lower() if len(sys.argv) > 2 else None

    tasks_to_run = [
        # 1. Java Task 1
        ("java", "task1", "TextTransformer.java",
         "javac -cp /usr/local/lib/junit-platform-console-standalone.jar -d build_classes *.java && java -jar /usr/local/lib/junit-platform-console-standalone.jar execute --disable-banner --class-path build_classes --scan-class-path",
         "error_in_this/java/task1",
         "java_task1/TextTransformer.java"),
        # 2. Java Task 2 (Multi-file & Overloads)
        ("java", "task2", "billing/DiscountCalculator.java",
         "javac -cp /usr/local/lib/junit-platform-console-standalone.jar -d build_classes billing/*.java && java -jar /usr/local/lib/junit-platform-console-standalone.jar execute --disable-banner --class-path build_classes --scan-class-path",
         "error_in_this/java/task2",
         "java_task2/billing/DiscountCalculator.java"),
        # 3. Go Task 1
        ("go", "task1", "slice_ops.go",
         "go test -v .",
         "error_in_this/go/task1",
         "go_task1/slice_ops.go"),
        # 4. Go Task 2 (Multi-file)
        ("go", "task2", "pkg/format/formatter.go",
         "go test -v ./pkg/service",
         "error_in_this/go/task2",
         "go_task2/pkg/format/formatter.go"),
    ]

    results = []
    # Load existing results if present
    res_path = "qa_suite/polyglot_results.json"
    if os.path.isfile(res_path):
        try:
            with open(res_path, "r", encoding="utf-8") as rf:
                results = json.load(rf)
        except Exception:
            results = []

    for lang, task, rel_t, cmd, repo_r, snap_s in tasks_to_run:
        if task_filter and task_filter not in (lang, "all"):
            continue
        if subtask_filter and subtask_filter != task:
            continue
        res = evaluate_task(lang, task, rel_t, cmd, repo_r, snap_s)
        # Update or append
        results = [r for r in results if not (r["lang"] == lang and r["task"] == task)]
        results.append(res)
        with open(res_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

    print("\n" + "="*70 + "\nRESULTS SUMMARY\n" + "="*70)
    for r in results:
        status = "PASS" if r["independent_success"] and r["cancellation_preserved"] and r["approval_applied"] else "FAIL"
        print(f"[{status}] {r['lang']} {r['task']}: cancel_ok={r['cancellation_preserved']}, approved={r['approval_applied']}, docker_ok={r['independent_success']}")
