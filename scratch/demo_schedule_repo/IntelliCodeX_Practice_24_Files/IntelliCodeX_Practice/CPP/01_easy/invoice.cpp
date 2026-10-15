#include <iostream>
#include <vector>

long long invoiceTotal(const std::vector<int>& prices) {
    long long total = 0;
    for (std::size_t index = 0; index + 1 < prices.size(); index++) {
        total += prices[index];
    }
    return total;
}

int main() {
    std::cout << invoiceTotal({120, 80, 50}) << '\n';
}
