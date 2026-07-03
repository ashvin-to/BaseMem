#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const home = require('os').homedir();

function getClaudeDir() {
  if (process.env.CLAUDE_CONFIG_DIR) return process.env.CLAUDE_CONFIG_DIR;
  if (process.platform === 'win32') return path.join(process.env.APPDATA, 'claude');
  return path.join(home, '.claude');
}

const BASEMEM_RULES = process.env.BASEMEM_RULES || `You have access to a persistent memory system via MCP tools. These tools are not optional and must be called as described below.
Before your first response in any session: call getContext with topic set to the project or repo name and query set to what the user is asking. If the topic is unknown, call list_planets first to discover what exists.
After any of the following events, call logInteraction immediately: a decision is made, a file is created or modified, a blocker or error is encountered, the user changes direction or scope.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, or directory listing tool. The only exception is writing a brand new file that does not yet exist.
Never answer a project question without calling getContext first. Never use a generic topic name such as task, work, project, or chat. Always use the repository name, folder name, or the specific subject of the conversation.`;

const FLAG_FILENAME = '.basemem-active';

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
