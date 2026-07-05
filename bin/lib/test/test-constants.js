const assert = require('assert');
const path = require('path');
const os = require('os');
const constants = require('../constants.js');

// ── Exports ──────────────────────────────────────────────────────
assert.strictEqual(constants.MARKER_START, 'basemem-managed-start');
assert.strictEqual(constants.MARKER_END, 'basemem-managed-end');
assert.strictEqual(constants.FLAG_FILENAME, '.basemem-active');
assert.strictEqual(constants.HOOKS_SUBDIR, 'hooks');
console.log('PASS MARKER_START, MARKER_END, FLAG_FILENAME, HOOKS_SUBDIR');

// ── getClaudeDir ──────────────────────────────────────────────────
const claudeDir = constants.getClaudeDir();
assert.ok(claudeDir);
assert.ok(claudeDir.endsWith('.claude'));
console.log(`PASS getClaudeDir: ${claudeDir}`);

// CLAUDE_CONFIG_DIR override
const bak = process.env.CLAUDE_CONFIG_DIR;
process.env.CLAUDE_CONFIG_DIR = '/tmp/claude-test';
assert.strictEqual(constants.getClaudeDir(), '/tmp/claude-test');
if (bak) process.env.CLAUDE_CONFIG_DIR = bak;
else delete process.env.CLAUDE_CONFIG_DIR;
console.log('PASS getClaudeDir: CLAUDE_CONFIG_DIR override');

// ── getAgentPaths ─────────────────────────────────────────────────
const paths = constants.getAgentPaths();
const expected = ['claude', 'cursor', 'windsurf', 'cline', 'copilot', 'continue',
  'zed', 'aider', 'codex', 'opencode', 'gemini', 'agy', 'vscode'];

for (const name of expected) {
  assert.ok(paths[name], `getAgentPaths should have ${name}`);
  assert.ok(paths[name].detect, `${name}.detect`);
  assert.ok(paths[name].install, `${name}.install`);
}
assert.strictEqual(Object.keys(paths).length, 15, `Expected 15 agents, got ${Object.keys(paths).length}`);
console.log(`PASS getAgentPaths: ${expected.length} agents (claude..vscode)`);

// Agent install paths should be absolute
for (const name of expected) {
  assert.ok(path.isAbsolute(paths[name].install), `${name}.install should be absolute`);
}
console.log('PASS getAgentPaths: all install paths are absolute');

console.log('\nAll constants.js tests passed');
