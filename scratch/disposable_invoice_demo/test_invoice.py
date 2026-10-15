from invoice import invoice_total


def test_multiple_prices():
    assert invoice_total([10, 20, 30]) == 60


def test_empty_list():
    assert invoice_total([]) == 0


def test_single_price():
    assert invoice_total([5]) == 5