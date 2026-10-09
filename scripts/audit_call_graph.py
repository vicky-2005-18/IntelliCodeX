"""
Audit Call Graph Precision and Recall
Supports two audit modes:
1. Precision mode: Samples N edges from the CALL GRAPH (seeded), prints caller, callee,
   line and snippet, and reads a labels file to report the false-match rate.
2. Recall mode: Samples N call sites from the SOURCE code (seeded), prints caller,
   the call expression, line, snippet, and whether the current graph has an edge to a plausible callee.
   Outputs a template JSON with un-prefilled labels (null), and reads a labels file to report:
   recall = true internal calls with an edge / true internal calls.
"""
import argparse
import ast
import json
import os
import random
import sys
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath("."))
from core.parser import walk_repository, SourceFile
from core.chunker import chunk_repository, CodeChunk
from core.call_graph import build_call_graph, _extract_tree_sitter_calls


def load_line_snippet(repo_path: str, file_path: str, line_no: int, window: int = 1) -> str:
    """Reads line snippet from repo file around line_no."""
    if not file_path or not line_no:
        return ""
    full_path = os.path.join(repo_path, file_path)
    if not os.path.exists(full_path):
        return ""
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        start = max(0, line_no - 1 - window)
        end = min(len(lines), line_no + window)
        snippet_lines = []
        for idx in range(start, end):
            curr_line = idx + 1
            prefix = "--> " if curr_line == line_no else "    "
            snippet_lines.append(f"{prefix}{curr_line:4d}: {lines[idx].rstrip()}")
        return "\n".join(snippet_lines)
    except Exception:
        return ""


def extract_source_call_sites(source_files: List[SourceFile], chunks: List[CodeChunk]) -> List[Dict[str, Any]]:
    """Extracts all raw function/method call sites from source files."""
    chunks_by_file: Dict[str, List[CodeChunk]] = {}
    for c in chunks:
        chunks_by_file.setdefault(c.file_path, []).append(c)
    for f in chunks_by_file:
        chunks_by_file[f].sort(key=lambda c: (c.end_line - c.start_line, c.start_line))

    call_sites: List[Dict[str, Any]] = []

    for sf in source_files:
        f_chunks = chunks_by_file.get(sf.rel_path, [])
        if sf.language == "python":
            try:
                tree = ast.parse(sf.content, filename=sf.rel_path)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    line = getattr(node, "lineno", 1)
                    symbol = ""
                    call_expr = ""
                    if hasattr(ast, "unparse"):
                        try:
                            call_expr = ast.unparse(node.func)
                        except Exception:
                            call_expr = ""

                    if isinstance(node.func, ast.Name):
                        symbol = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        symbol = node.func.attr

                    if not symbol:
                        continue
                    if not call_expr:
                        call_expr = symbol

                    caller_chunk = None
                    for c in f_chunks:
                        if c.start_line <= line <= c.end_line:
                            caller_chunk = c
                            break

                    caller_id = caller_chunk.chunk_id if caller_chunk else f"{sf.rel_path}::<module>"
                    call_sites.append({
                        "file_path": sf.rel_path,
                        "line": line,
                        "symbol": symbol,
                        "call_expression": call_expr,
                        "caller": caller_id,
                    })
        else:
            raw_calls = _extract_tree_sitter_calls(sf.content, sf.rel_path, sf.language) if sf.has_tree_sitter else []
            for rc in raw_calls:
                line = rc.get("line", 1)
                symbol = rc.get("name", "")
                if not symbol:
                    continue
                caller_chunk = None
                for c in f_chunks:
                    if c.start_line <= line <= c.end_line:
                        caller_chunk = c
                        break
                caller_id = caller_chunk.chunk_id if caller_chunk else f"{sf.rel_path}::<file>"
                call_sites.append({
                    "file_path": sf.rel_path,
                    "line": line,
                    "symbol": symbol,
                    "call_expression": symbol,
                    "caller": caller_id,
                })

    # Sort deterministically
    call_sites.sort(key=lambda s: (s["file_path"], s["line"], s["symbol"]))
    return call_sites


