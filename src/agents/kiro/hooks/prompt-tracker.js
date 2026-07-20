#!/usr/bin/env node
const path = require('path');

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../../..');

let BASEMEM_RULES = '';
try {
  ({ BASEMEM_RULES } = require(path.resolve(BASEMEM_ROOT, 'bin/lib/rules.js')));
} catch (_) {}

const reminder = `[Memory Reminder] BaseMem memory is active — use mem_*/code_* tools; log edits with logInteraction(topic=<repo>).

${BASEMEM_RULES}`;

// Kiro: STDOUT is added to conversation context
process.stdout.write(reminder + '\n');
