import re
from collections import Counter
from typing import List

def strip_comments_and_strings(code: str) -> str:
    code = re.sub(r'//[^\n]*', '', code)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
    code = re.sub(r"'(?:\\.|[^'\\])*'", "''", code)
    code = re.sub(r'`(?:\\.|[^`\\])*`', '``', code)
    return code

def detect_ts_duplicates(code: str) -> List[str]:
    clean = strip_comments_and_strings(code)
    lines = clean.splitlines()
    brace_depth = 0
    current_class_stack = []
    
    class_re = re.compile(r'\b(?:class|interface)\s+([a-zA-Z0-9_$]+)')
    fn_impl_re = re.compile(r'^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\([^)]*\)[^{;]*\{')
    var_re = re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*[:=]')
    method_re = re.compile(r'^\s*(?:public|private|protected|static|async|\s)*([a-zA-Z0-9_$]+)\s*\([^)]*\)[^{;]*\{')
    
    classes = Counter()
    top_level_fns = Counter()
    top_level_vars = Counter()
    class_methods = Counter()
    dups = []
    
    for line in lines:
        stripped = line.strip()
        m_cls = class_re.search(stripped)
        if m_cls and "{" in stripped:
            cls_name = m_cls.group(1)
            classes[cls_name] += 1
            if classes[cls_name] > 1:
                dups.append(f"class {cls_name}")
            current_class_stack.append((brace_depth, cls_name))
            
        m_fn = fn_impl_re.search(line)
        if m_fn and not current_class_stack:
            fn_name = m_fn.group(1)
            top_level_fns[fn_name] += 1
            if top_level_fns[fn_name] > 1:
                dups.append(f"function {fn_name}")
                
        m_var = var_re.search(line)
        if m_var and not current_class_stack:
            var_name = m_var.group(1)
            top_level_vars[var_name] += 1
            if top_level_vars[var_name] > 1:
                dups.append(f"const/let {var_name}")
                
        if current_class_stack and "{" in stripped and not m_cls:
            m_meth = method_re.search(line)
            if m_meth:
                meth_name = m_meth.group(1)
                if meth_name not in ("if", "for", "while", "switch", "catch"):
                    cur_cls = current_class_stack[-1][1]
                    sig = (cur_cls, meth_name)
                    class_methods[sig] += 1
                    if class_methods[sig] > 1:
                        dups.append(f"{cur_cls}.{meth_name}")
                        
        brace_depth += stripped.count('{') - stripped.count('}')
        while current_class_stack and brace_depth <= current_class_stack[-1][0]:
            current_class_stack.pop()

    return sorted(list(set(dups)))

def test_ts():
    valid_ts = """
    function parse(x: string): string;
    function parse(x: number): number;
    function parse(x: any): any {
        return x;
    }

    class ServiceA {
        execute(): void {}
    }

    class ServiceB {
        execute(): void {}
    }
    """
    assert detect_ts_duplicates(valid_ts) == []
    print("TypeScript valid overloads and multiple classes: PASS")

    invalid_ts = """
    function parse(x: any): any { return x; }
    function parse(x: any): any { return x; }
    """
    dups = detect_ts_duplicates(invalid_ts)
    assert len(dups) == 1
    assert "function parse" in dups[0]
    print("TypeScript duplicate implementation: PASS (caught:", dups, ")")

if __name__ == "__main__":
    test_ts()
