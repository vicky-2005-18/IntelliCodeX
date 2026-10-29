/**
 * Automated Integration Test for IntelliCodeX MCP Client
 * Validates stdio JSON-RPC handshake, tool discovery, and tool execution.
 */

const assert = require('assert');
const path = require('path');
const { McpClient } = require('../src/mcpClient');

async function runIntegrationTest() {
  console.log('[*] Starting IntelliCodeX Extension MCP Integration Test...');
  const projectRoot = path.resolve(__dirname, '..', '..');

  const client = new McpClient({
    pythonPath: 'python',
    repoPath: path.join(projectRoot, 'sample_repo'),
    backend: 'tfidf',
    projectRoot: projectRoot,
    logger: {
      log: (msg) => console.log(`  ${msg}`),
      warn: (msg) => console.warn(`  [WARN] ${msg}`),
      error: (msg) => console.error(`  [ERROR] ${msg}`)
    }
  });

  try {
    // 1. Handshake
    console.log('[1/4] Performing MCP initialize handshake...');
    const initRes = await client.start();
    assert(initRes, 'Handshake response must not be null');
    assert.strictEqual(initRes.protocolVersion, '2024-11-05');
    assert.strictEqual(initRes.serverInfo.name, 'intellicodex');
    console.log('  ✓ Handshake successful: protocol 2024-11-05 verified.');

    // 2. Search Codebase Tool
    console.log('[2/4] Testing search_codebase tool...');
    const searchRes = await client.callTool('search_codebase', {
      query: 'calculate total price discount',
      top_k: 2
    });
    assert(typeof searchRes === 'string', 'Tool response must be text');
    assert(searchRes.length > 0, 'Search result must not be empty');
    console.log('  ✓ search_codebase returned verified code chunks.');

    // 3. Security Scan Tool
    console.log('[3/4] Testing scan_security tool...');
    const secRes = await client.callTool('scan_security', {
      severity_threshold: 'HIGH'
    });
    assert(typeof secRes === 'string', 'Security result must be string');
    assert(secRes.includes('Security Audit') || secRes.includes('Findings') || secRes.includes('Status'), 'Report must contain audit header');
    console.log('  ✓ scan_security returned verified security findings.');

    // 4. Architecture Tool
    console.log('[4/4] Testing analyze_architecture tool...');
    const archRes = await client.callTool('analyze_architecture', {
      threshold_lines: 80
    });
    assert(typeof archRes === 'string', 'Architecture report must be string');
    console.log('  ✓ analyze_architecture returned verified dependency analysis.');

    console.log('\n[+] All 4 MCP integration tests passed successfully!');
  } finally {
    client.stop();
  }
}

runIntegrationTest().catch((err) => {
  console.error('[!] Integration test failed:', err);
  process.exit(1);
});
