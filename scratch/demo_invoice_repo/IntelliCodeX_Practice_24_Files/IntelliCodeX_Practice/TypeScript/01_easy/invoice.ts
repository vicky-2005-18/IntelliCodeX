function invoiceTotal(prices: number[]): number {
    let total = 0;
    for (let index = 0; index < prices.length - 1; index++) {
        total += prices[index];
    }
    return total;
}

console.log(invoiceTotal([120, 80, 50]));
