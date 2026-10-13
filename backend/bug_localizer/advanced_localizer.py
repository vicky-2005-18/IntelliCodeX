"""
Facade and re-export for canonical AdvancedBugLocalizer from core.bug_localizer.
Eliminates code duplication and guarantees feature parity across all backend and core imports.
"""
from core.bug_localizer import (
    BugLocalizer,
    AdvancedBugLocalizer,
    StackTraceParser,
    StackFrame,
    ParsedStackTrace,
    CoverageRecord,
    calculate_ochiai_score,
    calculate_ochiai_spectrum,
)

__all__ = [
    "BugLocalizer",
    "AdvancedBugLocalizer",
    "StackTraceParser",
    "StackFrame",
    "ParsedStackTrace",
    "CoverageRecord",
    "calculate_ochiai_score",
    "calculate_ochiai_spectrum",
]
