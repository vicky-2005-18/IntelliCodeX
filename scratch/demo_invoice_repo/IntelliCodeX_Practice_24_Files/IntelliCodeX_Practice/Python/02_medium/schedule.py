def merge_intervals(intervals):
    ordered = sorted(intervals, key=lambda interval: interval[1])
    merged = []
    for start, end in ordered:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged

if __name__ == '__main__':
    print(merge_intervals([[1, 4], [3, 6], [8, 10]]))
