"""
Held-out Evaluation Benchmark for Self-Improving Bug Repair (REQ-FUT-10).

This benchmark consists of 20 realistic, reproducible bug cases across 5 distinct error categories:
- KeyError (4 cases)
- IndexError (4 cases)
- ZeroDivisionError (4 cases)
- TypeError (4 cases)
- AttributeError (4 cases)

None of these test cases or snippets exist in DEFAULT_GOLDEN_EXPERIENCES or the experience bank.
Each benchmark case contains:
1. `case_id`: Unique identifier.
2. `error_type`: Error category.
3. `error_report`: Realistic traceback or error message.
4. `target_file`: Simulated file path.
5. `original_code`: The flawed implementation.
6. `test_code`: Rigorous regression test verifying functional business logic,
   not just exception absence.
"""

from typing import List, Dict, Any

BENCHMARK_CASES: List[Dict[str, Any]] = [
    # ------------------ 1. KeyError Cases (4) ------------------
    {
        "case_id": "bench_keyerror_nested_prefs",
        "error_type": "KeyError",
        "error_report": "KeyError: 'display' while reading nested user theme",
        "target_file": "preferences.py",
        "original_code": (
            "def get_theme_preference(user_profile: dict) -> str:\n"
            "    return user_profile['display']['theme']\n"
        ),
        "test_code": (
            "import pytest\n"
            "from preferences import get_theme_preference\n\n"
            "def test_get_theme_present():\n"
            "    assert get_theme_preference({'display': {'theme': 'dark'}}) == 'dark'\n\n"
            "def test_get_theme_missing_display():\n"
            "    assert get_theme_preference({}) == 'light'\n"
            "    assert get_theme_preference({'display': {}}) == 'light'\n"
        ),
    },
    {
        "case_id": "bench_keyerror_query_param",
        "error_type": "KeyError",
        "error_report": "KeyError: 'page_size' in request query parameters",
        "target_file": "pagination.py",
        "original_code": (
            "def get_page_size(query_params: dict) -> int:\n"
            "    return int(query_params['page_size'])\n"
        ),
        "test_code": (
            "import pytest\n"
            "from pagination import get_page_size\n\n"
            "def test_page_size_present():\n"
            "    assert get_page_size({'page_size': '25'}) == 25\n\n"
            "def test_page_size_fallback():\n"
            "    assert get_page_size({}) == 10\n"
            "    assert get_page_size({'other': 'val'}) == 10\n"
        ),
    },
    {
        "case_id": "bench_keyerror_webhook_signature",
        "error_type": "KeyError",
        "error_report": "KeyError: 'x-hub-signature' in incoming webhook headers",
        "target_file": "security.py",
        "original_code": (
            "def extract_signature(headers: dict) -> str:\n"
            "    return headers['x-hub-signature']\n"
        ),
        "test_code": (
            "import pytest\n"
            "from security import extract_signature\n\n"
            "def test_extract_signature_present():\n"
            "    assert extract_signature({'x-hub-signature': 'sha256=abc'}) == 'sha256=abc'\n\n"
            "def test_extract_signature_missing():\n"
            "    assert extract_signature({}) == ''\n"
        ),
    },
    {
        "case_id": "bench_keyerror_cache_lookup",
        "error_type": "KeyError",
        "error_report": "KeyError: 'session_token' in cache store",
        "target_file": "cache.py",
        "original_code": (
            "def fetch_session_expiry(cache: dict, token: str) -> int:\n"
            "    return cache[token]['ttl']\n"
        ),
        "test_code": (
            "import pytest\n"
            "from cache import fetch_session_expiry\n\n"
            "def test_cache_hit():\n"
            "    assert fetch_session_expiry({'tok1': {'ttl': 3600}}, 'tok1') == 3600\n\n"
            "def test_cache_miss():\n"
            "    assert fetch_session_expiry({}, 'tok2') == 0\n"
        ),
    },

    # ------------------ 2. IndexError Cases (4) ------------------
    {
        "case_id": "bench_indexerror_first_token",
        "error_type": "IndexError",
        "error_report": "IndexError: list index out of range when parsing token stream",
        "target_file": "lexer.py",
        "original_code": (
            "def peek_first_token(tokens: list) -> str:\n"
            "    return tokens[0]\n"
        ),
        "test_code": (
            "import pytest\n"
            "from lexer import peek_first_token\n\n"
            "def test_peek_non_empty():\n"
            "    assert peek_first_token(['ident', 'semi']) == 'ident'\n\n"
            "def test_peek_empty():\n"
            "    assert peek_first_token([]) is None\n"
        ),
    },
    {
        "case_id": "bench_indexerror_coordinate_pair",
        "error_type": "IndexError",
        "error_report": "IndexError: tuple index out of range for 1D coordinate point",
        "target_file": "geometry.py",
        "original_code": (
            "def get_y_coordinate(point: tuple) -> float:\n"
            "    return float(point[1])\n"
        ),
        "test_code": (
            "import pytest\n"
            "from geometry import get_y_coordinate\n\n"
            "def test_2d_point():\n"
            "    assert get_y_coordinate((10.0, 20.0)) == 20.0\n\n"
            "def test_1d_point():\n"
            "    assert get_y_coordinate((15.0,)) == 0.0\n"
            "    assert get_y_coordinate(()) == 0.0\n"
        ),
    },
    {
        "case_id": "bench_indexerror_split_field",
        "error_type": "IndexError",
        "error_report": "IndexError: list index out of range on malformed CSV line",
        "target_file": "csv_parser.py",
        "original_code": (
            "def get_second_column(line: str) -> str:\n"
            "    parts = line.split(',')\n"
            "    return parts[1]\n"
        ),
        "test_code": (
            "import pytest\n"
            "from csv_parser import get_second_column\n\n"
            "def test_valid_csv():\n"
            "    assert get_second_column('alice,30,engineer') == '30'\n\n"
            "def test_malformed_csv():\n"
            "    assert get_second_column('single_value') == ''\n"
        ),
    },
    {
        "case_id": "bench_indexerror_last_history",
        "error_type": "IndexError",
        "error_report": "IndexError: pop from empty list in undo stack",
        "target_file": "history.py",
        "original_code": (
            "def pop_last_action(history_stack: list) -> str:\n"
            "    return history_stack.pop()\n"
        ),
        "test_code": (
            "import pytest\n"
            "from history import pop_last_action\n\n"
            "def test_pop_non_empty():\n"
            "    stack = ['open', 'edit']\n"
            "    assert pop_last_action(stack) == 'edit'\n"
            "    assert stack == ['open']\n\n"
            "def test_pop_empty():\n"
            "    stack = []\n"
            "    assert pop_last_action(stack) is None\n"
        ),
    },

    # ------------------ 3. ZeroDivisionError Cases (4) ------------------
    {
        "case_id": "bench_zerodiv_average_rating",
        "error_type": "ZeroDivisionError",
        "error_report": "ZeroDivisionError: division by zero in average calculation",
        "target_file": "metrics.py",
        "original_code": (
            "def compute_average_rating(ratings: list) -> float:\n"
            "    return sum(ratings) / len(ratings)\n"
        ),
        "test_code": (
            "import pytest\n"
            "from metrics import compute_average_rating\n\n"
            "def test_ratings_present():\n"
            "    assert compute_average_rating([4, 5, 3]) == 4.0\n\n"
            "def test_ratings_empty():\n"
            "    assert compute_average_rating([]) == 0.0\n"
        ),
    },
    {
        "case_id": "bench_zerodiv_progress_pct",
        "error_type": "ZeroDivisionError",
        "error_report": "ZeroDivisionError: division by zero when calculating percentage",
        "target_file": "progress.py",
        "original_code": (
            "def calculate_percentage(completed: int, total: int) -> float:\n"
            "    return (completed / total) * 100.0\n"
        ),
        "test_code": (
            "import pytest\n"
            "from progress import calculate_percentage\n\n"
            "def test_normal_percentage():\n"
            "    assert calculate_percentage(50, 100) == 50.0\n\n"
            "def test_zero_total():\n"
            "    assert calculate_percentage(0, 0) == 0.0\n"
        ),
    },
    {
        "case_id": "bench_zerodiv_aspect_ratio",
        "error_type": "ZeroDivisionError",
        "error_report": "ZeroDivisionError: division by zero in image aspect ratio",
        "target_file": "image_utils.py",
        "original_code": (
            "def get_aspect_ratio(width: int, height: int) -> float:\n"
            "    return width / height\n"
        ),
        "test_code": (
            "import pytest\n"
            "from image_utils import get_aspect_ratio\n\n"
            "def test_aspect_ratio():\n"
            "    assert get_aspect_ratio(1920, 1080) == pytest.approx(1.7777, rel=1e-3)\n\n"
            "def test_zero_height():\n"
            "    assert get_aspect_ratio(100, 0) == 0.0\n"
        ),
    },
    {
        "case_id": "bench_zerodiv_slope",
        "error_type": "ZeroDivisionError",
        "error_report": "ZeroDivisionError: division by zero for vertical line slope",
        "target_file": "charting.py",
        "original_code": (
            "def calculate_slope(x1: float, y1: float, x2: float, y2: float) -> float:\n"
            "    return (y2 - y1) / (x2 - x1)\n"
        ),
        "test_code": (
            "import pytest\n"
            "from charting import calculate_slope\n\n"
            "def test_regular_slope():\n"
            "    assert calculate_slope(0.0, 0.0, 2.0, 4.0) == 2.0\n\n"
            "def test_vertical_line():\n"
            "    assert calculate_slope(3.0, 1.0, 3.0, 5.0) == 0.0\n"
        ),
    },

    # ------------------ 4. TypeError Cases (4) ------------------
    {
        "case_id": "bench_typeerror_string_concat",
        "error_type": "TypeError",
        "error_report": "TypeError: can only concatenate str (not 'NoneType') to str",
        "target_file": "formatter.py",
        "original_code": (
            "def format_greeting(prefix: str, name: str) -> str:\n"
            "    return prefix + ', ' + name\n"
        ),
        "test_code": (
            "import pytest\n"
            "from formatter import format_greeting\n\n"
            "def test_greeting_valid():\n"
            "    assert format_greeting('Hello', 'Alice') == 'Hello, Alice'\n\n"
            "def test_greeting_none_name():\n"
            "    assert format_greeting('Hello', None) == 'Hello, Guest'\n"
        ),
    },
    {
        "case_id": "bench_typeerror_list_iteration",
        "error_type": "TypeError",
        "error_report": "TypeError: 'NoneType' object is not iterable",
        "target_file": "collector.py",
        "original_code": (
            "def count_valid_items(items: list) -> int:\n"
            "    count = 0\n"
            "    for item in items:\n"
            "        if item:\n"
            "            count += 1\n"
            "    return count\n"
        ),
        "test_code": (
            "import pytest\n"
            "from collector import count_valid_items\n\n"
            "def test_count_list():\n"
            "    assert count_valid_items([1, 0, 2, None]) == 2\n\n"
            "def test_count_none():\n"
            "    assert count_valid_items(None) == 0\n"
        ),
    },
    {
        "case_id": "bench_typeerror_length_check",
        "error_type": "TypeError",
        "error_report": "TypeError: object of type 'int' has no len()",
        "target_file": "validator.py",
        "original_code": (
            "def validate_payload_size(data) -> int:\n"
            "    return len(data)\n"
        ),
        "test_code": (
            "import pytest\n"
            "from validator import validate_payload_size\n\n"
            "def test_len_str():\n"
            "    assert validate_payload_size('hello') == 5\n\n"
            "def test_len_int_or_none():\n"
            "    assert validate_payload_size(12345) == 5\n"
            "    assert validate_payload_size(None) == 0\n"
        ),
    },
    {
        "case_id": "bench_typeerror_number_addition",
        "error_type": "TypeError",
        "error_report": "TypeError: unsupported operand type(s) for +: 'float' and 'str'",
        "target_file": "billing.py",
        "original_code": (
            "def add_tax(amount: float, tax) -> float:\n"
            "    return amount + tax\n"
        ),
        "test_code": (
            "import pytest\n"
            "from billing import add_tax\n\n"
            "def test_numeric_tax():\n"
            "    assert add_tax(100.0, 15.0) == 115.0\n\n"
            "def test_string_tax():\n"
            "    assert add_tax(100.0, '15.5') == 115.5\n"
            "    assert add_tax(100.0, None) == 100.0\n"
        ),
    },

    # ------------------ 5. AttributeError Cases (4) ------------------
    {
        "case_id": "bench_attrerror_strip_none",
        "error_type": "AttributeError",
        "error_report": "AttributeError: 'NoneType' object has no attribute 'strip'",
        "target_file": "sanitizer.py",
        "original_code": (
            "def clean_username(raw_username) -> str:\n"
            "    return raw_username.strip()\n"
        ),
        "test_code": (
            "import pytest\n"
            "from sanitizer import clean_username\n\n"
            "def test_clean_string():\n"
            "    assert clean_username('  bob ') == 'bob'\n\n"
            "def test_clean_none_or_int():\n"
            "    assert clean_username(None) == ''\n"
            "    assert clean_username(123) == '123'\n"
        ),
    },
    {
        "case_id": "bench_attrerror_object_name",
        "error_type": "AttributeError",
        "error_report": "AttributeError: 'NoneType' object has no attribute 'name'",
        "target_file": "user_service.py",
        "original_code": (
            "def get_account_name(account) -> str:\n"
            "    return account.name\n"
        ),
        "test_code": (
            "import pytest\n"
            "from types import SimpleNamespace\n"
            "from user_service import get_account_name\n\n"
            "def test_valid_account():\n"
            "    acc = SimpleNamespace(name='Admin')\n"
            "    assert get_account_name(acc) == 'Admin'\n\n"
            "def test_none_account():\n"
            "    assert get_account_name(None) == 'Anonymous'\n"
        ),
    },
    {
        "case_id": "bench_attrerror_lowercase",
        "error_type": "AttributeError",
        "error_report": "AttributeError: 'list' object has no attribute 'lower'",
        "target_file": "normalizer.py",
        "original_code": (
            "def normalize_tag(tag) -> str:\n"
            "    return tag.lower()\n"
        ),
        "test_code": (
            "import pytest\n"
            "from normalizer import normalize_tag\n\n"
            "def test_str_tag():\n"
            "    assert normalize_tag('PYTHON') == 'python'\n\n"
            "def test_non_str_tag():\n"
            "    assert normalize_tag(['python', 'ai']) == 'python, ai'\n"
            "    assert normalize_tag(None) == ''\n"
        ),
    },
    {
        "case_id": "bench_attrerror_status_code",
        "error_type": "AttributeError",
        "error_report": "AttributeError: 'dict' object has no attribute 'status_code'",
        "target_file": "http_client.py",
        "original_code": (
            "def is_successful_response(response) -> bool:\n"
            "    return response.status_code == 200\n"
        ),
        "test_code": (
            "import pytest\n"
            "from types import SimpleNamespace\n"
            "from http_client import is_successful_response\n\n"
            "def test_response_obj():\n"
            "    res = SimpleNamespace(status_code=200)\n"
            "    assert is_successful_response(res) is True\n\n"
            "def test_response_dict():\n"
            "    assert is_successful_response({'status_code': 200}) is True\n"
            "    assert is_successful_response({'status': 'ok'}) is False\n"
            "    assert is_successful_response(None) is False\n"
        ),
    },
]
