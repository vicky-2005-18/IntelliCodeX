import pytest
from services.checkout_service import process_checkout
from inventory.pricing import calculate_discounted_total

def test_pricing_discount_calculation():
    # 100 with 10% discount -> 90.0
    assert calculate_discounted_total([50, 50], 0.10) == 90.0

def test_pricing_zero_discount():
    assert calculate_discounted_total([25, 75], 0.0) == 100.0

def test_checkout_service_integration():
    items = [{'price': 100, 'qty': 1}]
    # 100 with 20% discount = 80; tax @ 5% = 4.00 -> total 84.00
    assert process_checkout(items, discount_rate=0.20, tax_rate=0.05) == 84.00
