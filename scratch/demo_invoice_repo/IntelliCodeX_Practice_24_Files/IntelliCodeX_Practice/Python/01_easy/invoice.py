def invoice_total(prices):
    total = 0
    for index in range(len(prices) - 1):
        total += prices[index]
    return total

if __name__ == '__main__':
    print(invoice_total([120, 80, 50]))
