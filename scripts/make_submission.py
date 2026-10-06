#!/usr/bin/env python3
"""
Create a clean submission zip containing only tracked Git files.

This script builds a zip archive from `git ls-files` to ensure only
tracked files are included in the submission package.
"""

import os
import subprocess
import zipfile
from pathlib import Path
from datetime import datetime


def get_tracked_files():
    """Get list of all tracked files from git."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.splitlines()


def create_submission_zip(output_path, files):
    """Create zip archive from list of files."""
    repo_root = Path.cwd()
    file_count = 0
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file_path in files:
            full_path = repo_root / file_path
            if full_path.exists() and full_path.is_file():
                zf.write(full_path, file_path)
                file_count += 1
            else:
                print(f"Warning: {file_path} not found, skipping")
    
    return file_count


def main():
    """Main entry point."""
    repo_root = Path.cwd()
    if not (repo_root / ".git").exists():
        print("Error: Not in a git repository")
        return 1
    
    print(f"Building submission from: {repo_root}")
    
    # Get tracked files
    print("Getting tracked files from git...")
    files = get_tracked_files()
    print(f"Found {len(files)} tracked files")
    
    # Create output filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = repo_root / f"intellicodex_submission_{timestamp}.zip"
    
    # Create zip
    print(f"Creating zip archive: {output_path.name}")
    file_count = create_submission_zip(output_path, files)
    
    # Get file size
    size_mb = output_path.stat().st_size / (1024 * 1024)
    
    print(f"\nSubmission created successfully!")
    print(f"  Files archived: {file_count}")
    print(f"  Output: {output_path}")
    print(f"  Size: {size_mb:.2f} MB")
    
    if size_mb >= 20:
        print(f"\nWarning: Archive size ({size_mb:.2f} MB) exceeds 20 MB limit")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
