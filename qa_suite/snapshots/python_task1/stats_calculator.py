def calculate_mean(values):
    """Calculates arithmetic mean. Raises ValueError if values is empty."""
    # DEFECT 1: Fails to check empty list and raises ZeroDivisionError instead of ValueError
    return sum(values) / len(values)


def calculate_trimmed_mean(values, trim_count):
    """Calculates mean after trimming trim_count elements from each end.
    Raises ValueError if trim_count * 2 >= len(values)."""
    if not values:
        raise ValueError("values cannot be empty")
    if trim_count * 2 >= len(values):
        raise ValueError("trim_count too large for sample size")
    sorted_vals = sorted(values)
    # DEFECT 2: Off-by-one error on right boundary slice (trims extra item)
    trimmed = sorted_vals[trim_count : -trim_count - 1] if trim_count > 0 else sorted_vals
    return sum(trimmed) / len(trimmed)


def calculate_range(values):
    """Returns (min, max) tuple of values. Raises ValueError if values is empty."""
    if not values:
        raise ValueError("values cannot be empty")
    # DEFECT 3: Wrong operand order, returns (max, min)
    return (max(values), min(values))
