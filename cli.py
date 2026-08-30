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
from core.dependency_graph import files_likely_affected_by


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
  deps:<filepath>        - Find files depending on <filepath> (e.g. 'deps:pkg/db.py')
  repo <path_or_url>     - Switch/clone active repository (e.g. 'repo https://github.com/user/repo')
  backend <ollama|tfidf> - Switch active backend engine dynamically
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
    args = parser.parse_args()

    print_banner()

    embedder, llm, active_backend = create_components(args.backend)

    try:
        current_path = resolve_repo_path(args.repo_path)
        print(f"[*] Ingesting repository: {current_path}")
        result = ingest_repository(current_path, embedder)
    except Exception as e:
        print(f"[!] Error ingesting repository '{args.repo_path}': {e}")
        return 1

    print(f"[*] Indexed {result.num_files} files -> {result.num_chunks} code chunks")
    print(f"[*] Dependency graph: {result.graph.number_of_nodes()} nodes, {result.graph.number_of_edges()} edges")

    engine = QueryEngine(result.store, embedder, llm)

    print("\nIntelliCodeX ready. Type a question or 'help' for options, 'exit' to quit.\n")

    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting IntelliCodeX CLI. Goodbye!")
            break

        # Strip leading prompt markers like '>>' or '>' or '$' if user accidentally included them
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

        if query.lower().startswith("backend "):
            new_backend = query.split(maxsplit=1)[1].strip().lower()
            if new_backend not in ("ollama", "tfidf"):
                print("[!] Invalid backend. Choose 'ollama' or 'tfidf'.\n")
                continue
            embedder, llm, active_backend = create_components(new_backend)
            print(f"[*] Re-indexing repository with '{active_backend}' backend...")
            result = ingest_repository(current_path, embedder)
            engine = QueryEngine(result.store, embedder, llm)
            print(f"[*] Backend updated to '{active_backend}'.\n")
            continue

        # Handle repo switching: 'repo <target>', 'repo:<target>', 'use <target>', or direct URLs
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
                engine = QueryEngine(result.store, embedder, llm)
                print(f"[*] Indexed {result.num_files} files -> {result.num_chunks} chunks")
                print(f"[*] Dependency graph: {result.graph.number_of_nodes()} nodes, {result.graph.number_of_edges()} edges")
                print(f"[*] Successfully switched active repository to '{new_path}'!\n")
            except Exception as e:
                print(f"[!] Error switching repository: {e}\n")
            continue

        if query.startswith("deps:"):
            target = query[len("deps:"):].strip()
            affected = files_likely_affected_by(result.graph, target)
            print(f"\nFiles depending on {target}: {affected or '(none found)'}\n")
            continue

        response = engine.ask(query)
        print(f"\n--- Retrieved {len(response['retrieved_chunks'])} chunks ---")
        for c in response["retrieved_chunks"]:
            print(f"  {c['file']} :: {c['name']} (lines {c['lines']}, score={c['score']:.3f})")
        print(f"\n--- Answer ---\n{response['answer']}\n")


if __name__ == "__main__":
    sys.exit(main())


