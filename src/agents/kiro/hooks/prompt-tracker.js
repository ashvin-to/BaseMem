#!/usr/bin/env node
const path = require('path');

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../../..');

let BASEMEM_RULES = '';
try {
  ({ BASEMEM_RULES } = require(path.resolve(BASEMEM_ROOT, 'bin/lib/rules.js')));
} catch (_) {}

const reminder = `[Memory Reminder] BaseMem memory is active — use mem_*/code_* tools; log edits with logInteraction(topic=<repo>).

${BASEMEM_RULES}`;

// Kiro: STDOUT is added to conversation context.
// Per-prompt recall: query-aware FTS5 hits are appended by prompt-context when available.
let stdinData = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { stdinData += chunk; });
process.stdin.on('end', () => {
  let extra = '';
  try {
    const { extractPromptText, fetchPromptContext } = require('../../hooks/lib/prompt-context.js');
    const prompt = extractPromptText(stdinData || '');
    if (prompt) extra = fetchPromptContext(prompt);
  } catch (_) { extra = ''; }
  let out = reminder;
  if (extra) out += `\n\n<BASEMEM_PROMPT_CONTEXT>\n${extra}\n</BASEMEM_PROMPT_CONTEXT>`;
  process.stdout.write(out + '\n');
});
