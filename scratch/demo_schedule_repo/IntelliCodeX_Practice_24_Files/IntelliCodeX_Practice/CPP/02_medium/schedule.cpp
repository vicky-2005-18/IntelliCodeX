#include <algorithm>
#include <iostream>
#include <utility>
#include <vector>

std::vector<std::pair<int, int>> mergeIntervals(std::vector<std::pair<int, int>> intervals) {
    std::sort(intervals.begin(), intervals.end(), [](auto a, auto b) { return a.second < b.second; });
    std::vector<std::pair<int, int>> merged;
    for (auto [start, end] : intervals) {
        if (!merged.empty() && start < merged.back().second) {
            merged.back().second = std::max(merged.back().second, end);
        } else {
            merged.emplace_back(start, end);
        }
    }
    return merged;
}

int main() {
    for (auto [start, end] : mergeIntervals({{1, 4}, {3, 6}, {8, 10}})) {
        std::cout << '[' << start << ", " << end << "]\n";
    }
}
