"""
Tree-Sitter Language Loader Module
Provides unified loading for tree-sitter language grammars and parser instances across Python, JS/TS, Java, C/C++, Go, and Rust.
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Cache loaded tree-sitter language objects and parsers (None indicates failed/unsupported)
_LANGUAGES: Dict[str, Any] = {}
_PARSERS: Dict[str, Any] = {}
_TREE_SITTER_WARNED_LANGS = set()


def _init_language(lang_name: str):
    """Dynamically loads and registers tree-sitter language grammar bindings."""
    if lang_name in _LANGUAGES:
        return _LANGUAGES[lang_name]

    try:
        from tree_sitter import Language

        if lang_name == "python":
            import tree_sitter_python as tspython
            lang_obj = Language(tspython.language())
        elif lang_name == "javascript":
            import tree_sitter_javascript as tsjs
            lang_obj = Language(tsjs.language())
        elif lang_name == "typescript":
            import tree_sitter_typescript as tsts
            lang_obj = Language(tsts.language_typescript())
        elif lang_name == "tsx":
            import tree_sitter_typescript as tsts
            lang_obj = Language(tsts.language_tsx())
        elif lang_name == "java":
            import tree_sitter_java as tsjava
            lang_obj = Language(tsjava.language())
        elif lang_name == "c":
            import tree_sitter_c as tsc
            lang_obj = Language(tsc.language())
        elif lang_name in ("cpp", "c++"):
            import tree_sitter_cpp as tscpp
            lang_obj = Language(tscpp.language())
        elif lang_name == "go":
            import tree_sitter_go as tsgo
            lang_obj = Language(tsgo.language())
        elif lang_name == "rust":
            import tree_sitter_rust as tsrust
            lang_obj = Language(tsrust.language())
        else:
            _LANGUAGES[lang_name] = None
            return None

        _LANGUAGES[lang_name] = lang_obj
        return lang_obj
    except Exception as e:
        if lang_name not in _TREE_SITTER_WARNED_LANGS:
            logger.debug(f"Tree-sitter binding for '{lang_name}' unavailable ({e}). Using fallback chunker.")
            _TREE_SITTER_WARNED_LANGS.add(lang_name)
        _LANGUAGES[lang_name] = None
        return None


def is_tree_sitter_available(lang_name: str) -> bool:
    """Returns True if tree-sitter is installed and grammar binding is supported for lang_name."""
    return _init_language(lang_name) is not None


def get_tree_sitter_parser(lang_name: str):
    """Returns a configured tree-sitter Parser object for the requested language, or None if unavailable."""
    if lang_name in _PARSERS:
        return _PARSERS[lang_name]

    lang_obj = _init_language(lang_name)
    if lang_obj is None:
        return None

    try:
        from tree_sitter import Parser
        parser = Parser(lang_obj)
        _PARSERS[lang_name] = parser
        return parser
    except Exception as e:
        logger.warning(f"Failed to create tree-sitter parser for '{lang_name}': {e}")
        return None
