#!/usr/bin/env node
const { emitTrackerOutput } = require('../../../hooks/lib/tracker.js');
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try { JSON.parse(input); } catch (_) {}
  emitTrackerOutput('devin');
});
