const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { validateHookFields, mergeSettings, removeHookEntries } = require('../settings.js');

const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-settings-'));
const settingsPath = path.join(tmpDir, 'settings.json');

// ── validateHookFields ───────────────────────────────────────────
assert.doesNotThrow(() => validateHookFields({
  SessionStart: [{ type: 'command', command: 'node foo.js' }],
}));
console.log('PASS validateHookFields: valid hook');

assert.doesNotThrow(() => validateHookFields({
  UserPromptSubmit: [{
    matcher: 'test',
    hooks: [{ type: 'command', command: 'node bar.js', timeout: 5 }],
  }],
}));
console.log('PASS validateHookFields: nested valid hook');

// Missing command — throws
assert.throws(() => validateHookFields({
  SessionStart: [{ type: 'command' }],
}), /command/);
console.log('PASS validateHookFields: throws on missing command');

// Missing command in nested group — throws
assert.throws(() => validateHookFields({
  SessionStart: [{ matcher: 'x', hooks: [{ type: 'command' }] }],
}), /command/);
console.log('PASS validateHookFields: throws on nested missing command');

// Non-array hooks — silently skipped (no throw)
assert.doesNotThrow(() => validateHookFields({
  SessionStart: null,
}));
console.log('PASS validateHookFields: handles non-array gracefully');

// ── mergeSettings ────────────────────────────────────────────────
const BASEMEM_CMD = 'node basemem-start.js';
const BASEMEM_STATUS = '/path/to/basemem-statusline.sh';

mergeSettings(settingsPath, {
  hooks: {
    SessionStart: [
      { type: 'command', command: BASEMEM_CMD },
    ],
  },
  statusLine: { command: BASEMEM_STATUS },
});

let config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.ok(config.hooks);
assert.strictEqual(config.hooks.SessionStart.length, 1);
assert.strictEqual(config.hooks.SessionStart[0].command, BASEMEM_CMD);
assert.strictEqual(config.statusLine.command, BASEMEM_STATUS);
console.log('PASS mergeSettings: initial merge');

// Idempotent — same merge again doesn't duplicate (detected by "basemem" in command)
mergeSettings(settingsPath, {
  hooks: {
    SessionStart: [
      { type: 'command', command: BASEMEM_CMD },
    ],
  },
  statusLine: { command: BASEMEM_STATUS },
});
config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.strictEqual(config.hooks.SessionStart.length, 1, 'no duplicate');
assert.strictEqual(config.statusLine.command, BASEMEM_STATUS, 'statusLine preserved');
console.log('PASS mergeSettings: idempotent');

// Merge additional event
mergeSettings(settingsPath, {
  hooks: {
    UserPromptSubmit: [
      { type: 'command', command: 'node basemem-prompt.js', timeout: 5 },
    ],
  },
});
config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.strictEqual(config.hooks.SessionStart.length, 1, 'SessionStart preserved');
assert.strictEqual(config.hooks.UserPromptSubmit.length, 1, 'UserPromptSubmit added');
console.log('PASS mergeSettings: adds new event without removing existing');

// Merge to non-existent file creates it
const newPath = path.join(tmpDir, 'new.json');
mergeSettings(newPath, { hooks: { Test: [{ type: 'command', command: 'echo' }] } });
assert.ok(fs.existsSync(newPath));
console.log('PASS mergeSettings: creates file if missing');

// Merge with null hooks is safe
mergeSettings(settingsPath, {});
config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.ok(config.hooks);
assert.strictEqual(config.hooks.SessionStart.length, 1);
console.log('PASS mergeSettings: empty additions preserves existing');

// ── removeHookEntries ────────────────────────────────────────────
removeHookEntries(settingsPath);
config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.strictEqual(config.hooks.SessionStart.length, 0, 'SessionStart removed');
assert.strictEqual(config.hooks.UserPromptSubmit.length, 0, 'UserPromptSubmit removed');
assert.ok(!config.statusLine, 'statusLine removed');
console.log('PASS removeHookEntries: removes basemem hooks + statusLine');

// Removing again is harmless
removeHookEntries(settingsPath);
config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.strictEqual(config.hooks.SessionStart.length, 0);
console.log('PASS removeHookEntries: idempotent');

// No-op on non-existent file
removeHookEntries(path.join(tmpDir, 'nope.json'));
console.log('PASS removeHookEntries: no-op on missing file');

// Preserves non-basemem hooks (command without "basemem" in the name)
fs.writeFileSync(settingsPath, JSON.stringify({
  hooks: {
    SessionStart: [
      { type: 'command', command: 'node basemem-start.js' },
    ],
    OtherEvent: [
      { type: 'command', command: 'node other.js' },
    ],
  },
}), 'utf-8');
removeHookEntries(settingsPath);
config = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
assert.strictEqual(config.hooks.SessionStart.length, 0, 'basemem removed');
assert.strictEqual(config.hooks.OtherEvent.length, 1, 'other preserved');
console.log('PASS removeHookEntries: preserves non-basemem hooks');

// ── readJson error handling ──────────────────────────────────────
const badPath = path.join(tmpDir, 'bad.json');
fs.writeFileSync(badPath, '{invalid json', 'utf-8');
mergeSettings(badPath, { hooks: { E: [{ type: 'command', command: 'echo' }] } });
// File should not have been overwritten
const badContent = fs.readFileSync(badPath, 'utf-8');
assert.ok(badContent.includes('invalid'), 'should not overwrite invalid JSON');
console.log('PASS mergeSettings: skips invalid JSON without clobbering');

// Cleanup
fs.rmSync(tmpDir, { recursive: true });

console.log('\nAll settings.js tests passed');
