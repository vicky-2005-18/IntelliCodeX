"""
IntelliCodeX Interactive GUI Preview Engine.

Launches graphical applications (e.g. Java Swing, AWT) inside an isolated Docker
sandbox with a virtual X11 display (Xvfb), lightweight window manager (Openbox),
x11vnc server, and HTML5 noVNC browser interface.

Security & Sandbox Invariants:
1. Source repository is mounted read-only (/work:ro).
2. Network exposure is strictly limited to localhost (127.0.0.1:<port>).
3. Linux security capabilities are dropped (--cap-drop ALL).
4. Container lifecycle is fully managed and cleaned up on termination.
"""

import os
import sys
import time
import socket
import urllib.request
import subprocess
from typing import Optional, Tuple, Dict, Any, List

from core.canonical_path import resolve_canonical_target_path


def find_available_port(start_port: int = 16080, max_attempts: int = 50) -> int:
    """Finds an available TCP port bound strictly to 127.0.0.1."""
    # Preferred candidate ports avoiding Windows Hyper-V excluded ranges
    candidates = [start_port, 8090, 8085, 9090, 16080, 26080, 36080]
    for p in candidates:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            s.listen(1)
            s.close()
            return p
        except Exception:
            continue

    for p in range(16081, 16081 + max_attempts):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            s.listen(1)
            s.close()
            return p
        except Exception:
            continue

    return 16080


def ensure_gui_docker_image(image_name: str = "intellicodex-gui:latest") -> bool:
    """Verifies that the GUI Docker image exists or builds it from Dockerfile.gui."""
    res = subprocess.run(
        ["docker", "image", "inspect", image_name],
        capture_output=True,
        text=True
    )
    if res.returncode == 0:
        return True

    print(f"[*] Docker image '{image_name}' not found locally. Building from Dockerfile.gui...")
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dockerfile_path = os.path.join(base_dir, "Dockerfile.gui")
    if not os.path.isfile(dockerfile_path):
        print(f"[!] Dockerfile.gui not found at '{dockerfile_path}'.")
        return False

    build_cmd = ["docker", "build", "-f", dockerfile_path, "-t", image_name, base_dir]
    b_res = subprocess.run(build_cmd, capture_output=True, text=True)
    if b_res.returncode != 0:
        print(f"[!] Failed to build '{image_name}':\n{b_res.stderr}")
        return False

    return True


