"""
Facade and re-export for canonical PatchEngine from core.patch_generator.
Eliminates code duplication while maintaining backwards compatibility with backend imports.
"""
import logging

logger = logging.getLogger(__name__)

def __getattr__(name):
    import core.patch_generator as cpg
    return getattr(cpg, name)