def run_precision_audit(
    repo_path: str,
    legacy: bool = False,
    seed: int = 42,
    sample_size: int = 25,
    labels_file: Optional[str] = None,
    save_sample_file: Optional[str] = None,
):
    print(f"[*] Scanning repository: {repo_path}")
    source_files = walk_repository(repo_path)
    if not source_files:
        print(f"[!] No source files found in {repo_path}")
        return

    print(f"[*] Chunking repository ({len(source_files)} files)...")
    chunks = chunk_repository(source_files)
    chunk_map = {c.chunk_id: c for c in chunks}

    mode_name = "LEGACY (--legacy-call-graph)" if legacy else "PRECISION (scoped & deduped)"
    print(f"[*] Building call graph [{mode_name}]...")
    cg = build_call_graph(chunks, source_files, legacy=legacy)
    num_nodes = cg.number_of_nodes()
    num_edges = cg.number_of_edges()

    print(f"===========================================================")
    print(f" CALL GRAPH AUDIT: PRECISION MODE ({repo_path})")
    print(f" Mode: {mode_name}")
    print(f" Total Nodes: {num_nodes}")
    print(f" Total Edges: {num_edges}")
    print(f"===========================================================")

    edges = sorted(list(cg.edges(data=True)), key=lambda e: (e[0], e[1], e[2].get("call_line", 0)))
    if not edges:
        print("[!] No call graph edges generated.")
        return

    n_sample = min(sample_size, len(edges))
    rng = random.Random(seed)
    sampled_indices = sorted(rng.sample(range(len(edges)), n_sample))
    sampled_edges = [edges[i] for i in sampled_indices]

    labels: Dict[str, Any] = {}
    if labels_file and os.path.exists(labels_file):
        with open(labels_file, "r", encoding="utf-8") as f:
            raw_labels = json.load(f)
            if isinstance(raw_labels, list):
                for item in raw_labels:
                    if isinstance(item, dict):
                        idx_k = str(item.get("index"))
                        labels[idx_k] = item
            elif isinstance(raw_labels, dict):
                labels = raw_labels
        print(f"[*] Loaded labels from: {labels_file} ({len(labels)} entries)")

    sample_records = []
    false_match_count = 0
    true_match_count = 0
    unlabeled_count = 0

    print(f"\n--- SAMPLED EDGES (Seed: {seed}, Sample Size: {n_sample}/{len(edges)}) ---")
    for idx, (u, v, data) in enumerate(sampled_edges, 1):
        caller_chunk = chunk_map.get(u)
        callee_chunk = chunk_map.get(v)
        line_no = data.get("call_line")
        symbol = data.get("symbol")
        caller_file = caller_chunk.file_path if caller_chunk else data.get("caller_file", "")
        callee_file = callee_chunk.file_path if callee_chunk else data.get("callee_file", "")
        caller_name = caller_chunk.name if caller_chunk else u
        callee_name = callee_chunk.name if callee_chunk else v

        snippet = load_line_snippet(repo_path, caller_file, line_no)

        edge_key = f"{u} -> {v}"
        label_key_idx = str(idx)

        label_val = None
        if edge_key in labels:
            label_val = labels[edge_key]
        elif label_key_idx in labels:
            label_val = labels[label_key_idx]

        is_false_match = None
        if isinstance(label_val, dict):
            if "is_false_match" in label_val:
                is_false_match = label_val["is_false_match"]
            elif "valid" in label_val:
                is_false_match = not bool(label_val["valid"]) if label_val["valid"] is not None else None
        elif isinstance(label_val, bool):
            is_false_match = label_val

        status_str = "UNLABELED"
        if is_false_match is True:
            false_match_count += 1
            status_str = "[FALSE MATCH]"
        elif is_false_match is False:
            true_match_count += 1
            status_str = "[VALID MATCH]"
        else:
            unlabeled_count += 1

        print(f"\n[{idx:2d}/{n_sample:2d}] {status_str}")
        print(f"     Caller: {u} (line {line_no})")
        print(f"     Callee: {v}")
        print(f"     Symbol: '{symbol}'")
        if snippet:
            print(f"     Code Snippet:\n{snippet}")

        sample_records.append({
            "index": idx,
            "caller": u,
            "callee": v,
            "caller_file": caller_file,
            "callee_file": callee_file,
            "caller_name": caller_name,
            "callee_name": callee_name,
            "line": line_no,
            "symbol": symbol,
            "snippet": snippet,
            "is_false_match": None,  # NOT pre-filled for hand labeling template
        })

    if save_sample_file:
        with open(save_sample_file, "w", encoding="utf-8") as f:
            json.dump(sample_records, f, indent=2)
        print(f"\n[*] Sample exported for labeling to: {save_sample_file} (labels left as null)")

    print("\n===========================================================")
    print(" PRECISION AUDIT SUMMARY")
    print(f" Total Edges:        {num_edges}")
    print(f" Sample Size:        {n_sample}")
    print(f" Valid Matches:      {true_match_count}")
    print(f" False Matches:      {false_match_count}")
    print(f" Unlabeled:          {unlabeled_count}")

    labeled_total = true_match_count + false_match_count
    if labeled_total > 0:
        false_rate = (false_match_count / labeled_total) * 100.0
        print(f" False-Match Rate:   {false_rate:.1f}% ({false_match_count}/{labeled_total})")
    else:
        print(" False-Match Rate:   N/A (no labeled samples)")
    print("===========================================================\n")


