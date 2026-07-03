#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { getClaudeDir, FLAG_FILENAME } = require('../../bin/lib/constants.js');
const { BASEMEM_RULES } = require('../../bin/lib/rules.js');

function main() {
  const configDir = getClaudeDir();
  const flagFile = path.join(configDir, FLAG_FILENAME);

  const resolvedConfig = fs.realpathSync(configDir);

  let resolvedFlag;
  try {
    resolvedFlag = fs.realpathSync(flagFile);
  } catch (_) {
    resolvedFlag = path.join(resolvedConfig, FLAG_FILENAME);
  }

  if (!resolvedFlag.startsWith(resolvedConfig)) {
    process.exit(1);
  }

  fs.writeFileSync(flagFile, 'active', 'utf-8');

  const output = {
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext: BASEMEM_RULES,
    },
  };
  console.log(JSON.stringify(output));

  const settingsPath = path.join(configDir, 'settings.json');
  let settings = {};
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, 'utf-8'));
  } catch (_) {}

  if (!settings.statusLine) {
    const nudge = {
      hookSpecificOutput: {
        hookEventName: 'SessionStart',
        additionalContext:
          'The statusLine indicator is not configured. Offer to enable it by adding a statusLine entry pointing to the basemem statusline script so the user sees a [BASEMEM] indicator in their prompt.',
      },
    };
    console.log(JSON.stringify(nudge));
  }
}

main();
