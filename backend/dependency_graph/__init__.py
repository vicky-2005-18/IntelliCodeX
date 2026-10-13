"""
Enhanced Dependency Graph Package
"""
from backend.dependency_graph.enhanced_graph import EnhancedDependencyGraph
from core.architecture_optimizer import (
    ArchitectureOptimizer,
    ArchitectureReport,
    ModuleCoupling,
    RefactoringRecommendation,
)

__all__ = [
    "EnhancedDependencyGraph",
    "ArchitectureOptimizer",
    "ArchitectureReport",
    "ModuleCoupling",
    "RefactoringRecommendation",
]
