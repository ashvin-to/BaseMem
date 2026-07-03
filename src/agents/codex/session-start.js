#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const os = require('os');

function loadRules() {
  const root = process.env.BASEMEM_ROOT
    || path.resolve(__dirname, '../../..')
    || path.join(os.homedir(), '.basemem');
  try {
    return require(path.join(root, 'bin/lib/rules.js')).BASEMEM_RULES;
  } catch (_) {
    return `You have access to a persistent memory system via MCP tools. These tools are not optional and must be called as described below.
Before your first response in any session: call getContext with topic set to the project or repo name and query set to what the user is asking. If the topic is unknown, call list_planets first to discover what exists.
After any of the following events, call logInteraction immediately: a decision is made, a file is created or modified, a blocker or error is encountered, the user changes direction or scope.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, glob, or directory listing tool. The only exception is writing a brand new file that does not yet exist.
Never answer a project question without calling getContext first. Never use a generic topic name such as task, work, project, or chat. Always use the repository name, folder name, or the specific subject of the conversation.`;
  }
}

const BASEMEM_RULES = loadRules();

const BASEMEM_HOME = process.env.CODEX_PLUGIN_ROOT
  ? path.resolve(process.env.CODEX_PLUGIN_ROOT)
  : path.join(os.homedir(), '.codex');

const flagFile = path.join(BASEMEM_HOME, '.basemem-active');
const resolvedHome = fs.realpathSync(BASEMEM_HOME);

let resolvedFlag;
try {
  resolvedFlag = fs.realpathSync(flagFile);
} catch (_) {
  resolvedFlag = path.join(resolvedHome, '.basemem-active');
}

if (!resolvedFlag.startsWith(resolvedHome)) {
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
