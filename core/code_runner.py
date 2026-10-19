"""
Interactive Code Runner for IntelliCodeX.

Safely executes single-file Java, Python, and JavaScript programs inside an isolated,
hardened Docker sandbox with interactive stdin/stdout, compiler isolation,
precise infrastructure probing, and repository-scoped activity tracking.

Design Guarantees:
1. Docker Sandbox Explicit: Never executes user code on the host system.
2. Hardened Isolation: Network disabled (--network none), read-only source mount (/work:ro),
   tmpfs storage (/tmp:rw,exec), non-root execution (1000:1000), dropped capabilities (ALL),
   no-new-privileges, and resource limits.
3. Java Isolation: Compiles into temporary container storage (/tmp) and runs from /tmp.
4. Interactive Terminal: Passes real stdin/stdout to child console applications and cleanly
   suspends UI mascot/watcher animations.
5. Clean Lifecycle: Traps Ctrl+C, force-removes the running container, and restores terminal modes.
6. Execution vs Verification: Clearly reports execution status without conflating it with test/security gates.
7. Dependency Detection: Reports missing dependencies without network mutation.
8. Activity Persistence: Records repository-scoped run activity in SQLite metadata database.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.canonical_path import normalize_repo_relative_path, resolve_canonical_target_path
from core.persistence import get_repo_id, save_repo_activity
from core.safe_paths import resolve_within

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".java": "java",
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
}


def detect_run_language(file_path: str) -> Optional[str]:
    """Detects supported language for execution from file extension."""
    if not file_path:
        return None
    _, ext = os.path.splitext(file_path.strip().lower())
    return SUPPORTED_EXTENSIONS.get(ext)


def extract_java_main_class(file_content: str, rel_path: str) -> str:
    """
    Extracts the fully qualified class name for Java execution.
    Inspects package declaration and main class name.
    """
    pkg = None
    m_pkg = re.search(r"^\s*package\s+([a-zA-Z0-9_\.]+)\s*;", file_content, re.MULTILINE)
    if m_pkg:
        pkg = m_pkg.group(1).strip()

    class_name = None
    # 1. Prefer public class
    m_pub = re.search(r"\bpublic\s+(?:final\s+|abstract\s+)?class\s+([A-Za-z0-9_]+)", file_content)
    if m_pub:
        class_name = m_pub.group(1).strip()
    else:
        # 2. Any class with main method
        m_main = re.search(r"\bclass\s+([A-Za-z0-9_]+)[^{]*\{[^}]*public\s+static\s+void\s+main", file_content, re.DOTALL)
        if m_main:
            class_name = m_main.group(1).strip()
        else:
            # 3. Any class declaration
            m_any = re.search(r"\bclass\s+([A-Za-z0-9_]+)", file_content)
            if m_any:
                class_name = m_any.group(1).strip()
            else:
                base = os.path.basename(rel_path)
                class_name = os.path.splitext(base)[0]

    if pkg:
        return f"{pkg}.{class_name}"
    return class_name


def parse_run_target(
    query: str,
    repo_path: str,
    candidate_files: Optional[List[str]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parses and canonically resolves the run target file inside the active repository.

    Returns:
        (canonical_rel_path, language, error_message)
    """
    clean_query = query.strip()
    # Strip prefix 'run:' or 'run '
    if clean_query.lower().startswith("run:"):
        raw_target = clean_query[4:].strip()
    elif clean_query.lower().startswith("run "):
        raw_target = clean_query[4:].strip()
    else:
        raw_target = clean_query

    # Extract target candidate (handling @"file with spaces", @'file with spaces', @file, or direct filename)
    target_candidate = None
    m_quoted = re.search(r'@["\']([^"\']+)["\']', raw_target)
    if m_quoted:
        target_candidate = m_quoted.group(1).strip()
    else:
        m_at = re.search(r"@([^\s,;]+)", raw_target)
        if m_at:
            target_candidate = m_at.group(1).strip().strip("'\"`")
        else:
            # Check for direct quoted filename without @
            m_direct_quoted = re.search(r'^["\']([^"\']+)["\']', raw_target)
            if m_direct_quoted:
                target_candidate = m_direct_quoted.group(1).strip()
            else:
                tokens = raw_target.split()
                if tokens:
                    target_candidate = tokens[0].strip().strip("'\"`")

    if not target_candidate:
        return (
            None,
            None,
            "No target file specified. Usage: 'run: @<file>' (e.g. 'run: @TodoApp.java', 'run: @calculator.py', 'run: @app.js').",
        )

    # Path traversal protection check
    target_clean = target_candidate.replace("\\", "/").strip()
    try:
        abs_target = resolve_within(repo_path, target_clean)
    except ValueError as e:
        return (
            None,
            None,
            f"Path traversal rejected: target path '{target_clean}' escapes active repository ({e}).",
        )

    # Canonical resolution against active repository files
    canon_rel, disambig_err = resolve_canonical_target_path(
        repo_path, target_clean, candidate_files=candidate_files
    )
    if disambig_err:
        return None, None, disambig_err

    # Check existence on disk
    full_path = os.path.join(repo_path, canon_rel)
    if not os.path.isfile(full_path):
        return (
            None,
            None,
            f"Target file '{canon_rel}' does not exist as a regular file in active repository '{repo_path}'.",
        )

    # Language support validation
    language = detect_run_language(canon_rel)
    if not language:
        _, ext = os.path.splitext(canon_rel)
        supported_desc = "Java (.java), Python (.py), and JavaScript (.js, .mjs, .cjs)"
        return (
            None,
            None,
            f"Unsupported language extension '{ext}' for target '{canon_rel}'. The 'run:' command currently supports {supported_desc} programs.",
        )

    return canon_rel, language, None


