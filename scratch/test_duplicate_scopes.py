import re
from collections import Counter
from typing import List, Tuple, Optional

def strip_comments_and_strings(code: str) -> str:
    code = re.sub(r'//[^\n]*', '', code)
    code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
    code = re.sub(r'"(?:\\.|[^"\\])*"', '""', code)
    code = re.sub(r"'(?:\\.|[^'\\])*'", "''", code)
    return code

def detect_java_duplicates(code: str) -> List[str]:
    clean = strip_comments_and_strings(code)
    lines = clean.splitlines()
    brace_depth = 0
    current_class_stack = []
    
    class_decl_re = re.compile(r'\b(?:class|interface|enum|record)\s+([a-zA-Z0-9_$]+)')
    method_decl_re = re.compile(
        r'(?:public|protected|private|static|final|native|synchronized|abstract|\s)+'
        r'[\w<>\[\], ?]+\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)\s*(?:throws\s+[\w.,\s]+)?\s*\{'
    )
    
    class_methods = Counter()
    classes = Counter()
    dups = []
    
    for line in lines:
        stripped = line.strip()
        m_cls = class_decl_re.search(stripped)
        if m_cls and "{" in stripped:
            cls_name = m_cls.group(1)
            classes[cls_name] += 1
            if classes[cls_name] > 1:
                dups.append(f"class {cls_name}")
            current_class_stack.append((brace_depth, cls_name))
        
        m_meth = method_decl_re.search(stripped)
        if m_meth and "{" in stripped:
            meth_name = m_meth.group(1)
            raw_params = m_meth.group(2).strip()
            param_types = []
            if raw_params:
                for param in raw_params.split(','):
                    parts = param.strip().split()
                    if parts:
                        param_types.append(parts[0].split('<')[0])
            cur_cls = current_class_stack[-1][1] if current_class_stack else "Global"
            sig = (cur_cls, meth_name, tuple(param_types))
            class_methods[sig] += 1
            if class_methods[sig] > 1:
                dups.append(f"{cur_cls}.{meth_name}({', '.join(param_types)})")
        
        brace_depth += stripped.count('{') - stripped.count('}')
        while current_class_stack and brace_depth <= current_class_stack[-1][0]:
            current_class_stack.pop()

    return sorted(list(set(dups)))

def detect_rust_duplicates(code: str) -> List[str]:
    clean = strip_comments_and_strings(code)
    lines = clean.splitlines()
    brace_depth = 0
    current_impl_stack = []
    
    impl_re = re.compile(r'\bimpl(?:\s+<[^>]+>)?\s+(?:(?P<trait>[\w:]+)\s+for\s+)?(?P<type>[\w:]+)')
    fn_re = re.compile(r'\b(?:pub(?:\([^)]+\))?\s+)?fn\s+([a-zA-Z0-9_]+)\s*\(')
    
    methods = Counter()
    free_funcs = Counter()
    dups = []
    
    for line in lines:
        stripped = line.strip()
        m_impl = impl_re.search(stripped)
        if m_impl and "{" in stripped:
            target_type = m_impl.group("type")
            trait_name = m_impl.group("trait") or ""
            impl_scope = f"{trait_name} for {target_type}".strip() if trait_name else target_type
            current_impl_stack.append((brace_depth, impl_scope))
        
        m_fn = fn_re.search(stripped)
        if m_fn and not stripped.startswith("//"):
            fn_name = m_fn.group(1)
            if current_impl_stack:
                scope = current_impl_stack[-1][1]
                sig = (scope, fn_name)
                methods[sig] += 1
                if methods[sig] > 1:
                    dups.append(f"impl {scope}::fn {fn_name}")
            else:
                free_funcs[fn_name] += 1
                if free_funcs[fn_name] > 1:
                    dups.append(f"fn {fn_name}")
        
        brace_depth += stripped.count('{') - stripped.count('}')
        while current_impl_stack and brace_depth <= current_impl_stack[-1][0]:
            current_impl_stack.pop()

    return sorted(list(set(dups)))

def detect_go_duplicates(code: str) -> List[str]:
    clean = strip_comments_and_strings(code)
    fn_re = re.compile(r'^\s*func\s+(?:\((?P<recv>[^)]+)\)\s+)?(?P<name>[a-zA-Z0-9_]+)\s*\(', re.MULTILINE)
    
    free_funcs = Counter()
    method_funcs = Counter()
    dups = []
    
    for m in fn_re.finditer(clean):
        recv = m.group("recv")
        name = m.group("name")
        if recv:
            parts = recv.strip().split()
            recv_type = parts[-1].lstrip("*") if parts else "recv"
            sig = (recv_type, name)
            method_funcs[sig] += 1
            if method_funcs[sig] > 1:
                dups.append(f"({recv_type}).{name}")
        else:
            free_funcs[name] += 1
            if free_funcs[name] > 1:
                dups.append(f"func {name}")

    return sorted(list(set(dups)))

def test_rust():
    valid_rust = """
    struct Foo;
    struct Baz;

    impl Foo {
        fn calculate(&self) -> i32 { 1 }
    }

    impl Baz {
        fn calculate(&self) -> i32 { 2 }
    }
    """
    assert detect_rust_duplicates(valid_rust) == []
    print("Rust separate impl blocks: PASS")

    invalid_rust = """
    impl Foo {
        fn calculate(&self) -> i32 { 1 }
        fn calculate(&self) -> i32 { 2 }
    }
    """
    dups = detect_rust_duplicates(invalid_rust)
    assert len(dups) == 1
    assert "impl Foo::fn calculate" in dups[0]
    print("Rust duplicate in same impl block: PASS (caught:", dups, ")")

def test_go():
    valid_go = """
    func (f *Foo) Process() error { return nil }
    func (b *Bar) Process() error { return nil }
    """
    assert detect_go_duplicates(valid_go) == []
    print("Go separate receivers: PASS")

    invalid_go = """
    func (f *Foo) Process() error { return nil }
    func (f *Foo) Process() error { return nil }
    """
    dups = detect_go_duplicates(invalid_go)
    assert len(dups) == 1
    assert "(Foo).Process" in dups[0]
    print("Go duplicate on same receiver: PASS (caught:", dups, ")")

if __name__ == "__main__":
    test_rust()
    test_go()
