package mathslice

import "errors"

func MinMax(nums []int) (int, int, error) {
    if len(nums) == 0 {
        return 0, 0, errors.New("empty slice")
    }
    minVal, maxVal := nums[0], nums[0]
    for _, n := range nums[1:] {
        if n < minVal {
            minVal = n
        }
        if n > maxVal {
            maxVal = n
        }
    }
    // DEFECT 1: Inverted return values (returns maxVal, minVal instead of minVal, maxVal)
    return maxVal, minVal, nil
}

func Average(nums []int) (float64, error) {
    // DEFECT 2: Missing empty check, panics or returns NaN on empty slice
    sum := 0
    for _, n := range nums {
        sum += n
    }
    if len(nums) == 0 {
        return float64(sum) / float64(len(nums)), nil
    }
    return float64(sum) / float64(len(nums)), nil
}