def probe_run_infrastructure(image: str, language: str) -> Dict[str, Any]:
    """
    Probes Docker daemon and container image toolchain before execution.
    Never executes code on the host system.
    """
    backend_name = f"Docker Sandbox (image: {image})"
    docker_cli = shutil.which("docker")
    if not docker_cli:
        blocker = "Docker CLI executable ('docker') not found on system PATH."
        guidance = "Install Docker Desktop or Docker Engine and ensure 'docker' is on system PATH."
        return {
            "backend": backend_name,
            "mode": "docker",
            "image": image,
            "daemon_available": False,
            "daemon_version": None,
            "daemon_error": blocker,
            "toolchain_available": False,
            "toolchain_error": blocker,
            "infrastructure_blocker": blocker,
            "actionable_guidance": guidance,
        }

    # 1. Probe Docker daemon responsiveness
    try:
        res_v = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res_v.returncode != 0 or not res_v.stdout.strip():
            err_raw = (res_v.stderr or res_v.stdout or "").strip()
            blocker = f"Docker daemon unavailable: {err_raw}"
            guidance = "Start Docker Desktop or start Docker daemon ('systemctl start docker')."
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": False,
                "daemon_version": None,
                "daemon_error": blocker,
                "toolchain_available": False,
                "toolchain_error": "Docker daemon unavailable",
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }
        daemon_ver = res_v.stdout.strip()
    except subprocess.TimeoutExpired:
        blocker = "Docker daemon unresponsive (timed out after 5s)."
        guidance = "Ensure Docker Desktop or daemon is running and responsive. Restart Docker daemon if frozen."
        return {
            "backend": backend_name,
            "mode": "docker",
            "image": image,
            "daemon_available": False,
            "daemon_version": None,
            "daemon_error": blocker,
            "toolchain_available": False,
            "toolchain_error": blocker,
            "infrastructure_blocker": blocker,
            "actionable_guidance": guidance,
        }
    except Exception as e:
        blocker = f"Docker daemon communication error: {e}"
        guidance = "Check Docker daemon permissions and connectivity."
        return {
            "backend": backend_name,
            "mode": "docker",
            "image": image,
            "daemon_available": False,
            "daemon_version": None,
            "daemon_error": blocker,
            "toolchain_available": False,
            "toolchain_error": blocker,
            "infrastructure_blocker": blocker,
            "actionable_guidance": guidance,
        }

    # 2. Probe container image toolchain based on language
    if language == "java":
        try:
            res_jc = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", image, "javac", "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            javac_out = (res_jc.stdout or res_jc.stderr or "").strip()
            if res_jc.returncode != 0:
                blocker = f"Configured sandbox image '{image}' lacks javac compiler ({javac_out or 'command not found'})."
                guidance = f"Rebuild or configure container image with JDK installed (e.g. 'docker build -t {image} .')."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "image": image,
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }

            res_jv = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", image, "java", "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            java_out = (res_jv.stdout or res_jv.stderr or "").strip()
            if res_jv.returncode != 0:
                blocker = f"Configured sandbox image '{image}' lacks java runtime ({java_out or 'command not found'})."
                guidance = f"Rebuild or configure container image with Java runtime installed for image '{image}'."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "image": image,
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }

            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": True,
                "toolchain_version": f"{javac_out} | {java_out.splitlines()[0] if java_out else 'Java'}",
                "toolchain_error": None,
                "infrastructure_blocker": None,
                "actionable_guidance": None,
            }
        except subprocess.TimeoutExpired:
            blocker = f"Container toolchain probe timed out after 10s for image '{image}'."
            guidance = f"Check Docker runtime responsiveness for image '{image}'."
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": False,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }
        except Exception as e:
            blocker = f"Container toolchain probe error: {e}"
            guidance = f"Verify Docker container execution for image '{image}'."
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": False,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }

    elif language == "python":
        try:
            res_py = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", image, "python", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            py_out = (res_py.stdout or res_py.stderr or "").strip()
            if res_py.returncode != 0:
                blocker = f"Configured sandbox image '{image}' lacks python runtime ({py_out or 'command not found'})."
                guidance = f"Rebuild or configure container image with Python installed for image '{image}'."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "image": image,
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": True,
                "toolchain_version": py_out,
                "toolchain_error": None,
                "infrastructure_blocker": None,
                "actionable_guidance": None,
            }
        except Exception as e:
            blocker = f"Container python toolchain probe error: {e}"
            guidance = f"Verify container runtime for image '{image}'."
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": False,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }

    elif language == "javascript":
        try:
            res_node = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", image, "node", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            node_out = (res_node.stdout or res_node.stderr or "").strip()
            if res_node.returncode != 0:
                blocker = f"Configured sandbox image '{image}' lacks node runtime ({node_out or 'command not found'})."
                guidance = f"Rebuild or configure container image with Node.js installed for image '{image}'."
                return {
                    "backend": backend_name,
                    "mode": "docker",
                    "image": image,
                    "daemon_available": True,
                    "daemon_version": daemon_ver,
                    "daemon_error": None,
                    "toolchain_available": False,
                    "toolchain_error": blocker,
                    "infrastructure_blocker": blocker,
                    "actionable_guidance": guidance,
                }
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": True,
                "toolchain_version": node_out,
                "toolchain_error": None,
                "infrastructure_blocker": None,
                "actionable_guidance": None,
            }
        except Exception as e:
            blocker = f"Container node toolchain probe error: {e}"
            guidance = f"Verify container runtime for image '{image}'."
            return {
                "backend": backend_name,
                "mode": "docker",
                "image": image,
                "daemon_available": True,
                "daemon_version": daemon_ver,
                "daemon_error": None,
                "toolchain_available": False,
                "toolchain_error": blocker,
                "infrastructure_blocker": blocker,
                "actionable_guidance": guidance,
            }

    return {
        "backend": backend_name,
        "mode": "docker",
        "image": image,
        "daemon_available": True,
        "daemon_version": daemon_ver,
        "daemon_error": None,
        "toolchain_available": True,
        "toolchain_version": None,
        "toolchain_error": None,
        "infrastructure_blocker": None,
        "actionable_guidance": None,
    }


