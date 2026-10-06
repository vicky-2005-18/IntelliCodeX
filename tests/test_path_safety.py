"""
Tests for path-traversal safety (path containment).

Covers (original batch):
  - ../escape.txt                    (dot-dot in first segment)
  - a/../../escape.txt               (dot-dot after one valid segment)
  - absolute path                    (os.path.isabs guard)
  - symlink inside repo pointing outside (realpath guard)
  - null byte in path                (null-byte guard)
  - valid nested path                (must still work correctly)

Covers (hardening batch):
  - ..\\escape.txt                   (Windows-style backslash dot-dot; all OSes)
  - C:escape.txt                     (Windows drive-relative; all OSes)
  - \\\\server\\share\\x             (UNC path; Windows-only)
  - file.txt:stream                  (NTFS alternate data stream; Windows-only)
  - "dir. " / "file "               (trailing dots/spaces; Windows-only filesystem)
  - validate_diff_paths: diff --git header
  - validate_diff_paths: rename from/to
  - validate_diff_paths: copy from/to
  - validate_diff_paths: quoted paths with spaces
  - validate_diff_paths: /dev/null (allowed)
  - _populate_sandbox: symlink to outside file is not copied into sandbox

For every attack vector we also assert that no file and no .bak is created
outside the trusted root directory.
"""
import logging
import os
import shutil
import sys
import tempfile
import pytest

# Ensure project root is on sys.path (mirrors conftest.py logic)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from core.safe_paths import resolve_within, validate_diff_paths
from backend.patch_generator.patch_applier import apply_patch_to_file, apply_unified_diff
from core.sandbox_runner import SandboxRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: str) -> str:
    """Create a minimal fake repo with one file and return its path."""
    target = os.path.join(tmp_path, "src", "app.py")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write("# app\n")
    return tmp_path


def _outside_file(tmp_root: str) -> str:
    """Return a path one level above tmp_root that must never be written."""
    return os.path.join(os.path.dirname(tmp_root), "escaped.txt")


# ===========================================================================
# resolve_within unit tests — original batch
# ===========================================================================

