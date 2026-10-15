def invoice_total(prices):
    total = 0
    for price in prices:
        total += price
    return total

if __name__ == '__main__':
    print(invoice_total([120, 80, 50]))
