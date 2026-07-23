const assert = require('assert');
const path = require('path');
const fs = require('fs');
const os = require('os');
const child_process = require('child_process');

const { fetchContext } = require('../../../src/hooks/lib/context.js');
const { emitHookOutput } = require('../../../src/hooks/lib/output.js');
const { emitTrackerOutput } = require('../../../src/hooks/lib/tracker.js');

let originalSpawnSync = child_process.spawnSync;
let originalCwd = process.cwd;
let originalExistsSync = fs.existsSync;

// ─── Test: fetchContext includes codeStats when mem code status succeeds ───

function testCodeStatsPresent() {
  const origSpawnSync = child_process.spawnSync;
  const origExistsSync = fs.existsSync;
  const origCwd = process.cwd;

  let spawnCalls = [];
  process.cwd = () => path.join(os.homedir(), 'testproject');
  fs.existsSync = function(p) {
    if (p.includes('package.json')) return true;
    if (p.includes('pyproject.toml')) return false;
    return origExistsSync(p);
  };
  const origReadFileSync = fs.readFileSync;
  fs.readFileSync = function(p, enc) {
    if (p.includes('package.json')) return JSON.stringify({ name: 'testproject' });
    return origReadFileSync(p, enc);
  };

  child_process.spawnSync = function(cmd, args, opts) {
    spawnCalls.push({ cmd, args, opts });
    if (args && args[0] === 'agent-context') {
      return { status: 0, stdout: 'Test memory context data' };
    }
    if (args && args[0] === 'code' && args[1] === 'status') {
      return { status: 0, stdout: 'testproject: 82 files, 660 symbols, 1200 edges' };
    }
    // For planet read and compact calls
    return { status: 1, error: new Error("not needed") };
  };

  const result = fetchContext();
  assert.ok(result !== null, 'fetchContext should return a result');
  assert.ok(result.codeStats, 'result should have codeStats field');
  assert.ok(result.codeStats.includes('82 files'), `codeStats should contain file count, got: ${result.codeStats}`);
  assert.ok(result.codeStats.includes('660 symbols'), `codeStats should contain symbol count, got: ${result.codeStats}`);
  assert.ok(result.codeStats.includes('code_find'), `codeStats should reference code_find, got: ${result.codeStats}`);

  child_process.spawnSync = origSpawnSync;
  fs.existsSync = origExistsSync;
  fs.readFileSync = origReadFileSync;
  process.cwd = origCwd;
}

// ─── Test: fetchContext includes not-initialized message when mem code status fails ───

function testCodeStatsNotInitialized() {
  const origSpawnSync = child_process.spawnSync;
  const origExistsSync = fs.existsSync;
  const origCwd = process.cwd;

  process.cwd = () => path.join(os.homedir(), 'testproject');
  fs.existsSync = function(p) {
    if (p.includes('package.json')) return true;
    if (p.includes('pyproject.toml')) return false;
    return origExistsSync(p);
  };
  const origReadFileSync = fs.readFileSync;
  fs.readFileSync = function(p, enc) {
    if (p.includes('package.json')) return JSON.stringify({ name: 'testproject' });
    return origReadFileSync(p, enc);
  };

  child_process.spawnSync = function(cmd, args, opts) {
    if (args && args[0] === 'agent-context') {
      return { status: 0, stdout: 'Test memory context data' };
    }
    if (args && args[0] === 'code' && args[1] === 'status') {
      return { status: 1, error: new Error("not found") };
    }
    return { status: 1, error: new Error("not needed") };
  };

  const result = fetchContext();
  assert.ok(result !== null, 'fetchContext should return a result');
  assert.ok(result.codeStats, 'result should have codeStats field');
  assert.ok(result.codeStats.includes('not initialized'), `codeStats should say not initialized, got: ${result.codeStats}`);
  assert.ok(result.codeStats.includes('code_init'), `codeStats should reference code_init, got: ${result.codeStats}`);

  child_process.spawnSync = origSpawnSync;
  fs.existsSync = origExistsSync;
  fs.readFileSync = origReadFileSync;
  process.cwd = origCwd;
}

// ─── Test: emitTrackerOutput contains code_find and logInteraction for all formats ───

function testTrackerOutputContent() {
  const formats = ['claude', 'codex', 'cursor', 'agy', 'other'];

  for (const format of formats) {
    const origWrite = process.stdout.write;
    let output = '';
    process.stdout.write = function(data) {
      output += data;
      return true;
    };

    emitTrackerOutput(format);

    process.stdout.write = origWrite;

    assert.ok(output.includes('code_find'), `${format} tracker output should mention code_find, got: ${output}`);
    assert.ok(output.includes('logInteraction'), `${format} tracker output should mention logInteraction, got: ${output}`);
    assert.ok(output.includes('code_read'), `${format} tracker output should mention code_read, got: ${output}`);
    assert.ok(output.includes('code_explore'), `${format} tracker output should mention code_explore, got: ${output}`);
  }
}

// ─── Run all tests ───

console.log("Running testCodeStatsPresent...");
testCodeStatsPresent();
console.log("Running testCodeStatsNotInitialized...");
testCodeStatsNotInitialized();
console.log("Running testTrackerOutputContent...");
testTrackerOutputContent();
console.log("All test_code_tools_hooks tests passed.");
