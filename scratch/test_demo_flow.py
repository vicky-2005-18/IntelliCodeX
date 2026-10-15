import os
import sys

# Ensure project root is on sys.path
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from core.pipeline import ingest_repository
from core.embedder import OllamaEmbedder
from core.llm_client import OllamaLLM
from core.patch_generator import PatchEngine
from core.sandbox_runner import SandboxRunner
from core.persistence import get_repo_id

demo_repo = os.path.join(repo_root, "scratch", "demo_calculator_repo")
embedder = OllamaEmbedder(model="nomic-embed-text")
llm = OllamaLLM(model="qwen2.5-coder:3b", temperature=0.0)

print("[1] Ingesting repository...")
ingest_res = ingest_repository(demo_repo, embedder=embedder)

print("[2] Initializing SandboxRunner & PatchEngine...")
sb_runner = SandboxRunner(
    sandbox_mode="docker",
    docker_image="intellicodex-sandbox:latest",
    allow_local_sandbox=True,
    is_admin=True,
)

patch_engine = PatchEngine(
    store=ingest_res.store,
    embedder=embedder,
    llm=llm,
    graph=ingest_res.graph,
    repo_path=demo_repo,
    sandbox_runner=sb_runner,
    is_admin=True,
    allow_local_sandbox=True,
    experience_bank=None, # Isolated demo storage
)

def on_progress(turn, max_turns, msg):
    print(f"[*] Progress [{turn}/{max_turns}]: {msg}")

error_report = """
FAILED tests/test_calculator.py::test_subtract_reproducing_bug - AssertionError: assert 14 == 6
where 14 = subtract(10, 4)
"""

print("[3] Generating patch with live Ollama & Docker sandbox verification...")
patch_rec = patch_engine.generate_patch(
    repo_id=get_repo_id(demo_repo),
    error_report=error_report,
    target_file="calculator.py",
    verify_in_sandbox=True,
    max_iterations=3,
    progress_callback=on_progress,
)

print("\n--- Patch Result ---")
print("Status:", patch_rec.get("status"))
print("Target file:", patch_rec.get("target_file"))
print("Confidence score:", patch_rec.get("confidence_score"))
print("Sandbox Validation:", patch_rec.get("sandbox_validation"))
print("Explanation:", patch_rec.get("explanation"))
print("Diff:\n", patch_rec.get("git_diff"))
