"""
IntelliCodeX CLI — ingest a repository and query it interactively.

Usage:
    python cli.py <repo_path> [--backend ollama|tfidf]

With --backend tfidf (default if Ollama isn't running), everything works
fully offline for development/testing. Switch to --backend ollama once you
have `ollama serve` running with qwen2.5-coder + nomic-embed-text pulled.
"""
import argparse
import sys
from core.pipeline import ingest_repository
from core.embedder import TfidfEmbedder, OllamaEmbedder
from core.llm_client import OllamaLLM
from rag.query_engine import QueryEngine
from core.dependency_graph import files_likely_affected_by


def main():
    parser = argparse.ArgumentParser(description="IntelliCodeX CLI")
    parser.add_argument("repo_path")
    parser.add_argument("--backend", choices=["ollama", "tfidf"], default="tfidf")
    args = parser.parse_args()

    print(f"[*] Ingesting repository: {args.repo_path}")
    embedder = OllamaEmbedder() if args.backend == "ollama" else TfidfEmbedder()
    llm = OllamaLLM() if args.backend == "ollama" else None

    try:
        result = ingest_repository(args.repo_path, embedder)
    except Exception as e:
        print(f"[!] Error ingesting repository: {e}")
        return 1

    print(f"[*] Indexed {result.num_files} files -> {result.num_chunks} chunks")
    print(f"[*] Dependency graph: {result.graph.number_of_nodes()} nodes, "
          f"{result.graph.number_of_edges()} edges")

    engine = QueryEngine(result.store, embedder, llm)

    print("\nIntelliCodeX ready. Ask a question about the repo, or type 'exit'.")
    print("Prefix with 'deps:' to do a dependency lookup, e.g. 'deps:pkg/db.py'\n")

    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in ("exit", "quit"):
            break

        if query.startswith("deps:"):
            target = query[len("deps:"):].strip()
            affected = files_likely_affected_by(result.graph, target)
            print(f"Files depending on {target}: {affected or '(none found)'}\n")
            continue

        response = engine.ask(query)
        print(f"\n--- Retrieved {len(response['retrieved_chunks'])} chunks ---")
        for c in response["retrieved_chunks"]:
            print(f"  {c['file']} :: {c['name']} (lines {c['lines']}, score={c['score']:.3f})")
        print(f"\n--- Answer ---\n{response['answer']}\n")


if __name__ == "__main__":
    sys.exit(main())
