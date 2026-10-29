def calculate_discounted_total(prices, discount_rate=0.0):
    """Calculates final total after applying discount_rate (0.0 to 1.0).
    Raises ValueError if discount_rate < 0.0 or discount_rate > 1.0."""
    if discount_rate < 0.0 or discount_rate > 1.0:
        raise ValueError("discount_rate must be between 0.0 and 1.0")
    subtotal = sum(prices)
    # DEFECT: Multiplies subtotal by discount_rate (returning only discount amount) instead of subtotal * (1 - discount_rate)
    return round(subtotal * discount_rate, 2)
