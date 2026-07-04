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

function findProjectName() {
  const cwd = process.cwd();
  let current = cwd;
  for (let i = 0; i <= 3; i++) {
    try {
      const pkgPath = path.join(current, 'package.json');
      if (fs.existsSync(pkgPath)) {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
        if (pkg.name) return pkg.name;
      }
      const pyprojectPath = path.join(current, 'pyproject.toml');
      if (fs.existsSync(pyprojectPath)) {
        const content = fs.readFileSync(pyprojectPath, 'utf-8');
        const match = content.match(/^name\s*=\s*"([^"]+)"/m);
        if (match) return match[1];
      }
    } catch (_) {}
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  return path.basename(cwd);
}

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

  let additionalContext = BASEMEM_RULES;

  try {
    const projectName = findProjectName();
    if (projectName) {
      const { execSync } = require('child_process');
      const ctx = execSync(`mem agent-context --topic "${projectName}"`, {
        timeout: 3000,
        encoding: 'utf-8',
        stdio: ['ignore', 'pipe', 'pipe'],
      }).trim();
      if (ctx) {
        additionalContext = BASEMEM_RULES + '\n\n' + ctx;
      }
    }
  } catch (_) {}

  const output = {
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext,
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
