"""
Tests for Multi-Language Dependency Graph Engine
"""
import pytest
import networkx as nx
from core.parser import SourceFile
from core.dependency_graph import (
    extract_file_imports,
    resolve_import_to_file,
    build_dependency_graph,
    files_likely_affected_by,
)


def test_extract_js_ts_imports():
    sf = SourceFile(
        path="/tmp/app.ts",
        rel_path="src/app.ts",
        language="typescript",
        content="""
import { getUser } from './services/user';
import React from 'react';
const db = require('../db');
export * from './types';
""",
        has_tree_sitter=True
    )
    imports = extract_file_imports(sf)
    assert "./services/user" in imports
    assert "react" in imports
    assert "../db" in imports
    assert "./types" in imports


def test_extract_java_imports():
    sf = SourceFile(
        path="/tmp/UserService.java",
        rel_path="src/main/java/com/app/UserService.java",
        language="java",
        content="""
package com.app;
import com.app.models.User;
import com.app.repository.UserRepository;
""",
        has_tree_sitter=True
    )
    imports = extract_file_imports(sf)
    assert "com.app.models.User" in imports
    assert "com.app.repository.UserRepository" in imports


def test_extract_c_cpp_includes():
    sf = SourceFile(
        path="/tmp/main.cpp",
        rel_path="src/main.cpp",
        language="cpp",
        content="""
#include "utils/math.h"
#include <iostream>
#include "../config.hpp"
""",
        has_tree_sitter=True
    )
    imports = extract_file_imports(sf)
    assert "utils/math.h" in imports
    assert "../config.hpp" in imports


def test_multilang_dependency_graph_resolution():
    sf1 = SourceFile(
        path="/repo/src/index.ts",
        rel_path="src/index.ts",
        language="typescript",
        content="import { helper } from './utils/helper';",
        has_tree_sitter=True
    )
    sf2 = SourceFile(
        path="/repo/src/utils/helper.ts",
        rel_path="src/utils/helper.ts",
        language="typescript",
        content="export function helper() { return 42; }",
        has_tree_sitter=True
    )

    graph = build_dependency_graph([sf1, sf2])
    assert isinstance(graph, nx.DiGraph)
    assert graph.has_edge("src/index.ts", "src/utils/helper.ts")

    # Test reverse dependency lookup (affected files when helper.ts changes)
    affected = files_likely_affected_by(graph, "src/utils/helper.ts")
    assert "src/index.ts" in affected