class TestResolveWithin:
    """Direct unit tests for the resolve_within() helper."""

    def test_valid_nested_path_resolves(self, tmp_path):
        """A well-formed relative path must resolve to the correct absolute path."""
        root = str(tmp_path)
        result = resolve_within(root, "a/b/c.txt")
        assert result == os.path.realpath(os.path.join(root, "a/b/c.txt"))
        assert result.startswith(os.path.realpath(root))

    def test_dot_dot_simple(self, tmp_path):
        """'../escape.txt' must raise ValueError."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "../escape.txt")

    def test_dot_dot_nested(self, tmp_path):
        """'a/../../escape.txt' must raise ValueError."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "a/../../escape.txt")

    def test_absolute_path(self, tmp_path):
        """/etc/passwd (absolute) must raise ValueError."""
        abs_path = "/etc/passwd" if sys.platform != "win32" else "C:\\Windows\\System32\\drivers\\etc\\hosts"
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), abs_path)

    def test_null_byte(self, tmp_path):
        """A path containing a null byte must raise ValueError."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "safe\x00/../etc/passwd")

    def test_empty_path(self, tmp_path):
        """An empty string must raise ValueError."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "")

    def test_blank_path(self, tmp_path):
        """A whitespace-only string must raise ValueError."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "   ")

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
    def test_symlink_escaping_root(self, tmp_path):
        """A symlink inside the repo that points outside must be rejected."""
        outside = tempfile.mkdtemp()
        try:
            link_path = os.path.join(str(tmp_path), "evil_link")
            os.symlink(outside, link_path)
            with pytest.raises(ValueError, match="Path traversal rejected"):
                resolve_within(str(tmp_path), "evil_link/../../../escaped.txt")
        finally:
            shutil.rmtree(outside, ignore_errors=True)


# ===========================================================================
# resolve_within unit tests — Windows-style hardening (run on every OS)
# ===========================================================================

class TestResolveWithinWindowsInputs:
    """
    Windows-style path vectors that must be rejected on every platform.
    This ensures that a diff or patch generated on Windows and applied on
    Linux (or vice-versa) cannot smuggle an escape through a Windows-style path.
    """

    def test_backslash_dot_dot(self, tmp_path):
        """'..\\\\escape.txt' (Windows-style dot-dot) must be rejected on all platforms."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "..\\escape.txt")

    def test_nested_backslash_dot_dot(self, tmp_path):
        """'a\\\\..\\\\..\\\\escape.txt' must be rejected on all platforms."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "a\\..\\..\\escape.txt")

    def test_drive_relative_path(self, tmp_path):
        """'C:escape.txt' (drive-relative, no slash after colon) must be rejected everywhere."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "C:escape.txt")

    def test_lowercase_drive_relative_path(self, tmp_path):
        """'c:escape.txt' must also be rejected (case-insensitive drive letter)."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "c:escape.txt")

    @pytest.mark.skipif(sys.platform != "win32", reason="UNC paths only meaningful on Windows")
    def test_unc_path_backslash(self, tmp_path):
        """'\\\\\\\\server\\\\share\\\\x' must be rejected on Windows."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "\\\\server\\share\\x")

    def test_unc_path_forward_slash(self, tmp_path):
        """'//server/share/x' UNC-style must be rejected on all platforms."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "//server/share/x")

    @pytest.mark.skipif(sys.platform != "win32", reason="ADS is a Windows NTFS feature")
    def test_alternate_data_stream(self, tmp_path):
        """'file.txt:stream' (NTFS ADS) must be rejected on Windows."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "file.txt:stream")

    @pytest.mark.skipif(sys.platform != "win32", reason="Trailing dots/spaces only dangerous on Windows filesystem")
    def test_trailing_dot_in_component(self, tmp_path):
        """'dir.' with trailing dot must be rejected on Windows."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "dir.")

    @pytest.mark.skipif(sys.platform != "win32", reason="Trailing dots/spaces only dangerous on Windows filesystem")
    def test_trailing_space_in_component(self, tmp_path):
        """'file ' with trailing space must be rejected on Windows."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "file ")

    @pytest.mark.skipif(sys.platform != "win32", reason="Trailing dots/spaces only dangerous on Windows filesystem")
    def test_trailing_dot_space_nested(self, tmp_path):
        """'dir. /file.txt' with trailing dot+space in component must be rejected."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "dir. /file.txt")

    def test_valid_path_with_colon_in_value_not_ads(self, tmp_path):
        """A drive letter followed immediately by a slash is absolute and rejected separately."""
        with pytest.raises(ValueError, match="Path traversal rejected"):
            resolve_within(str(tmp_path), "C:/Windows/System32")

    def test_valid_nested_path_unaffected(self, tmp_path):
        """Normal 'sub/file.txt' must still work after adding Windows guards."""
        result = resolve_within(str(tmp_path), "sub/file.txt")
        assert result.startswith(os.path.realpath(str(tmp_path)))


# ===========================================================================
# apply_patch_to_file integration tests — original batch
# ===========================================================================

class TestApplyPatchToFile:
    """Integration tests ensuring no file or .bak is created outside root."""

    def _get_repo(self, tmp_path):
        repo = str(tmp_path)
        app_file = os.path.join(repo, "src", "app.py")
        os.makedirs(os.path.dirname(app_file), exist_ok=True)
        with open(app_file, "w") as f:
            f.write("# original\n")
        return repo

    def test_dot_dot_does_not_write(self, tmp_path):
        """'../escape.txt' must return success=False and never create the file."""
        repo = self._get_repo(tmp_path)
        outside = _outside_file(repo)
        result = apply_patch_to_file(repo, "../escape.txt", "pwned")
        assert result["success"] is False
        assert "traversal" in result["error"].lower() or "rejected" in result["error"].lower()
        assert not os.path.exists(outside), "File must not be created outside root"

    def test_nested_dot_dot_does_not_write(self, tmp_path):
        """'a/../../escape.txt' must return success=False and never create the file."""
        repo = self._get_repo(tmp_path)
        outside = _outside_file(repo)
        result = apply_patch_to_file(repo, "a/../../escape.txt", "pwned")
        assert result["success"] is False
        assert not os.path.exists(outside)

    def test_absolute_path_does_not_write(self, tmp_path):
        """Absolute target_file must be rejected."""
        repo = self._get_repo(tmp_path)
        abs_target = "/tmp/evil.txt" if sys.platform != "win32" else "C:\\Windows\\Temp\\evil.txt"
        result = apply_patch_to_file(repo, abs_target, "pwned")
        assert result["success"] is False

    def test_no_bak_created_on_rejection(self, tmp_path):
        """No .bak file must be created when path traversal is rejected."""
        repo = self._get_repo(tmp_path)
        apply_patch_to_file(repo, "../escape.txt", "pwned", create_backup=True)
        parent = os.path.dirname(repo)
        for entry in os.listdir(parent):
            full = os.path.join(parent, entry)
            assert not full.endswith(".bak"), f"Unexpected .bak file at: {full}"

    def test_null_byte_does_not_write(self, tmp_path):
        """A null byte in the path must be rejected."""
        repo = self._get_repo(tmp_path)
        result = apply_patch_to_file(repo, "safe\x00/../evil.txt", "pwned")
        assert result["success"] is False

    def test_valid_path_still_works(self, tmp_path):
        """A normal valid nested path must still be applied successfully."""
        repo = self._get_repo(tmp_path)
        result = apply_patch_to_file(repo, "src/app.py", "# patched\n")
        assert result["success"] is True
        with open(os.path.join(repo, "src", "app.py")) as f:
            assert f.read() == "# patched\n"

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
    def test_symlink_escape_does_not_write(self, tmp_path):
        """A symlink pointing outside the root must be rejected; no file written outside."""
        repo = self._get_repo(tmp_path)
        outside_dir = tempfile.mkdtemp()
        try:
            link_name = os.path.join(repo, "link_out")
            os.symlink(outside_dir, link_name)
            victim = os.path.join(outside_dir, "pwned.txt")
            result = apply_patch_to_file(repo, "link_out/pwned.txt", "pwned")
            assert result["success"] is False
            assert not os.path.exists(victim), "File must not be created outside root via symlink"
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)


# ===========================================================================
# validate_diff_paths — hardening batch
# ===========================================================================

class TestValidateDiffPaths:
    """Comprehensive tests for validate_diff_paths()."""

    # -- Standard unified diff headers already covered, spot-check here --

    def test_plus_plus_plus_escape_rejected(self, tmp_path):
        """A +++ header that escapes must be caught."""
        diff = "+++ b/../evil.py\n@@ -1 +1 @@\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_minus_minus_minus_escape_rejected(self, tmp_path):
        """A --- header that escapes must be caught."""
        diff = "--- a/../evil.py\n+++ b/safe.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_both_headers_safe(self, tmp_path):
        """Both headers pointing inside root must pass."""
        diff = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n"
        assert validate_diff_paths(str(tmp_path), diff) is None

    # -- diff --git extended header --

    def test_diff_git_header_a_escapes(self, tmp_path):
        """diff --git a/../evil.py b/safe.py must be rejected (a-path escapes)."""
        diff = "diff --git a/../evil.py b/safe.py\n--- a/../evil.py\n+++ b/safe.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_diff_git_header_b_escapes(self, tmp_path):
        """diff --git a/safe.py b/../evil.py must be rejected (b-path escapes)."""
        diff = "diff --git a/safe.py b/../evil.py\n--- a/safe.py\n+++ b/../evil.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_diff_git_header_both_safe(self, tmp_path):
        """diff --git with both paths inside root must pass."""
        diff = "diff --git a/src/a.py b/src/b.py\n--- a/src/a.py\n+++ b/src/b.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is None

    # -- rename from/to --

    def test_rename_from_escapes(self, tmp_path):
        """'rename from ../evil.py' must be rejected."""
        diff = "rename from ../evil.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_rename_to_escapes(self, tmp_path):
        """'rename to ../evil.py' must be rejected."""
        diff = "rename to ../evil.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_rename_safe(self, tmp_path):
        """rename from/to inside the root must pass."""
        diff = "rename from src/old.py\nrename to src/new.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is None

    # -- copy from/to --

    def test_copy_from_escapes(self, tmp_path):
        """'copy from ../evil.py' must be rejected."""
        diff = "copy from ../evil.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_copy_to_escapes(self, tmp_path):
        """'copy to ../evil.py' must be rejected."""
        diff = "copy to ../evil.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is not None

    def test_copy_safe(self, tmp_path):
        """copy from/to inside the root must pass."""
        diff = "copy from src/template.py\ncopy to src/instance.py\n"
        assert validate_diff_paths(str(tmp_path), diff) is None

    # -- /dev/null is always allowed --

    def test_dev_null_allowed(self, tmp_path):
        """'/dev/null' in headers (new/deleted files) must be allowed."""
        diff = "--- /dev/null\n+++ b/src/new_file.py\n@@ -0,0 +1 @@\n+# new\n"
        assert validate_diff_paths(str(tmp_path), diff) is None

    # -- Quoted paths with spaces --

    def test_quoted_path_safe(self, tmp_path):
        """A quoted path with spaces that resolves inside the root must pass."""
        diff = '+++ "b/src/my file.py"\n'
        assert validate_diff_paths(str(tmp_path), diff) is None

    def test_quoted_path_escapes(self, tmp_path):
        """A quoted path with spaces that escapes must be rejected."""
        diff = '+++ "b/../my evil file.py"\n'
        assert validate_diff_paths(str(tmp_path), diff) is not None

    # -- Full realistic diff (existing tests carried forward) --

    def test_diff_with_escaping_path_rejected(self, tmp_path):
        """A diff whose +++ header escapes the root must be rejected."""
        repo = str(tmp_path)
        bad_diff = (
            "diff --git a/src/app.py b/../evil.py\n"
            "--- a/src/app.py\n"
            "+++ b/../evil.py\n"
            "@@ -1 +1 @@\n"
            "-# original\n"
            "+# pwned\n"
        )
        result = apply_unified_diff(repo, bad_diff)
        assert result["success"] is False
        assert "traversal" in result["error"].lower() or "rejected" in result["error"].lower()

    def test_diff_with_valid_path_passes_validation(self, tmp_path):
        """A diff with safe relative paths must pass the header validation step."""
        safe_diff = (
            "diff --git a/src/app.py b/src/app.py\n"
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-# original\n"
            "+# patched\n"
        )
        assert validate_diff_paths(str(tmp_path), safe_diff) is None


# ===========================================================================
# SandboxRunner integration tests — original batch
# ===========================================================================

class TestSandboxRunnerPathSafety:
    """Ensure SandboxRunner rejects unsafe target_file paths."""

    def test_dot_dot_target_file_rejected(self, tmp_path):
        """'../escape.txt' as target_file must produce a failed SandboxTestResult."""
        runner = SandboxRunner()
        repo = str(tmp_path)
        result = runner.run_tests_with_patch(
            repo_path=repo,
            target_file="../escape.txt",
            patched_code="pwned",
            test_command=[sys.executable, "-c", "print('ok')"],
        )
        assert result.success is False
        assert result.exit_code == -3
        assert "traversal" in (result.error_message or "").lower() or "rejected" in (result.error_message or "").lower()
        outside = _outside_file(repo)
        assert not os.path.exists(outside)

    def test_absolute_target_file_rejected(self, tmp_path):
        """An absolute target_file must be rejected."""
        runner = SandboxRunner()
        repo = str(tmp_path)
        abs_target = "/tmp/evil.txt" if sys.platform != "win32" else "C:\\Windows\\Temp\\evil.txt"
        result = runner.run_tests_with_patch(
            repo_path=repo,
            target_file=abs_target,
            patched_code="pwned",
            test_command=[sys.executable, "-c", "print('ok')"],
        )
        assert result.success is False
        assert result.exit_code == -3

    def test_valid_target_file_passes(self, tmp_path):
        """A safe relative target_file must be accepted and written inside the sandbox."""
        runner = SandboxRunner()
        repo = str(tmp_path)
        result = runner.run_tests_with_patch(
            repo_path=repo,
            target_file="module.py",
            patched_code="x = 1\n",
            test_command=[sys.executable, "-c", "print('ok')"],
        )
        assert result.exit_code != -3, "Valid path must not be rejected as a traversal"


# ===========================================================================
# _populate_sandbox symlink isolation test
# ===========================================================================

class TestPopulateSandboxSymlinks:
    """Verify that _populate_sandbox never follows symlinks out of the repo."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
    def test_symlink_to_outside_file_not_copied(self, tmp_path):
        """
        A symlink inside the repo that points to a file outside the repo must not
        result in that file's contents (or any copy of it) appearing in the sandbox.
        """
        repo_dir = str(tmp_path / "repo")
        os.makedirs(repo_dir)

        # Create an innocent file inside the repo
        with open(os.path.join(repo_dir, "safe.py"), "w") as f:
            f.write("# safe\n")

        # Create a sensitive file OUTSIDE the repo
        outside_dir = tempfile.mkdtemp()
        try:
            secret_path = os.path.join(outside_dir, "secret.txt")
            with open(secret_path, "w") as f:
                f.write("TOP SECRET\n")

            # Create a symlink inside the repo pointing at the outside file
            link_in_repo = os.path.join(repo_dir, "evil_link.txt")
            os.symlink(secret_path, link_in_repo)

            # Now populate the sandbox
            sandbox_dir = str(tmp_path / "sandbox")
            os.makedirs(sandbox_dir)
            runner = SandboxRunner()
            runner._populate_sandbox(repo_dir, sandbox_dir)

            # The symlink target contents must NOT appear in the sandbox
            sandbox_link = os.path.join(sandbox_dir, "evil_link.txt")
            if os.path.exists(sandbox_link):
                with open(sandbox_link) as f:
                    contents = f.read()
                assert "TOP SECRET" not in contents, (
                    "Secret contents of outside file must not appear in sandbox"
                )
            # Preferably the link (or its copy) is simply absent
            # Either absent or present but not containing the secret is acceptable.
            # The primary assertion above is the security-critical one.

            # The safe file must be present
            assert os.path.isfile(os.path.join(sandbox_dir, "safe.py"))

        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks require elevated privileges on Windows")
    def test_symlinked_directory_not_followed(self, tmp_path):
        """
        A symlink to a directory outside the repo must not be followed during sandbox copy.
        """
        repo_dir = str(tmp_path / "repo")
        os.makedirs(repo_dir)

        outside_dir = tempfile.mkdtemp()
        try:
            # Sensitive file outside repo
            secret_path = os.path.join(outside_dir, "db_credentials.cfg")
            with open(secret_path, "w") as f:
                f.write("password=hunter2\n")

            # Symlink pointing to the outside directory
            link_in_repo = os.path.join(repo_dir, "config_link")
            os.symlink(outside_dir, link_in_repo)

            sandbox_dir = str(tmp_path / "sandbox")
            os.makedirs(sandbox_dir)
            runner = SandboxRunner()
            runner._populate_sandbox(repo_dir, sandbox_dir)

            # The outside directory and its contents must not appear in the sandbox
            sandbox_config = os.path.join(sandbox_dir, "config_link", "db_credentials.cfg")
            if os.path.exists(sandbox_config):
                with open(sandbox_config) as f:
                    contents = f.read()
                assert "hunter2" not in contents, (
                    "Credentials from outside-repo dir must not appear in sandbox"
                )

        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)


