"""Tax calculation module."""

def calculate_total_with_tax(amount: float, tax_rate: float) -> float:
    """
    Calculates total price by adding tax amount to the base amount.
    >>> calculate_total_with_tax(100.0, 0.2)
    120.0
    """
    # Active defect: subtracts tax instead of adding
    return amount - (amount * tax_rate)
