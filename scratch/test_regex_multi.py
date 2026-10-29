import re

s = "calculate_discount(100, 0.2) returns 80.0. Also extra_feature(5) returns 10. Target: 'test.py'"
text_no_target = re.sub(r'(?i)\btarget\s*:\s*["\']?[^"\']+["\']?', '', s)

# Improved p1 pattern
p1 = list(re.finditer(
    r'(?i)\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)\s*(?:must\s+return|returns|==)\s*([^\n;]+?)(?=\.\s+[A-Z]|\.\s*$|[;\n]|$)',
    text_no_target
))
print("P1:", [(m.group(1), m.group(2), m.group(3).strip()) for m in p1])

# Improved p2 pattern
s2 = "Given (100, 0.2) calculate_discount returns 80.0. Given (5) extra_feature returns 10."
p2 = list(re.finditer(
    r'(?i)(?:when\s+given|given|input)\s+([^\n]+?)\s*(?:,\s*|\s+)(?:([a-zA-Z_][a-zA-Z0-9_]*)\s+)?(?:must\s+return|returns|output|expected|==)\s+([^\n;]+?)(?=\.\s+[A-Z]|\.\s*$|[;\n]|$)',
    s2
))
print("P2:", [(m.group(1).strip(), m.group(2), m.group(3).strip()) for m in p2])