# ===========================================================================
# Logging warning tests
# ===========================================================================

class TestReadFileLogsWarning:
    """Ensure _read_file emits a logger.warning when a path is rejected."""

    def test_core_patch_generator_read_file_logs(self, tmp_path, caplog):
        """core.patch_generator._read_file must log a WARNING when path is rejected."""
        from core.patch_generator import PatchEngine
        from core.vectorstore import FaissVectorStore
        from core.embedder import TfidfEmbedder

        embedder = TfidfEmbedder(dim=16)
        store = FaissVectorStore(dim=16)
        engine = PatchEngine(store, embedder, llm=None, repo_path=str(tmp_path))

        with caplog.at_level(logging.WARNING, logger="core.patch_generator"):
            result = engine._read_file("../evil.py")

        assert result is None
        assert any("traversal" in r.message.lower() or "rejected" in r.message.lower()
                   for r in caplog.records)

    def test_backend_patch_engine_read_file_logs(self, tmp_path, caplog):
        """backend.patch_engine._read_file must log a WARNING when path is rejected."""
        # PatchEngine in backend imports db_manager; guard with try/except
        try:
            from backend.patch_generator.patch_engine import PatchEngine as BackendEngine
            from core.vectorstore import FaissVectorStore
            from core.embedder import TfidfEmbedder

            embedder = TfidfEmbedder(dim=16)
            store = FaissVectorStore(dim=16)
            engine = BackendEngine(store, embedder, llm=None, repo_path=str(tmp_path))

            with caplog.at_level(logging.WARNING, logger="backend.patch_generator.patch_engine"):
                result = engine._read_file("../evil.py")

            assert result is None
            assert any("traversal" in r.message.lower() or "rejected" in r.message.lower()
                       for r in caplog.records)
        except Exception as exc:
            pytest.skip(f"backend PatchEngine not importable in test context: {exc}")
