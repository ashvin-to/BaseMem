const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');

// ── detect + detectAll ───────────────────────────────────────────
const { detectAll, detect, deriveTier, detectCapabilities, AGENTS } = require('../install.js');

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

// ── deriveTier ──────────────────────────────────────────────────
assert.strictEqual(deriveTier(['rules', 'mcp', 'hooks']), 1, 'hooks → tier 1');
assert.strictEqual(deriveTier(['rules', 'mcp', 'plugin']), 2, 'plugin → tier 2');
assert.strictEqual(deriveTier(['rules', 'mcp']), 3, 'rules+mcp → tier 3');
assert.strictEqual(deriveTier(['rules']), 3, 'rules only → tier 3');
assert.strictEqual(deriveTier(['mcp']), 3, 'mcp only → tier 3');
assert.strictEqual(deriveTier([]), 3, 'empty → tier 3');
console.log('PASS deriveTier: all tiers correct');

// ── detectCapabilities ──────────────────────────────────────────
// Baseline unchanged when no additional evidence
const tmpCaps = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-caps-'));
const origHome = process.env.HOME;
process.env.HOME = tmpCaps;

// Create a minimal detect path for opencode (no hooks, no plugin extras)
fs.mkdirSync(path.join(tmpCaps, '.config', 'opencode'), { recursive: true });

const baselineOnly = detectCapabilities('opencode');
assert.deepStrictEqual(baselineOnly, ['rules', 'mcp', 'plugin'],
  'detectCapabilities: baseline unchanged when no extras');
console.log('PASS detectCapabilities: baseline unchanged without extras');

// detectCapabilities adds hooks when hooks.json found
const detectDir = path.join(tmpCaps, '.gemini');
fs.mkdirSync(detectDir, { recursive: true });
fs.writeFileSync(path.join(detectDir, 'hooks.json'), '{}', 'utf-8');
const geminiCaps = detectCapabilities('gemini');
assert.ok(geminiCaps.includes('hooks'),
  'detectCapabilities: hooks added when hooks.json found');
console.log('PASS detectCapabilities: hooks added from hooks.json');

// detectCapabilities adds plugin when plugin.json found (and no hooks)
const detectDir2 = path.join(tmpCaps, '.copilot-detect');
fs.mkdirSync(detectDir2, { recursive: true });
const origAgentPaths = require('../constants.js').getAgentPaths;
// We'll test via the copilot agent — its detect path is ~/.github
// Create a temp ~/.github with plugin.json
const githubDir = path.join(tmpCaps, '.github');
fs.mkdirSync(githubDir, { recursive: true });
fs.writeFileSync(path.join(githubDir, 'plugin.json'), '{}', 'utf-8');
const copilotCaps = detectCapabilities('copilot');
assert.ok(copilotCaps.includes('plugin'),
  'detectCapabilities: plugin added when plugin.json found');
console.log('PASS detectCapabilities: plugin added from plugin.json');

process.env.HOME = origHome;
fs.rmSync(tmpCaps, { recursive: true });

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

// ── writeCodexHooksTOML / removeCodexHooks ──────────────────────
const { writeCodexHooksTOML, removeCodexHooks } = require('../install.js');

const tmpCodex = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-codex-'));
const prevHome = process.env.HOME;
process.env.HOME = tmpCodex;
fs.mkdirSync(path.join(tmpCodex, '.codex'), { recursive: true });
// Create an initial config.toml with MCP section
fs.writeFileSync(path.join(tmpCodex, '.codex', 'config.toml'), `[mcp_servers.mem]
command = "/tmp/test"
`, 'utf-8');

// Write hooks TOML
const hookDir = path.join(tmpCodex, '.codex', 'hooks');
fs.mkdirSync(hookDir, { recursive: true });
const hResult = writeCodexHooksTOML(hookDir);
assert.ok(hResult.merged, 'writeCodexHooksTOML: merged');
const toml = fs.readFileSync(path.join(tmpCodex, '.codex', 'config.toml'), 'utf-8');
assert.ok(toml.includes('[[hooks.SessionStart]]'), 'writeCodexHooksTOML: SessionStart section');
assert.ok(toml.includes('[[hooks.UserPromptSubmit]]'), 'writeCodexHooksTOML: UserPromptSubmit section');
assert.ok(toml.includes('session-start.js'), 'writeCodexHooksTOML: session-start ref');
assert.ok(toml.includes('prompt-tracker.js'), 'writeCodexHooksTOML: prompt-tracker ref');
assert.ok(toml.includes('[mcp_servers.mem]'), 'writeCodexHooksTOML: preserves existing MCP section');
console.log('PASS writeCodexHooksTOML: writes hooks TOML without removing MCP');

