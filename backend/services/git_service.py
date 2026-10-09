"""
Git Integration Service (Phase 9)
Clones remote GitHub/GitLab repositories, fetches branches, commit history, diffs, and syncs status.
"""
import os
import subprocess
import shutil
from typing import List, Dict, Any, Optional
from backend.config import settings


import re
import urllib.parse


def sanitize_git_url(url: str) -> str:
    """Redacts credentials in URL for safe logging/printing."""
    return re.sub(r"://([^@/]+)@", r"://***@", url)


class GitService:
    def clone_repository(self, repo_url: str, repo_id: str, timeout_seconds: int = 60, full_history: bool = False) -> str:
        """Clones a remote repository URL into local storage directory (shallow clone --depth 1 by default)."""
        import stat

        if not repo_url:
            raise ValueError("Git clone URL cannot be empty.")
        if repo_url.startswith("-"):
            raise ValueError(f"Invalid git clone URL: '{repo_url}' cannot start with '-'")
        if any(c.isspace() for c in repo_url):
            raise ValueError(f"Git clone URL cannot contain whitespace: '{repo_url}'")
        if not repo_url.startswith("https://"):
            raise ValueError("Git clone URL must use https:// protocol only.")

        try:
            parsed = urllib.parse.urlparse(repo_url)
        except Exception as e:
            raise ValueError(f"Malformed git clone URL: {e}")

        # Reject URLs with embedded credentials (userinfo)
        if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
            raise ValueError("Git clone URL must not contain embedded credentials.")

        url = repo_url

        def remove_readonly(func, path, exc_info):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        def _cleanup_dir(d: str) -> None:
            if os.path.exists(d):
                try:
                    shutil.rmtree(d, onerror=remove_readonly)
                except Exception:
                    pass
                if os.path.exists(d):
                    import time
                    backup_dir = f"{d}_{int(time.time())}"
                    try:
                        os.rename(d, backup_dir)
                        shutil.rmtree(backup_dir, onerror=remove_readonly)
                    except Exception:
                        pass

        target_dir = os.path.abspath(os.path.join(settings.REPOS_DIR, repo_id))
        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        git_env["GIT_ALLOW_PROTOCOL"] = "https"

        # Check if target_dir is a valid git repository with working status
        is_valid = False
        if os.path.exists(target_dir) and os.path.join(target_dir, ".git"):
            try:
                check_res = subprocess.run(
                    ["git", "status"],
                    cwd=target_dir,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    env=git_env,
                )
                if check_res.returncode == 0:
                    is_valid = True
            except subprocess.TimeoutExpired:
                pass

        if is_valid:
            try:
                pull_res = subprocess.run(
                    ["git", "pull"],
                    cwd=target_dir,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=git_env,
                )
                if pull_res.returncode == 0:
                    return target_dir
            except subprocess.TimeoutExpired:
                pass

        _cleanup_dir(target_dir)

        cmd = ["git", "clone"]
        if not full_history:
            cmd.extend(["--depth", "1"])
        cmd.extend(["--", url, target_dir])
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, env=git_env)
        except subprocess.TimeoutExpired:
            _cleanup_dir(target_dir)
            raise RuntimeError(f"Git clone operation timed out after {timeout_seconds} seconds.")
        except Exception:
            _cleanup_dir(target_dir)
            raise

        if res.returncode != 0:
            _cleanup_dir(target_dir)
            raise RuntimeError(f"Git clone failed: {res.stderr}")
        return target_dir

    def get_commit_history(self, repo_path: str, max_count: int = 15) -> List[Dict[str, str]]:
        """Retrieves recent commit log history."""
        if not os.path.exists(os.path.join(repo_path, ".git")):
            return []

        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        cmd = ["git", "log", f"-n{max_count}", "--pretty=format:%H|%an|%s|%cr"]
        try:
            res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=15, env=git_env)
        except subprocess.TimeoutExpired:
            return []

        if res.returncode != 0:
            return []

        commits = []
        for line in res.stdout.splitlines():
            parts = line.split("|")
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "message": parts[2],
                    "date": parts[3]
                })
        return commits

    def get_branches(self, repo_path: str) -> List[str]:
        """Lists repository branches."""
        if not os.path.exists(os.path.join(repo_path, ".git")):
            return ["main"]

        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        cmd = ["git", "branch", "-a"]
        try:
            res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=15, env=git_env)
        except subprocess.TimeoutExpired:
            return ["main"]

        if res.returncode != 0:
            return ["main"]

        branches = [b.strip("* ").strip() for b in res.stdout.splitlines()]
        return branches or ["main"]

    def get_changed_files(self, repo_path: str) -> List[str]:
        """Gets list of modified or untracked files."""
        if not os.path.exists(os.path.join(repo_path, ".git")):
            return []

        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        cmd = ["git", "status", "--porcelain"]
        try:
            res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=15, env=git_env)
        except subprocess.TimeoutExpired:
            return []

        if res.returncode != 0:
            return []

        changed = []
        for line in res.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                changed.append(parts[1])
        return changed
