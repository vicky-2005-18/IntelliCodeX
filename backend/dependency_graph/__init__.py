"""
Enhanced Dependency Graph Package
"""
from backend.dependency_graph.enhanced_graph import (
    EnhancedDependencyGraph,
    SUPPORTED_RELATIONSHIPS,
    UNSUPPORTED_RELATIONSHIPS,
)
from core.architecture_optimizer import (
    ArchitectureOptimizer,
    ArchitectureReport,
    ModuleCoupling,
    RefactoringRecommendation,
)

__all__ = [
    "EnhancedDependencyGraph",
    "SUPPORTED_RELATIONSHIPS",
    "UNSUPPORTED_RELATIONSHIPS",
    "ArchitectureOptimizer",
    "ArchitectureReport",
    "ModuleCoupling",
    "RefactoringRecommendation",
]
