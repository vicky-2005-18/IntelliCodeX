def merge_intervals(intervals):
    if not intervals:
        return []
    
    # Sort intervals by their start time
    ordered = sorted(intervals, key=lambda interval: interval[0])
    
    merged = [ordered[0]]
    
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        
        if start <= last_end:
            # Merge the current interval with the last merged interval
            merged[-1][1] = max(last_end, end)
        else:
            # Add the current interval as a new merged interval
            merged.append([start, end])
    
    return merged

if __name__ == '__main__':
    print(merge_intervals([[1, 4], [3, 6], [8, 10]]))
