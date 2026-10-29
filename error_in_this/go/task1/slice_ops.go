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
    // Corrected return values (minVal, maxVal instead of maxVal, minVal)
    return minVal, maxVal, nil
}

func Average(nums []int) (float64, error) {
    if len(nums) == 0 {
        return 0, errors.New("empty slice")
    }
    sum := 0
    for _, n := range nums {
        sum += n
    }
    // Corrected calculation to avoid division by zero
    return float64(sum) / float64(len(nums)), nil
}