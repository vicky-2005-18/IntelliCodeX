"""
Model Context Protocol (MCP) Server for IntelliCodeX.
Provides a standardized JSON-RPC 2.0 stdio server compliant with the MCP specification (2024-11-05).
Exposes IntelliCodeX's code search, bug localization, call graph navigation, patch generation,
security scanning, architecture analysis, and organizational memory as tools to modern AI IDEs
(Cursor, Claude Desktop, Antigravity, VS Code Roo Code/Continue).
"""

import sys
import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

# Ensure repository root is in sys.path
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Direct all standard logger output to stderr to prevent stdout JSON-RPC corruption
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[IntelliCodeX-MCP] %(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("intellicodex_mcp")

# Core IntelliCodeX imports
from core.pipeline import ingest_repository, IngestedRepository
from core.embedder import TfidfEmbedder, OllamaEmbedder
from core.llm_client import OllamaLLM
from rag.query_engine import QueryEngine
from core.call_graph import find_callers_of_symbol, get_top_central_symbols
from core.dependency_graph import files_likely_affected_by, get_top_central_files
from core.bug_localizer import BugLocalizer
from core.patch_generator import PatchEngine
from core.security_scanner import run_security_scan
from core.architecture_optimizer import ArchitectureOptimizer
from core.org_memory import OrgMemoryStore, OrgMemoryItem
from core.persistence import get_repo_id

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "intellicodex"
SERVER_VERSION = "1.0.0"

# Tool definitions according to MCP specification
AVAILABLE_TOOLS = [
    {
        "name": "search_codebase",
        "description": "Perform hybrid BM25 lexical and FAISS dense vector search with graph context expansion over the indexed codebase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question, symbol name, or keywords to search for in the codebase."
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of code chunks to retrieve (default: 5).",
                    "default": 5
                },
                "file_filter": {
                    "type": "string",
                    "description": "Optional substring to filter results by file path."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "explain_code",
        "description": "Generate an in-depth, quote-grounded technical explanation of a function, class, or architectural component in the codebase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Specific question about what a component does or how it works."
                },
                "file_filter": {
                    "type": "string",
                    "description": "Optional file path to focus context retrieval on."
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "locate_bug",
        "description": "Analyze an error message, exception, or stack trace using Spectrum-Based Fault Localization (Ochiai SBFL) to rank suspicious files and functions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "error_message": {
                    "type": "string",
                    "description": "Error description or exception message."
                },
                "stack_trace": {
                    "type": "string",
                    "description": "Optional multi-line stack trace or error log."
                }
            },
            "required": ["error_message"]
        }
    },
    {
        "name": "get_call_hierarchy",
        "description": "Inspect caller and callee relationships for a code symbol, including PageRank centrality.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Name of the function or method symbol."
                },
                "direction": {
                    "type": "string",
                    "description": "Relationship direction: 'callers' (who calls this), 'callees' (who this calls), or 'both'.",
                    "enum": ["callers", "callees", "both"],
                    "default": "both"
                }
            },
            "required": ["symbol_name"]
        }
    },
    {
        "name": "generate_patch",
        "description": "Synthesize a context-aware bug fix or code modification, validated with AST syntax verification and unified git diff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_description": {
                    "type": "string",
                    "description": "Description of the bug, defective behavior, or desired change."
                },
                "target_file": {
                    "type": "string",
                    "description": "Repository-relative path of the file to fix."
                },
                "error_details": {
                    "type": "string",
                    "description": "Optional stack trace, test assertion failure, or error log."
                }
            },
            "required": ["issue_description", "target_file"]
        }
    },
    {
        "name": "scan_security",
        "description": "Run static AST vulnerability detection (Bandit) and hardcoded secret scanning with synthetic credential redaction.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_file": {
                    "type": "string",
                    "description": "Optional specific file to scan. If omitted, scans the entire repository."
                },
                "severity_threshold": {
                    "type": "string",
                    "description": "Minimum severity to report: 'HIGH', 'MEDIUM', or 'LOW'.",
                    "enum": ["HIGH", "MEDIUM", "LOW"],
                    "default": "HIGH"
                }
            }
        }
    },
    {
        "name": "analyze_architecture",
        "description": "Evaluate codebase architecture for circular dependency cycles, high-coupling bottleneck modules, and maintainability metrics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "threshold_lines": {
                    "type": "integer",
                    "description": "Line length threshold for flagging overly complex components (default: 80).",
                    "default": 80
                }
            }
        }
    },
    {
        "name": "query_org_memory",
        "description": "Search organizational memory for historical architectural decisions (ADRs), git rationale, and verified repair records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about past decisions, rationale, or known bug fixes."
                },
                "category": {
                    "type": "string",
                    "description": "Filter by record category: 'decision', 'repair', 'summary', 'commit', 'adr', or empty for all.",
                    "enum": ["decision", "repair", "summary", "commit", "adr", ""]
                }
            },
            "required": ["query"]
        }
    }
]


