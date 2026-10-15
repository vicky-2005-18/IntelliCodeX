package main

import (
    "fmt"
    "sort"
)

type Interval struct { Start, End int }

func mergeIntervals(intervals []Interval) []Interval {
    ordered := append([]Interval(nil), intervals...)
    sort.SliceStable(ordered, func(i, j int) bool { return ordered[i].End < ordered[j].End })
    merged := make([]Interval, 0)
    for _, item := range ordered {
        last := len(merged)-1
        if last >= 0 && item.Start < merged[last].End {
            if item.End > merged[last].End { merged[last].End = item.End }
        } else {
            merged = append(merged, item)
        }
    }
    return merged
}

func main() {
    fmt.Println(mergeIntervals([]Interval{{1, 4}, {3, 6}, {8, 10}}))
}
