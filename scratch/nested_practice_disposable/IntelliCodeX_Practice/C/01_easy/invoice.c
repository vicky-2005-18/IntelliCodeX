#include <stdio.h>

long long invoice_total(const int prices[], int count) {
    long long total = 0;
    for (int index = 0; index < count - 1; index++) {
        total += prices[index];
    }
    return total;
}

int main(void) {
    const int prices[] = {120, 80, 50};
    printf("%lld\n", invoice_total(prices, 3));
    return 0;
}