class IntelliCodeXMcpServer:
    """Implements standard MCP protocol methods and dispatches to IntelliCodeX core engines."""

    def __init__(self, repo_path: str = "sample_repo", backend: str = "tfidf"):
        self.repo_path = os.path.abspath(repo_path)
        self.backend_choice = backend
        self.ingested: Optional[IngestedRepository] = None
        self.embedder = None
        self.llm = None
        self.query_engine: Optional[QueryEngine] = None
        self.bug_localizer: Optional[BugLocalizer] = None
        self.patch_engine: Optional[PatchEngine] = None
        self.arch_optimizer: Optional[ArchitectureOptimizer] = None
        self.org_memory_store: Optional[OrgMemoryStore] = None
        self.initialized = False

    def initialize_engines(self):
        """Initializes embedder, vector store, graphs, and engines."""
        if self.initialized:
            return

        logger.info(f"Ingesting repository: {self.repo_path} (Backend: {self.backend_choice})")
        if self.backend_choice == "ollama":
            self.embedder = OllamaEmbedder()
            self.llm = OllamaLLM()
        else:
            self.embedder = TfidfEmbedder()
            self.llm = None  # Offline / rule-based fallback

        self.ingested = ingest_repository(self.repo_path, embedder=self.embedder)

        self.query_engine = QueryEngine(
            store=self.ingested.store,
            embedder=self.embedder,
            llm=self.llm,
            dep_graph=self.ingested.graph,
            call_graph=self.ingested.call_graph,
            lexical_index=self.ingested.lexical_index,
            repo_path=self.repo_path,
        )

        self.bug_localizer = BugLocalizer(
            store=self.ingested.store,
            embedder=self.embedder,
            graph=self.ingested.graph,
        )

        self.patch_engine = PatchEngine(
            store=self.ingested.store,
            embedder=self.embedder,
            llm=self.llm,
            graph=self.ingested.graph,
            repo_path=self.repo_path,
        )

        self.arch_optimizer = ArchitectureOptimizer()

        repo_id = get_repo_id(self.repo_path)
        self.org_memory_store = OrgMemoryStore(
            embedder=self.embedder,
            org_id="default_org",
            repo_id=repo_id,
        )
        try:
            self.org_memory_store.ingest_repository(self.repo_path, max_commits=30)
        except Exception as exc:
            logger.warning(f"Org memory ingestion notice: {exc}")

        self.initialized = True
        logger.info(f"Engines successfully initialized. {self.ingested.num_files} files, {self.ingested.num_chunks} chunks indexed.")

    # -------------------------------------------------------------------------
    # Tool Execution Handlers
    # -------------------------------------------------------------------------

    def tool_search_codebase(self, query: str, top_k: int = 5, file_filter: str = "") -> str:
        self.initialize_engines()
        hits = self.query_engine.retrieve(
            query=query,
            top_k=top_k,
            file_filter=file_filter or None,
        )

        if not hits:
            return f"No matching code chunks found for query: '{query}'"

        lines = [f"Found {len(hits)} matching code chunk(s) for query: '{query}'\n"]
        for idx, item in enumerate(hits, 1):
            chunk = item[0]
            score = item[1]
            reason = "Hybrid/Dense Match"
            lines.append(f"### [{idx}] {chunk.file_path} (Lines {chunk.start_line}-{chunk.end_line}) | Score: {score} | {reason}")
            if chunk.name:
                lines.append(f"**Symbol**: `{chunk.name}`")
            lines.append("```python")
            # Show first 15 lines of chunk
            code_lines = chunk.code.splitlines()
            preview = "\n".join(code_lines[:15])
            if len(code_lines) > 15:
                preview += f"\n... [{len(code_lines) - 15} more lines]"
            lines.append(preview)
            lines.append("```\n")

        return "\n".join(lines)

    def tool_explain_code(self, question: str, file_filter: str = "") -> str:
        self.initialize_engines()
        res = self.query_engine.query(
            question,
            file_filter=file_filter or None,
        )
        if isinstance(res, dict):
            answer = res.get("answer", "")
            trace = res.get("trace", None)
            output = [f"## Code Explanation\n\n{answer}"]
            if trace and hasattr(trace, "sources") and trace.sources:
                output.append("\n### Sources Consulted:")
                for s in trace.sources[:5]:
                    output.append(f"- `{s.file_path}` lines {s.start_line}-{s.end_line} ({s.symbol_name})")
            return "\n".join(output)
        return str(res)

    def tool_locate_bug(self, error_message: str, stack_trace: str = "") -> str:
        self.initialize_engines()
        error_report = f"{error_message}\n{stack_trace}".strip()
        report = self.bug_localizer.localize(error_report=error_report)
        lines = [f"## Fault Localization Report (Ochiai SBFL)\n"]
        lines.append(f"**Error Diagnosed**: `{error_message}`\n")

        candidates = report.get("candidates", [])
        if candidates:
            lines.append("### Ranked Suspicious Locations:")
            for cand in candidates[:5]:
                f_path = cand.get("file_path", "unknown")
                score = cand.get("confidence_score", 0.0)
                sym = cand.get("symbol") or cand.get("name", "")
                sym_str = f" in `{sym}`" if sym else ""
                lines.append(f"- `{f_path}`{sym_str} (Suspiciousness: {score:.3f})")
            lines.append("")

        root_cause = report.get("root_cause_explanation", "")
        if root_cause:
            lines.append(f"### Root Cause Analysis:\n{root_cause}\n")

        rec = report.get("recommended_focus")
        if rec:
            lines.append(f"**Recommended Focus**: `{rec.get('file_path')}`")

        return "\n".join(lines)

    def tool_get_call_hierarchy(self, symbol_name: str, direction: str = "both") -> str:
        self.initialize_engines()
        lines = [f"## Call Hierarchy for Symbol: `{symbol_name}`\n"]

        call_graph = self.ingested.call_graph
        if not call_graph:
            return f"No call graph available for this repository."

        if direction in ("callers", "both"):
            callers = find_callers_of_symbol(call_graph, symbol_name)
            lines.append(f"### Inbound Callers ({len(callers)}):")
            if callers:
                for c in callers[:10]:
                    lines.append(f"- `{c}`")
            else:
                lines.append("- *(No inbound callers detected in static call graph)*")
            lines.append("")

        if direction in ("callees", "both"):
            callees = []
            if symbol_name in call_graph:
                callees = list(call_graph.successors(symbol_name))
            else:
                # Search for matching node by symbol suffix
                for node in call_graph.nodes:
                    if node == symbol_name or str(node).endswith(f"::{symbol_name}"):
                        callees.extend(list(call_graph.successors(node)))
            callees = list(dict.fromkeys(callees))
            lines.append(f"### Outbound Callees ({len(callees)}):")
            if callees:
                for callee in callees[:10]:
                    lines.append(f"- `{callee}`")
            else:
                lines.append("- *(No outbound callees detected)*")
            lines.append("")

        return "\n".join(lines)

    def tool_generate_patch(self, issue_description: str, target_file: str, error_details: str = "") -> str:
        self.initialize_engines()
        norm_target = target_file.replace("\\", "/")
        full_target_path = os.path.join(self.repo_path, norm_target)
        if not os.path.exists(full_target_path):
            return f"Error: Target file '{target_file}' does not exist in repository root '{self.repo_path}'."

        repo_id = get_repo_id(self.repo_path)
        error_report = f"{issue_description}\n{error_details}".strip()

        result = self.patch_engine.generate_patch(
            repo_id=repo_id,
            error_report=error_report,
            target_file=norm_target,
        )

        lines = [f"## Proposed Code Patch for `{norm_target}`\n"]
        status = result.get("status", "pending")
        diff = result.get("git_diff", "") or ""
        explanation = result.get("explanation", "") or "Context-aware patch generated."
        validation = result.get("validation", {})
        syntax_valid = validation.get("is_valid", True) if isinstance(validation, dict) else True

        lines.append(f"**Patch ID**: `{result.get('patch_id', 'unknown')}`")
        lines.append(f"**Status**: `{status}`")
        lines.append(f"**AST Syntax Valid**: {syntax_valid}")
        lines.append(f"\n### Explanation:\n{explanation}\n")

        if diff:
            lines.append("### Unified Git Diff:\n```diff")
            lines.append(diff)
            lines.append("```\n")
        else:
            lines.append("*(No code diff produced)*")

        return "\n".join(lines)

    def tool_scan_security(self, target_file: str = "", severity_threshold: str = "HIGH") -> str:
        self.initialize_engines()
        scan_target = os.path.join(self.repo_path, target_file) if target_file else self.repo_path
        res = run_security_scan(
            target_path=scan_target,
            repo_root=self.repo_path,
            severity_threshold=severity_threshold.upper(),
        )

        lines = [f"## Security Vulnerability & Secret Scan Report\n"]
        lines.append(f"**Target**: `{scan_target}`")
        lines.append(f"**Policy Outcome**: {'PASSED' if res.get('passed') else 'FAILED'}")
        lines.append(f"**Severity Threshold**: `{severity_threshold.upper()}`\n")

        findings = res.get("findings", [])
        lines.append(f"### Total Findings: {len(findings)}\n")
        if not findings:
            lines.append("Clean scan: Zero security vulnerabilities or secrets found matching threshold.")
        else:
            for idx, f in enumerate(findings[:10], 1):
                rule = f.get("rule_id", "VULN")
                sev = f.get("severity", "HIGH")
                f_path = f.get("file", "")
                f_line = f.get("line", "")
                desc = f.get("text") or f.get("explanation", "")
                remed = f.get("remediation", "")
                lines.append(f"[{idx}] **[{sev}] {rule}** at `{f_path}:{f_line}`")
                lines.append(f"    - **Finding**: {desc}")
                if remed:
                    lines.append(f"    - **Remediation**: {remed}")
            if len(findings) > 10:
                lines.append(f"\n... and {len(findings) - 10} more findings.")

        return "\n".join(lines)

    def tool_analyze_architecture(self, threshold_lines: int = 80) -> str:
        self.initialize_engines()
        self.arch_optimizer.complexity_lines_threshold = threshold_lines
        report = self.arch_optimizer.analyze(
            dep_graph=self.ingested.graph,
            source_files=self.ingested.files,
        )

        lines = [f"## Architecture & Dependency Optimization Report\n"]
        cycles = getattr(report, "cycles", []) or []
        lines.append(f"### Circular Dependency Cycles: {len(cycles)}")
        if cycles:
            for idx, cycle in enumerate(cycles[:5], 1):
                cycle_str = " -> ".join(cycle)
                lines.append(f"- Cycle {idx}: `{cycle_str}`")
        else:
            lines.append("- No circular dependency cycles detected.")
        lines.append("")

        bottlenecks = getattr(report, "bottlenecks", []) or []
        lines.append(f"### High-Coupling Bottlenecks: {len(bottlenecks)}")
        if bottlenecks:
            for b in bottlenecks[:5]:
                m_name = getattr(b, "module", str(b))
                ca = getattr(b, "afferent_coupling", 0)
                ce = getattr(b, "efferent_coupling", 0)
                inst = getattr(b, "instability", 0.0)
                lines.append(f"- `{m_name}`: Ca={ca} (dependents), Ce={ce} (dependencies), Instability={inst:.2f}")
        else:
            lines.append("- No high-coupling bottleneck modules detected.")
        lines.append("")

        recs = getattr(report, "recommendations", []) or []
        lines.append(f"### Actionable Grounded Recommendations: {len(recs)}")
        for idx, rec in enumerate(recs[:3], 1):
            f_type = getattr(rec, "finding_type", "Finding")
            target = getattr(rec, "target", "")
            prop = getattr(rec, "proposed_improvement", "")
            lines.append(f"[{idx}] **{f_type}** (`{target}`):\n    {prop}")

        return "\n".join(lines)

    def tool_query_org_memory(self, query: str, category: str = "") -> str:
        self.initialize_engines()
        results = self.org_memory_store.search(
            query=query,
            top_k=5,
            memory_type_filter=category or None,
        )

        lines = [f"## Organizational Memory Query Results for '{query}'\n"]
        if not results:
            lines.append("No historical decisions, ADRs, or repair experiences match this query.")
            return "\n".join(lines)

        for idx, (item, score) in enumerate(results, 1):
            m_type = item.memory_type.upper()
            status = item.verification_status
            lines.append(f"### [{idx}] [{m_type}] {item.title} (Relevance: {score:.3f})")
            lines.append(f"**Author**: {item.author} | **Date**: {item.date_str} | **Status**: `{status}`")
            if item.source_references:
                lines.append(f"**References**: {', '.join(item.source_references)}")
            lines.append(f"\n{item.content[:350]}\n")

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # JSON-RPC Protocol Dispatcher
    # -------------------------------------------------------------------------

    def dispatch(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        # Handle notifications (no id)
        if req_id is None:
            if method == "notifications/initialized":
                logger.info("Client sent notifications/initialized handshake.")
            return None

        # Standard MCP Methods
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION
                    }
                }
            }

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": AVAILABLE_TOOLS
                }
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            try:
                if tool_name == "search_codebase":
                    text = self.tool_search_codebase(
                        query=args.get("query", ""),
                        top_k=args.get("top_k", 5),
                        file_filter=args.get("file_filter", ""),
                    )
                elif tool_name == "explain_code":
                    text = self.tool_explain_code(
                        question=args.get("question", ""),
                        file_filter=args.get("file_filter", ""),
                    )
                elif tool_name == "locate_bug":
                    text = self.tool_locate_bug(
                        error_message=args.get("error_message", ""),
                        stack_trace=args.get("stack_trace", ""),
                    )
                elif tool_name == "get_call_hierarchy":
                    text = self.tool_get_call_hierarchy(
                        symbol_name=args.get("symbol_name", ""),
                        direction=args.get("direction", "both"),
                    )
                elif tool_name == "generate_patch":
                    text = self.tool_generate_patch(
                        issue_description=args.get("issue_description", ""),
                        target_file=args.get("target_file", ""),
                        error_details=args.get("error_details", ""),
                    )
                elif tool_name == "scan_security":
                    text = self.tool_scan_security(
                        target_file=args.get("target_file", ""),
                        severity_threshold=args.get("severity_threshold", "HIGH"),
                    )
                elif tool_name == "analyze_architecture":
                    text = self.tool_analyze_architecture(
                        threshold_lines=args.get("threshold_lines", 80),
                    )
                elif tool_name == "query_org_memory":
                    text = self.tool_query_org_memory(
                        query=args.get("query", ""),
                        category=args.get("category", ""),
                    )
                else:
                    return {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool '{tool_name}' not found."
                        }
                    }

                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": text
                            }
                        ]
                    }
                }
            except Exception as e:
                logger.exception(f"Error executing tool '{tool_name}': {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing tool '{tool_name}': {str(e)}"
                            }
                        ]
                    }
                }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not implemented."
                }
            }


