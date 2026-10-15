import os
import sys
sys.path.insert(0, ".")

from core.code_review import display_review_screen
from cli import render_patch_card

patch_rec = {
    "patch_id": "demo-patch-42",
    "target_file": "calculator.py",
    "confidence_score": 0.99,
    "status": "verified",
    "explanation": "Fixed arithmetic bug in subtract: changed 'return a + b' to 'return a - b'. All 2 pytest tests passed in Docker sandbox.",
    "git_diff": """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -5,8 +5,7 @@
 
 def subtract(a: float, b: float) -> float:
     \"\"\"Returns the difference of a and b.\"\"\"
-    # Intentional arithmetic bug: uses addition instead of subtraction
-    return a + b
+    return a - b
 
 
 def multiply(a: float, b: float) -> float:
""",
    "sandbox_validation": {
        "verified": True,
        "test_status": "passed",
        "iterations_count": 1,
        "test_result": {
            "passed_count": 2,
            "failed_count": 0,
            "duration_seconds": 2.15,
        }
    },
    "security": {
        "status": "passed",
        "findings_count": 0,
        "policy": "strict"
    }
}

orig_code = open("scratch/demo_calculator_repo/calculator.py").read()
patched_code = orig_code.replace(
    "# Intentional arithmetic bug: uses addition instead of subtraction\n    return a + b",
    "return a - b"
)

print("\n--- [1] Patch Summary Card ---")
render_patch_card(patch_rec, fix_time=10.2)

print("\n--- [2] Developer Review Gate (Unified Diff View) ---")
display_review_screen(
    filename="calculator.py",
    original_code=orig_code,
    patched_code=patched_code,
    explanation=patch_rec["explanation"],
    mode="unified",
)
