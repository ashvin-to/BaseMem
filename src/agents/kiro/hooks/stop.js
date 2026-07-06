#!/usr/bin/env node
const { emitStopOutput } = require('../../../hooks/lib/tracker.js');
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try { JSON.parse(input); } catch (_) {}
  emitStopOutput('kiro');
});
