import os
import tempfile
import pytest
from core.canonical_path import discover_relevant_tests
from core.patch_generator import validate_candidate_interface, replace_ast_symbols_in_python
from core.sandbox_runner import SandboxRunner

def test_cross_file_integration_test_discovery():
    """Verifies that discover_relevant_tests discovers both unit tests and cross-file caller/integration tests importing the target."""
    with tempfile.TemporaryDirectory(prefix="icx_cross_file_") as tmp_dir:
        # 1. Target file: utils/math_ops.py
        utils_dir = os.path.join(tmp_dir, "utils")
        os.makedirs(utils_dir, exist_ok=True)
        target_path = os.path.join(utils_dir, "math_ops.py")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("def compute_discount(price, rate):\n    return price * (1 - rate)\n")

        # 2. Unit test file: tests/test_math_ops.py
        tests_dir = os.path.join(tmp_dir, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        unit_test_path = os.path.join(tests_dir, "test_math_ops.py")
        with open(unit_test_path, "w", encoding="utf-8") as f:
            f.write("from utils.math_ops import compute_discount\ndef test_discount():\n    assert compute_discount(100, 0.1) == 90\n")

        # 3. Caller file: services/order_service.py
        services_dir = os.path.join(tmp_dir, "services")
        os.makedirs(services_dir, exist_ok=True)
        caller_path = os.path.join(services_dir, "order_service.py")
        with open(caller_path, "w", encoding="utf-8") as f:
            f.write("from utils.math_ops import compute_discount\ndef process_order(total):\n    return compute_discount(total, 0.05)\n")

        # 4. Cross-file integration test: tests/test_order_integration.py
        integ_test_path = os.path.join(tests_dir, "test_order_integration.py")
        with open(integ_test_path, "w", encoding="utf-8") as f:
            f.write("from services.order_service import process_order\nfrom utils import math_ops\ndef test_integ():\n    assert process_order(200) == 190\n")

        # 5. Unrelated test: tests/test_auth.py
        auth_test_path = os.path.join(tests_dir, "test_auth.py")
        with open(auth_test_path, "w", encoding="utf-8") as f:
            f.write("def test_login():\n    assert True\n")

        # Run discovery on target utils/math_ops.py
        discovered = discover_relevant_tests(tmp_dir, "utils/math_ops.py")

        # Must include both unit test AND cross-file integration test that imports math_ops
        assert "tests/test_math_ops.py" in discovered
        assert "tests/test_order_integration.py" in discovered
        # Must exclude unrelated test
        assert "tests/test_auth.py" not in discovered


def test_java_toolchain_execution_in_docker():
    """Verifies that Java candidate patches with overloaded methods compile and execute using real javac/junit in Docker."""
    sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
    if not sb._check_docker_available():
        pytest.skip("Docker daemon not available for real toolchain test")

    with tempfile.TemporaryDirectory(prefix="icx_java_toolchain_") as tmp_dir:
        java_src = (
            "public class Calculator {\n"
            "    public int add(int a, int b) { return a + b; }\n"
            "    public double add(double a, double b) { return a + b; }\n"
            "}\n"
        )
        src_path = os.path.join(tmp_dir, "Calculator.java")
        with open(src_path, "w", encoding="utf-8") as f:
            f.write(java_src)

        test_src = (
            "import org.junit.jupiter.api.Test;\n"
            "import static org.junit.jupiter.api.Assertions.assertEquals;\n"
            "public class CalculatorTest {\n"
            "    @Test\n"
            "    public void testIntAdd() {\n"
            "        Calculator calc = new Calculator();\n"
            "        assertEquals(5, calc.add(2, 3));\n"
            "    }\n"
            "    @Test\n"
            "    public void testDoubleAdd() {\n"
            "        Calculator calc = new Calculator();\n"
            "        assertEquals(5.5, calc.add(2.3, 3.2), 0.001);\n"
            "    }\n"
            "}\n"
        )
        test_path = os.path.join(tmp_dir, "CalculatorTest.java")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write(test_src)

        res = sb.run_tests_with_patch(
            repo_path=tmp_dir,
            target_file="Calculator.java",
            patched_code=java_src,
            runtime="java",
            timeout=25,
        )
        assert res.success is True
        assert res.passed_count == 2
        assert res.failed_count == 0


def test_go_toolchain_execution_in_docker():
    """Verifies that Go candidate patches with receiver methods compile and execute using real go test in Docker."""
    sb = SandboxRunner(sandbox_mode="docker", is_admin=True)
    if not sb._check_docker_available():
        pytest.skip("Docker daemon not available for real toolchain test")

    with tempfile.TemporaryDirectory(prefix="icx_go_toolchain_") as tmp_dir:
        mod_src = "module example.com/calc\n\ngo 1.20\n"
        with open(os.path.join(tmp_dir, "go.mod"), "w", encoding="utf-8") as f:
            f.write(mod_src)

        go_src = (
            "package calc\n\n"
            "type Calc struct{}\n\n"
            "func (c *Calc) Add(a, b int) int {\n"
            "    return a + b\n"
            "}\n"
        )
        with open(os.path.join(tmp_dir, "calc.go"), "w", encoding="utf-8") as f:
            f.write(go_src)

        test_src = (
            "package calc\n\n"
            "import \"testing\"\n\n"
            "func TestCalcAdd(t *testing.T) {\n"
            "    c := &Calc{}\n"
            "    if got := c.Add(2, 3); got != 5 {\n"
            "        t.Fatalf(\"Expected 5, got %d\", got)\n"
            "    }\n"
            "}\n"
        )
        with open(os.path.join(tmp_dir, "calc_test.go"), "w", encoding="utf-8") as f:
            f.write(test_src)

        res = sb.run_tests_with_patch(
            repo_path=tmp_dir,
            target_file="calc.go",
            patched_code=go_src,
            runtime="go",
            timeout=60,
        )
        assert res.success is True
        assert res.passed_count >= 1
        assert res.failed_count == 0