def run_recall_audit(
    repo_path: str,
    legacy: bool = False,
    seed: int = 42,
    sample_size: int = 25,
    labels_file: Optional[str] = None,
    save_sample_file: Optional[str] = None,
):
    print(f"[*] Scanning repository for source call sites: {repo_path}")
    source_files = walk_repository(repo_path)
    if not source_files:
        print(f"[!] No source files found in {repo_path}")
        return

    print(f"[*] Chunking repository ({len(source_files)} files)...")
    chunks = chunk_repository(source_files)
    mode_name = "LEGACY (--legacy-call-graph)" if legacy else "PRECISION (scoped & deduped)"
    print(f"[*] Building call graph [{mode_name}]...")
    cg = build_call_graph(chunks, source_files, legacy=legacy)

    print(f"[*] Extracting all call sites from source code...")
    all_call_sites = extract_source_call_sites(source_files, chunks)
    print(f"[*] Total source call sites found: {len(all_call_sites)}")

    if not all_call_sites:
        print("[!] No source call sites found.")
        return

    n_sample = min(sample_size, len(all_call_sites))
    rng = random.Random(seed)
    sampled_indices = sorted(rng.sample(range(len(all_call_sites)), n_sample))
    sampled_calls = [all_call_sites[i] for i in sampled_indices]

    labels: Dict[str, Any] = {}
    if labels_file and os.path.exists(labels_file):
        with open(labels_file, "r", encoding="utf-8") as f:
            raw_labels = json.load(f)
            if isinstance(raw_labels, list):
                for item in raw_labels:
                    if isinstance(item, dict):
                        idx_k = str(item.get("index"))
                        labels[idx_k] = item
            elif isinstance(raw_labels, dict):
                labels = raw_labels
        print(f"[*] Loaded labels from: {labels_file} ({len(labels)} entries)")

    sample_records = []
    true_internal_count = 0
    true_internal_with_edge_count = 0
    non_internal_count = 0
    unlabeled_count = 0

    print(f"\n===========================================================")
    print(f" CALL GRAPH AUDIT: RECALL MODE ({repo_path})")
    print(f" Mode: {mode_name}")
    print(f" Total Source Call Sites: {len(all_call_sites)}")
    print(f" Graph Nodes: {cg.number_of_nodes()} | Graph Edges: {cg.number_of_edges()}")
    print(f" Sample Size: {n_sample} (Seed: {seed})")
    print(f"===========================================================")

    for idx, sc in enumerate(sampled_calls, 1):
        caller = sc["caller"]
        symbol = sc["symbol"]
        call_expr = sc["call_expression"]
        line = sc["line"]
        file_path = sc["file_path"]

        snippet = load_line_snippet(repo_path, file_path, line)

        # Check if current graph has an edge from caller to a plausible callee
        has_edge = False
        graph_callees: List[str] = []
        if caller in cg:
            for succ in cg.successors(caller):
                edge_data = cg.get_edge_data(caller, succ) or {}
                # Plausible callee: matching line, matching symbol name, or symbol in node ID
                if edge_data.get("call_line") == line or edge_data.get("symbol") == symbol or symbol in succ:
                    has_edge = True
                    graph_callees.append(succ)

        label_key_idx = str(idx)
        label_val = None
        if label_key_idx in labels:
            label_val = labels[label_key_idx]

        is_true_internal = None
        if isinstance(label_val, dict):
            if "is_true_internal_call" in label_val:
                is_true_internal = label_val["is_true_internal_call"]
            elif "is_internal" in label_val:
                is_true_internal = label_val["is_internal"]
        elif isinstance(label_val, bool):
            is_true_internal = label_val

        status_str = "UNLABELED"
        if is_true_internal is True:
            true_internal_count += 1
            if has_edge:
                true_internal_with_edge_count += 1
                status_str = "[TRUE INTERNAL: EDGE PRESENT]"
            else:
                status_str = "[TRUE INTERNAL: MISSING EDGE]"
        elif is_true_internal is False:
            non_internal_count += 1
            status_str = "[NON-INTERNAL / EXTERNAL CALL]"
        else:
            unlabeled_count += 1

        print(f"\n[{idx:2d}/{n_sample:2d}] {status_str}")
        print(f"     Caller:          {caller} (line {line})")
        print(f"     Call Expression: {call_expr}")
        print(f"     Symbol:          '{symbol}'")
        print(f"     Edge in Graph:   {has_edge} -> {graph_callees if graph_callees else 'None'}")
        if snippet:
            print(f"     Code Snippet:\n{snippet}")

        sample_records.append({
            "index": idx,
            "caller": caller,
            "file_path": file_path,
            "line": line,
            "call_expression": call_expr,
            "symbol": symbol,
            "snippet": snippet,
            "has_edge_in_graph": has_edge,
            "graph_callees": graph_callees,
            "is_true_internal_call": None,  # NOT pre-filled for hand labeling template
        })

    if save_sample_file:
        with open(save_sample_file, "w", encoding="utf-8") as f:
            json.dump(sample_records, f, indent=2)
        print(f"\n[*] Recall sample template exported to: {save_sample_file} (labels left as null)")

    print("\n===========================================================")
    print(" RECALL AUDIT SUMMARY")
    print(f" Total Source Call Sites:     {len(all_call_sites)}")
    print(f" Sample Size:                 {n_sample}")
    print(f" True Internal Calls (Hand):  {true_internal_count}")
    print(f" Non-Internal / External:     {non_internal_count}")
    print(f" Unlabeled:                   {unlabeled_count}")
    print(f" True Internal with Edge:     {true_internal_with_edge_count}")

    if true_internal_count > 0:
        recall_rate = (true_internal_with_edge_count / true_internal_count) * 100.0
        print(f" Recall:                      {recall_rate:.1f}% ({true_internal_with_edge_count}/{true_internal_count})")
    else:
        print(" Recall:                      N/A (no true internal calls labeled)")
    print("===========================================================\n")