// Second call should be idempotent (single hooks section)
writeCodexHooksTOML(hookDir);
const toml2 = fs.readFileSync(path.join(tmpCodex, '.codex', 'config.toml'), 'utf-8');
const hookCount = (toml2.match(/\[\[hooks\.SessionStart\]\]/g) || []).length;
assert.strictEqual(hookCount, 1, `writeCodexHooksTOML idempotent: expected 1 section, got ${hookCount}`);
console.log('PASS writeCodexHooksTOML: idempotent');

// Remove hooks TOML
const rResult = removeCodexHooks();
assert.ok(rResult.removed, 'removeCodexHooks: removed');
const toml3 = fs.readFileSync(path.join(tmpCodex, '.codex', 'config.toml'), 'utf-8');
assert.ok(!toml3.includes('[[hooks.SessionStart]]'), 'removeCodexHooks: SessionStart removed');
assert.ok(toml3.includes('[mcp_servers.mem]'), 'removeCodexHooks: preserves MCP section');
console.log('PASS removeCodexHooks: removes hooks, preserves MCP');

// Second remove is no-op
const rResult2 = removeCodexHooks();
assert.strictEqual(rResult2.removed, false, 'removeCodexHooks: second call no-op');
console.log('PASS removeCodexHooks: idempotent');

process.env.HOME = prevHome;
fs.rmSync(tmpCodex, { recursive: true });

// ── install idempotency + tier selection ─────────────────────────
const { install } = require('../install.js');
const { getAgentPaths } = require('../constants.js');

const tmpHome = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-home-'));
process.env.HOME = tmpHome;
// Create detect paths
fs.mkdirSync(path.join(tmpHome, '.config', 'opencode'), { recursive: true });
fs.mkdirSync(path.join(tmpHome, '.claude'), { recursive: true });
fs.mkdirSync(path.join(tmpHome, '.codex'), { recursive: true });
fs.mkdirSync(path.join(tmpHome, '.cursor', 'rules'), { recursive: true });

// Install opencode (tier 2 — plugin)
const paths_oc = getAgentPaths()['opencode'];
const first = install('opencode');
assert.ok(first.rule.written !== undefined, 'rule.written exists');
assert.ok(first.mcp.written !== undefined, 'mcp.written exists');

// Verify tier 2 rules were written
const ocContent = fs.readFileSync(paths_oc.install, 'utf-8');
assert.ok(ocContent.includes('Memory context injected above'),
  'opencode gets tier 2 rules (context already injected)');
assert.ok(!ocContent.includes('call getContext once'),
  'opencode rules should not have getContext once instruction');
console.log('PASS install(opencode): tier 2 rules (context injected)');

// Install claude (tier 1 — hooks)
const paths_cl = getAgentPaths()['claude'];
const claudeInstall = install('claude');
assert.ok(claudeInstall.rule.written, 'claude rule written');
const clBasememMd = path.join(path.dirname(paths_cl.install), 'basemem.md');
const clContent = fs.readFileSync(clBasememMd, 'utf-8');
assert.ok(clContent.includes('Memory context injected above'),
  'claude gets tier 1 rules (context already injected)');
console.log('PASS install(claude): tier 1 rules (context injected)');

// Install aider (tier 3 — rules only, no mcp)
const paths_ai = getAgentPaths()['aider'];
// Create aider detect file
fs.writeFileSync(path.join(tmpHome, '.aider.conf.yml'), '', 'utf-8');
const aiderInstall = install('aider');
assert.ok(aiderInstall.rule.written, 'aider rule written');
const aiContent = fs.readFileSync(paths_ai.install, 'utf-8');
assert.ok(!aiContent.includes('already injected above'),
  'aider rules should not mention already injected');
assert.ok(aiContent.includes('Call getContext exactly once at session start'),
  'aider gets tier 3 rules (manual getContext at start)');
console.log('PASS install(aider): tier 3 rules (no hook/plugin)');

// Second install should not duplicate markers
const second = install('opencode');
const ocContent2 = fs.readFileSync(paths_oc.install, 'utf-8');
const markerCount = (ocContent2.match(/<!-- basemem-managed-start -->/g) || []).length;
assert.strictEqual(markerCount, 1,
  `install idempotent: expected 1 marker, got ${markerCount}`);
console.log('PASS install idempotent: single marker after second call');

// Cleanup
process.env.HOME = origHome;
fs.rmSync(tmpHome, { recursive: true });

if (prevRoot) process.env.BASEMEM_ROOT = prevRoot;
else delete process.env.BASEMEM_ROOT;
fs.rmSync(tmpDir, { recursive: true });

console.log('\nAll install.js tests passed');
