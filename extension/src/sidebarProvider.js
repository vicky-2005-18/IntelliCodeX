/**
 * IntelliCodeX Sidebar Webview Provider
 * Renders an interactive AI assistant sidebar directly in VS Code / Cursor.
 */

const vscode = require('vscode');
const path = require('path');
const fs = require('fs');

class IntelliCodeXSidebarProvider {
  constructor(extensionUri, mcpClient) {
    this._extensionUri = extensionUri;
    this._mcpClient = mcpClient;
    this._view = null;
  }

  resolveWebviewView(webviewView, context, _token) {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [this._extensionUri]
    };

    webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

    webviewView.webview.onDidReceiveMessage(async (data) => {
      switch (data.type) {
        case 'askQuestion': {
          await this._handleAskQuestion(data.question, data.fileFilter);
          break;
        }
        case 'searchCode': {
          await this._handleSearchCode(data.query, data.fileFilter);
          break;
        }
        case 'scanSecurity': {
          await this._handleScanSecurity(data.file);
          break;
        }
        case 'auditArchitecture': {
          await this._handleAuditArchitecture();
          break;
        }
        case 'generateFix': {
          await this._handleGenerateFix(data.targetFile, data.description);
          break;
        }
        case 'openFileAtLine': {
          await this._handleOpenFileAtLine(data.filePath, data.line);
          break;
        }
        case 'applyDiff': {
          await this._handleApplyDiff(data.targetFile, data.patchedCode);
          break;
        }
      }
    });
  }

  async _handleAskQuestion(question, fileFilter) {
    this._sendMessage({ type: 'loading', state: true, message: 'Retrieving context & reasoning...' });
    try {
      const response = await this._mcpClient.callTool('explain_code', {
        question,
        file_filter: fileFilter || ''
      });
      this._sendMessage({ type: 'qaResult', response });
    } catch (err) {
      this._sendMessage({ type: 'error', error: err.message });
    } finally {
      this._sendMessage({ type: 'loading', state: false });
    }
  }

  async _handleSearchCode(query, fileFilter) {
    this._sendMessage({ type: 'loading', state: true, message: 'Searching hybrid BM25 + FAISS index...' });
    try {
      const response = await this._mcpClient.callTool('search_codebase', {
        query,
        top_k: 5,
        file_filter: fileFilter || ''
      });
      this._sendMessage({ type: 'searchResult', response });
    } catch (err) {
      this._sendMessage({ type: 'error', error: err.message });
    } finally {
      this._sendMessage({ type: 'loading', state: false });
    }
  }

  async _handleScanSecurity(file) {
    this._sendMessage({ type: 'loading', state: true, message: 'Scanning Bandit AST & secrets...' });
    try {
      const response = await this._mcpClient.callTool('scan_security', {
        target_file: file || '',
        severity_threshold: 'LOW'
      });
      this._sendMessage({ type: 'securityResult', response });
    } catch (err) {
      this._sendMessage({ type: 'error', error: err.message });
    } finally {
      this._sendMessage({ type: 'loading', state: false });
    }
  }

  async _handleAuditArchitecture() {
    this._sendMessage({ type: 'loading', state: true, message: 'Analyzing dependency cycles & bottlenecks...' });
    try {
      const response = await this._mcpClient.callTool('analyze_architecture', {
        threshold_lines: 80
      });
      this._sendMessage({ type: 'architectureResult', response });
    } catch (err) {
      this._sendMessage({ type: 'error', error: err.message });
    } finally {
      this._sendMessage({ type: 'loading', state: false });
    }
  }

  async _handleGenerateFix(targetFile, description) {
    this._sendMessage({ type: 'loading', state: true, message: 'Synthesizing context-aware repair patch...' });
    try {
      const response = await this._mcpClient.callTool('generate_patch', {
        target_file: targetFile,
        issue_description: description
      });
      this._sendMessage({ type: 'fixResult', response, targetFile });
    } catch (err) {
      this._sendMessage({ type: 'error', error: err.message });
    } finally {
      this._sendMessage({ type: 'loading', state: false });
    }
  }

  async _handleOpenFileAtLine(filePath, line) {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
      const fullPath = path.isAbsolute(filePath) ? filePath : path.join(workspaceFolder, filePath);
      const uri = vscode.Uri.file(fullPath);
      const doc = await vscode.workspace.openTextDocument(uri);
      const editor = await vscode.window.showTextDocument(doc);
      if (line && line > 0) {
        const lineNum = Math.max(0, line - 1);
        const pos = new vscode.Position(lineNum, 0);
        editor.selection = new vscode.Selection(pos, pos);
        editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
      }
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to open file: ${err.message}`);
    }
  }

  async _handleApplyDiff(targetFile, patchedCode) {
    try {
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
      const fullPath = path.isAbsolute(targetFile) ? targetFile : path.join(workspaceFolder, targetFile);
      const uri = vscode.Uri.file(fullPath);

      // Create a backup
      if (fs.existsSync(fullPath)) {
        const bakPath = `${fullPath}.bak.${Date.now()}`;
        fs.copyFileSync(fullPath, bakPath);
      }

      await vscode.workspace.fs.writeFile(uri, Buffer.from(patchedCode, 'utf8'));
      vscode.window.showInformationMessage(`[IntelliCodeX] Patch applied successfully to '${targetFile}'.`);
      this._sendMessage({ type: 'patchApplied', targetFile });
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to apply patch: ${err.message}`);
    }
  }

  _sendMessage(message) {
    if (this._view) {
      this._view.webview.postMessage(message);
    }
  }

  _getHtmlForWebview(webview) {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>IntelliCodeX Assistant</title>
  <style>
    body {
      padding: 12px;
      color: var(--vscode-foreground);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      background-color: var(--vscode-sideBar-background);
    }
    .header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }
    .header h3 {
      margin: 0;
      font-size: 14px;
      font-weight: 600;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .tabs {
      display: flex;
      gap: 4px;
      margin-bottom: 12px;
      border-bottom: 1px solid var(--vscode-panel-border);
    }
    .tab-btn {
      flex: 1;
      padding: 6px 4px;
      font-size: 11px;
      background: transparent;
      border: none;
      color: var(--vscode-descriptionForeground);
      cursor: pointer;
      border-bottom: 2px solid transparent;
      transition: all 0.2s;
    }
    .tab-btn.active {
      color: var(--vscode-foreground);
      border-bottom-color: var(--vscode-button-background);
      font-weight: 600;
    }
    .tab-content {
      display: none;
    }
    .tab-content.active {
      display: block;
    }
    textarea, input[type="text"] {
      width: 100%;
      box-sizing: border-box;
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border);
      border-radius: 4px;
      padding: 8px;
      margin-bottom: 8px;
      font-family: inherit;
      resize: vertical;
    }
    button.action-btn {
      width: 100%;
      padding: 8px;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-weight: 600;
      margin-bottom: 8px;
    }
    button.action-btn:hover {
      background: var(--vscode-button-hoverBackground);
    }
    .output-card {
      margin-top: 10px;
      padding: 10px;
      background: var(--vscode-editor-background);
      border: 1px solid var(--vscode-panel-border);
      border-radius: 6px;
      font-size: 12px;
      line-height: 1.5;
      max-height: 380px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      border: 2px solid var(--vscode-descriptionForeground);
      border-top-color: var(--vscode-button-background);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-right: 6px;
      vertical-align: middle;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .badge {
      display: inline-block;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 600;
      background: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
    }
  </style>
</head>
<body>
  <div class="header">
    <span style="font-size: 18px;">⚡</span>
    <h3>IntelliCodeX Assistant</h3>
    <span class="badge" id="connStatus">Ready</span>
  </div>

  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('qaTab')">💬 Q&A</button>
    <button class="tab-btn" onclick="switchTab('secTab')">🔒 Security</button>
    <button class="tab-btn" onclick="switchTab('archTab')">🏛️ Arch</button>
    <button class="tab-btn" onclick="switchTab('fixTab')">🛠️ Fix</button>
  </div>

  <!-- Q&A Tab -->
  <div id="qaTab" class="tab-content active">
    <textarea id="qaInput" rows="3" placeholder="Ask anything about the codebase (e.g. how does FAISS indexing work?)..."></textarea>
    <input type="text" id="qaFilter" placeholder="Optional file scope (e.g. core/embedder.py)" />
    <button class="action-btn" onclick="askQuestion()">Ask IntelliCodeX</button>
    <div id="qaLoading" style="display:none;"><span class="spinner"></span> <span id="qaLoadingMsg">Reasoning...</span></div>
    <div id="qaOutput" class="output-card" style="display:none;"></div>
  </div>

  <!-- Security Tab -->
  <div id="secTab" class="tab-content">
    <input type="text" id="secTarget" placeholder="Target file (leave blank for workspace)" />
    <button class="action-btn" onclick="scanSecurity()">Audit Vulnerabilities & Secrets</button>
    <div id="secLoading" style="display:none;"><span class="spinner"></span> <span>Running Bandit AST & secret audit...</span></div>
    <div id="secOutput" class="output-card" style="display:none;"></div>
  </div>

  <!-- Architecture Tab -->
  <div id="archTab" class="tab-content">
    <button class="action-btn" onclick="auditArchitecture()">Detect Cycles & Bottlenecks</button>
    <div id="archLoading" style="display:none;"><span class="spinner"></span> <span>Analyzing module graph & coupling...</span></div>
    <div id="archOutput" class="output-card" style="display:none;"></div>
  </div>

  <!-- Fix Tab -->
  <div id="fixTab" class="tab-content">
    <input type="text" id="fixTarget" placeholder="Target file (e.g. pkg/calc.py)" />
    <textarea id="fixDesc" rows="3" placeholder="Describe the defect or error to repair..."></textarea>
    <button class="action-btn" onclick="generateFix()">Synthesize Repair Patch</button>
    <div id="fixLoading" style="display:none;"><span class="spinner"></span> <span>Synthesizing and pre-validating fix...</span></div>
    <div id="fixOutput" class="output-card" style="display:none;"></div>
  </div>

  <script>
    const vscode = acquireVsCodeApi();

    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById(tabId).classList.add('active');
    }

    function askQuestion() {
      const q = document.getElementById('qaInput').value.trim();
      const filter = document.getElementById('qaFilter').value.trim();
      if (!q) return;
      document.getElementById('qaLoading').style.display = 'block';
      document.getElementById('qaOutput').style.display = 'none';
      vscode.postMessage({ type: 'askQuestion', question: q, fileFilter: filter });
    }

    function scanSecurity() {
      const file = document.getElementById('secTarget').value.trim();
      document.getElementById('secLoading').style.display = 'block';
      document.getElementById('secOutput').style.display = 'none';
      vscode.postMessage({ type: 'scanSecurity', file: file });
    }

    function auditArchitecture() {
      document.getElementById('archLoading').style.display = 'block';
      document.getElementById('archOutput').style.display = 'none';
      vscode.postMessage({ type: 'auditArchitecture' });
    }

    function generateFix() {
      const target = document.getElementById('fixTarget').value.trim();
      const desc = document.getElementById('fixDesc').value.trim();
      if (!target || !desc) return;
      document.getElementById('fixLoading').style.display = 'block';
      document.getElementById('fixOutput').style.display = 'none';
      vscode.postMessage({ type: 'generateFix', targetFile: target, description: desc });
    }

    window.addEventListener('message', event => {
      const msg = event.data;
      switch (msg.type) {
        case 'qaResult':
          document.getElementById('qaLoading').style.display = 'none';
          const qaOut = document.getElementById('qaOutput');
          qaOut.textContent = msg.response;
          qaOut.style.display = 'block';
          break;
        case 'securityResult':
          document.getElementById('secLoading').style.display = 'none';
          const secOut = document.getElementById('secOutput');
          secOut.textContent = msg.response;
          secOut.style.display = 'block';
          break;
        case 'architectureResult':
          document.getElementById('archLoading').style.display = 'none';
          const archOut = document.getElementById('archOutput');
          archOut.textContent = msg.response;
          archOut.style.display = 'block';
          break;
        case 'fixResult':
          document.getElementById('fixLoading').style.display = 'none';
          const fixOut = document.getElementById('fixOutput');
          fixOut.textContent = msg.response;
          fixOut.style.display = 'block';
          break;
        case 'loading':
          if (!msg.state) {
            document.querySelectorAll('[id$="Loading"]').forEach(el => el.style.display = 'none');
          }
          break;
        case 'error':
          document.querySelectorAll('[id$="Loading"]').forEach(el => el.style.display = 'none');
          alert('IntelliCodeX Error: ' + msg.error);
          break;
      }
    });
  </script>
</body>
</html>`;
  }
}

module.exports = { IntelliCodeXSidebarProvider };
