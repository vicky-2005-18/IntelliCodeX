/**
 * IntelliCodeX VS Code / Cursor Extension Entry Point
 * Activates the sidebar, context menu commands, and MCP background bridge.
 */

const vscode = require('vscode');
const path = require('path');
const { McpClient } = require('./mcpClient');
const { IntelliCodeXSidebarProvider } = require('./sidebarProvider');

let mcpClient = null;
let outputChannel = null;
let statusBarItem = null;

function activate(context) {
  outputChannel = vscode.window.createOutputChannel('IntelliCodeX');
  outputChannel.appendLine('[IntelliCodeX] Extension initializing...');

  const config = vscode.workspace.getConfiguration('intellicodex');
  const pythonPath = config.get('pythonPath') || 'python';
  const backend = config.get('backend') || 'tfidf';
  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();

  // Initialize MCP client
  mcpClient = new McpClient({
    pythonPath,
    repoPath: workspaceRoot,
    backend,
    logger: {
      log: (msg) => outputChannel.appendLine(`[LOG] ${msg}`),
      warn: (msg) => outputChannel.appendLine(`[WARN] ${msg}`),
      error: (msg) => outputChannel.appendLine(`[ERROR] ${msg}`)
    },
    onStatusChange: (status, details) => {
      updateStatusBar(status);
    }
  });

  // Setup Status Bar Item
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = 'intellicodex.openTerminal';
  statusBarItem.text = '$(sync~spin) IntelliCodeX: Starting...';
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  if (config.get('autoStartServer', true)) {
    mcpClient.start().catch((err) => {
      outputChannel.appendLine(`[ERROR] Failed to start MCP client: ${err.message}`);
      updateStatusBar('error');
    });
  }

  // Register Sidebar Webview Provider
  const sidebarProvider = new IntelliCodeXSidebarProvider(context.extensionUri, mcpClient);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider('intellicodex.sidebarView', sidebarProvider)
  );

  // Command: Ask Question
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.ask', async () => {
      const q = await vscode.window.showInputBox({
        prompt: 'Ask IntelliCodeX a question about this repository',
        placeHolder: 'e.g. How does vector retrieval work?'
      });
      if (!q) return;

      vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'IntelliCodeX: Searching & Reasoning...',
        cancellable: false
      }, async () => {
        try {
          const res = await mcpClient.callTool('explain_code', { question: q });
          showMarkdownPanel('IntelliCodeX Answer', res);
        } catch (err) {
          vscode.window.showErrorMessage(`IntelliCodeX Error: ${err.message}`);
        }
      });
    })
  );

  // Command: Explain Selected Symbol / Code
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.explain', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;

      const selection = editor.selection;
      const selectedText = editor.document.getText(selection).trim();
      const relPath = vscode.workspace.asRelativePath(editor.document.uri);

      const prompt = selectedText 
        ? `Explain this code from ${relPath}:\n\`\`\`\n${selectedText}\n\`\`\``
        : `Explain the purpose and architecture of ${relPath}`;

      vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `IntelliCodeX: Explaining ${selectedText ? 'selection' : relPath}...`,
        cancellable: false
      }, async () => {
        try {
          const res = await mcpClient.callTool('explain_code', { question: prompt, file_filter: relPath });
          showMarkdownPanel(`Explanation: ${path.basename(relPath)}`, res);
        } catch (err) {
          vscode.window.showErrorMessage(`IntelliCodeX Error: ${err.message}`);
        }
      });
    })
  );

  // Command: Autonomous Bug Fix on Active File
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.fix', async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;

      const relPath = vscode.workspace.asRelativePath(editor.document.uri);
      const desc = await vscode.window.showInputBox({
        prompt: `Describe the issue to repair in '${relPath}'`,
        placeHolder: 'e.g. Fix off-by-one boundary error in loop'
      });
      if (!desc) return;

      vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `IntelliCodeX: Synthesizing & Verifying Repair for ${path.basename(relPath)}...`,
        cancellable: false
      }, async () => {
        try {
          const res = await mcpClient.callTool('generate_patch', {
            target_file: relPath,
            issue_description: desc
          });
          showMarkdownPanel(`Patch Proposal: ${path.basename(relPath)}`, res);
        } catch (err) {
          vscode.window.showErrorMessage(`IntelliCodeX Repair Error: ${err.message}`);
        }
      });
    })
  );

  // Command: Scan Active File for Security Vulnerabilities
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.scanSecurity', async (uri) => {
      const targetUri = uri || vscode.window.activeTextEditor?.document.uri;
      const relPath = targetUri ? vscode.workspace.asRelativePath(targetUri) : '';

      vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `IntelliCodeX: Scanning ${relPath || 'workspace'} for security vulnerabilities...`,
        cancellable: false
      }, async () => {
        try {
          const res = await mcpClient.callTool('scan_security', {
            target_file: relPath,
            severity_threshold: 'LOW'
          });
          showMarkdownPanel(`Security Audit: ${relPath || 'Workspace'}`, res);
        } catch (err) {
          vscode.window.showErrorMessage(`Security Scan Error: ${err.message}`);
        }
      });
    })
  );

  // Command: Audit Architecture Cycles & Coupling
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.auditArchitecture', async () => {
      vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: 'IntelliCodeX: Analyzing dependency cycles & module bottlenecks...',
        cancellable: false
      }, async () => {
        try {
          const res = await mcpClient.callTool('analyze_architecture', { threshold_lines: 80 });
          showMarkdownPanel('Architecture Optimization Report', res);
        } catch (err) {
          vscode.window.showErrorMessage(`Architecture Audit Error: ${err.message}`);
        }
      });
    })
  );

  // Command: Inspect Call Hierarchy
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.getCallHierarchy', async () => {
      const editor = vscode.window.activeTextEditor;
      let symbol = editor ? editor.document.getText(editor.selection).trim() : '';
      if (!symbol) {
        symbol = await vscode.window.showInputBox({
          prompt: 'Enter function or class symbol name to inspect',
          placeHolder: 'e.g. ingest_repository'
        });
      }
      if (!symbol) return;

      vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: `IntelliCodeX: Resolving call hierarchy for '${symbol}'...`,
        cancellable: false
      }, async () => {
        try {
          const res = await mcpClient.callTool('get_call_hierarchy', {
            symbol_name: symbol,
            direction: 'both'
          });
          showMarkdownPanel(`Call Hierarchy: ${symbol}`, res);
        } catch (err) {
          vscode.window.showErrorMessage(`Call Hierarchy Error: ${err.message}`);
        }
      });
    })
  );

  // Command: Launch CLI Terminal Session
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.openTerminal', () => {
      const term = vscode.window.createTerminal({
        name: 'IntelliCodeX CLI',
        cwd: workspaceRoot
      });
      term.show();
      term.sendText(`${pythonPath} cli.py .`);
    })
  );

  // Command: Restart MCP Server
  context.subscriptions.push(
    vscode.commands.registerCommand('intellicodex.restartServer', async () => {
      if (mcpClient) {
        mcpClient.stop();
        updateStatusBar('starting');
        try {
          await mcpClient.start();
          vscode.window.showInformationMessage('[IntelliCodeX] MCP Server restarted successfully.');
        } catch (err) {
          vscode.window.showErrorMessage(`[IntelliCodeX] Restart failed: ${err.message}`);
        }
      }
    })
  );
}