def detect_missing_dependencies(output: str, language: str) -> List[str]:
    """
    Detects missing package/module dependency errors in execution output.
    Does not auto-install or mutate project files.
    """
    if not output:
        return []

    missing: List[str] = []
    if language == "python":
        # ModuleNotFoundError: No module named 'foo'
        for m in re.finditer(r"(?:ModuleNotFoundError|ImportError):\s*No module named\s*['\"]([^'\"]+)['\"]", output):
            dep = m.group(1).strip()
            if dep and dep not in missing:
                missing.append(dep)
        for m in re.finditer(r"ImportError:\s*cannot import name\s*['\"]([^'\"]+)['\"]\s*from\s*['\"]([^'\"]+)['\"]", output):
            dep = m.group(2).strip()
            if dep and dep not in missing:
                missing.append(dep)

    elif language == "javascript":
        # Error: Cannot find module 'foo' or MODULE_NOT_FOUND
        for m in re.finditer(r"(?:Cannot find module|Cannot find package)\s*['\"]([^'\"]+)['\"]", output):
            dep = m.group(1).strip()
            if dep and dep not in missing:
                missing.append(dep)

    elif language == "java":
        # package org.apache.commons does not exist
        for m in re.finditer(r"package\s+([a-zA-Z0-9_\.]+)\s+does not exist", output):
            dep = m.group(1).strip()
            if dep and dep not in missing:
                missing.append(dep)
        for m in re.finditer(r"cannot find symbol\s+symbol:\s+class\s+([A-Za-z0-9_]+)", output):
            sym = m.group(1).strip()
            if sym and sym not in missing and sym not in ("String", "System", "Object", "Scanner", "List", "Map"):
                missing.append(sym)

    return missing


