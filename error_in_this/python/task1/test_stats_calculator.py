import pytest
from stats_calculator import calculate_mean, calculate_trimmed_mean, calculate_range

def test_calculate_mean_happy_path():
    assert calculate_mean([1, 2, 3, 4, 5]) == 3.0

def test_calculate_mean_empty_raises_value_error():
    with pytest.raises(ValueError):
        calculate_mean([])

def test_calculate_trimmed_mean_happy_path():
    # [-100, 2, 3, 4, 500] trimmed by 1 -> [2, 3, 4] -> mean 3.0
    assert calculate_trimmed_mean([-100, 2, 3, 4, 500], 1) == 3.0

def test_calculate_range_order():
    assert calculate_range([10, 2, 8]) == (2, 10)
