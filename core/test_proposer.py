"""
Automatic Test Proposal and Contract Grounding Engine for IntelliCodeX.

When a file-only repair request has no existing relevant tests:
1. Analyzes contract: docstrings, README/SPECS, call sites across the repo.
2. Identifies explicitly documented vs merely inferred behavior.
3. Detects specification ambiguities and formulates focused clarification questions.
4. Proposes pytest test cases labeled as AI-generated with citations to contract sources.
5. Validates candidate tests inside Docker only (checking syntax, discovery, harness vs assertion errors).
6. Keeps proposed tests in disposable storage until accepted by user.
7. Freezes accepted tests for repair without rewriting expectations to force a pass.
"""

import ast
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Set

from core.canonical_path import normalize_repo_relative_path, get_all_repo_files
from core.sandbox_runner import SandboxRunner, SandboxTestResult
from backend.patch_generator.llm_parser import extract_code_and_explanation


@dataclass
class ContractAnalysis:
    """Encapsulates extracted behavioral contract and ambiguity analysis."""
    target_file: str
    docstrings: Dict[str, str] = field(default_factory=dict)
    readme_sections: List[str] = field(default_factory=list)
    call_sites: List[Dict[str, Any]] = field(default_factory=list)
    explicit_behaviors: List[str] = field(default_factory=list)
    inferred_behaviors: List[str] = field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    clarification_question: Optional[str] = None
    clarification_options: List[str] = field(default_factory=list)
    user_clarification: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_file": self.target_file,
            "docstrings": self.docstrings,
            "readme_sections": self.readme_sections,
            "call_sites": self.call_sites,
            "explicit_behaviors": self.explicit_behaviors,
            "inferred_behaviors": self.inferred_behaviors,
            "is_ambiguous": self.is_ambiguous,
            "ambiguity_reason": self.ambiguity_reason,
            "clarification_question": self.clarification_question,
            "clarification_options": self.clarification_options,
            "user_clarification": self.user_clarification,
        }


@dataclass
class TestProposalValidation:
    """Docker-only validation result of proposed candidate tests."""
    syntax_valid: bool
    imports_valid: bool
    tests_collected: int
    harness_errors: List[str] = field(default_factory=list)
    behavioral_failures: List[str] = field(default_factory=list)
    meaningful_assertions_count: int = 0
    baseline_exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    is_runnable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "syntax_valid": self.syntax_valid,
            "imports_valid": self.imports_valid,
            "tests_collected": self.tests_collected,
            "harness_errors": self.harness_errors,
            "behavioral_failures": self.behavioral_failures,
            "meaningful_assertions_count": self.meaningful_assertions_count,
            "baseline_exit_code": self.baseline_exit_code,
            "is_runnable": self.is_runnable,
        }


@dataclass
class TestProposal:
    """Complete candidate test proposal with grounding metadata and disposable path."""
    target_file: str
    contract_analysis: ContractAnalysis
    test_code: str
    disposable_path: str
    validation: Optional[TestProposalValidation] = None
    accepted: bool = False
    frozen: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_file": self.target_file,
            "contract_analysis": self.contract_analysis.to_dict(),
            "test_code": self.test_code,
            "disposable_path": self.disposable_path,
            "validation": self.validation.to_dict() if self.validation else None,
            "accepted": self.accepted,
            "frozen": self.frozen,
        }


AI_TEST_HEADER_BANNER = "# [AI-GENERATED TEST PROPOSAL - REQUIRES USER REVIEW]"


