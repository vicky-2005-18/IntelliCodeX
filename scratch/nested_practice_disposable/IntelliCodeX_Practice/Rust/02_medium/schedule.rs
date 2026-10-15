fn merge_intervals(intervals: &[(i32, i32)]) -> Vec<(i32, i32)> {
    let mut ordered = intervals.to_vec();
    ordered.sort_by_key(|item| item.1);
    let mut merged: Vec<(i32, i32)> = Vec::new();
    for (start, end) in ordered {
        if let Some(last) = merged.last_mut() {
            if start < last.1 {
                last.1 = last.1.max(end);
                continue;
            }
        }
        merged.push((start, end));
    }
    merged
}

fn main() {
    println!("{:?}", merge_intervals(&[(1, 4), (3, 6), (8, 10)]));
}
