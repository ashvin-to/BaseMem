const assert = require('assert');
const { extractPromptText, fetchPromptContext, handlePromptInput } = require('../../../src/hooks/lib/prompt-context.js');

function testExtract() {
  assert.strictEqual(extractPromptText(JSON.stringify({ prompt: 'hello world foo' })), 'hello world foo');
  assert.strictEqual(extractPromptText(JSON.stringify({ userPrompt: 'second try here now' })), 'second try here now');
  assert.strictEqual(extractPromptText(JSON.stringify({ input: { prompt: 'nested prompt here ok' } })), 'nested prompt here ok');
  assert.strictEqual(extractPromptText(''), '');
  assert.strictEqual(extractPromptText(JSON.stringify({ foo: 1 })), '');
  // short prompts are extracted but fetch short-circuits
  assert.strictEqual(fetchPromptContext('hi', { topic: 't', projectRoot: '/tmp' }), '');
  // over-long prompts are capped
  const long = 'x'.repeat(5000);
  assert.ok(extractPromptText(long).length <= 2000);
}

function testHandleSilent() {
  const origWrite = process.stdout.write;
  let out = '';
  process.stdout.write = (d) => { out += d; return true; };
  try {
    handlePromptInput('claude', JSON.stringify({ prompt: 'hi' }));
  } finally {
    process.stdout.write = origWrite;
  }
  assert.ok(out.includes('code_find'), `tracker nudge preserved, got: ${out.slice(0, 120)}`);
  assert.ok(!out.includes('BASEMEM_PROMPT_CONTEXT'), 'no recall block for short prompt');
}

function testHandleRecall() {
  const child_process = require('child_process');
  const orig = child_process.spawnSync;
  child_process.spawnSync = () => ({ status: 0, stdout: '[Relevant memory]\n- (decision) t: c\n' });
  const origWrite = process.stdout.write;
  let out = '';
  process.stdout.write = (d) => { out += d; return true; };
  try {
    handlePromptInput('claude', JSON.stringify({ prompt: 'how do I fix the authentication session flow here' }));
  } finally {
    process.stdout.write = origWrite;
    child_process.spawnSync = orig;
  }
  assert.ok(out.includes('BASEMEM_PROMPT_CONTEXT'), `recall block injected, got: ${out.slice(0, 300)}`);
  assert.ok(out.includes('[Relevant memory]'), 'recall content present');
}

console.log('Running testExtract...');
testExtract();
console.log('Running testHandleSilent...');
testHandleSilent();
console.log('Running testHandleRecall...');
testHandleRecall();
console.log('All test_prompt_context tests passed.');
