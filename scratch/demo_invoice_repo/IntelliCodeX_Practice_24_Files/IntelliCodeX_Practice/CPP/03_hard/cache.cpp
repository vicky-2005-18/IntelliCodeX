#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <unordered_map>
#include <vector>

class LRUCache {
    std::size_t capacity;
    std::unordered_map<int, int> values;
    std::vector<int> order;
public:
    explicit LRUCache(int limit) {
        if (limit < 1) throw std::invalid_argument("capacity must be positive");
        capacity = static_cast<std::size_t>(limit);
    }

    int get(int key) {
        auto item = values.find(key);
        return item == values.end() ? -1 : item->second;
    }

    void put(int key, int value) {
        if (values.count(key)) {
            order.erase(std::find(order.begin(), order.end(), key));
        } else if (values.size() == capacity) {
            values.erase(order.front());
            order.erase(order.begin());
        }
        values[key] = value;
        order.push_back(key);
    }
};

int main() {
    LRUCache cache(2);
    cache.put(1, 100);
    cache.put(2, 200);
    std::cout << cache.get(1) << '\n';
    cache.put(3, 300);
    std::cout << cache.get(2) << '\n';
    std::cout << cache.get(1) << '\n';
}
