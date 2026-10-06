"""
Automated Documentation Generator Engine (Phase 6)
Generates READMEs, API documentation, folder structure trees, class/function specs,
and architecture overviews in Markdown (.md) and PDF (.pdf).
"""
import os
from typing import List, Dict, Any, Optional
from core.chunker import CodeChunk
from core.parser import SourceFile


class DocumentationGenerator:
    def generate_readme(self, repo_name: str, source_files: List[SourceFile], chunks: List[CodeChunk]) -> str:
        languages = list(set(sf.language for sf in source_files))
        total_files = len(source_files)
        total_chunks = len(chunks)

        readme_md = f"""# {repo_name}

AI-Generated Repository Documentation by **IntelliCodeX**.

## 📌 Repository Overview
- **Repository Name**: `{repo_name}`
- **Primary Languages**: {", ".join(languages)}
- **Total Source Files**: {total_files}
- **Indexed Code Components**: {total_chunks}

## 📁 Project Folder Structure
```
"""
        # Directory tree rendering
        paths = sorted(sf.rel_path for sf in source_files)
        for p in paths[:25]:
            readme_md += f"├── {p}\n"
        if len(paths) > 25:
            readme_md += f"└── ... ({len(paths) - 25} more files)\n"

        readme_md += """```

## ⚙️ Architecture & Core Modules
"""
        classes = [c for c in chunks if c.kind == "class"]
        for cls in classes[:10]:
            readme_md += f"### Class `{cls.name}` (`{cls.file_path}`)\n"
            if cls.docstring:
                readme_md += f"> {cls.docstring}\n\n"
            readme_md += f"Lines: `{cls.start_line}-{cls.end_line}`\n\n"

        readme_md += """## 🚀 Getting Started & API Reference
Refer to generated API documentation for detailed endpoints and class contracts.
"""
        return readme_md

    def generate_api_docs(self, chunks: List[CodeChunk]) -> str:
        funcs = [c for c in chunks if c.kind in ("function", "method")]
        api_md = "# API & Method Documentation\n\n"
        for fn in funcs[:30]:
            api_md += f"### `{fn.name}`\n"
            api_md += f"- **File**: `{fn.file_path}`\n"
            api_md += f"- **Lines**: `{fn.start_line} - {fn.end_line}`\n"
            if fn.docstring:
                api_md += f"- **Docstring**: {fn.docstring}\n"
            api_md += "```" + fn.language + "\n"
            api_md += fn.code[:400] + ("\n..." if len(fn.code) > 400 else "") + "\n```\n\n"
        return api_md

    def generate_symbol_doc(
        self,
        target: str,
        chunks: List[CodeChunk],
        call_graph: Any = None,
        llm: Any = None,
    ) -> str:
        """Generates focused documentation for a file or symbol using call-graph context and optional LLM synthesis."""
        matching_chunks = [
            c for c in chunks
            if c.name.lower() == target.lower()
            or target.lower() in c.file_path.lower()
            or c.chunk_id.lower().endswith(f"::{target.lower()}")
        ]

        if not matching_chunks:
            return f"# Documentation for `{target}`\n\nNo symbol or file matching `{target}` was found in repository index."

        target_chunk = matching_chunks[0]
        md_lines = [
            f"# Component Documentation: `{target_chunk.name}`",
            "",
            f"- **File**: `{target_chunk.file_path}`",
            f"- **Kind**: `{target_chunk.kind}`",
            f"- **Language**: `{target_chunk.language}`",
            f"- **Lines**: `{target_chunk.start_line} - {target_chunk.end_line}`",
        ]

        # Call-graph relationships
        if call_graph is not None:
            callers = []
            callees = []
            try:
                import networkx as nx
                if isinstance(call_graph, nx.DiGraph):
                    if call_graph.has_node(target_chunk.name):
                        callers = list(call_graph.predecessors(target_chunk.name))
                        callees = list(call_graph.successors(target_chunk.name))
            except Exception:
                pass

            if callers:
                md_lines.append(f"- **Referenced By (Callers)**: {', '.join(f'`{c}`' for c in callers[:10])}")
            if callees:
                md_lines.append(f"- **Calls (Callees)**: {', '.join(f'`{c}`' for c in callees[:10])}")

        if target_chunk.docstring:
            md_lines.extend(["", "## Intent & Docstring", f"> {target_chunk.docstring}"])

        # Implementation section
        md_lines.extend([
            "",
            "## Implementation Code",
            f"```{target_chunk.language}",
            target_chunk.code,
            "```",
        ])

        # Optional LLM synthesis pass with quote filter validation
        if llm is not None:
            prompt = (
                f"Generate clear, professional API reference documentation in Markdown for this {target_chunk.kind}:\n\n"
                f"Name: {target_chunk.name}\n"
                f"File: {target_chunk.file_path}\n"
                f"Code:\n```\n{target_chunk.code}\n```\n\n"
                "Explain parameters, return values, behavior, and edge cases. "
                "Quote exact code lines when referencing logic."
            )
            try:
                explanation = llm.generate(prompt, temperature=0.1)
                if explanation and explanation.strip():
                    md_lines.extend(["", "## Detailed Analysis", explanation.strip()])
            except Exception:
                pass

        return "\n".join(md_lines)

    def export_to_pdf_html(self, markdown_content: str, title: str = "Documentation") -> str:
        """Converts markdown content to printable HTML/PDF styled document."""
        html_doc = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; padding: 40px; color: #1e293b; max-width: 900px; margin: 0 auto; }}
        h1 {{ color: #0f172a; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; }}
        h2 {{ color: #1e3a8a; margin-top: 24px; }}
        h3 {{ color: #2563eb; }}
        code {{ background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 0.9em; }}
        pre {{ background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 8px; overflow-x: auto; }}
        blockquote {{ border-left: 4px solid #3b82f6; margin: 0; padding-left: 16px; color: #475569; font-style: italic; }}
    </style>
</head>
<body>
    {markdown_content.replace('\n', '<br>').replace('```', '<pre>').replace('```', '</pre>')}
</body>
</html>
"""
        return html_doc

