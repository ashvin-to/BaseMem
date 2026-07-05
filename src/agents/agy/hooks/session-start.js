#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext } = require('../../../hooks/lib/context.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

let stdinData = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  stdinData += chunk;
});

process.stdin.on('end', () => {
  let invocationNum = 0;
  try {
    if (stdinData.trim()) {
      const payload = JSON.parse(stdinData);
      invocationNum = payload.invocationNum || 0;
    }
  } catch (err) {
    // ignore
  }

  if (invocationNum === 1 || invocationNum === 0) {
    const configDir = process.env.AGY_PLUGIN_ROOT || path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem');
    writeFlagFile(configDir);
    const contextResult = fetchContext();
    
    const ctxStr = contextResult ? contextResult.context : '';
    const hasData = ctxStr.trim().length > 0 && 
                    !ctxStr.includes("No stored context found") && 
                    !ctxStr.includes("Error automatically fetching");
                    
    const conditionalText = hasData 
      ? `Project memory context is already injected above — do not call getContext or list_planets at session start. Only use getContext mid-session if you need a refresh or switch topics.\n\n**Memory data:**\n${ctxStr}`
      : `No context was automatically fetched. Call getContext at session start with your current project topic to retrieve available memory. Do not call list_planets.`;

    const replaceTarget = "Memory context for this project is already injected above — do not call getContext or list_planets at session start. Only use getContext mid-session if you need a refresh or switch topics.";
    
    let combined = BASEMEM_RULES_TIER1;
    if (combined.includes(replaceTarget)) {
      combined = combined.replace(replaceTarget, conditionalText);
    } else {
      combined = combined + "\n\n" + conditionalText;
    }

    const output = {
      injectSteps: [
        {
          ephemeralMessage: "<EXTREMELY_IMPORTANT>\n" + combined + "\n</EXTREMELY_IMPORTANT>"
        }
      ]
    };
    process.stdout.write(JSON.stringify(output) + '\n');
  } else {
    process.stdout.write('{}\n');
  }
});