def build_docker_run_command(
    repo_path: str,
    target_rel: str,
    language: str,
    image: str,
    container_name: str,
    is_interactive: bool = True,
    memory_limit: str = "512m",
    cpu_limit: str = "1",
    pids_limit: str = "256",
) -> Tuple[List[str], List[str]]:
    """
    Constructs the security-hardened docker run command and the internal container command.
    """
    abs_repo = os.path.abspath(repo_path)
    # Ensure forward slashes in target_rel inside Linux container
    rel_linux = target_rel.replace("\\", "/")

    # Determine command based on language
    if language == "java":
        full_path = os.path.join(abs_repo, target_rel)
        try:
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            content = ""
        main_class = extract_java_main_class(content, target_rel)
        # Compile into /tmp container storage, then run
        container_cmd = [
            "sh",
            "-c",
            f"javac -d /tmp /work/{rel_linux} && java -cp /tmp {main_class}",
        ]
    elif language == "python":
        container_cmd = ["python", "-u", f"/work/{rel_linux}"]
    elif language == "javascript":
        container_cmd = ["node", f"/work/{rel_linux}"]
    else:
        container_cmd = [f"/work/{rel_linux}"]

    docker_args = [
        "docker",
        "run",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,exec",
        "--user",
        "1000:1000",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        memory_limit,
        "--cpus",
        cpu_limit,
        "--pids-limit",
        pids_limit,
        "-v",
        f"{abs_repo}:/work:ro",
        "-w",
        "/work",
        "-e",
        "HOME=/tmp",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-e",
        "NODE_PATH=/usr/local/lib/node_modules",
    ]

    if is_interactive:
        docker_args.extend(["-i", "-t"])
    else:
        docker_args.append("-i")

    docker_args.append(image)
    docker_args.extend(container_cmd)

    return docker_args, container_cmd


