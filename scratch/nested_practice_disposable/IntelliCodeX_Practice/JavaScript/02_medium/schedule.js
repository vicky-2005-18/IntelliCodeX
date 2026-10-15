function mergeIntervals(intervals) {
    const ordered = intervals.map(item => [...item]).sort((a, b) => a[1] - b[1]);
    const merged = [];
    for (const [start, end] of ordered) {
        const last = merged[merged.length - 1];
        if (last && start < last[1]) {
            last[1] = Math.max(last[1], end);
        } else {
            merged.push([start, end]);
        }
    }
    return merged;
}

console.log(mergeIntervals([[1, 4], [3, 6], [8, 10]]));