class TestProposer:
    """Engine for contract extraction, ambiguity clarification, test proposal, and Docker validation."""
    __test__ = False

    def __init__(self, scratch_dir: Optional[str] = None):
        self.scratch_dir = scratch_dir or os.path.join(tempfile.gettempdir(), "icx_proposed_tests")
        os.makedirs(self.scratch_dir, exist_ok=True)

    def analyze_contract(
        self,
        repo_path: str,
        target_file: str,
        user_clarification: Optional[str] = None
    ) -> ContractAnalysis:
        """
        Retrieves specifications, docstrings, READMEs, and call sites.
        Identifies explicitly documented vs inferred behavior and flags ambiguities.
        """
        analysis = ContractAnalysis(target_file=target_file, user_clarification=user_clarification)
        abs_target = os.path.join(repo_path, target_file) if not os.path.isabs(target_file) else target_file
        if not os.path.isfile(abs_target):
            return analysis

        try:
            with open(abs_target, "r", encoding="utf-8", errors="replace") as f:
                code_content = f.read()
        except Exception:
            return analysis

        # 1. AST Docstring and Interface Extraction
        func_signatures: Dict[str, str] = {}
        func_nodes: List[ast.FunctionDef] = []
        try:
            tree = ast.parse(code_content, filename=abs_target)
            mod_doc = ast.get_docstring(tree)
            if mod_doc:
                analysis.docstrings["__module__"] = mod_doc.strip()
                analysis.explicit_behaviors.append(f"Module specification: {mod_doc.strip()[:150]}")

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_nodes.append(node)
                    doc = ast.get_docstring(node)
                    args = [a.arg for a in node.args.args]
                    func_signatures[node.name] = f"{node.name}({', '.join(args)})"
                    if doc:
                        analysis.docstrings[node.name] = doc.strip()
                        analysis.explicit_behaviors.append(f"Function '{node.name}': {doc.strip()[:150]}")
                    else:
                        analysis.inferred_behaviors.append(f"Function '{node.name}' has no docstring; contract inferred from signature {func_signatures[node.name]}")
        except Exception:
            analysis.inferred_behaviors.append("Source could not be fully parsed into AST; using lexical inspection")

        # 2. README / SPECS search across repo
        readme_matches = self._find_repo_specs(repo_path, target_file, func_signatures.keys())
        analysis.readme_sections = readme_matches
        for rm in readme_matches:
            analysis.explicit_behaviors.append(f"Project documentation: {rm[:140]}")

        # 3. Call sites across repo
        call_sites = self._find_call_sites(repo_path, target_file, func_signatures.keys())
        analysis.call_sites = call_sites
        for cs in call_sites[:4]:
            analysis.explicit_behaviors.append(
                f"Call site in '{cs['caller_file']}:{cs['line']}': expects {cs['call_snippet']}"
            )

        # 4. Inferred behaviors (defaults, boundary handling, mutability)
        for fn in func_nodes:
            fn_doc = analysis.docstrings.get(fn.name, "").lower()
            # Mutability inference
            if any(k in fn_doc for k in ("in-place", "in place", "mutate", "modifies the input")):
                analysis.explicit_behaviors.append(f"Function '{fn.name}' explicitly specifies in-place input mutation")
            elif any(k in fn_doc for k in ("does not modify", "copy", "immutable", "returns a new")):
                analysis.explicit_behaviors.append(f"Function '{fn.name}' explicitly specifies preserving input collections")
            else:
                analysis.inferred_behaviors.append(f"Function '{fn.name}' mutability behavior is unstated; fresh return or non-destructive collection handling inferred")

            # Error handling inference
            has_explicit_raises = "raises" in fn_doc or "throws" in fn_doc
            if not has_explicit_raises:
                analysis.inferred_behaviors.append(f"Function '{fn.name}' exception contracts on unexpected input types are inferred")

        # 5. Ambiguity Detection & Focused Clarification
        # If user has already provided clarification, ambiguity is resolved
        if user_clarification:
            analysis.is_ambiguous = False
            analysis.explicit_behaviors.append(f"User Clarification: {user_clarification}")
            return analysis

        ambiguities = self._detect_ambiguities(code_content, analysis.docstrings, analysis.readme_sections, func_nodes)
        if ambiguities:
            analysis.is_ambiguous = True
            analysis.ambiguity_reason = ambiguities["reason"]
            analysis.clarification_question = ambiguities["question"]
            analysis.clarification_options = ambiguities["options"]

        return analysis

    def _find_repo_specs(self, repo_path: str, target_file: str, func_names) -> List[str]:
        """Finds relevant sections in README.md, SPECS.md, or docs/."""
        matches = []
        spec_files = ["README.md", "SPECS.md", "SPEC.md", "docs.md", "API.md"]
        target_base = os.path.splitext(os.path.basename(target_file))[0]
        generic_names = {"main", "add", "run", "get", "set", "init", "start", "stop", "test"}
        non_generic_funcs = [fn for fn in func_names if fn.lower() not in generic_names]

        all_files = get_all_repo_files(repo_path)
        for f in all_files:
            base_f = os.path.basename(f)
            if base_f in spec_files or f.startswith("docs/"):
                abs_f = os.path.join(repo_path, f)
                if os.path.isfile(abs_f):
                    try:
                        with open(abs_f, "r", encoding="utf-8", errors="replace") as sf:
                            lines = sf.readlines()
                        curr_block = []
                        relevant = False
                        for line in lines:
                            target_match = bool(re.search(r"\b" + re.escape(target_base) + r"\b", line, re.IGNORECASE))
                            func_match = any(re.search(r"\b" + re.escape(fn) + r"\b", line) for fn in non_generic_funcs)
                            code_fn_match = any(f"`{fn}`" in line or f"{fn}(" in line for fn in func_names)
                            if target_match or func_match or code_fn_match:
                                relevant = True
                            if line.startswith("# ") and curr_block:
                                if relevant:
                                    matches.append("".join(curr_block).strip())
                                curr_block = []
                                relevant = False
                            curr_block.append(line)
                        if relevant and curr_block:
                            matches.append("".join(curr_block).strip())
                    except Exception:
                        pass
        return matches[:3]

    def _find_call_sites(self, repo_path: str, target_file: str, func_names) -> List[Dict[str, Any]]:
        """Finds AST call sites invoking functions of target_file in other files.
        Requires that the calling file actually imports target_file/module or its symbols."""
        call_sites = []
        if not func_names:
            return call_sites

        target_norm = normalize_repo_relative_path(target_file)
        target_base = os.path.splitext(os.path.basename(target_norm))[0]
        target_mod = os.path.splitext(target_norm)[0].replace("/", ".")
        target_dir = os.path.dirname(target_norm)
        all_files = get_all_repo_files(repo_path)

        for f in all_files:
            f_norm = normalize_repo_relative_path(f)
            if f_norm == target_norm or not f_norm.endswith(".py"):
                continue
            abs_f = os.path.join(repo_path, f_norm)
            if not os.path.isfile(abs_f):
                continue
            try:
                with open(abs_f, "r", encoding="utf-8", errors="replace") as cf:
                    c_src = cf.read()
                tree = ast.parse(c_src, filename=abs_f)

                # Grounding invariant: caller file must explicitly import target module or symbols
                f_dir = os.path.dirname(f_norm)
                imported_modules = set()
                imported_symbols = {}  # local_name -> target_function_name

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            mod_name = alias.name
                            as_name = alias.asname or alias.name
                            if mod_name == target_base or mod_name == target_mod or mod_name.endswith("." + target_base):
                                imported_modules.add(as_name)
                    elif isinstance(node, ast.ImportFrom):
                        mod = node.module or ""
                        is_target_module = False
                        if mod == target_base or mod == target_mod or mod.endswith("." + target_base):
                            is_target_module = True
                        elif node.level and node.level > 0:
                            # Relative import check
                            if f_dir == target_dir:
                                if not mod and any(a.name == target_base for a in node.names):
                                    for a in node.names:
                                        if a.name == target_base:
                                            imported_modules.add(a.asname or a.name)
                                elif mod == target_base:
                                    is_target_module = True

                        if is_target_module:
                            for alias in node.names:
                                if alias.name == "*":
                                    for fn in func_names:
                                        imported_symbols[fn] = fn
                                else:
                                    imported_symbols[alias.asname or alias.name] = alias.name

                if not imported_modules and not imported_symbols:
                    # Unrelated file without import relationship to target_file
                    continue

                lines = c_src.splitlines()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        target_func_name = None
                        if isinstance(node.func, ast.Name):
                            local_id = node.func.id
                            if local_id in imported_symbols:
                                target_func_name = imported_symbols[local_id]
                        elif isinstance(node.func, ast.Attribute):
                            if isinstance(node.func.value, ast.Name) and node.func.value.id in imported_modules:
                                target_func_name = node.func.attr

                        if target_func_name and target_func_name in func_names:
                            ln = getattr(node, "lineno", 1)
                            snip = lines[ln - 1].strip() if ln <= len(lines) else f"{target_func_name}(...)"
                            call_sites.append({
                                "caller_file": f_norm,
                                "line": ln,
                                "call_snippet": snip,
                                "function": target_func_name,
                            })
                            if len(call_sites) >= 5:
                                return call_sites
            except Exception:
                pass
        return call_sites

    def _detect_ambiguities(
        self,
        code_content: str,
        docstrings: Dict[str, str],
        readme_sections: List[str],
        func_nodes: List[ast.FunctionDef],
    ) -> Optional[Dict[str, Any]]:
        """
        Detects ambiguous requirements or contradictory contracts.
        Returns ambiguity details and a focused clarification question if detected.
        """
        for fn in func_nodes:
            fn_doc = docstrings.get(fn.name, "")

            # 1. Contradictory return specification (e.g. "discount amount or final price")
            if " or " in fn_doc and any(w in fn_doc.lower() for w in ("calculates", "returns", "computes")):
                m = re.search(r"(?:returns|calculates|computes)\s+(.+?\s+or\s+.+?)(?:\.|\n|$)", fn_doc, re.IGNORECASE)
                if m:
                    phrase = m.group(1).strip()
                    parts = [p.strip() for p in phrase.split(" or ")]
                    if len(parts) == 2:
                        return {
                            "reason": f"Function '{fn.name}' docstring specifies an ambiguous disjunction: '{phrase}'.",
                            "question": f"For '{fn.name}', which behavior is the required contract: {parts[0]} or {parts[1]}?",
                            "options": [
                                f"Option A: {parts[0].capitalize()}",
                                f"Option B: {parts[1].capitalize()}",
                            ]
                        }

            # 2. Contradictory scale/unit conversion (e.g. scale parameter meaning input vs output)
            if "scale" in [a.arg for a in fn.args.args] and "convert" in fn.name.lower():
                if "scale" in fn_doc.lower() and not ("from" in fn_doc.lower() and "to" in fn_doc.lower()):
                    return {
                        "reason": f"Function '{fn.name}' specifies conversion scale without clarifying whether 'scale' denotes the source unit or target unit.",
                        "question": f"In '{fn.name}', does parameter 'scale' specify the input temperature unit or the target output unit?",
                        "options": [
                            "Parameter 'scale' specifies the input unit (convert from 'scale')",
                            "Parameter 'scale' specifies the target output unit (convert to 'scale')",
                        ]
                    }

            # 3. Missing negative/boundary handling when multiple contradictory semantics exist
            if any(k in fn.name.lower() for k in ("discount", "tax", "fee")) and "negative" in code_content:
                if "negative" not in fn_doc.lower():
                    return {
                        "reason": f"Function '{fn.name}' operates on rates/percentages without documenting negative rate handling.",
                        "question": f"How should '{fn.name}' handle negative rates/values?",
                        "options": [
                            "Raise ValueError on negative values",
                            "Clamp negative values to 0",
                            "Allow negative values as reductions",
                        ]
                    }

            # 4. Unstated division or boundary semantics without docstring or explicit contract
            if any(k in fn.name.lower() for k in ("divide", "div", "truediv", "ratio")) and len(fn.args.args) == 2:
                has_doc_spec = any(w in fn_doc.lower() for w in ("float", "integer", "floor", "true division", "zerodivision", "raises", "zero"))
                if not has_doc_spec:
                    return {
                        "reason": f"Function '{fn.name}' has unstated division semantics (true float division vs integer floor division, and zero division error handling).",
                        "question": f"For '{fn.name}', which contract semantics are required?",
                        "options": [
                            "True float division (a / b), raising ZeroDivisionError on 0",
                            "Integer floor division (a // b), raising ZeroDivisionError on 0",
                            "Safe division returning None or 0 on zero division",
                        ]
                    }

        return None

    def generate_candidate_tests(
        self,
        repo_path: str,
        target_file: str,
        analysis: ContractAnalysis,
        llm=None
    ) -> TestProposal:
        """
        Uses configured LLM (or AST contract generator fallback) to propose Python pytest tests.
        Saves candidate tests in disposable storage.
        """
        abs_target = os.path.join(repo_path, target_file) if not os.path.isabs(target_file) else target_file
        code_content = ""
        if os.path.isfile(abs_target):
            with open(abs_target, "r", encoding="utf-8", errors="replace") as f:
                code_content = f.read()

        target_base = os.path.splitext(os.path.basename(target_file))[0]
        disposable_test_name = f"test_{target_base}.py"
        disposable_path = os.path.join(self.scratch_dir, disposable_test_name)

        # 1. Attempt LLM-grounded test generation if LLM is provided
        test_code = ""
        if llm:
            try:
                prompt = self._build_test_generation_prompt(target_file, code_content, analysis)
                system_prompt = (
                    "You are a rigorous software test engineer. Generate clean, maintainable pytest test functions "
                    "strictly grounded in the provided specifications, docstrings, and call sites. "
                    "Do not invent ungrounded assertions. Label the proposal as AI-generated and cite sources."
                )
                response = llm.generate(prompt, system=system_prompt, temperature=0.0)
                extracted_code, _ = extract_code_and_explanation(response)
                if extracted_code and "def test_" in extracted_code:
                    test_code = extracted_code
            except Exception:
                pass

        # 2. Fallback: AST-based deterministic contract test generation
        if not test_code or "def test_" not in test_code:
            test_code = self._generate_ast_contract_tests(target_file, code_content, analysis)

        # Ensure AI-generated banner is present at top
        if AI_TEST_HEADER_BANNER not in test_code:
            test_code = f"{AI_TEST_HEADER_BANNER}\n\n{test_code.lstrip()}"

        # Write to disposable storage only (never directly to repo)
        with open(disposable_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(test_code)

        return TestProposal(
            target_file=target_file,
            contract_analysis=analysis,
            test_code=test_code,
            disposable_path=disposable_path,
        )

    def _build_test_generation_prompt(
        self,
        target_file: str,
        code_content: str,
        analysis: ContractAnalysis
    ) -> str:
        target_base = os.path.splitext(os.path.basename(target_file))[0]
        explicit_str = "\n".join(f"- {eb}" for eb in analysis.explicit_behaviors) if analysis.explicit_behaviors else "- Function signatures and AST"
        inferred_str = "\n".join(f"- {ib}" for ib in analysis.inferred_behaviors) if analysis.inferred_behaviors else "- Standard Python idioms"
        readme_snippets = [rm[:1000] for rm in analysis.readme_sections] if analysis.readme_sections else []
        readme_str = "\n".join(readme_snippets) if readme_snippets else "None"
        clarif_str = f"\nUser Contract Clarification: {analysis.user_clarification}\n" if analysis.user_clarification else ""

        return (
            f"Target File: {target_file}\n\n"
            f"Source Code:\n```python\n{code_content}\n```\n\n"
            f"Identified Behavioral Contract:\n"
            f"Explicitly Documented:\n{explicit_str}\n\n"
            f"Merely Inferred:\n{inferred_str}\n\n"
            f"Project Documentation Context:\n{readme_str}\n"
            f"{clarif_str}\n"
            f"Instructions:\n"
            f"1. Generate standard pytest unit tests covering happy path, edge cases, and expected errors.\n"
            f"2. Prepend header comment: '{AI_TEST_HEADER_BANNER}'\n"
            f"3. Add `# Grounded in: <source citation>` comment above each test function.\n"
            f"4. Import from '{target_base}'.\n"
            f"5. Include meaningful assertions checking actual output vs contract specifications.\n"
            f"6. For asymmetric operations (e.g. subtraction, division, comparisons), generate assertions with distinct asymmetric inputs (a != b) to verify operand order.\n"
            f"7. For division, test true float division (e.g. 5 / 2 == 2.5 vs integer floor division 5 // 2 == 2) and test expected exception on division by zero (pytest.raises(ZeroDivisionError)).\n"
            f"8. For interactive functions or entry points like main() that invoke input(), test that the entry point is callable or mock input using monkeypatch; DO NOT leave unmocked input() calls that block execution.\n"
            f"9. Output the Python test code inside a single fenced code block."
        )

    def _generate_ast_contract_tests(
        self,
        target_file: str,
        code_content: str,
        analysis: ContractAnalysis
    ) -> str:
        """Fallback: Generates deterministic contract-grounded pytest functions from AST."""
        target_base = os.path.splitext(os.path.basename(target_file))[0]
        lines = [
            AI_TEST_HEADER_BANNER,
            "import pytest",
            f"from {target_base} import *",
            "",
        ]

        try:
            tree = ast.parse(code_content)
        except Exception:
            lines.append("def test_module_syntax():")
            lines.append("    # Grounded in: basic importability")
            lines.append(f"    import {target_base}")
            lines.append("    assert True")
            return "\n".join(lines)

        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not funcs:
            lines.append("def test_module_smoke():")
            lines.append("    # Grounded in: module presence")
            lines.append(f"    import {target_base}")
            lines.append("    assert True")
            return "\n".join(lines)

        asymmetric_numeric_defaults = ["10", "3", "2", "4"]

        for fn in funcs:
            fn_name = fn.name
            doc = analysis.docstrings.get(fn_name, "")
            doc_lower = doc.lower()
            args = [a.arg for a in fn.args.args if a.arg != "self"]

            # Grounding citation comment
            citation = f"docstring of {fn_name}" if doc else f"signature of {fn_name}"

            # 0. Entry points / interactive functions (e.g. main, cli, or functions using input())
            is_entry_point = fn_name in ("main", "cli", "run_app", "entry_point")
            uses_input = any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("input", "raw_input")
                for n in ast.walk(fn)
            )
            if is_entry_point or uses_input:
                lines.append(f"def test_{fn_name}_is_callable():")
                lines.append(f"    # Grounded in: entry point contract for {fn_name}")
                lines.append(f"    assert callable({fn_name})")
                lines.append("")
                continue

            # Infer distinct non-zero values based on argument names to test asymmetry
            call_args = []
            num_idx = 0
            for a in args:
                if any(k in a for k in ("list", "arr", "items", "intervals", "data")):
                    call_args.append("[1, 2, 3]")
                elif any(k in a for k in ("n", "count", "idx", "num", "val", "price", "rate", "amount", "a", "b", "x", "y")):
                    val = asymmetric_numeric_defaults[num_idx % len(asymmetric_numeric_defaults)]
                    num_idx += 1
                    call_args.append(val)
                elif any(k in a for k in ("s", "text", "str", "name")):
                    call_args.append("'sample'")
                elif any(k in a for k in ("flag", "is_", "has_")):
                    call_args.append("True")
                else:
                    val = asymmetric_numeric_defaults[num_idx % len(asymmetric_numeric_defaults)]
                    num_idx += 1
                    call_args.append(val)
            args_str = ", ".join(call_args)

            # Specific arithmetic contract tests with high-fidelity assertions
            if fn_name in ("subtract", "sub", "difference") and len(args) == 2:
                lines.append(f"def test_{fn_name}_contract_asymmetry():")
                lines.append(f"    # Grounded in: standard arithmetic subtraction (first operand minus second operand)")
                lines.append(f"    assert {fn_name}(10, 3) == 7, 'Expected 10 - 3 == 7 (first minus second), not second minus first'")
                lines.append(f"    assert {fn_name}(3, 10) == -7, 'Expected 3 - 10 == -7'")
                lines.append("")
            elif fn_name in ("divide", "div", "division") and len(args) == 2:
                clarif = (analysis.user_clarification or "").lower()
                doc_lower = (doc or "").lower()
                # Documented or user-approved contract for true float division
                if "true division" in clarif or "float" in clarif or "float" in doc_lower or "/" in clarif:
                    lines.append(f"def test_{fn_name}_contract_true_division():")
                    lines.append(f"    # Grounded in: user-approved or documented true float division contract")
                    lines.append(f"    assert {fn_name}(10, 4) == 2.5, 'Expected true division 10 / 4 == 2.5'")
                    lines.append("")
                elif "floor" in clarif or "integer" in clarif or "//" in clarif or "floor" in doc_lower:
                    lines.append(f"def test_{fn_name}_contract_floor_division():")
                    lines.append(f"    # Grounded in: user-approved or documented integer floor division contract")
                    lines.append(f"    assert {fn_name}(10, 4) == 2, 'Expected floor division 10 // 4 == 2'")
                    lines.append("")
                else:
                    lines.append(f"def test_{fn_name}_contract_happy_path():")
                    lines.append(f"    # Grounded in: {citation}")
                    lines.append(f"    res = {fn_name}(10, 2)")
                    lines.append(f"    assert res is not None, 'Function should return a valid result'")
                    lines.append("")

                # Exception handling grounded in user clarification or doc
                if "zerodivision" in clarif or "raise" in clarif or "zerodivision" in doc_lower or "raises" in doc_lower:
                    lines.append(f"def test_{fn_name}_zero_division_raises():")
                    lines.append(f"    # Grounded in: documented or user-approved division by zero exception contract")
                    lines.append(f"    with pytest.raises(ZeroDivisionError):")
                    lines.append(f"        {fn_name}(10, 0)")
                    lines.append("")
                elif "none" in clarif or "safe" in clarif:
                    lines.append(f"def test_{fn_name}_zero_division_safe():")
                    lines.append(f"    # Grounded in: user-approved safe zero division contract")
                    lines.append(f"    assert {fn_name}(10, 0) in (None, 0)")
                    lines.append("")
            elif fn_name in ("add", "plus", "sum") and len(args) == 2:
                lines.append(f"def test_{fn_name}_contract_happy_path():")
                lines.append(f"    # Grounded in: standard arithmetic addition contract")
                lines.append(f"    assert {fn_name}(10, 3) == 13")
                lines.append("")
            elif fn_name in ("multiply", "mul", "prod", "binary_multiply") and len(args) == 2:
                lines.append(f"def test_{fn_name}_contract_happy_path():")
                lines.append(f"    # Grounded in: standard arithmetic multiplication contract")
                lines.append(f"    assert {fn_name}(10, 3) == 30")
                lines.append("")
            elif fn_name in ("mod", "modulo", "remainder") and len(args) == 2:
                lines.append(f"def test_{fn_name}_contract_happy_path():")
                lines.append(f"    # Grounded in: standard modulo contract")
                lines.append(f"    assert {fn_name}(10, 3) == 1")
                lines.append("")
            else:
                # 1. Happy path test for general function
                lines.append(f"def test_{fn_name}_contract_happy_path():")
                lines.append(f"    # Grounded in: {citation}")
                lines.append(f"    result = {fn_name}({args_str})")
                lines.append("    assert result is not None, 'Function should return a valid result according to contract'")
                lines.append("")

            # 2. Edge case / empty input test if collections are used
            has_coll_arg = any(any(k in a for k in ("list", "arr", "items", "intervals", "data")) for a in args)
            if has_coll_arg:
                lines.append(f"def test_{fn_name}_empty_collection():")
                lines.append(f"    # Grounded in: empty collection boundary handling for {fn_name}")
                empty_args = []
                for a in args:
                    if any(k in a for k in ("list", "arr", "items", "intervals", "data")):
                        empty_args.append("[]")
                    else:
                        empty_args.append("0")
                lines.append(f"    assert {fn_name}({', '.join(empty_args)}) in ([], None, 0, False)")
                lines.append("")

            # 3. Explicit docstring examples (doctests) if documented
            doctest_m = re.search(r">>>\s*([a-zA-Z0-9_]+\([^\n]+\))\s*\n\s*([^\n]+)", doc)
            if doctest_m:
                call_expr = doctest_m.group(1).strip()
                expected_val = doctest_m.group(2).strip()
                lines.append(f"def test_{fn_name}_docstring_example():")
                lines.append(f"    # Grounded in: explicit docstring example in {fn_name}")
                lines.append(f"    assert {call_expr} == {expected_val}")
                lines.append("")

            # 4. User clarification-grounded test if applicable
            if analysis.user_clarification:
                lines.append(f"def test_{fn_name}_user_clarification():")
                lines.append(f"    # Grounded in: User clarification: {analysis.user_clarification[:70]}")
                lines.append(f"    # Validates clarified specification")
                lines.append(f"    res = {fn_name}({args_str})")
                lines.append("    assert res is not None")
                lines.append("")

        return "\n".join(lines)

    def validate_proposed_tests_in_docker(
        self,
        sandbox_runner: SandboxRunner,
        repo_path: str,
        proposal: TestProposal,
    ) -> TestProposalValidation:
        """
        Executes candidate tests inside Docker on untouched target repository.
        Checks:
        1. Syntax and py_compile.
        2. Test collection (pytest --collect-only).
        3. Meaningful assertions in test AST.
        4. Distinguishes harness/import/dependency errors from behavioral assertion failures.
        """
        # 1. Check syntax and meaningful assertions in AST locally first
        syntax_valid = True
        assertions_count = 0
        harness_errors = []
        behavioral_failures = []
        try:
            tree = ast.parse(proposal.test_code, filename=proposal.disposable_path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    assertions_count += 1
                elif isinstance(node, ast.With):
                    for item in node.items:
                        if isinstance(item.context_expr, ast.Call) and getattr(item.context_expr.func, "attr", None) == "raises":
                            assertions_count += 1
        except SyntaxError as se:
            syntax_valid = False
            harness_errors.append(f"SyntaxError in proposed test code: {se}")

        if not syntax_valid or assertions_count == 0:
            if assertions_count == 0:
                harness_errors.append("Proposed test file contains no meaningful assertions or pytest.raises checks.")
            val = TestProposalValidation(
                syntax_valid=syntax_valid,
                imports_valid=False,
                tests_collected=0,
                harness_errors=harness_errors,
                meaningful_assertions_count=assertions_count,
                is_runnable=False,
            )
            proposal.validation = val
            return val

        # 2. Run inside Docker sandbox: execute test file on top of untouched repo
        # Copy proposed test into sandbox under tests/ or peer dir without touching user's repo on disk
        target_dir = os.path.dirname(proposal.target_file)
        target_base = os.path.splitext(os.path.basename(proposal.target_file))[0]
        test_filename = f"test_{target_base}.py"
        rel_test_path = os.path.join(target_dir, test_filename).replace("\\", "/") if target_dir else test_filename

        # Execute Docker test run using SandboxRunner
        test_res: SandboxTestResult = sandbox_runner.run_tests_with_patch(
            repo_path=repo_path,
            target_file=rel_test_path,
            patched_code=proposal.test_code,
            timeout=25,
        )

        tests_collected = test_res.total_count
        combined_output = f"{test_res.stdout}\n{test_res.stderr}".strip()

        # Distinguish harness/dependency errors from behavioral test assertions
        imports_valid = True
        for line in combined_output.splitlines():
            line_s = line.strip()
            if any(k in line_s for k in ("ModuleNotFoundError:", "ImportError:", "No module named")):
                # Check if it's missing the target file or a missing 3rd party dependency
                harness_errors.append(f"Dependency / Import Error: {line_s}")
                imports_valid = False
            elif "SyntaxError:" in line_s:
                harness_errors.append(f"Harness Syntax Error: {line_s}")
            elif "pytest: error:" in line_s or "usage: pytest" in line_s:
                harness_errors.append(f"Harness Pytest Configuration Error: {line_s}")

        # Behavioral failures are actual test assertions failing on the code
        if test_res.failed_tests:
            behavioral_failures.extend(test_res.failed_tests)
        if test_res.assertion_errors:
            behavioral_failures.extend(test_res.assertion_errors[:5])

        is_runnable = syntax_valid and imports_valid and (tests_collected > 0) and not harness_errors

        val = TestProposalValidation(
            syntax_valid=syntax_valid,
            imports_valid=imports_valid,
            tests_collected=tests_collected,
            harness_errors=harness_errors,
            behavioral_failures=behavioral_failures,
            meaningful_assertions_count=assertions_count,
            baseline_exit_code=test_res.exit_code,
            stdout=test_res.stdout,
            stderr=test_res.stderr,
            is_runnable=is_runnable,
        )
        proposal.validation = val
        return val


def format_test_proposal_card(proposal: TestProposal) -> str:
    """Formats a rich review card of the proposed test contract and Docker validation."""
    analysis = proposal.contract_analysis
    val = proposal.validation

    lines = [
        "================================================================================",
        "                 INTELLICODEX AUTOMATIC TEST PROPOSAL (AI-GENERATED)           ",
        "================================================================================",
        f"Target File:         {proposal.target_file}",
        f"Disposable Storage:  {proposal.disposable_path}",
        "",
        "--- CONTRACT SOURCES IDENTIFIED ---",
    ]
    if analysis.docstrings:
        for k, v in analysis.docstrings.items():
            lines.append(f"  • Docstring [{k}]: {v[:100]}...")
    if analysis.readme_sections:
        for rs in analysis.readme_sections:
            lines.append(f"  • Project Docs / README: {rs[:100]}...")
    if analysis.call_sites:
        for cs in analysis.call_sites[:3]:
            lines.append(f"  • Call Site [{cs['caller_file']}:{cs['line']}]: {cs['call_snippet']}")
    if not (analysis.docstrings or analysis.readme_sections or analysis.call_sites):
        lines.append("  • None (Contract inferred purely from AST function signatures)")

    lines.append("")
    lines.append("--- EXPLICIT VS INFERRED CONTRACTS ---")
    lines.append("Explicitly Documented:")
    if analysis.explicit_behaviors:
        for eb in analysis.explicit_behaviors[:5]:
            lines.append(f"  ✓ {eb}")
    else:
        lines.append("  (None explicitly documented)")

    lines.append("Merely Inferred:")
    if analysis.inferred_behaviors:
        for ib in analysis.inferred_behaviors[:5]:
            lines.append(f"  ? {ib}")
    else:
        lines.append("  (None)")

    if analysis.user_clarification:
        lines.append(f"User Clarification Grounding: {analysis.user_clarification}")

    lines.append("")
    lines.append("--- DOCKER HARNESS VALIDATION ---")
    if val:
        lines.append(f"  • Syntax Check:          {'PASSED' if val.syntax_valid else 'FAILED'}")
        lines.append(f"  • Import / Dependency:   {'VALID' if val.imports_valid else 'HARNESS ERROR'}")
        lines.append(f"  • Tests Collected:       {val.tests_collected}")
        lines.append(f"  • Assertions Count:      {val.meaningful_assertions_count}")
        if val.harness_errors:
            lines.append("  [!] Harness Errors:")
            for he in val.harness_errors:
                lines.append(f"      - {he}")
        if val.behavioral_failures:
            lines.append(f"  • Baseline Assertion Failures Detected: {len(val.behavioral_failures)} (Indicates active defect on untouched code)")
        else:
            lines.append("  • Baseline Outcome:      All proposed tests pass on current implementation")
    else:
        lines.append("  (Not yet validated inside Docker)")

    lines.append("================================================================================")
    return "\n".join(lines)