def run_stdio_server(repo_path: str = "sample_repo", backend: str = "tfidf"):
    """Runs the main stdio loop for JSON-RPC 2.0 communication."""
    server = IntelliCodeXMcpServer(repo_path=repo_path, backend=backend)
    logger.info("IntelliCodeX MCP Server started on stdio.")

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break

            line_strip = line.strip()
            if not line_strip:
                continue

            # Support Content-Length header framing if client sends it
            if line_strip.lower().startswith("content-length:"):
                parts = line_strip.split(":", 1)
                length = int(parts[1].strip())
                # Read until blank line
                while True:
                    hdr = sys.stdin.readline().strip()
                    if not hdr:
                        break
                payload = sys.stdin.read(length)
            else:
                payload = line_strip

            try:
                request = json.loads(payload)
            except Exception as parse_err:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {str(parse_err)}"
                    }
                }
                out = json.dumps(response)
                sys.stdout.write(out + "\n")
                sys.stdout.flush()
                continue

            resp = server.dispatch(request)
            if resp is not None:
                out = json.dumps(resp)
                sys.stdout.write(out + "\n")
                sys.stdout.flush()

        except KeyboardInterrupt:
            logger.info("MCP server received KeyboardInterrupt, exiting.")
            break
        except Exception as e:
            logger.exception(f"Fatal error in stdio server loop: {e}")
            break


