"""
Tests for Tree-Sitter Semantic Chunker (JS/TS/TSX & Java)
"""
import pytest
from core.parser import SourceFile
from core.chunker import chunk_file


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


def test_chunk_typescript_file():
    code = """
interface UserProfile {
    id: string;
    name: string;
}

export class AuthService {
    async login(user: string): Promise<boolean> {
        return true;
    }
}
"""
    sf = SourceFile(
        path="/tmp/auth.ts",
        rel_path="src/auth.ts",
        language="typescript",
        content=code,
        has_tree_sitter=True,
        line_count=len(code.splitlines()),
        size_bytes=len(code.encode("utf-8"))
    )

    chunks = chunk_file(sf)
    chunk_names = [c.name for c in chunks]

    assert "UserProfile" in chunk_names
    assert "AuthService" in chunk_names
    assert "AuthService.login" in chunk_names


def test_chunk_java_file():
    code = """
public class OrderService {
    private int orderId;

    public OrderService(int id) {
        this.orderId = id;
    }

    public void processOrder() {
        System.out.println("Processing " + this.orderId);
    }
}
"""
    sf = SourceFile(
        path="/tmp/OrderService.java",
        rel_path="src/OrderService.java",
        language="java",
        content=code,
        has_tree_sitter=True,
        line_count=len(code.splitlines()),
        size_bytes=len(code.encode("utf-8"))
    )

    chunks = chunk_file(sf)
    chunk_names = [c.name for c in chunks]

    assert "OrderService" in chunk_names
    assert "OrderService.OrderService" in chunk_names
    assert "OrderService.processOrder" in chunk_names
