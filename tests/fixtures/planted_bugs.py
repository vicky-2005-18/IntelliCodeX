"""
Planted Bug Benchmark Fixtures for IntelliCodeX Evaluation (Phase 4).
Contains exactly:
- 8 functions with intentional known bugs (syntax, name error, off-by-one, type error, zero division, wrong operator, bad return, inverted boolean)
- 6 clean functions with correct implementations
"""

# ============================================================================
# BUGGY FUNCTIONS (8)
# ============================================================================

def bug1_syntax():
    """Bug 1: Syntax error (missing colon)."""
    # Note: Placed in string form below for eval script ast parsing to avoid syntax error on import
    pass

BUG1_SOURCE = """def calculate_total(prices):
    total = 0
    for p in prices
        total += p
    return total
"""

def bug2_undefined_variable(x: int) -> int:
    """Bug 2: Undefined variable reference."""
    multiplier = 10
    return x * unknown_factor  # Undefined variable 'unknown_factor'

def bug3_zero_division(total: float, count: int) -> float:
    """Bug 3: Zero division without guarding empty count."""
    return total / 0  # Explicit ZeroDivisionError

def bug4_off_by_one(items: list) -> any:
    """Bug 4: Index out of range off-by-one error."""
    return items[len(items)]  # IndexError on non-empty list

def bug5_inverted_boolean(user: dict) -> bool:
    """Bug 5: Inverted auth condition."""
    # Intent: allow active users only. Bug: returns True if inactive!
    return not user.get("is_active", False)

def bug6_operator_precedence(a: int, b: int, c: int) -> int:
    """Bug 6: Operator error - wrong operator used."""
    # Intent: add all three numbers. Bug: subtraction used for c
    return a + b - c

def bug7_type_mismatch(prefix: str, count: int) -> str:
    """Bug 7: Type error concatenating string and int directly."""
    return prefix + count  # TypeError: can only concatenate str to str

def bug8_missing_return(values: list) -> int:
    """Bug 8: Missing return statement producing None."""
    total = sum(values)
    # Bug: forgets return total


# ============================================================================
# CLEAN FUNCTIONS (6)
# ============================================================================

def clean1_sum(numbers: list[int]) -> int:
    """Clean 1: Correct sum."""
    return sum(numbers)

def clean2_is_even(n: int) -> bool:
    """Clean 2: Correct parity check."""
    return n % 2 == 0

def clean3_format_name(first: str, last: str) -> str:
    """Clean 3: Correct name formatting."""
    return f"{first.strip()} {last.strip()}"

def clean4_safe_divide(a: float, b: float) -> float:
    """Clean 4: Correct division with zero guard."""
    if b == 0:
        return 0.0
    return a / b

def clean5_filter_positive(values: list[int]) -> list[int]:
    """Clean 5: Correct list filtering."""
    return [v for v in values if v > 0]

def clean6_clamp(val: int, low: int, high: int) -> int:
    """Clean 6: Correct clamping logic."""
    return max(low, min(val, high))


PLANTED_BENCHMARK_SPEC = {
    "buggy": [
        {"id": "bug1", "name": "calculate_total", "type": "SyntaxError", "source": BUG1_SOURCE},
        {"id": "bug2", "name": "bug2_undefined_variable", "type": "UndefinedVariable"},
        {"id": "bug3", "name": "bug3_zero_division", "type": "ZeroDivision"},
        {"id": "bug4", "name": "bug4_off_by_one", "type": "IndexError"},
        {"id": "bug5", "name": "bug5_inverted_boolean", "type": "LogicInversion"},
        {"id": "bug6", "name": "bug6_operator_precedence", "type": "WrongOperator"},
        {"id": "bug7", "name": "bug7_type_mismatch", "type": "TypeError"},
        {"id": "bug8", "name": "bug8_missing_return", "type": "MissingReturn"},
    ],
    "clean": [
        {"id": "clean1", "name": "clean1_sum"},
        {"id": "clean2", "name": "clean2_is_even"},
        {"id": "clean3", "name": "clean3_format_name"},
        {"id": "clean4", "name": "clean4_safe_divide"},
        {"id": "clean5", "name": "clean5_filter_positive"},
        {"id": "clean6", "name": "clean6_clamp"},
    ],
}
