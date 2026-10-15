from copy import deepcopy
from schedule import merge_intervals


def test_overlapping_intervals():
    assert merge_intervals([[1, 4], [3, 6], [8, 10]]) == [
        [1, 6], [8, 10]
    ]


def test_nested_intervals():
    assert merge_intervals([[1, 10], [2, 3], [4, 5]]) == [
        [1, 10]
    ]


def test_shared_endpoint():
    assert merge_intervals([[1, 3], [3, 5]]) == [[1, 5]]


def test_empty_input():
    assert merge_intervals([]) == []


def test_input_unchanged():
    intervals = [[8, 10], [1, 4], [3, 6]]
    original = deepcopy(intervals)
    merge_intervals(intervals)
    assert intervals == original