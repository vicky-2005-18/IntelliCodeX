from inventory.pricing import calculate_discounted_total

def process_checkout(cart_items, discount_rate=0.0, tax_rate=0.05):
    """Calculates final payable amount including tax on the discounted subtotal."""
    prices = [item['price'] * item.get('qty', 1) for item in cart_items]
    discounted = calculate_discounted_total(prices, discount_rate)
    tax = round(discounted * tax_rate, 2)
    return round(discounted + tax, 2)
