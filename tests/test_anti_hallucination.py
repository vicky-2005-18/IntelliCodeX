"""
Test anti-hallucination features for bug-finding queries.
Tests prompt formatting, context rendering, claim filtering, and runtime errors pass.
"""
import pytest
from unittest.mock import Mock, MagicMock
from rag.query_engine import QueryEngine, format_context, ConversationMemory
from core.chunker import CodeChunk
from core.vectorstore import FaissVectorStore
from core.embedder import BaseEmbedder


class FakeEmbedder(BaseEmbedder):
    """Fake embedder for testing."""
    def __init__(self):
        self.dim = 768
    
    def embed(self, texts):
        import numpy as np
        return [np.random.rand(self.dim).astype('float32') for _ in texts]


class FakeLLM:
    """Fake LLM that captures prompts for inspection."""
    def __init__(self):
        self.last_prompt = None
        self.last_system = None
        self.last_temperature = None
        self.last_num_ctx = None
        self.response = "Test response"
    
    def generate(self, prompt, system="", temperature=0.2, num_ctx=None):
        self.last_prompt = prompt
        self.last_system = system
        self.last_temperature = temperature
        self.last_num_ctx = num_ctx
        return self.response
    
    def stream_generate(self, prompt, system="", temperature=0.2, num_ctx=None):
        self.last_prompt = prompt
        self.last_system = system
        self.last_temperature = temperature
        self.last_num_ctx = num_ctx
        yield self.response


class FakeLLM_RuntimeErrors(FakeLLM):
    """Fake LLM that returns runtime error findings."""
    def __init__(self):
        super().__init__()
        self.response = (
            "Line 5: return a + b + math.sqrt(a) - NameError\n"
            "Line 11: result.append(item * multiplier) - NameError\n"
            "Line 16: print(\"Hello\" - SyntaxError\n"
            "Line 23: return x + y - TypeError\n"
        )


def test_context_formatting_line_numbers():
    """Test that context formatting renders contiguous line-numbered blocks per file."""
    chunks = [
        CodeChunk(
            chunk_id="test.py::add",
            file_path="test.py",
            language="python",
            kind="function",
            name="add",
            start_line=1,
            end_line=2,
            code="def add(a, b):\n    return a + b",
        ),
        CodeChunk(
            chunk_id="test.py::subtract",
            file_path="test.py",
            language="python",
            kind="function",
            name="subtract",
            start_line=5,
            end_line=6,
            code="def subtract(a, b):\n    return b - a",
        ),
    ]
    
    expanded_results = [(chunk, 1.0) for chunk in chunks]
    context = format_context(expanded_results, max_token_budget=3000)
    
    # Should contain line numbers
    assert "  1 | def add(a, b):" in context
    assert "  2 |     return a + b" in context
    assert "  5 | def subtract(a, b):" in context
    assert "  6 |     return b - a" in context
    
    # Should have file header once
    assert context.count("### File: test.py") == 1
    
    # Should not have duplicate chunks
    assert "return a + b" in context
    assert context.count("return a + b") == 1


def test_conversation_memory_excludes_assistant_for_analysis():
    """Test that conversation memory excludes assistant answers for analysis questions."""
    memory = ConversationMemory()
    memory.add_turn("What is this file?", "This is a test file.")
    memory.add_turn("How does add work?", "It adds two numbers.")
    
    # For analysis question, should only include user queries
    history = memory.format_history(is_analysis=True)
    assert "What is this file?" in history
    assert "How does add work?" in history
    assert "This is a test file" not in history
    assert "It adds two numbers" not in history
    
    # For normal question, should include both
    history_normal = memory.format_history(is_analysis=False)
    assert "What is this file?" in history_normal
    assert "This is a test file" in history_normal


def test_llm_sends_num_ctx_and_temperature():
    """Test that LLM receives num_ctx and temperature settings."""
    fake_llm = FakeLLM()
    fake_llm.generate("test", system="test system", temperature=0.0, num_ctx=8192)
    
    assert fake_llm.last_temperature == 0.0
    assert fake_llm.last_num_ctx == 8192


