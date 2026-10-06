"""
Patch Generator Package (Phase 1)
"""
from backend.patch_generator.patch_validator import validate_patch, compute_patch_quality_score
from backend.patch_generator.patch_applier import apply_patch_to_file, merge_snippet_into_file
from backend.patch_generator.llm_parser import extract_code_and_explanation

def __getattr__(name):
    if name in ("PatchEngine", "generate_git_diff", "PATCH_SYSTEM_PROMPT"):
        import core.patch_generator as cpg
        return getattr(cpg, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
