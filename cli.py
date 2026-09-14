"""
IntelliCodeX CLI — Ingest and query software repositories interactively.

Usage:
    python cli.py [repo_path_or_url] [--backend ollama|tfidf]

Examples:
    python cli.py sample_repo
    python cli.py https://github.com/vicky-2005-18/TB --backend ollama
"""
import argparse
import os
import subprocess
import sys
import requests
from core.pipeline import ingest_repository
from core.embedder import TfidfEmbedder, OllamaEmbedder
from core.llm_client import OllamaLLM
from rag.query_engine import QueryEngine
from core.dependency_graph import files_likely_affected_by, get_top_central_files
from core.call_graph import find_callers_of_symbol, get_top_central_symbols
from core.git_hooks import install_git_hooks, uninstall_git_hooks, check_git_hooks_status
from core.patch_generator import PatchEngine
from core.persistence import get_repo_id



def check_ollama_available(host: str = "http://localhost:11434") -> bool:
    """Checks if local Ollama server is running and accessible."""
    try:
        resp = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def resolve_repo_path(repo_target: str) -> str:
    """Resolves local directory path or clones remote Git repository URL into .repos folder."""
    repo_target = repo_target.strip()
    if repo_target.startswith("http://") or repo_target.startswith("https://") or repo_target.startswith("git@"):
        repo_name = repo_target.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        target_dir = os.path.abspath(os.path.join(".repos", repo_name))

        if os.path.exists(target_dir) and os.path.exists(os.path.join(target_dir, ".git")):
            print(f"[*] Local clone found at '{target_dir}'. Syncing latest changes...")
            try:
                subprocess.run(["git", "pull"], cwd=target_dir, capture_output=True, text=True, timeout=15)
            except subprocess.TimeoutExpired:
                print(f"[!] Warning: 'git pull' timed out after 15s. Using existing local files.")
            except Exception as e:
                print(f"[!] Warning: 'git pull' encountered an issue: {e}. Using existing local files.")
        else:
            os.makedirs(".repos", exist_ok=True)
            print(f"[*] Cloning remote Git repository '{repo_target}' into '{target_dir}'...")
            try:
                res = subprocess.run(["git", "clone", "--depth", "50", repo_target, target_dir], capture_output=True, text=True, timeout=45)
                if res.returncode != 0:
                    raise RuntimeError(f"Git clone failed: {res.stderr.strip() or 'Unknown error or empty repository'}")
            except subprocess.TimeoutExpired:
                raise RuntimeError("Git clone operation timed out (45s). Please check repository URL or network connection.")
        return target_dir

    if not os.path.exists(repo_target):
        raise FileNotFoundError(f"Repository path or URL invalid / not found: '{repo_target}'")
    return os.path.abspath(repo_target)


def print_banner():
    banner = """
=======================================================================
               INTELLICODEX INTERACTIVE CLI ASSISTANT
  AI-Powered Repository Search, Dependency Analysis & Code Intelligence
=======================================================================
"""
    print(banner)


def print_help():
    help_text = """
Available Commands:
  fix:<err_or_file>      - Diagnose bug & generate automated code patch (e.g. 'fix:KeyError in auth.py')
  deps:<filepath>        - View direct & reverse dependencies for <filepath> (e.g. 'deps:pkg/db.py')
  callers:<func>         - Find all function call sites calling <func> (e.g. 'callers:fetch_user')
  top / centrality       - Show top central files and critical functions (PageRank score)
  repo <path_or_url>     - Switch/clone active repository (e.g. 'repo https://github.com/user/repo')
  backend <ollama|tfidf> - Switch active backend engine dynamically
  persona <name>         - Switch AI persona (general, security, reviewer, refactor, fixer)
  model <model_name>     - Switch active Ollama model (e.g. 'model qwen2.5-coder:7b')
  history / clear-chat   - View or clear multi-turn chat memory
  hooks / setup-hooks   - Install Git background re-indexing hooks for current repository
  hooks:status          - Check status of installed Git hooks
  hooks:remove          - Uninstall Git background re-indexing hooks
  files / ls             - List all indexed source files in the active repository
  clear / cls            - Clear terminal screen
  help / ?               - Show this help message
  exit / quit            - Exit IntelliCodeX CLI
"""
    print(help_text)




