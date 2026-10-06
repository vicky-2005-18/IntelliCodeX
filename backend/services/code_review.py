"""
Code Review Assistant & Commit Message Generator (Phases 14 & 15)
Performs automated static quality scans (bugs, code smells, complexity, security issues)
and generates concise, descriptive Git commit messages from diffs.
"""
import re
from typing import List, Dict, Any, Optional
from core.llm_client import OllamaLLM


class CodeReviewAssistant:
    def __init__(self, llm: Optional[OllamaLLM] = None):
        self.llm = llm

    def analyze_file(self, code_content: str, file_path: str = "code.py") -> Dict[str, Any]:
        """Scans source code for potential bugs, smells, complexity, naming & security issues."""
        issues = []
        lines = code_content.splitlines()

        for idx, line in enumerate(lines, 1):
            # Security scan
            if re.search(r'\b(eval\(|exec\(|os\.system\(|subprocess\.Popen\(.*shell=True|password\s*=\s*["\'][^"\']+["\'])\b', line):
                issues.append({
                    "line": idx,
                    "category": "security",
                    "severity": "high",
                    "message": "Potential hardcoded credential or dangerous shell execution identified.",
                })

            # Code Smell / Naming issue
            if re.search(r'def\s+[A-Z]\w*', line) and file_path.endswith(".py"):
                issues.append({
                    "line": idx,
                    "category": "naming",
                    "severity": "low",
                    "message": "Python function names should follow snake_case naming conventions.",
                })

            # High Complexity / Nested blocks
            if line.startswith("                ") and any(k in line for k in ("if ", "for ", "while ")):
                issues.append({
                    "line": idx,
                    "category": "complexity",
                    "severity": "medium",
                    "message": "Deeply nested conditional block (cyclomatic complexity warning).",
                })

            # Performance issue
            if re.search(r'\b(time\.sleep|while\s+True:)\b', line):
                issues.append({
                    "line": idx,
                    "category": "performance",
                    "severity": "medium",
                    "message": "Unbounded loop or blocking sleep detected.",
                })

        suggestions = [
            "Consider extracting nested logic into decoupled helper functions.",
            "Ensure input validation and parameter checks are enforced on public methods.",
            "Verify all external system calls handle timeout and connection error exceptions."
        ]

        return {
            "file_path": file_path,
            "total_lines": len(lines),
            "issues_found": len(issues),
            "issues": issues,
            "suggestions": suggestions,
            "quality_rating": "A" if len(issues) == 0 else "B" if len(issues) < 3 else "C",
        }

    def generate_commit_message(self, git_diff: str) -> str:
        """Generates AI commit message from git diff."""
        if not git_diff.strip():
            return "Chore: routine code cleanup and maintenance updates."

        if self.llm:
            try:
                prompt = (
                    f"Given the following git diff, generate a concise, professional standard "
                    f"conventional commit message (1-2 sentences):\n\n```diff\n{git_diff[:2000]}\n```\n"
                )
                msg = self.llm.generate(prompt)
                return msg.strip('"\n ')
            except Exception:
                pass

        # Fallback commit message generator
        if "auth" in git_diff.lower() or "login" in git_diff.lower():
            return "feat(auth): fix authentication and improve JWT validation"
        elif "fix" in git_diff.lower() or "bug" in git_diff.lower() or "error" in git_diff.lower():
            return "fix: resolve bug and handle boundary null check exceptions"
        elif "test" in git_diff.lower():
            return "test: expand unit test coverage across backend modules"
        else:
            return "refactor: optimize core module logic and update dependency structures"