def generate_ide_config_snippets(repo_path: str = ".") -> Dict[str, Any]:
    """Generates ready-to-copy MCP JSON configs for popular IDEs."""
    abs_repo = os.path.abspath(repo_path)
    python_exe = sys.executable

    return {
        "claude_desktop_config.json": {
            "mcpServers": {
                "intellicodex": {
                    "command": python_exe,
                    "args": ["-m", "core.mcp_server", "--repo", abs_repo]
                }
            }
        },
        "cursor_mcp.json": {
            "mcpServers": {
                "intellicodex": {
                    "command": python_exe,
                    "args": ["-m", "core.mcp_server", "--repo", abs_repo]
                }
            }
        },
        "gemini_antigravity_mcp_config.json": {
            "mcpServers": {
                "intellicodex": {
                    "command": python_exe,
                    "args": ["-m", "core.mcp_server", "--repo", abs_repo]
                }
            }
        }
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="IntelliCodeX Model Context Protocol (MCP) Server")
    parser.add_argument("--repo", default="sample_repo", help="Target repository path to index and analyze")
    parser.add_argument("--backend", default="tfidf", choices=["tfidf", "ollama"], help="Embedding backend (default: tfidf)")
    parser.add_argument("--config", action="store_true", help="Print sample IDE configuration JSON and exit")
    args = parser.parse_args()

    if args.config:
        configs = generate_ide_config_snippets(args.repo)
        print(json.dumps(configs, indent=2))
        sys.exit(0)

    run_stdio_server(repo_path=args.repo, backend=args.backend)
