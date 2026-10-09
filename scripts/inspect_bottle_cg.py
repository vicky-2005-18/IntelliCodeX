import random
import linecache
import sys
import os
sys.path.insert(0, os.path.abspath("."))
from core.parser import walk_repository
from core.chunker import chunk_repository
from core.call_graph import build_call_graph

repo_path = ".repos/bottle"
source_files = walk_repository(repo_path)
chunks = chunk_repository(source_files)
chunk_map = {c.chunk_id: c for c in chunks}

cg = build_call_graph(chunks, source_files)
print(f"Nodes: {cg.number_of_nodes()}, Edges: {cg.number_of_edges()}")

random.seed(42)
edges = list(cg.edges(data=True))
sample = random.sample(edges, min(15, len(edges)))

for idx, (u, v, d) in enumerate(sample, 1):
    caller = chunk_map.get(u)
    callee = chunk_map.get(v)
    line_no = d.get("call_line")
    symbol = d.get("symbol")
    caller_name = caller.name if caller else u
    caller_file = caller.file_path if caller else d.get("caller_file")
    callee_name = callee.name if callee else v
    callee_file = callee.file_path if callee else d.get("callee_file")
    
    # Read the actual line of code from file
    actual_line = ""
    if caller_file:
        full_path = f"{repo_path}/{caller_file}"
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                if 0 <= line_no - 1 < len(lines):
                    actual_line = lines[line_no - 1].strip()
        except Exception:
            pass

    print(f"[{idx:2d}] Line {line_no:4d}: '{symbol}'")
    print(f"     Caller: {caller_file} :: {caller_name}")
    print(f"     Callee: {callee_file} :: {callee_name}")
    print(f"     Code  : {actual_line}")
    print()
