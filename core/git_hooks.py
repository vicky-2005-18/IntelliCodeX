"""
Git Hook Generator & Installer Module
Installs post-commit and post-merge hooks into target Git repositories to trigger
automatic background incremental re-indexing whenever repository code changes.
"""
import os
import sys
import stat
from typing import Tuple, Dict, Optional

HOOK_MARKER = "# IntelliCodeX Auto-Reindex Hook"

HOOK_SCRIPT_TEMPLATE = f"""#!/bin/sh
{HOOK_MARKER}
# Automatically triggers background incremental re-indexing upon git commit/merge
echo "[IntelliCodeX] Triggering background incremental re-indexing..."

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

$PYTHON_CMD -c "from core.pipeline import ingest_repository; from core.embedder import TfidfEmbedder; ingest_repository('.', TfidfEmbedder(), force_reindex=False)" >/dev/null 2>&1 &
"""


def find_git_dir(repo_path: str) -> Optional[str]:
    """Locates the .git directory inside repo_path (supports regular git repos and git worktrees)."""
    abs_path = os.path.abspath(repo_path)
    git_dir = os.path.join(abs_path, ".git")

    if os.path.isdir(git_dir):
        return git_dir

    if os.path.isfile(git_dir):
        # Handle git worktree or submodule file pointing to git dir
        try:
            with open(git_dir, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("gitdir:"):
                target_path = content.split(":", 1)[1].strip()
                target_abs = os.path.abspath(os.path.join(abs_path, target_path))
                if os.path.exists(target_abs):
                    return target_abs
        except Exception:
            pass

    return None


def install_git_hooks(repo_path: str) -> Tuple[bool, str]:
    """
    Installs post-commit and post-merge hooks into <repo_path>/.git/hooks/.
    Returns (success_flag, message_string).
    """
    git_dir = find_git_dir(repo_path)
    if not git_dir:
        return False, f"Not a valid Git repository: '{repo_path}' (no .git directory found)"

    hooks_dir = os.path.join(git_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    target_hooks = ["post-commit", "post-merge"]
    installed_hooks = []

    for hook_name in target_hooks:
        hook_file = os.path.join(hooks_dir, hook_name)

        if os.path.exists(hook_file):
            with open(hook_file, "r", encoding="utf-8", errors="ignore") as f:
                existing_content = f.read()

            if HOOK_MARKER in existing_content:
                # Already installed
                installed_hooks.append(hook_name)
                continue
            else:
                # Append to existing hook script
                new_content = existing_content + "\n\n" + HOOK_SCRIPT_TEMPLATE
        else:
            new_content = HOOK_SCRIPT_TEMPLATE

        with open(hook_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)

        # Set executable permissions (chmod +x)
        try:
            current_perms = os.stat(hook_file).st_mode
            os.chmod(hook_file, current_perms | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass

        installed_hooks.append(hook_name)

    return True, f"Successfully installed Git hooks ({', '.join(installed_hooks)}) in '{hooks_dir}'!"


def uninstall_git_hooks(repo_path: str) -> Tuple[bool, str]:
    """
    Removes IntelliCodeX hook sections from post-commit and post-merge files.
    Returns (success_flag, message_string).
    """
    git_dir = find_git_dir(repo_path)
    if not git_dir:
        return False, f"Not a valid Git repository: '{repo_path}'"

    hooks_dir = os.path.join(git_dir, "hooks")
    target_hooks = ["post-commit", "post-merge"]
    removed_count = 0

    for hook_name in target_hooks:
        hook_file = os.path.join(hooks_dir, hook_name)
        if not os.path.exists(hook_file):
            continue

        with open(hook_file, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        # Remove lines matching the hook template section
        new_lines = []
        skip = False
        for line in lines:
            if HOOK_MARKER in line:
                skip = True
                removed_count += 1
                continue
            if skip and line.startswith("#!"):
                skip = False

            if not skip:
                new_lines.append(line)

        cleaned_content = "".join(new_lines).strip()
        if not cleaned_content:
            os.remove(hook_file)
        else:
            with open(hook_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(cleaned_content + "\n")

    return True, f"Uninstalled IntelliCodeX Git hooks from '{hooks_dir}'."


def check_git_hooks_status(repo_path: str) -> Dict[str, bool]:
    """Returns a dict mapping hook names (post-commit, post-merge) -> boolean installation status."""
    git_dir = find_git_dir(repo_path)
    status = {"post-commit": False, "post-merge": False}
    if not git_dir:
        return status

    hooks_dir = os.path.join(git_dir, "hooks")
    for hook_name in status.keys():
        hook_file = os.path.join(hooks_dir, hook_name)
        if os.path.exists(hook_file):
            try:
                with open(hook_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                status[hook_name] = HOOK_MARKER in content
            except Exception:
                status[hook_name] = False

    return status
