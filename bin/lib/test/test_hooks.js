const assert = require('assert');
const path = require('path');
const fs = require('fs');
const os = require('os');
const child_process = require('child_process');

const { fetchContext } = require('../../../src/hooks/lib/context.js');

let originalSpawnSync = child_process.spawnSync;
let spawnCallArgs = null;
let originalCwd = process.cwd;
let originalExistsSync = fs.existsSync;
let existsSyncCalls = [];

function setup() {
  delete process.env.PWD;
  spawnCallArgs = null;
  existsSyncCalls = [];
  child_process.spawnSync = function(cmd, args, opts) {
    spawnCallArgs = { cmd, args, opts };
    return { status: 1, error: new Error("ENOENT") };
  };
  fs.existsSync = function(p) {
    existsSyncCalls.push(p);
    return originalExistsSync(p);
  };
}

function teardown() {
  child_process.spawnSync = originalSpawnSync;
  process.cwd = originalCwd;
  fs.existsSync = originalExistsSync;
}

function testDefaults() {
  setup();
  process.cwd = () => path.join(os.homedir(), 'a/b/c/d/e');
  fs.existsSync = function(p) {
    existsSyncCalls.push(p);
    return false;
  };
  fetchContext();
  assert.ok(spawnCallArgs);
  assert.strictEqual(spawnCallArgs.opts.timeout, 3000);
  
  assert.strictEqual(existsSyncCalls.length, 8); // 2 files * 4 levels (0, 1, 2, 3)
  teardown();
}

function testMissingMemPath() {
  setup();
  process.cwd = () => os.homedir();
  const result = fetchContext();
  assert.strictEqual(result, null);
  teardown();
}

function testGenericFolder() {
  setup();
  const mockDesktop = path.join(os.homedir(), 'Desktop');
  fs.existsSync = function(p) {
    if (p.includes('package.json') || p.includes('pyproject.toml')) return false;
    return originalExistsSync(p);
  };
  process.cwd = () => mockDesktop;
  
  child_process.spawnSync = function(cmd, args, opts) {
    spawnCallArgs = { cmd, args, opts };
    return { status: 0, stdout: "test output" };
  };
  
  const result = fetchContext();
  assert.ok(result !== null);
  assert.strictEqual(result.topic, 'Desktop');
  assert.ok(spawnCallArgs.args.includes('Desktop'));
  
  teardown();
}

console.log("Running testDefaults...");
testDefaults();
console.log("Running testMissingMemPath...");
testMissingMemPath();
console.log("Running testGenericFolder...");
testGenericFolder();
console.log("All test_hooks tests passed.");
