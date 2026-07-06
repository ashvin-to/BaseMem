#!/usr/bin/env node
const path = require('path');

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../../..');

let BASEMEM_RULES = '';
try {
  ({ BASEMEM_RULES } = require(path.resolve(BASEMEM_ROOT, 'bin/lib/rules.js')));
} catch (_) {}

const reminder = `[Memory Reminder] Use MCP memory tools (getContext, logInteraction, code_find, etc.) and check the KNOWLEDGE_BASE_CONTEXT block above before calling getContext — it may already be injected.

${BASEMEM_RULES}`;

// Kiro: STDOUT is added to conversation context
process.stdout.write(reminder + '\n');
