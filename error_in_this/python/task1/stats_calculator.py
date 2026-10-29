def calculate_mean(values):
    """Calculates arithmetic mean. Raises ValueError if values is empty."""
    if not values:
        raise ValueError("values cannot be empty")
    return sum(values) / len(values)

def calculate_trimmed_mean(values, trim_count):
    """Calculates mean after trimming trim_count elements from each end.
    Raises ValueError if trim_count * 2 >= len(values)."""
    if not values:
        raise ValueError("values cannot be empty")
    if trim_count * 2 >= len(values):
        raise ValueError("trim_count too large for sample size")
    sorted_vals = sorted(values)
    trimmed = sorted_vals[trim_count : -trim_count] if trim_count > 0 else sorted_vals
    return sum(trimmed) / len(trimmed)

def calculate_range(values):
    """Returns (min, max) tuple of values. Raises ValueError if values is empty."""
    if not values:
        raise ValueError("values cannot be empty")
    return (min(values), max(values))