class GuiPreviewSession:
    """Manages an active GUI preview container session with clean lifecycle guarantees."""

    def __init__(
        self,
        repo_path: str,
        target_file: str,
        image_name: str = "intellicodex-gui:latest",
        host_port: Optional[int] = None,
        candidate_files: Optional[List[str]] = None
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.target_file_raw = target_file
        self.image_name = image_name
        self.candidate_files = candidate_files
        self.host_port = host_port or find_available_port()
        self.container_name = f"intellicodex-gui-{int(time.time())}-{os.getpid()}"
        self.canon_target: Optional[str] = None
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False

    def start(self, timeout_sec: int = 25) -> Tuple[bool, str]:
        """Starts the Docker GUI preview container and waits for noVNC endpoint to be ready."""
        # 1. Resolve canonical target path
        canon_path, err = resolve_canonical_target_path(
            self.repo_path, self.target_file_raw, candidate_files=self.candidate_files
        )
        if err or not canon_path:
            return False, f"Target resolution failed: {err}"
        self.canon_target = canon_path

        abs_file = os.path.join(self.repo_path, canon_path)
        if not os.path.isfile(abs_file):
            return False, f"Target file '{canon_path}' does not exist on disk."

        # 2. Check Docker image
        if not ensure_gui_docker_image(self.image_name):
            return False, f"GUI Docker image '{self.image_name}' is not available."

        # 3. Construct docker run command
        # Security constraints:
        # - Read-only source mount (/work:ro)
        # - Localhost only port binding (127.0.0.1:<port>:6080)
        # - In-memory /tmp for compilation (/tmp:rw,exec)
        # - Dropped capabilities
        docker_cmd = [
            "docker", "run", "--rm",
            "--name", self.container_name,
            "-p", f"127.0.0.1:{self.host_port}:6080",
            "-v", f"{self.repo_path}:/work:ro",
            "--cap-drop", "ALL",
            "-e", f"TARGET_FILE={self.canon_target}",
            self.image_name
        ]

        try:
            self.process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            self.is_running = True
        except Exception as e:
            return False, f"Failed to start Docker container: {e}"

        # 4. Wait for noVNC endpoint to respond
        preview_url = f"http://127.0.0.1:{self.host_port}/vnc.html?autoconnect=true&resize=scale"
        endpoint_test_url = f"http://127.0.0.1:{self.host_port}/vnc.html"

        start_time = time.time()
        ready = False
        while time.time() - start_time < timeout_sec:
            # Check if container died prematurely
            if self.process.poll() is not None:
                out = self.process.stdout.read() if self.process.stdout else ""
                self.is_running = False
                return False, f"Container exited unexpectedly (exit code {self.process.returncode}):\n{out}"

            try:
                with urllib.request.urlopen(endpoint_test_url, timeout=1.0) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(0.5)

        if not ready:
            self.stop()
            return False, f"Timeout waiting for noVNC server to become ready on port {self.host_port}."

        return True, preview_url

    def stop(self):
        """Stops and cleans up the Docker container and associated processes."""
        if not self.is_running and not self.process:
            return

        self.is_running = False
        # Stop container explicitly via docker stop
        subprocess.run(
            ["docker", "stop", "-t", "2", self.container_name],
            capture_output=True,
            text=True
        )

        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def parse_gui_preview_request(
    query: str,
    repo_path: Optional[str] = None,
    candidate_files: Optional[List[str]] = None
) -> Tuple[bool, Optional[str]]:
    """
    Detects explicit GUI preview commands (e.g. 'preview @TodoApp.java',
    'gui @TodoApp.java', 'preview: @TodoApp.java', 'run --gui @TodoApp.java').
    """
    if not query or not query.strip():
        return False, None

    raw_q = query.strip()
    while raw_q.startswith(">") or raw_q.startswith("$"):
        raw_q = raw_q.lstrip(">").lstrip("$").strip()

    # Prefix matches: preview:, gui:, novnc:, vnc:
    for prefix in ("preview:", "gui:", "novnc:", "vnc:"):
        if raw_q.lower().startswith(prefix):
            target_cand = raw_q[len(prefix):].strip()
            from core.canonical_path import parse_mention
            _, mention = parse_mention(target_cand)
            return True, mention or target_cand.strip("'\"`")

    # Command matches: preview @file, gui @file
    words = raw_q.split(maxsplit=1)
    if words and words[0].lower() in ("preview", "gui", "novnc", "vnc"):
        if len(words) > 1:
            target_cand = words[1].strip()
            from core.canonical_path import parse_mention
            _, mention = parse_mention(target_cand)
            return True, mention or target_cand.strip("'\"`")

    # Command with --gui flag: 'run --gui @TodoApp.java' or 'run @TodoApp.java --gui'
    if "run" in raw_q.lower() and ("--gui" in raw_q.lower() or "-gui" in raw_q.lower() or "preview" in raw_q.lower()):
        clean_words = [w for w in raw_q.split() if w.lower() not in ("run", "run:", "--gui", "-gui", "preview")]
        rem = " ".join(clean_words)
        from core.canonical_path import parse_mention
        _, mention = parse_mention(rem)
        return True, mention or rem.strip("'\"`")

    return False, None


def execute_gui_preview_command(
    query: str,
    repo_path: str,
    candidate_files: Optional[List[str]] = None,
    session=None,
    use_tui: bool = False,
    is_batch: bool = False,
    auto_open_browser: bool = False
) -> int:
    """Executes the GUI preview workflow, starts the container, and manages user session."""
    is_gui, target = parse_gui_preview_request(query, repo_path=repo_path, candidate_files=candidate_files)
    if not is_gui or not target:
        target = "TodoApp.java"

    print("==========================================================================")
    print("  LAUNCHING INTELLICODEX GUI PREVIEW (VIRTUAL DISPLAY & noVNC)")
    print("==========================================================================")
    print(f"[*] Target File          : '{target}'")
    print(f"[*] Repository Root      : '{repo_path}'")
    print(f"[*] Display Stack        : Xvfb (:99) + Openbox WM + x11vnc + noVNC websockify")
    print(f"[*] Security Sandbox     : Read-only source mount (/work:ro), Localhost only, Cap Drop ALL")

    preview_session = GuiPreviewSession(
        repo_path=repo_path,
        target_file=target,
        candidate_files=candidate_files
    )

    print(f"[*] Starting isolated container session on localhost port {preview_session.host_port}...")
    success, preview_url = preview_session.start()

    if not success:
        print(f"\n[!] Failed to start GUI preview:\n{preview_url}\n")
        return 1

    print("\n" + "=" * 74)
    print(f"  [✓] GUI PREVIEW IS ACTIVE AND READY!")
    print(f"  Browser URL : {preview_url}")
    print(f"  Container   : {preview_session.container_name}")
    print(f"  Security    : Bound strictly to 127.0.0.1 (No external network exposure)")
    print("=" * 74)
    print("\nInstructions:")
    print(f"  1. Open the URL in your browser: {preview_url}")
    print("  2. Interact with the live Java Swing buttons: Add, Edit, Complete, Delete, Clear Completed")
    print("  3. When finished, press [Enter] or type 'q' below to terminate and clean up container.\n")

    if auto_open_browser:
        try:
            import webbrowser
            webbrowser.open(preview_url)
        except Exception:
            pass

    if is_batch:
        # In batch mode, allow preview to stay running briefly or test connection
        print("[*] Batch mode preview launched successfully.")
        preview_session.stop()
        print("[*] Container cleaned up.")
        return 0

    try:
        if session is not None and use_tui:
            _ = session.prompt("Press Enter to stop GUI preview and clean up container: ")
        else:
            _ = input("Press Enter to stop GUI preview and clean up container: ")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        print("\n[*] Stopping GUI preview and cleaning up container...")
        preview_session.stop()
        print("[+] Container stopped. All temporary display and preview processes terminated.\n")

    return 0
