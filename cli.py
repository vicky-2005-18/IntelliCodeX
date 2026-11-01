"""
IntelliCodeX CLI — Ingest and query software repositories interactively.

Modular CLI architecture with 100% backward compatibility wrapper.
Delegates to core.cli subsystem while re-exporting all legacy public symbols,
constants, and utility functions for test and packaging compatibility.

Usage:
    python cli.py [repo_path_or_url] [--backend ollama|tfidf]

Examples:
    python cli.py sample_repo
    python cli.py https://github.com/vicky-2005-18/TB --backend ollama
"""

import os
import sys

# Ensure console output handles unicode without crashing on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root is on sys.path
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Load environment configuration if present
_env_path = os.path.join(_project_root, ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception:
        pass

# Import core.cli subsystem and pipeline dependencies
import core.cli as _core_cli
from core.cli import *
from core.pipeline import ingest_repository


class _CLIModule(sys.modules[__name__].__class__):
    """Dynamic module proxy synchronizing patches and attributes with core.cli."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if name != "_core_cli":
            try:
                if hasattr(_core_cli, name):
                    setattr(_core_cli, name, value)
                main_mod = getattr(_core_cli, "main_module", None) or sys.modules.get("core.cli.main")
                if main_mod is not None and hasattr(main_mod, name):
                    setattr(main_mod, name, value)
            except Exception:
                pass

    def __getattr__(self, name: str) -> object:
        if hasattr(_core_cli, name):
            return getattr(_core_cli, name)
        main_mod = getattr(_core_cli, "main_module", None) or sys.modules.get("core.cli.main")
        if main_mod is not None and hasattr(main_mod, name):
            return getattr(main_mod, name)
        raise AttributeError(f"module 'cli' has no attribute '{name}'")


sys.modules[__name__].__class__ = _CLIModule

# Re-export all public symbols
__all__ = list(_core_cli.__all__)
if "ingest_repository" not in __all__:
    __all__.append("ingest_repository")


def main(argv=None):
    """
    Main CLI entrypoint. Delegates directly to core.cli.main().
    """
    if argv is not None:
        old_argv = sys.argv
        sys.argv = argv
        try:
            return _core_cli.main()
        finally:
            sys.argv = old_argv
    return _core_cli.main()


if __name__ == "__main__":
    sys.exit(main())
