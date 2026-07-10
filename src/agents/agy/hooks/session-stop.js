#!/usr/bin/env node
const fs = require('fs');
const { emitStopOutput } = require('../../../hooks/lib/tracker.js');

let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  let hasLogged = false;
  
  const checkHasLogged = (str) => {
    if (str.includes('"name":"mcp__mem__logInteraction"') || str.includes('"name":"logInteraction"')) return true;
    if (/"ToolName"\s*:\s*(?:\\")?"logInteraction(?:\\")?"/.test(str)) return true;
    if (str.includes('FINAL SESSION NOTICE')) return true;
    return false;
  };

  try {
    const data = JSON.parse(input);
    const str = JSON.stringify(data);
    if (checkHasLogged(str)) {
      hasLogged = true;
    }
    if (!hasLogged && data.transcriptPath && fs.existsSync(data.transcriptPath)) {
      const transcript = fs.readFileSync(data.transcriptPath, 'utf8');
      if (checkHasLogged(transcript)) {
        hasLogged = true;
      }
    }
  } catch (_) {
    if (checkHasLogged(input)) {
      hasLogged = true;
    }
  }

  if (!hasLogged) {
    emitStopOutput('agy');
  } else {
    // Return empty JSON to allow termination
    process.stdout.write('{}\n');
  }
});
