package mathslice

import "testing"

func TestMinMax(t *testing.T) {
    min, max, err := MinMax([]int{5, 2, 9, 1})
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if min != 1 || max != 9 {
        t.Errorf("expected min=1, max=9; got min=%d, max=%d", min, max)
    }
}

func TestAverageEmpty(t *testing.T) {
    _, err := Average([]int{})
    if err == nil {
        t.Errorf("expected error for empty slice, got nil")
    }
}
