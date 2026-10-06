"""
Tests for Multi-Language Tree-Sitter & Smart Windowed Chunker
(JavaScript, TypeScript, TSX, Java, C, C++, Go, Rust, Markdown, HTML/CSS)
"""
import pytest
from core.parser import SourceFile
from core.chunker import chunk_file, _chunk_markdown_file, _windowed_chunks


def test_chunk_javascript_file():
    code = """
function processPayment(amount) {
    return amount * 1.05;
}

class InvoiceManager {
    generateInvoice(id) {
        return "Invoice-" + id;
    }
}

const sendEmail = (to, body) => {
    console.log(to, body);
};
"""
    sf = SourceFile(
        path="/tmp/payment.js",
        rel_path="src/payment.js",
        language="javascript",
        content=code,
        has_tree_sitter=True,
        line_count=len(code.splitlines()),
        size_bytes=len(code.encode("utf-8"))
    )

    chunks = chunk_file(sf)
    chunk_names = [c.name for c in chunks]

    assert "processPayment" in chunk_names
    assert "InvoiceManager" in chunk_names
    assert "InvoiceManager.generateInvoice" in chunk_names
    assert "sendEmail" in chunk_names


def test_chunk_c_cpp_files():
    code_c = """
int compute_sum(int a, int b) {
    return a + b;
}

struct Vector3D {
    float x;
    float y;
    float z;
};
"""
    sf_c = SourceFile(
        path="/tmp/math.c",
        rel_path="src/math.c",
        language="c",
        content=code_c,
        has_tree_sitter=True,
        line_count=len(code_c.splitlines()),
        size_bytes=len(code_c.encode("utf-8"))
    )

    chunks = chunk_file(sf_c)
    names = [c.name for c in chunks]

    assert "compute_sum" in names
    assert "Vector3D" in names


def test_chunk_go_file():
    code_go = """
package main

type Account struct {
    Balance int
}

func (a *Account) Deposit(amount int) {
    a.Balance += amount
}

func NewAccount() *Account {
    return &Account{Balance: 0}
}
"""
    sf_go = SourceFile(
        path="/tmp/account.go",
        rel_path="src/account.go",
        language="go",
        content=code_go,
        has_tree_sitter=True,
        line_count=len(code_go.splitlines()),
        size_bytes=len(code_go.encode("utf-8"))
    )

    chunks = chunk_file(sf_go)
    names = [c.name for c in chunks]

    assert "Account" in names
    assert "NewAccount" in names


def test_chunk_rust_file():
    code_rs = """
struct Calculator;

impl Calculator {
    fn add(a: i32, b: i32) -> i32 {
        a + b
    }
}

fn main() {
    println!("Hello Rust");
}
"""
    sf_rs = SourceFile(
        path="/tmp/main.rs",
        rel_path="src/main.rs",
        language="rust",
        content=code_rs,
        has_tree_sitter=True,
        line_count=len(code_rs.splitlines()),
        size_bytes=len(code_rs.encode("utf-8"))
    )

    chunks = chunk_file(sf_rs)
    names = [c.name for c in chunks]

    assert "Calculator" in names
    assert "Calculator::add" in names
    assert "main" in names


def test_chunk_markdown_file():
    md = """# Architecture Overview
This document describes the design.

## Storage Layer
Details about FAISS vector store.

## RAG Engine
Details about retrieval.
"""
    sf_md = SourceFile(
        path="/tmp/README.md",
        rel_path="README.md",
        language="markdown",
        content=md,
        has_tree_sitter=False,
        line_count=len(md.splitlines()),
        size_bytes=len(md.encode("utf-8"))
    )

    chunks = chunk_file(sf_md)
    names = [c.name for c in chunks]

    assert "Architecture Overview" in names
    assert "Storage Layer" in names
    assert "RAG Engine" in names


def test_windowed_chunks_for_long_file():
    long_content = "\n".join([f"line_{i} = {i}" for i in range(120)])
    sf = SourceFile(
        path="/tmp/config.json",
        rel_path="config.json",
        language="json",
        content=long_content,
        has_tree_sitter=False,
        line_count=120,
        size_bytes=len(long_content.encode("utf-8"))
    )

    chunks = chunk_file(sf)
    assert len(chunks) > 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 50
