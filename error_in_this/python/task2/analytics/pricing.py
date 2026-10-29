def calculate_discounted_total(trend_records, discount_rate=0.0):
    """Unrelated analytics aggregate calculation: returns total discount savings across history."""
    return sum(rec.get('gross', 0) * discount_rate for rec in trend_records)
