/**
 * IntelliCodeX Model Context Protocol (MCP) Client
 * Connects to the local Python stdio JSON-RPC 2.0 server.
 */

const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

class McpClient {
  constructor(options = {}) {
    this.pythonPath = options.pythonPath || 'python';
    this.repoPath = options.repoPath || process.cwd();
    this.backend = options.backend || 'tfidf';
    this.logger = options.logger || console;
    this.projectRoot = options.projectRoot || path.resolve(__dirname, '..', '..');

    this.process = null;
    this.rl = null;
    this.nextId = 1;
    this.pendingRequests = new Map();
    this.isInitialized = false;
    this.onStatusChange = options.onStatusChange || (() => {});
  }

  start() {
    if (this.process) {
      return Promise.resolve();
    }

    return new Promise((resolve, reject) => {
      try {
        const args = [
          '-m',
          'core.mcp_server',
          '--repo',
          this.repoPath,
          '--backend',
          this.backend
        ];

        this.logger.log(`[McpClient] Spawning MCP server: ${this.pythonPath} ${args.join(' ')}`);

        this.process = spawn(this.pythonPath, args, {
          cwd: this.projectRoot,
          env: {
            ...process.env,
            PYTHONUNBUFFERED: '1',
            PYTHONPATH: this.projectRoot
          },
          stdio: ['pipe', 'pipe', 'pipe']
        });

        this.rl = readline.createInterface({
          input: this.process.stdout,
          terminal: false
        });

        this.rl.on('line', (line) => {
          this.handleIncomingLine(line);
        });

        this.process.stderr.on('data', (chunk) => {
          const msg = chunk.toString();
          this.logger.log(`[MCP Stderr] ${msg.trim()}`);
        });

        this.process.on('error', (err) => {
          this.logger.error(`[MCP Error] Process error: ${err.message}`);
          this.onStatusChange('error', err.message);
          reject(err);
        });

        this.process.on('exit', (code, signal) => {
          this.logger.log(`[MCP Exit] Server exited with code: ${code}, signal: ${signal}`);
          this.cleanup();
          this.onStatusChange('disconnected');
        });

        // Send MCP handshake initialize
        this.sendRequest('initialize', {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {} },
          clientInfo: { name: 'intellicodex-vscode', version: '1.0.0' }
        })
          .then((initRes) => {
            this.isInitialized = true;
            this.onStatusChange('connected', initRes);
            this.logger.log('[McpClient] Handshake successful.');
            resolve(initRes);
          })
          .catch((err) => {
            this.logger.error(`[McpClient] Handshake error: ${err.message}`);
            reject(err);
          });
      } catch (err) {
        reject(err);
      }
    });
  }

  handleIncomingLine(line) {
    const trimmed = line.trim();
    if (!trimmed) return;

    try {
      const msg = JSON.parse(trimmed);
      if (msg.id !== undefined && this.pendingRequests.has(msg.id)) {
        const { resolve, reject } = this.pendingRequests.get(msg.id);
        this.pendingRequests.delete(msg.id);

        if (msg.error) {
          reject(new Error(msg.error.message || `JSON-RPC Error ${msg.error.code}`));
        } else {
          resolve(msg.result);
        }
      }
    } catch (e) {
      this.logger.warn(`[McpClient] Non-JSON stdout received: ${trimmed}`);
    }
  }

  sendRequest(method, params = {}) {
    if (!this.process || this.process.killed) {
      return Promise.reject(new Error('IntelliCodeX MCP server process is not running.'));
    }

    const id = this.nextId++;
    const payload = JSON.stringify({
      jsonrpc: '2.0',
      id,
      method,
      params
    });

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        if (this.pendingRequests.has(id)) {
          this.pendingRequests.delete(id);
          reject(new Error(`MCP request '${method}' timed out after 60s`));
        }
      }, 60000);

      this.pendingRequests.set(id, {
        resolve: (val) => {
          clearTimeout(timeout);
          resolve(val);
        },
        reject: (err) => {
          clearTimeout(timeout);
          reject(err);
        }
      });

      this.process.stdin.write(payload + '\n', (err) => {
        if (err) {
          clearTimeout(timeout);
          this.pendingRequests.delete(id);
          reject(err);
        }
      });
    });
  }

  callTool(toolName, toolArgs = {}) {
    return this.sendRequest('tools/call', {
      name: toolName,
      arguments: toolArgs
    }).then((res) => {
      // MCP tool response returns array of content objects: [{ type: 'text', text: '...' }]
      if (res && Array.isArray(res.content)) {
        return res.content.map((c) => c.text).join('\n');
      }
      return typeof res === 'string' ? res : JSON.stringify(res, null, 2);
    });
  }

  cleanup() {
    this.isInitialized = false;
    this.process = null;
    this.rl = null;
    for (const [id, { reject }] of this.pendingRequests.entries()) {
      reject(new Error('MCP server process terminated.'));
    }
    this.pendingRequests.clear();
  }

  stop() {
    if (this.process) {
      this.process.kill();
      this.cleanup();
    }
  }
}

module.exports = { McpClient };