def execute_run_command(
    query: str,
    repo_path: str,
    args: Any = None,
    session: Any = None,
    use_tui: bool = True,
    engine: Any = None,
    candidate_files: Optional[List[str]] = None,
    auto_input: Optional[str] = None,
) -> int:
    """
    Interactively executes a target Java, Python, or JS file in isolated Docker container.

    Returns:
        Process exit code (0 on success).
    """
    abs_repo = os.path.abspath(repo_path)
    image = getattr(args, "docker_image", None) or os.environ.get(
        "INTELLICODEX_DOCKER_IMAGE", "intellicodex-sandbox:latest"
    )

    # 1. Parse & resolve target path
    canon_rel, language, err = parse_run_target(query, abs_repo, candidate_files=candidate_files)
    if err:
        print("\n" + "=" * 70)
        print("       TARGET RESOLUTION ERROR")
        print("=" * 70)
        print(f"[!] {err}\n")
        return 1

    # 2. Probe Docker and toolchain infrastructure (never silently execute on host)
    print(f"\n[*] Probing Docker sandbox infrastructure for {language.capitalize()} execution...")
    infra = probe_run_infrastructure(image, language)
    if infra.get("infrastructure_blocker"):
        print("\n" + "=" * 70)
        print("       DOCKER SANDBOX INFRASTRUCTURE BLOCKER")
        print("=" * 70)
        print(f"[!] Blocker: {infra['infrastructure_blocker']}")
        if infra.get("actionable_guidance"):
            print(f"    Actionable Guidance: {infra['actionable_guidance']}")
        print("\n[!] Execution aborted: IntelliCodeX will never execute unverified code on host.")
        print("=" * 70 + "\n")
        return 1

    print(f"[*] Docker Daemon: Ready ({infra.get('daemon_version') or 'available'})")
    print(f"[*] Sandbox Image: '{image}' (toolchain: {infra.get('toolchain_version') or 'ready'})")
    print(f"[*] Target File  : '{canon_rel}' ({language.capitalize()})")
    print(f"[*] Isolation    : Network isolated (--network none), Read-only source mount (/work:ro)")
    print(f"[*] Compilation  : In-memory container storage (/tmp:rw,exec)")
    print("-" * 70)
    print(f"[*] Launching interactive execution (Ctrl+C to terminate)...\n")

    # Import terminal utilities from cli defensively
    try:
        from cli import MascotSpinner, restore_terminal_mouse_modes, resume_mascot_rendering, suspend_mascot_rendering
    except ImportError:
        def suspend_mascot_rendering(): pass
        def resume_mascot_rendering(): pass
        def restore_terminal_mouse_modes(): pass
        class MascotSpinner:
            @staticmethod
            def stop_all(): pass

    container_name = f"icx-run-{uuid.uuid4().hex[:12]}"
    is_tty = sys.stdin.isatty() and sys.stdout.isatty() and auto_input is None

    docker_cmd, _ = build_docker_run_command(
        abs_repo,
        canon_rel,
        language,
        image,
        container_name,
        is_interactive=is_tty,
    )

    exit_code = -1
    captured_logs = ""
    start_time = time.time()

    # 3. Suspend mascot rendering & stop spinners so child owns terminal
    suspend_mascot_rendering()
    MascotSpinner.stop_all()

    try:
        if auto_input is not None:
            # Piped/automated mode for testing
            res = subprocess.run(
                docker_cmd,
                input=auto_input,
                capture_output=True,
                text=True,
                timeout=getattr(args, "timeout", 60),
            )
            exit_code = res.returncode
            if res.stdout:
                sys.stdout.write(res.stdout)
                sys.stdout.flush()
            if res.stderr:
                sys.stderr.write(res.stderr)
                sys.stderr.flush()
            captured_logs = (res.stdout or "") + "\n" + (res.stderr or "")
        else:
            # Interactive terminal mode: child directly owns stdin/stdout/stderr
            proc = subprocess.Popen(docker_cmd)
            exit_code = proc.wait()

            # Retrieve container logs for dependency diagnosis if failed
            if exit_code != 0:
                try:
                    res_logs = subprocess.run(
                        ["docker", "logs", "--tail", "100", container_name],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    captured_logs = (res_logs.stdout or "") + "\n" + (res_logs.stderr or "")
                except Exception:
                    pass

    except KeyboardInterrupt:
        exit_code = 130
        print("\n\n[*] Ctrl+C detected: Stopping and cleaning up container...")
        try:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=5)
        except Exception:
            pass
    except Exception as e:
        exit_code = -1
        print(f"\n[!] Execution exception: {e}")
    finally:
        # Guarantee container is force-removed and no orphans remain
        try:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=5)
        except Exception:
            pass
        # Restore terminal mouse modes and resume mascot
        resume_mascot_rendering()
        restore_terminal_mouse_modes()

    # 4. Report results and distinguish execution from verification
    print("\n" + "=" * 70)
    if exit_code == 0:
        print("       EXECUTION FINISHED (Exit code: 0)")
        print("=" * 70)
        print(f"[*] Execution completed successfully for target '{canon_rel}'.")
        print("[NOTE] Execution exit code 0 indicates program ran to completion without crashing.")
        print("       This is an execution result, NOT a test pass or security verification.")
    elif exit_code == 130:
        print("       EXECUTION TERMINATED BY USER (Ctrl+C)")
        print("=" * 70)
        print(f"[*] Program execution stopped and container cleaned up.")
    else:
        print(f"       EXECUTION FAILED (Exit code: {exit_code})")
        print("=" * 70)
        print(f"[!] Program exited with non-zero exit code {exit_code}.")
        print("[NOTE] Execution failure indicates a runtime crash, syntax/compilation error,")
        print("       or non-zero program exit. It does not alter existing patch proposals.")

    # 5. Check for missing dependencies without auto-installing or modifying files
    if exit_code != 0 and exit_code != 130 and captured_logs:
        missing_deps = detect_missing_dependencies(captured_logs, language)
        if missing_deps:
            print("\n[!] Missing Project Dependencies Detected:")
            for dep in missing_deps:
                print(f"    - {dep}")
            print("[!] Note: IntelliCodeX sandbox enforces network isolation (--network none).")
            print("    Dependencies are not auto-installed, and dependency files are not modified.")
            print(f"    To run with these dependencies, vendor them in the repository or add")
            print(f"    them to your custom Docker sandbox image '{image}'.")

    print("=" * 70 + "\n")

    # 6. Record repository-scoped run activity
    outcome = "completed" if exit_code == 0 else ("terminated" if exit_code == 130 else "failed")
    repo_id = get_repo_id(abs_repo)
    activity_record = {
        "activity_type": "run",
        "target_file": canon_rel,
        "proposal_id": f"run-{uuid.uuid4().hex[:8]}",
        "verification_outcome": f"exit_code_{exit_code}",
        "save_outcome": outcome,
        "summary": f"Executed {canon_rel} in Docker Sandbox (image: {image}, exit code: {exit_code}, outcome: {outcome})",
        "details": {
            "target": canon_rel,
            "backend": f"Docker Sandbox (image: {image})",
            "docker_image": image,
            "exit_code": exit_code,
            "outcome": outcome,
            "language": language,
            "duration_seconds": round(time.time() - start_time, 2),
        },
        "timestamp": time.time(),
    }

    try:
        save_repo_activity(repo_id, activity_record)
    except Exception as e:
        logger.warning(f"Could not persist run activity: {e}")

    if engine and hasattr(engine, "memory") and hasattr(engine.memory, "activities"):
        try:
            engine.memory.activities.append(activity_record)
        except Exception:
            pass

    return exit_code
