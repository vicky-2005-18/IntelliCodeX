import pytest
from calculator import add, subtract, multiply, divide


def test_happy_path_addition_and_multiplication():
    """Happy-path test that always passes."""
    assert add(10, 5) == 15
    assert multiply(3, 4) == 12
    assert divide(20, 4) == 5.0


def test_subtract_reproducing_bug():
    """Bug reproducing test: 10 - 4 must equal 6."""
    assert subtract(10, 4) == 6
