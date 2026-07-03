const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ── detect + detectAll ───────────────────────────────────────────
const { detectAll, detect } = require('../install.js');

const results = detectAll();
assert.ok(typeof results === 'object');
const names = Object.keys(results);
assert.ok(names.length >= 12, `Expected 12+ agents, got ${names.length}`);

for (const [name, info] of Object.entries(results)) {
  assert.ok(typeof info.detected === 'boolean', `${name}.detected`);
  assert.ok(Array.isArray(info.existingPaths), `${name}.existingPaths`);
  assert.ok(typeof info.binaryDetected === 'boolean', `${name}.binaryDetected`);
  assert.ok(info.installPath, `${name}.installPath`);
}
console.log(`PASS detectAll: ${names.length} agents`);

// Detect a single known agent
const claude = detect('claude');
assert.ok(typeof claude.detected === 'boolean');
console.log(`PASS detect('claude'): detected=${claude.detected}`);

// Throws on unknown
assert.throws(() => detect('__nope__'), /Unknown agent/);
console.log('PASS detect(unknown): throws');

// ── writeMCPEntry / removeMCPEntry (vscode only — uses BASEMEM_ROOT) ──
const { writeMCPEntry, removeMCPEntry } = require('../install.js');

// Unknown agent — no-op
let r = writeMCPEntry('__nope__', 'mem');
assert.strictEqual(r.written, false);
console.log('PASS writeMCPEntry(unknown): no-op');

// vscode writes to BASEMEM_ROOT/.vscode/mcp.json
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-vscode-'));
const prevRoot = process.env.BASEMEM_ROOT;
process.env.BASEMEM_ROOT = tmpDir;

r = writeMCPEntry('vscode', 'mem');
assert.ok(r.written);
assert.ok(r.path);
assert.ok(fs.existsSync(r.path));

const data = JSON.parse(fs.readFileSync(r.path, 'utf-8'));
assert.ok(data.servers, 'vscode uses servers key');
assert.ok(data.servers.mem, 'has mem server');
assert.strictEqual(data.servers.mem.type, 'stdio', 'has type stdio');
assert.ok(data.servers.mem.command, 'has command');
console.log('PASS writeMCPEntry(vscode): servers key, type=stdio');

r = removeMCPEntry('vscode', 'mem');
assert.ok(r.removed);
const after = JSON.parse(fs.readFileSync(r.path, 'utf-8'));
assert.ok(!after.servers || !after.servers.mem, 'mem removed');
console.log('PASS removeMCPEntry(vscode): removed');

// Write a second entry to test removal leaves others
writeMCPEntry('vscode', 'mem');
writeMCPEntry('vscode', 'other-server');
const withBoth = JSON.parse(fs.readFileSync(r.path, 'utf-8'));
assert.ok(withBoth.servers.mem, 'mem present');
assert.ok(withBoth.servers['other-server'], 'other present');
removeMCPEntry('vscode', 'mem');
const afterRm = JSON.parse(fs.readFileSync(r.path, 'utf-8'));
assert.ok(!afterRm.servers.mem, 'mem removed');
assert.ok(afterRm.servers['other-server'], 'other preserved');
console.log('PASS removeMCPEntry(vscode): preserves other servers');

// ── install idempotency (uses BASEMEM_ROOT temp) ──────────────────
const { install } = require('../install.js');

// For a detected agent, first install should write, second should skip
const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-home-'));
const origHome = process.env.HOME;
process.env.HOME = tmpHome;
// Create a minimal dir structure so detection works for opencode
fs.mkdirSync(path.join(tmpHome, '.config', 'opencode'), { recursive: true });

const first = install('opencode');
assert.ok(first.rule.written !== undefined, 'rule.written exists');
assert.ok(first.mcp.written !== undefined, 'mcp.written exists');

const second = install('opencode');
// Rule should NOT be written again (markers already present)
if (first.rule.written) {
  assert.strictEqual(second.rule.written, false, 'install idempotent: rule not re-written');
}
// If MCP was written first time, second should skip
if (first.mcp.written) {
  assert.strictEqual(second.mcp.written, false, 'install idempotent: mcp not re-written');
}
console.log('PASS install idempotent: rule+mcp skipped on second call');

process.env.HOME = origHome;
fs.rmSync(tmpHome, { recursive: true });

// Cleanup
if (prevRoot) process.env.BASEMEM_ROOT = prevRoot;
else delete process.env.BASEMEM_ROOT;
fs.rmSync(tmpDir, { recursive: true });

console.log('\nAll install.js tests passed');
