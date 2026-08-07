"""
Git Integration Service (Phase 9)
Clones remote GitHub/GitLab repositories, fetches branches, commit history, diffs, and syncs status.
"""
import os
import subprocess
import shutil
from typing import List, Dict, Any, Optional
from backend.config import settings


class GitService:
    def clone_repository(self, repo_url: str, repo_id: str) -> str:
        """Clones a remote repository URL into local storage directory."""
        import stat

        def remove_readonly(func, path, exc_info):
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        target_dir = os.path.abspath(os.path.join(settings.REPOS_DIR, repo_id))

        # Check if target_dir is a valid git repository with working status
        is_valid = False
        if os.path.exists(target_dir) and os.path.exists(os.path.join(target_dir, ".git")):
            check_res = subprocess.run(["git", "status"], cwd=target_dir, capture_output=True, text=True)
            if check_res.returncode == 0:
                is_valid = True

        if is_valid:
            subprocess.run(["git", "pull"], cwd=target_dir, capture_output=True, text=True)
            return target_dir

        if os.path.exists(target_dir):
            try:
                shutil.rmtree(target_dir, onerror=remove_readonly)
            except Exception:
                pass
            if os.path.exists(target_dir):
                import time
                backup_dir = f"{target_dir}_{int(time.time())}"
                try:
                    os.rename(target_dir, backup_dir)
                    shutil.rmtree(backup_dir, onerror=remove_readonly)
                except Exception:
                    pass

        cmd = ["git", "clone", "--depth", "50", repo_url, target_dir]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"Git clone failed: {res.stderr}")
        return target_dir

    def get_commit_history(self, repo_path: str, max_count: int = 15) -> List[Dict[str, str]]:
        """Retrieves recent commit log history."""
        if not os.path.exists(os.path.join(repo_path, ".git")):
            return []

        cmd = ["git", "log", f"-n{max_count}", "--pretty=format:%H|%an|%s|%cr"]
        res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
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

        cmd = ["git", "branch", "-a"]
        res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
        if res.returncode != 0:
            return ["main"]

        branches = [b.strip("* ").strip() for b in res.stdout.splitlines()]
        return branches or ["main"]

    def get_changed_files(self, repo_path: str) -> List[str]:
        """Gets list of modified or untracked files."""
        if not os.path.exists(os.path.join(repo_path, ".git")):
            return []

        cmd = ["git", "status", "--porcelain"]
        res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
        if res.returncode != 0:
            return []

        changed = []
        for line in res.stdout.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) == 2:
                changed.append(parts[1])
        return changed
