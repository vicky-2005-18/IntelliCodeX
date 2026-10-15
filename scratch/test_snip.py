import sys
sys.path.insert(0, ".")
from backend.patch_generator.patch_applier import merge_snippet_into_file

with open("scratch/demo_calculator_repo/calculator.py") as f:
    full = f.read()

orig_snip = (
    'def subtract(a: float, b: float) -> float:\n'
    '    """Returns the difference of a and b."""\n'
    '    # Intentional arithmetic bug: uses addition instead of subtraction\n'
    '    return a + b'
)

patch_snip = (
    'def subtract(a: float, b: float) -> float:\n'
    '    """Returns the difference of a and b."""\n'
    '    return a - b'
)

print("Found exact in full:", orig_snip in full)
res = merge_snippet_into_file(full, orig_snip, patch_snip)
print("Merge success:", res is not None)
if res:
    print("Has add:", "def add(" in res)
    print("Has subtract:", "def subtract(" in res)
    print("Has multiply:", "def multiply(" in res)
    print("Has divide:", "def divide(" in res)
    print("Correct minus in subtract:", "return a - b" in res)