def create_components(backend_choice: str):
    """Factory helper to instantiate embedder and LLM with automatic fallback."""
    if backend_choice == "ollama":
        if check_ollama_available():
            print("[*] Backend: Ollama AI (qwen2.5-coder + nomic-embed-text)")
            return OllamaEmbedder(), OllamaLLM(), "ollama"
        else:
            print("[!] Ollama server not detected at http://localhost:11434.")
            print("[*] Automatically falling back to offline TF-IDF mode.")
            return TfidfEmbedder(), None, "tfidf"
    else:
        print("[*] Backend: Offline TF-IDF Mode")
        return TfidfEmbedder(), None, "tfidf"


def main():
    parser = argparse.ArgumentParser(description="IntelliCodeX CLI")
    parser.add_argument("repo_path", nargs="?", default="sample_repo",
                        help="Local directory path or Git URL (default: sample_repo)")
    parser.add_argument("--backend", choices=["ollama", "tfidf"], default="tfidf",
                        help="LLM & Embedding backend (default: tfidf)")
    parser.add_argument("--setup-hooks", action="store_true",
                        help="Install Git background re-indexing hooks for target repository")
    parser.add_argument("--check-hooks", action="store_true",
                        help="Check status of Git background re-indexing hooks")
    parser.add_argument("--remove-hooks", action="store_true",
                        help="Uninstall Git background re-indexing hooks")
    args = parser.parse_args()

    # Handle direct hook CLI flags if requested
    if args.setup_hooks:
        target = resolve_repo_path(args.repo_path)
        ok, msg = install_git_hooks(target)
        print(f"[*] {msg}")
        return 0 if ok else 1

    if args.check_hooks:
        target = resolve_repo_path(args.repo_path)
        st = check_git_hooks_status(target)
        print(f"[*] Git Hook Status for '{target}':")
        for hook, is_inst in st.items():
            print(f"  - {hook}: {'Installed' if is_inst else 'Not Installed'}")
        return 0

    if args.remove_hooks:
        target = resolve_repo_path(args.repo_path)
        ok, msg = uninstall_git_hooks(target)
        print(f"[*] {msg}")
        return 0 if ok else 1


    print_banner()

    embedder, llm, active_backend = create_components(args.backend)

    try:
        current_path = resolve_repo_path(args.repo_path)
        print(f"[*] Ingesting repository: {current_path}")
        result = ingest_repository(current_path, embedder)
    except Exception as e:
        print(f"[!] Error ingesting repository '{args.repo_path}': {e}")
        return 1

    print(f"[*] Indexed {result.num_files} files -> {result.num_chunks} code chunks ({result.ast_chunks_count} AST)")
    print(f"[*] Dependency graph: {result.graph.number_of_nodes()} nodes, {result.graph.number_of_edges()} edges")
    if getattr(result, "call_graph", None):
        print(f"[*] Call graph: {result.call_graph.number_of_nodes()} nodes, {result.call_graph.number_of_edges()} call edges")

    engine = QueryEngine(result.store, embedder, llm, dep_graph=result.graph, call_graph=getattr(result, "call_graph", None))

    print("\nIntelliCodeX ready. Type a question or 'help' for options, 'exit' to quit.\n")

    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting IntelliCodeX CLI. Goodbye!")
            break

        while query.startswith(">") or query.startswith("$"):
            query = query.lstrip(">").lstrip("$").strip()

        if not query:
            continue

        if query.lower() in ("exit", "quit"):
            print("Exiting IntelliCodeX CLI. Goodbye!")
            break

        if query.lower() in ("help", "?"):
            print_help()
            continue

        if query.lower() in ("clear", "cls"):
            os.system("cls" if os.name == "nt" else "clear")
            print_banner()
            continue

        if query.lower() in ("files", "ls"):
            indexed_files = sorted(list(set(c.file_path for c in result.store.chunks)))
            print(f"\n--- Indexed Source Files ({len(indexed_files)}) ---")
            for f in indexed_files:
                print(f"  - {f}")
            print()
            continue

        if query.lower() in ("top", "centrality"):
            top_files = get_top_central_files(result.graph, top_n=5)
            print("\n--- Top Central Files (PageRank Score) ---")
            if not top_files:
                print("  (no internal dependencies found)")
            else:
                for idx, (fpath, score) in enumerate(top_files, start=1):
                    print(f"  {idx}. {fpath} (score={score:.3f})")

            call_g = getattr(result, "call_graph", None)
            if call_g:
                top_syms = get_top_central_symbols(call_g, top_n=5)
                print("\n--- Top Central Function Symbols (PageRank Score) ---")
                if not top_syms:
                    print("  (no function call edges found)")
                else:
                    for idx, (cid, score) in enumerate(top_syms, start=1):
                        print(f"  {idx}. {cid} (score={score:.3f})")
            print()
            continue

        if query.lower().startswith("backend "):
            new_backend = query.split(maxsplit=1)[1].strip().lstrip("-").lower()
            if new_backend not in ("ollama", "tfidf"):
                print("[!] Invalid backend. Choose 'ollama' or 'tfidf'.\n")
                continue
            embedder, llm, active_backend = create_components(new_backend)
            print(f"[*] Re-indexing repository with '{active_backend}' backend...")
            result = ingest_repository(current_path, embedder)
            engine = QueryEngine(result.store, embedder, llm, dep_graph=result.graph, call_graph=getattr(result, "call_graph", None))
            print(f"[*] Backend updated to '{active_backend}'.\n")
            continue

        if (query.startswith("repo ") or query.startswith("repo:") or 
            query.startswith("use ") or query.startswith("ingest ") or 
            query.startswith("http://") or query.startswith("https://") or query.startswith("git@")):
            
            if query.startswith("repo:"):
                target = query[len("repo:"):].strip()
            elif query.startswith("repo ") or query.startswith("use ") or query.startswith("ingest "):
                target = query.split(maxsplit=1)[1].strip()
            else:
                target = query

            print(f"[*] Processing repository target: {target}")
            try:
                new_path = resolve_repo_path(target)
                print(f"[*] Parsing files and generating embeddings for '{new_path}'...")
                new_result = ingest_repository(new_path, embedder)
                result = new_result
                current_path = new_path
                engine = QueryEngine(result.store, embedder, llm, dep_graph=result.graph, call_graph=getattr(result, "call_graph", None))
                print(f"[*] Indexed {result.num_files} files -> {result.num_chunks} chunks")
                print(f"[*] Dependency graph: {result.graph.number_of_nodes()} nodes, {result.graph.number_of_edges()} edges")
                print(f"[*] Successfully switched active repository to '{new_path}'!\n")
            except Exception as e:
                print(f"[!] Error switching repository: {e}\n")
            continue

        if query.lower() in ("hooks:status", "hooks:check"):
            st = check_git_hooks_status(current_path)
            print(f"\n--- Git Hook Status for '{current_path}' ---")
            for hook, is_inst in st.items():
                print(f"  - {hook}: {'Installed' if is_inst else 'Not Installed'}")
            print()
            continue

        if query.lower() in ("hooks:remove", "hooks:uninstall"):
            ok, msg = uninstall_git_hooks(current_path)
            print(f"\n[*] {msg}\n")
            continue

        if query.lower() in ("hooks", "setup-hooks", "hooks:install", "hooks:setup"):
            ok, msg = install_git_hooks(current_path)
            print(f"\n[*] {msg}\n")
            continue

        if query.lower().startswith("persona"):
            parts = query.split(maxsplit=1)
            if len(parts) == 1:
                print(f"\n[*] Active Persona: '{engine.active_persona}'")
                print("Available Personas: general, security, reviewer, refactor, fixer\n")
            else:
                p_name = parts[1].strip()
                try:
                    active_p = engine.set_persona(p_name)
                    print(f"[*] Active Persona updated to: '{active_p}'\n")
                except ValueError as e:
                    print(f"[!] {e}\n")
            continue

        if query.lower().startswith("model "):
            new_model = query.split(maxsplit=1)[1].strip()
            engine.set_model(new_model)
            print(f"[*] Ollama LLM model set to: '{new_model}'\n")
            continue

        if query.lower() in ("history", "chat"):
            hist = engine.memory.format_history()
            if not hist:
                print("\n[*] Conversation history is empty.\n")
            else:
                print(f"\n{hist}\n")
            continue

        if query.lower() in ("clear-chat", "clear:history", "clear-memory"):
            engine.clear_memory()
            print("\n[*] Conversation history cleared.\n")
            continue


        if query.startswith("fix:") or query.startswith("fix "):
            err_input = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            
            # If err_input points to a file, read its error log content
            if os.path.isfile(err_input):
                try:
                    with open(err_input, "r", encoding="utf-8", errors="ignore") as f:
                        err_input = f.read()
                except Exception:
                    pass

            print("\n[*] Analyzing error report & localizing bug root cause...")
            patch_engine = PatchEngine(result.store, embedder, llm, graph=result.graph, repo_path=current_path)
            patch_rec = patch_engine.generate_patch(
                repo_id=get_repo_id(current_path),
                error_report=err_input
            )

            print("\n=======================================================================")
            print("                 INTELLICODEX AUTOMATED CODE PATCH")
            print("=======================================================================")
            print(f"Target File     : {patch_rec['target_file']}")
            print(f"Error Type      : {patch_rec.get('error_type', 'Unknown')}")
            print(f"Confidence      : {patch_rec['confidence_score']:.0%}")
            print(f"Explanation     : {patch_rec['explanation']}")
            print("\n--- Unified Git Diff ---")
            print(patch_rec["git_diff"])
            print("=======================================================================\n")

            if patch_rec["status"] != "failed" and patch_rec["git_diff"]:
                try:
                    ans = input(f"Apply this patch to '{patch_rec['target_file']}'? [y/N]: ").strip().lower()
                    if ans in ("y", "yes"):
                        ok_app, msg_app = patch_engine.apply_patch(patch_rec)
                        print(f"[*] {msg_app}\n")
                except (EOFError, KeyboardInterrupt):
                    pass
            continue



        if query.startswith("deps:") or query.startswith("deps "):
            target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            affected = files_likely_affected_by(result.graph, target)
            print(f"\n--- Dependency Analysis for '{target}' ---")
            print("  Reverse Dependencies (Files affected if modified):")
            if not affected:
                print("    (none found)")
            else:
                for aff in affected:
                    print(f"    ├── {aff}")
            print()
            continue

        if query.startswith("callers:") or query.startswith("callers "):
            symbol_target = query.split(":", 1)[1].strip() if ":" in query else query.split(maxsplit=1)[1].strip()
            call_g = getattr(result, "call_graph", None)
            if not call_g:
                print("[!] Call graph is unavailable.")
                continue

            callers = find_callers_of_symbol(call_g, symbol_target)
            print(f"\n--- Symbol Callers for '{symbol_target}' ---")
            if not callers:
                print("  (no calling function sites found)")
            else:
                for c_id in callers:
                    print(f"  ├── {c_id}")
            print()
            continue

        response = engine.ask(query)
        print(f"\n--- Retrieved {len(response['retrieved_chunks'])} chunks ---")
        for c in response["retrieved_chunks"]:
            reason_str = f", context={c['reason']}" if "reason" in c else ""
            print(f"  {c['file']} :: {c['name']} (lines {c['lines']}, score={c['score']:.3f}{reason_str})")
        print(f"\n--- Answer ---\n{response['answer']}\n")


if __name__ == "__main__":
    sys.exit(main())
