#!/usr/bin/env node
const { emitStopOutput } = require('../../../hooks/lib/tracker.js');
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  let hasLogged = false;
  try {
    const data = JSON.parse(input);
    const str = JSON.stringify(data);
    if (str.includes('"name":"mcp__mem__logInteraction"') || str.includes('"name":"logInteraction"') || str.includes('FINAL SESSION NOTICE')) {
      hasLogged = true;
    }
  } catch (_) {
    if (input.includes('"name":"mcp__mem__logInteraction"') || input.includes('"name":"logInteraction"') || input.includes('FINAL SESSION NOTICE')) {
      hasLogged = true;
    }
  }
  if (!hasLogged) {
    emitStopOutput('claude');
  }
});
