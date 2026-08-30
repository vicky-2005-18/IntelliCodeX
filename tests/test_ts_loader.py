"""
Tests for Tree-Sitter Language Loader Module
"""
import pytest
from core.ts_loader import get_tree_sitter_parser, is_tree_sitter_available


@pytest.mark.parametrize("lang", [
    "python", "javascript", "typescript", "java", "c", "cpp", "go", "rust"
])
def test_tree_sitter_loader(lang):
    assert is_tree_sitter_available(lang) is True
    parser = get_tree_sitter_parser(lang)
    assert parser is not None

    # Parse simple code snippet
    code = b"int x = 42;" if lang in ("c", "cpp", "java") else b"let x = 42;"
    tree = parser.parse(code)
    assert tree.root_node is not None
    assert tree.root_node.type != ""


def test_unknown_language():
    assert is_tree_sitter_available("unknown_language_xyz") is False
    assert get_tree_sitter_parser("unknown_language_xyz") is None
