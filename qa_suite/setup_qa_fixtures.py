import os
import shutil
import json
import hashlib

def hash_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def create_fixtures():
    base = os.path.abspath("error_in_this")
    qa_base = os.path.abspath("qa_suite")
    manifest = {}

    # =========================================================================
    # 1. PYTHON TASK 1: stats_calculator
    # =========================================================================
    py_t1_dir = os.path.join(base, "python", "task1")
    os.makedirs(py_t1_dir, exist_ok=True)
    
    stats_code = (
        "def calculate_mean(values):\n"
        "    \"\"\"Calculates arithmetic mean. Raises ValueError if values is empty.\"\"\"\n"
        "    # DEFECT 1: Fails to check empty list and raises ZeroDivisionError instead of ValueError\n"
        "    return sum(values) / len(values)\n"
        "\n"
        "\n"
        "def calculate_trimmed_mean(values, trim_count):\n"
        "    \"\"\"Calculates mean after trimming trim_count elements from each end.\n"
        "    Raises ValueError if trim_count * 2 >= len(values).\"\"\"\n"
        "    if not values:\n"
        "        raise ValueError(\"values cannot be empty\")\n"
        "    if trim_count * 2 >= len(values):\n"
        "        raise ValueError(\"trim_count too large for sample size\")\n"
        "    sorted_vals = sorted(values)\n"
        "    # DEFECT 2: Off-by-one error on right boundary slice (trims extra item)\n"
        "    trimmed = sorted_vals[trim_count : -trim_count - 1] if trim_count > 0 else sorted_vals\n"
        "    return sum(trimmed) / len(trimmed)\n"
        "\n"
        "\n"
        "def calculate_range(values):\n"
        "    \"\"\"Returns (min, max) tuple of values. Raises ValueError if values is empty.\"\"\"\n"
        "    if not values:\n"
        "        raise ValueError(\"values cannot be empty\")\n"
        "    # DEFECT 3: Wrong operand order, returns (max, min)\n"
        "    return (max(values), min(values))\n"
    )
    with open(os.path.join(py_t1_dir, "stats_calculator.py"), "w", encoding="utf-8") as f:
        f.write(stats_code)

    py_t1_test = (
        "import pytest\n"
        "from stats_calculator import calculate_mean, calculate_trimmed_mean, calculate_range\n"
        "\n"
        "def test_calculate_mean_happy_path():\n"
        "    assert calculate_mean([1, 2, 3, 4, 5]) == 3.0\n"
        "\n"
        "def test_calculate_mean_empty_raises_value_error():\n"
        "    with pytest.raises(ValueError):\n"
        "        calculate_mean([])\n"
        "\n"
        "def test_calculate_trimmed_mean_happy_path():\n"
        "    # [100, 2, 3, 4, 500] trimmed by 1 -> [2, 3, 4] -> mean 3.0\n"
        "    assert calculate_trimmed_mean([100, 2, 3, 4, 500], 1) == 3.0\n"
        "\n"
        "def test_calculate_range_order():\n"
        "    assert calculate_range([10, 2, 8]) == (2, 10)\n"
    )
    with open(os.path.join(py_t1_dir, "test_stats_calculator.py"), "w", encoding="utf-8") as f:
        f.write(py_t1_test)

    manifest["python_task1"] = {
        "path": "error_in_this/python/task1",
        "target_file": "stats_calculator.py",
        "runtime": "python",
        "test_command": "pytest test_stats_calculator.py",
        "defects": [
            "calculate_mean: raises ZeroDivisionError on empty list instead of ValueError",
            "calculate_trimmed_mean: off-by-one right slice trims extra element",
            "calculate_range: inverted return tuple order (max, min) instead of (min, max)"
        ]
    }

    # =========================================================================
    # 2. PYTHON TASK 2: 100+ files multi-module inventory service
    # =========================================================================
    py_t2_dir = os.path.join(base, "python", "task2")
    os.makedirs(os.path.join(py_t2_dir, "inventory"), exist_ok=True)
    os.makedirs(os.path.join(py_t2_dir, "services"), exist_ok=True)
    os.makedirs(os.path.join(py_t2_dir, "analytics"), exist_ok=True)
    os.makedirs(os.path.join(py_t2_dir, "models"), exist_ok=True)
    os.makedirs(os.path.join(py_t2_dir, "tests"), exist_ok=True)

    with open(os.path.join(py_t2_dir, "inventory", "__init__.py"), "w") as f: pass
    with open(os.path.join(py_t2_dir, "services", "__init__.py"), "w") as f: pass
    with open(os.path.join(py_t2_dir, "analytics", "__init__.py"), "w") as f: pass
    with open(os.path.join(py_t2_dir, "models", "__init__.py"), "w") as f: pass

    pricing_code = (
        "def calculate_discounted_total(prices, discount_rate=0.0):\n"
        "    \"\"\"Calculates final total after applying discount_rate (0.0 to 1.0).\n"
        "    Raises ValueError if discount_rate < 0.0 or discount_rate > 1.0.\"\"\"\n"
        "    if discount_rate < 0.0 or discount_rate > 1.0:\n"
        "        raise ValueError(\"discount_rate must be between 0.0 and 1.0\")\n"
        "    subtotal = sum(prices)\n"
        "    # DEFECT: Multiplies subtotal by discount_rate (returning only discount amount) instead of subtotal * (1 - discount_rate)\n"
        "    return round(subtotal * discount_rate, 2)\n"
    )
    with open(os.path.join(py_t2_dir, "inventory", "pricing.py"), "w", encoding="utf-8") as f:
        f.write(pricing_code)

    checkout_code = (
        "from inventory.pricing import calculate_discounted_total\n"
        "\n"
        "def process_checkout(cart_items, discount_rate=0.0, tax_rate=0.05):\n"
        "    \"\"\"Calculates final payable amount including tax on the discounted subtotal.\"\"\"\n"
        "    prices = [item['price'] * item.get('qty', 1) for item in cart_items]\n"
        "    discounted = calculate_discounted_total(prices, discount_rate)\n"
        "    tax = round(discounted * tax_rate, 2)\n"
        "    return round(discounted + tax, 2)\n"
    )
    with open(os.path.join(py_t2_dir, "services", "checkout_service.py"), "w", encoding="utf-8") as f:
        f.write(checkout_code)

    analytics_pricing = (
        "def calculate_discounted_total(trend_records, discount_rate=0.0):\n"
        "    \"\"\"Unrelated analytics aggregate calculation: returns total discount savings across history.\"\"\"\n"
        "    return sum(rec.get('gross', 0) * discount_rate for rec in trend_records)\n"
    )
    with open(os.path.join(py_t2_dir, "analytics", "pricing.py"), "w", encoding="utf-8") as f:
        f.write(analytics_pricing)

    for i in range(1, 103):
        m_code = (
            f"class ItemModel{i:03d}:\n"
            f"    def __init__(self, item_id: int, name: str, cost: float):\n"
            f"        self.item_id = item_id\n"
            f"        self.name = name\n"
            f"        self.cost = cost\n"
            f"    def get_sku(self) -> str:\n"
            f"        return f'SKU-{i:03d}-{{self.item_id}}'\n"
            f"    def compute_margin(self, sell_price: float) -> float:\n"
            f"        return round(sell_price - self.cost, 2)\n"
        )
        with open(os.path.join(py_t2_dir, "models", f"item_{i:03d}.py"), "w", encoding="utf-8") as f:
            f.write(m_code)

    py_t2_test = (
        "import pytest\n"
        "from services.checkout_service import process_checkout\n"
        "from inventory.pricing import calculate_discounted_total\n"
        "\n"
        "def test_pricing_discount_calculation():\n"
        "    # 100 with 10% discount -> 90.0\n"
        "    assert calculate_discounted_total([50, 50], 0.10) == 90.0\n"
        "\n"
        "def test_pricing_zero_discount():\n"
        "    assert calculate_discounted_total([25, 75], 0.0) == 100.0\n"
        "\n"
        "def test_checkout_service_integration():\n"
        "    items = [{'price': 100, 'qty': 1}]\n"
        "    # 100 with 20% discount = 80; tax @ 5% = 4.00 -> total 84.00\n"
        "    assert process_checkout(items, discount_rate=0.20, tax_rate=0.05) == 84.00\n"
    )
    with open(os.path.join(py_t2_dir, "tests", "test_checkout_service.py"), "w", encoding="utf-8") as f:
        f.write(py_t2_test)

    manifest["python_task2"] = {
        "path": "error_in_this/python/task2",
        "target_file": "inventory/pricing.py",
        "runtime": "python",
        "test_command": "pytest tests/test_checkout_service.py",
        "total_files": 108,
        "defects": [
            "calculate_discounted_total returns discount amount instead of discounted total (subtotal * (1 - discount_rate))",
            "Cross-file caller checkout_service produces wrong invoice amounts"
        ]
    }

    # =========================================================================
    # 3. JAVA TASK 1: TextTransformer
    # =========================================================================
    java_t1_dir = os.path.join(base, "java", "task1")
    os.makedirs(java_t1_dir, exist_ok=True)

    java_t1_code = (
        "package task1;\n"
        "\n"
        "import java.util.List;\n"
        "\n"
        "public class TextTransformer {\n"
        "    public static String truncate(String text, int maxLength, String suffix) {\n"
        "        if (text == null) return \"\";\n"
        "        if (suffix == null) suffix = \"\";\n"
        "        if (text.length() <= maxLength) return text;\n"
        "        // DEFECT 1: Off-by-one error (maxLength + 1 includes an extra character)\n"
        "        return text.substring(0, maxLength + 1) + suffix;\n"
        "    }\n"
        "\n"
        "    public static String joinTokens(List<String> tokens, String delimiter) {\n"
        "        // DEFECT 2: Throws NullPointerException when tokens is null instead of returning empty string\n"
        "        if (tokens.isEmpty()) return \"\";\n"
        "        return String.join(delimiter == null ? \"\" : delimiter, tokens);\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(java_t1_dir, "TextTransformer.java"), "w", encoding="utf-8") as f:
        f.write(java_t1_code)

    java_t1_test = (
        "package task1;\n"
        "\n"
        "import org.junit.jupiter.api.Test;\n"
        "import java.util.List;\n"
        "import static org.junit.jupiter.api.Assertions.*;\n"
        "\n"
        "public class TextTransformerTest {\n"
        "    @Test\n"
        "    void testTruncateWithinLength() {\n"
        "        assertEquals(\"hello\", TextTransformer.truncate(\"hello\", 10, \"...\"));\n"
        "    }\n"
        "\n"
        "    @Test\n"
        "    void testTruncateExceedingLength() {\n"
        "        // Exactly 5 chars + suffix\n"
        "        assertEquals(\"Hello...\", TextTransformer.truncate(\"Hello World\", 5, \"...\"));\n"
        "    }\n"
        "\n"
        "    @Test\n"
        "    void testJoinTokensNullSafe() {\n"
        "        assertEquals(\"\", TextTransformer.joinTokens(null, \",\"));\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(java_t1_dir, "TextTransformerTest.java"), "w", encoding="utf-8") as f:
        f.write(java_t1_test)

    manifest["java_task1"] = {
        "path": "error_in_this/java/task1",
        "target_file": "TextTransformer.java",
        "runtime": "java",
        "test_command": "java -jar /usr/share/java/junit-platform-console-standalone.jar -cp . --select-class task1.TextTransformerTest",
        "defects": [
            "truncate: off-by-one substring endIndex maxLength + 1",
            "joinTokens: NullPointerException on null tokens list instead of safe empty string"
        ]
    }

    # =========================================================================
    # 4. JAVA TASK 2: Overloads and cross-class billing
    # =========================================================================
    java_t2_dir = os.path.join(base, "java", "task2")
    os.makedirs(os.path.join(java_t2_dir, "billing"), exist_ok=True)

    discount_calc_java = (
        "package billing;\n"
        "\n"
        "public class DiscountCalculator {\n"
        "    // Valid overload 1\n"
        "    public double calculateNet(double amount) {\n"
        "        return calculateNet(amount, 0.0);\n"
        "    }\n"
        "\n"
        "    // Valid overload 2 - must not be rejected as duplicate\n"
        "    public double calculateNet(double amount, double discountRate) {\n"
        "        if (discountRate < 0.0 || discountRate > 1.0) {\n"
        "            throw new IllegalArgumentException(\"Invalid discount rate\");\n"
        "        }\n"
        "        // DEFECT: Multiplies by discountRate directly instead of amount * (1.0 - discountRate)\n"
        "        return amount * discountRate;\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(java_t2_dir, "billing", "DiscountCalculator.java"), "w", encoding="utf-8") as f:
        f.write(discount_calc_java)

    order_mgr_java = (
        "package billing;\n"
        "\n"
        "public class OrderManager {\n"
        "    private final DiscountCalculator calculator = new DiscountCalculator();\n"
        "\n"
        "    public double finalizeOrder(double amount, double discountRate) {\n"
        "        return calculator.calculateNet(amount, discountRate);\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(java_t2_dir, "billing", "OrderManager.java"), "w", encoding="utf-8") as f:
        f.write(order_mgr_java)

    order_mgr_test = (
        "package billing;\n"
        "\n"
        "import org.junit.jupiter.api.Test;\n"
        "import static org.junit.jupiter.api.Assertions.*;\n"
        "\n"
        "public class OrderManagerTest {\n"
        "    @Test\n"
        "    void testDefaultOverload() {\n"
        "        DiscountCalculator calc = new DiscountCalculator();\n"
        "        assertEquals(100.0, calc.calculateNet(100.0), 0.001);\n"
        "    }\n"
        "\n"
        "    @Test\n"
        "    void testCustomDiscountOverload() {\n"
        "        OrderManager mgr = new OrderManager();\n"
        "        // 200 with 15% discount -> 170.0\n"
        "        assertEquals(170.0, mgr.finalizeOrder(200.0, 0.15), 0.001);\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(java_t2_dir, "billing", "OrderManagerTest.java"), "w", encoding="utf-8") as f:
        f.write(order_mgr_test)

    manifest["java_task2"] = {
        "path": "error_in_this/java/task2",
        "target_file": "billing/DiscountCalculator.java",
        "runtime": "java",
        "test_command": "java -jar /usr/share/java/junit-platform-console-standalone.jar -cp . --select-class billing.OrderManagerTest",
        "defects": [
            "calculateNet(double, double): returns discount amount instead of net price amount * (1.0 - discountRate)",
            "Contains valid Java overloads that must be preserved without duplicate signature errors"
        ]
    }

    # =========================================================================
    # 5. GO TASK 1: mathslice
    # =========================================================================
    go_t1_dir = os.path.join(base, "go", "task1")
    os.makedirs(go_t1_dir, exist_ok=True)

    with open(os.path.join(go_t1_dir, "go.mod"), "w") as f:
        f.write("module mathslice\n\ngo 1.20\n")

    go_t1_code = (
        "package mathslice\n"
        "\n"
        "import \"errors\"\n"
        "\n"
        "func MinMax(nums []int) (int, int, error) {\n"
        "    if len(nums) == 0 {\n"
        "        return 0, 0, errors.New(\"empty slice\")\n"
        "    }\n"
        "    minVal, maxVal := nums[0], nums[0]\n"
        "    for _, n := range nums[1:] {\n"
        "        if n < minVal {\n"
        "            minVal = n\n"
        "        }\n"
        "        if n > maxVal {\n"
        "            maxVal = n\n"
        "        }\n"
        "    }\n"
        "    // DEFECT 1: Inverted return values (returns maxVal, minVal instead of minVal, maxVal)\n"
        "    return maxVal, minVal, nil\n"
        "}\n"
        "\n"
        "func Average(nums []int) (float64, error) {\n"
        "    // DEFECT 2: Missing empty check, panics or returns NaN on empty slice\n"
        "    sum := 0\n"
        "    for _, n := range nums {\n"
        "        sum += n\n"
        "    }\n"
        "    if len(nums) == 0 {\n"
        "        return float64(sum) / float64(len(nums)), nil\n"
        "    }\n"
        "    return float64(sum) / float64(len(nums)), nil\n"
        "}\n"
    )
    with open(os.path.join(go_t1_dir, "slice_ops.go"), "w", encoding="utf-8") as f:
        f.write(go_t1_code)

    go_t1_test = (
        "package mathslice\n"
        "\n"
        "import \"testing\"\n"
        "\n"
        "func TestMinMax(t *testing.T) {\n"
        "    min, max, err := MinMax([]int{5, 2, 9, 1})\n"
        "    if err != nil {\n"
        "        t.Fatalf(\"unexpected error: %v\", err)\n"
        "    }\n"
        "    if min != 1 || max != 9 {\n"
        "        t.Errorf(\"expected min=1, max=9; got min=%d, max=%d\", min, max)\n"
        "    }\n"
        "}\n"
        "\n"
        "func TestAverageEmpty(t *testing.T) {\n"
        "    _, err := Average([]int{})\n"
        "    if err == nil {\n"
        "        t.Errorf(\"expected error for empty slice, got nil\")\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(go_t1_dir, "slice_ops_test.go"), "w", encoding="utf-8") as f:
        f.write(go_t1_test)

    manifest["go_task1"] = {
        "path": "error_in_this/go/task1",
        "target_file": "slice_ops.go",
        "runtime": "go",
        "test_command": "go test -v .",
        "defects": [
            "MinMax: inverted return values (max, min) instead of (min, max)",
            "Average: returns NaN or nil error on empty slice instead of returning error"
        ]
    }

    # =========================================================================
    # 6. GO TASK 2: Multi-package tags formatter
    # =========================================================================
    go_t2_dir = os.path.join(base, "go", "task2")
    os.makedirs(os.path.join(go_t2_dir, "pkg", "format"), exist_ok=True)
    os.makedirs(os.path.join(go_t2_dir, "pkg", "service"), exist_ok=True)

    with open(os.path.join(go_t2_dir, "go.mod"), "w") as f:
        f.write("module tagsvc\n\ngo 1.20\n")

    go_callee = (
        "package format\n"
        "\n"
        "import \"strings\"\n"
        "\n"
        "func JoinClean(tags []string, sep string) string {\n"
        "    var cleaned []string\n"
        "    for _, t := range tags {\n"
        "        s := strings.TrimSpace(t)\n"
        "        if s != \"\" {\n"
        "            cleaned = append(cleaned, s)\n"
        "        }\n"
        "    }\n"
        "    // DEFECT: Appends trailing separator\n"
        "    return strings.Join(cleaned, sep) + sep\n"
        "}\n"
    )
    with open(os.path.join(go_t2_dir, "pkg", "format", "formatter.go"), "w", encoding="utf-8") as f:
        f.write(go_callee)

    go_caller = (
        "package service\n"
        "\n"
        "import \"tagsvc/pkg/format\"\n"
        "\n"
        "func BuildTagHeader(tags []string) string {\n"
        "    return format.JoinClean(tags, \", \")\n"
        "}\n"
    )
    with open(os.path.join(go_t2_dir, "pkg", "service", "header.go"), "w", encoding="utf-8") as f:
        f.write(go_caller)

    go_caller_test = (
        "package service\n"
        "\n"
        "import \"testing\"\n"
        "\n"
        "func TestBuildTagHeader(t *testing.T) {\n"
        "    res := BuildTagHeader([]string{\" golang \", \"\", \"docker\", \"testing \"})\n"
        "    expected := \"golang, docker, testing\"\n"
        "    if res != expected {\n"
        "        t.Errorf(\"expected '%s', got '%s'\", expected, res)\n"
        "    }\n"
        "}\n"
    )
    with open(os.path.join(go_t2_dir, "pkg", "service", "header_test.go"), "w", encoding="utf-8") as f:
        f.write(go_caller_test)

    manifest["go_task2"] = {
        "path": "error_in_this/go/task2",
        "target_file": "pkg/format/formatter.go",
        "runtime": "go",
        "test_command": "go test -v ./pkg/service",
        "defects": [
            "JoinClean appends extraneous trailing separator to joined string",
            "Cross-package caller BuildTagHeader fails expectation"
        ]
    }

    # Save manifest
    with open(os.path.join(qa_base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Save frozen snapshots
    snapshots_dir = os.path.join(qa_base, "snapshots")
    for key, info in manifest.items():
        src_dir = os.path.abspath(info["path"])
        dst_dir = os.path.join(snapshots_dir, key)
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir)
        shutil.copytree(src_dir, dst_dir)
        
        # Record file hashes
        hashes = {}
        for root, _, files in os.walk(src_dir):
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, src_dir)
                hashes[rel] = hash_file(p)
        info["initial_hashes"] = hashes

    with open(os.path.join(qa_base, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("[OK] Fixtures created, manifest established, and snapshots frozen.")

if __name__ == "__main__":
    create_fixtures()