def main():
    parser = argparse.ArgumentParser(description="Call Graph Quality Audit Tool (Precision & Recall)")
    parser.add_argument("--repo", default=".repos/bottle", help="Target repository path")
    parser.add_argument("--mode", choices=["precision", "recall"], default="precision", help="Audit mode (default: precision)")
    parser.add_argument("--legacy", action="store_true", help="Audit legacy call graph builder")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling (default: 42)")
    parser.add_argument("-n", "--n", "--sample-size", dest="n", type=int, default=25, help="Sample size N (default: 25)")
    parser.add_argument("--labels", default=None, help="Path to JSON file containing ground-truth labels")
    parser.add_argument("--save-sample", "--output-template", dest="save_sample", default=None, help="Path to export sampled items for hand labeling")

    args = parser.parse_args()

    if args.mode == "recall":
        run_recall_audit(
            repo_path=args.repo,
            legacy=args.legacy,
            seed=args.seed,
            sample_size=args.n,
            labels_file=args.labels,
            save_sample_file=args.save_sample,
        )
    else:
        run_precision_audit(
            repo_path=args.repo,
            legacy=args.legacy,
            seed=args.seed,
            sample_size=args.n,
            labels_file=args.labels,
            save_sample_file=args.save_sample,
        )


if __name__ == "__main__":
    main()