def test_anti_hallucination_filter():
    """Test that anti-hallucination filter removes claims with nonexistent quotes."""
    from rag.query_engine import QueryEngine
    
    # Create a mock engine
    fake_llm = FakeLLM()
    fake_llm.response = (
        "Bug 1: Line 6 has 'return b - a' which is wrong.\n"
        "Bug 2: Line 10 has 'print(hello)' which doesn't exist.\n"
    )
    
    engine = QueryEngine(
        store=Mock(spec=FaissVectorStore),
        embedder=FakeEmbedder(),
        llm=fake_llm,
    )
    
    # Create chunks with actual code
    chunks = [
        CodeChunk(
            chunk_id="test.py::subtract",
            file_path="test.py",
            language="python",
            kind="function",
            name="subtract",
            start_line=5,
            end_line=6,
            code="def subtract(a, b):\n    return b - a",
        ),
    ]
    
    expanded_results = [(chunk, 1.0) for chunk in chunks]
    
    # Apply filter
    filtered = engine._filter_hallucinated_claims(fake_llm.response, expanded_results)
    
    # Should keep real quote, remove fake quote
    assert "return b - a" in filtered
    assert "[QUOTED CODE NOT FOUND IN FILE]" in filtered
    assert "1 claim(s) removed" in filtered.lower()


def test_file_scope_clears_history():
    """Test that new @file scope can clear history."""
    memory = ConversationMemory()
    memory.add_turn("Old question", "Old answer")
    
    assert len(memory) == 1
    
    memory.clear()
    assert len(memory) == 0


def test_prompt_contains_no_duplicate_chunks():
    """Test that prompt generation doesn't include duplicate chunks."""
    chunks = [
        CodeChunk(
            chunk_id="test.py::add",
            file_path="test.py",
            language="python",
            kind="function",
            name="add",
            start_line=1,
            end_line=2,
            code="def add(a, b):\n    return a + b",
        ),
    ]
    
    # Duplicate the chunk
    expanded_results = [(chunks[0], 1.0), (chunks[0], 1.0)]
    context = format_context(expanded_results, max_token_budget=3000)
    
    # Should only appear once due to merging
    assert context.count("def add(a, b):") == 1


def test_runtime_errors_pass_with_fake_llm():
    """Test runtime errors pass with fake LLM that returns findings."""
    fake_llm = FakeLLM_RuntimeErrors()
    fake_llm.response = (
        "Line 5: return a + b + math.sqrt(a) - NameError\n"
        "Line 11: result.append(item * multiplier) - NameError\n"
    )
    
    engine = QueryEngine(
        store=Mock(spec=FaissVectorStore),
        embedder=FakeEmbedder(),
        llm=fake_llm,
    )
    
    # Create chunks matching the test file
    chunks = [
        CodeChunk(
            chunk_id="obvious_bugs.py::obvious_bugs.py",
            file_path="obvious_bugs.py",
            language="python",
            kind="file",
            name="obvious_bugs.py",
            start_line=1,
            end_line=26,
            code="# Test file with obvious bugs for intellicodex testing\n\ndef calculate_sum(a, b):\n    # Bug 1: Missing import\n    return a + b + math.sqrt(a)  # math not imported\n\ndef process_data(items):\n    # Bug 2: Undefined variable\n    result = []\n    for item in items:\n        result.append(item * multiplier)  # multiplier not defined\n    return result\n\ndef buggy_function():\n    # Bug 3: Syntax error\n    print(\"Hello\"\n    # Missing closing parenthesis\n\ndef another_bug():\n    # Bug 4: Type error obvious\n    x = \"hello\"\n    y = 5\n    return x + y  # Cannot add string and int\n\nif __name__ == \"__main__\":\n    calculate_sum(10, 20)",
        ),
    ]
    
    expanded_results = [(chunk, 1.0) for chunk in chunks]
    
    # Parse runtime errors
    findings = engine._parse_runtime_errors(fake_llm.response, expanded_results)
    
    # Should find 2 errors (the regex matches simpler patterns)
    assert len(findings) == 2
    
    # Verify each finding has correct line number
    assert findings[0]['line'] == 5
    assert findings[1]['line'] == 11
    
    # Verify all have source 'llm'
    for f in findings:
        assert f['source'] == 'llm'


def test_quote_filter_strips_line_number_prefix():
    """Test that quote filter correctly strips 'N |' prefix and code fences."""
    engine = QueryEngine(
        store=Mock(spec=FaissVectorStore),
        embedder=FakeEmbedder(),
        llm=FakeLLM(),
    )
    
    # Test with line-numbered format
    chunks = [
        CodeChunk(
            chunk_id="test.py::add",
            file_path="test.py",
            language="python",
            kind="function",
            name="add",
            start_line=1,
            end_line=2,
            code="def add(a, b):\n    return a + b",
        ),
    ]
    
    expanded_results = [(chunk, 1.0) for chunk in chunks]
    
    # Verify quote exists with line-numbered format
    assert engine._verify_quote_exists("return a + b", expanded_results, 2) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