function updateStatusBar(status) {
  if (!statusBarItem) return;
  if (status === 'connected') {
    statusBarItem.text = '$(shield-check) IntelliCodeX: Active';
    statusBarItem.tooltip = 'IntelliCodeX MCP Server is connected and ready.';
  } else if (status === 'error') {
    statusBarItem.text = '$(alert) IntelliCodeX: Error';
    statusBarItem.tooltip = 'IntelliCodeX MCP Server encountered an error. Click to open terminal.';
  } else {
    statusBarItem.text = '$(sync~spin) IntelliCodeX: Connecting...';
    statusBarItem.tooltip = 'Connecting to IntelliCodeX MCP stdio server...';
  }
}

function showMarkdownPanel(title, content) {
  const panel = vscode.window.createWebviewPanel(
    'intellicodexResult',
    title,
    vscode.ViewColumn.Beside,
    { enableScripts: true }
  );

  panel.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>${title}</title>
  <style>
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background-color: var(--vscode-editor-background);
      padding: 18px;
      line-height: 1.6;
    }
    pre {
      background: var(--vscode-textCodeBlock-background);
      padding: 12px;
      border-radius: 6px;
      overflow-x: auto;
    }
    code {
      font-family: var(--vscode-editor-font-family);
      font-size: var(--vscode-editor-font-size);
    }
    table {
      border-collapse: collapse;
      width: 100%;
      margin: 12px 0;
    }
    th, td {
      border: 1px solid var(--vscode-panel-border);
      padding: 6px 10px;
      text-align: left;
    }
    th {
      background: var(--vscode-editorGroupHeader-tabsBackground);
    }
  </style>
</head>
<body>
  <h2>${title}</h2>
  <div style="white-space: pre-wrap;">${content}</div>
</body>
</html>`;
}

function deactivate() {
  if (mcpClient) {
    mcpClient.stop();
  }
}

module.exports = { activate, deactivate };
