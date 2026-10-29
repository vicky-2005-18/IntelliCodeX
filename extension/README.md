# IntelliCodeX — VS Code & Cursor IDE Extension

Bring **IntelliCodeX AI Repository Intelligence & Autonomous Code Repair** directly into your developer editor (VS Code, Cursor, VSCodium, Antigravity IDE).

---

## 🚀 Key Features

* **💬 Grounded Q&A & Codebase Search**:
  Ask complex architectural questions and get quote-grounded answers with exact file and line citations powered by hybrid BM25 lexical + FAISS dense vector retrieval.
* **🔒 Real-Time Security & Secret Audit**:
  Run static Bandit AST vulnerability scans and regex credential detection across your active files or entire workspace with 1-click navigation to findings.
* **🏛️ Architectural Cycle & Bottleneck Detector**:
  Inspect circular import cycles, calculate Robert C. Martin coupling metrics ($C_a, C_e, I$), and view incoming/outgoing symbol call hierarchies.
* **🛠️ Autonomous Repair & Patch Review Gate**:
  Synthesize context-aware bug fixes with pre-validated Tree-sitter AST syntax and review side-by-side git diffs before applying to disk.
* **⚡ Activity Bar Sidebar & Editor Context Menus**:
  Right-click any selected code to explain, fix, inspect callers, or scan security without leaving the editor.

---

## 📦 Getting Started

### 1. Requirements
* Node.js v18+
* Python 3.10+ with IntelliCodeX dependencies installed (`pip install -r requirements.txt`)

### 2. Running in Development Mode
1. Open this workspace in **VS Code** or **Cursor**.
2. Press `F5` to open the **Extension Development Host**.
3. Click the **IntelliCodeX mascot shield icon** in the left Activity Bar to open the assistant sidebar.

### 3. Packaging into `.vsix`
To distribute and install in any editor:
```bash
npx @vscode/vsce package
code --install-extension intellicodex-vscode-1.0.0.vsix
```

---

## ⚙️ Extension Settings

| Setting | Default | Description |
| :--- | :--- | :--- |
| `intellicodex.pythonPath` | `"python"` | Python interpreter path. |
| `intellicodex.backend` | `"tfidf"` | Embedding backend (`"tfidf"` for offline, `"ollama"` for neural). |
| `intellicodex.model` | `"qwen2.5-coder:3b"` | Local Ollama LLM model name. |
| `intellicodex.autoStartServer` | `true` | Automatically spawn the background MCP stdio server on workspace load. |

---

## ⌨️ Contributed Commands

* `IntelliCodeX: Ask Question About Codebase` (`intellicodex.ask`)
* `IntelliCodeX: Explain Selected Code / Symbol` (`intellicodex.explain`)
* `IntelliCodeX: Autonomous Bug Fix on Selected Symbol` (`intellicodex.fix`)
* `IntelliCodeX: Scan Active File for Vulnerabilities & Secrets` (`intellicodex.scanSecurity`)
* `IntelliCodeX: Audit Workspace Dependency Cycles & Coupling` (`intellicodex.auditArchitecture`)
* `IntelliCodeX: Inspect Callers & Callees for Symbol` (`intellicodex.getCallHierarchy`)
* `IntelliCodeX: Launch Interactive CLI Terminal Session` (`intellicodex.openTerminal`)
* `IntelliCodeX: Restart MCP Server Process` (`intellicodex.restartServer`)
