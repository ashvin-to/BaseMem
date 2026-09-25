const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');
const { MARKER_START, MARKER_END, getAgentPaths, FLAG_FILENAME, getClaudeDir } = require('./constants.js');

const MARKER_COMMENT_START = `<!-- ${MARKER_START} -->`;
const { writeRuleFile, removeRuleBlock, BASEMEM_RULES_TIER1, BASEMEM_RULES_TIER2, BASEMEM_RULES_TIER3 } = require('./rules.js');
const { mergeSettings, removeHookEntries } = require('./settings.js');

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../..');
const DEFAULT_MCP_PYTHON = path.join(BASEMEM_ROOT, 'venv', 'bin', 'python3');
const DEFAULT_MCP_SCRIPT = path.join(BASEMEM_ROOT, 'mem-mcp.py');
const DEFAULT_MCP_DB = path.join(os.homedir(), '.basemem', 'basemem.db');

const AGENTS = [
  { name: 'claude',    format: 'markdown', capabilities: ['rules', 'mcp', 'hooks'] },
  { name: 'codex',     format: 'markdown', capabilities: ['rules', 'mcp', 'hooks'] },
  { name: 'agy',       format: 'markdown', capabilities: ['rules', 'mcp', 'hooks'] },
  { name: 'opencode',  format: 'markdown', capabilities: ['rules', 'mcp', 'plugin'] },
  { name: 'cursor',    format: 'mdc',      capabilities: ['rules', 'mcp', 'hooks'] },
  { name: 'devin',     format: 'markdown', capabilities: ['rules', 'mcp', 'hooks', 'plugin'] },
  { name: 'continue',  format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'cline',     format: 'markdown', capabilities: ['rules', 'mcp', 'plugin'] },
  { name: 'zed',       format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'gemini',    format: 'markdown', capabilities: ['rules', 'mcp', 'plugin'] },
  { name: 'copilot',   format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'aider',     format: 'markdown', capabilities: ['rules'], detectBinary: true },
  { name: 'vscode',    format: 'markdown', capabilities: ['mcp'], detectBinary: true, binaryName: 'code', skipRules: true },
  { name: 'kilo',      format: 'markdown', capabilities: ['rules', 'mcp', 'plugin'] },
  { name: 'kiro',      format: 'markdown', capabilities: ['rules', 'mcp', 'hooks'] },
  { name: 'hermes',    format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'vibe',      format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'windsurf',  format: 'markdown', capabilities: ['rules', 'mcp'] },
];

const TIER_RULES = { 1: BASEMEM_RULES_TIER1, 2: BASEMEM_RULES_TIER2, 3: BASEMEM_RULES_TIER3 };

function deriveTier(capabilities) {
  if (capabilities.includes('hooks')) return 1;
  if (capabilities.includes('plugin')) return 2;
  return 3;
}

function getAgent(name) {
  const agent = AGENTS.find(a => a.name === name);
  if (!agent) throw new Error(`Unknown agent: ${name}`);
  return agent;
}

function detect(name) {
  const agent = getAgent(name);
  const paths = getAgentPaths()[name];
  const detectPaths = Array.isArray(paths.detect) ? paths.detect : [paths.detect];
  const existing = detectPaths.filter(p => fs.existsSync(p));
  const detected = existing.length > 0;

  let binaryDetected = false;
  if (agent.detectBinary) {
    const bin = agent.binaryName || name;
    try {
      execSync(`which ${bin} 2>/dev/null`, { stdio: 'ignore' });
      binaryDetected = true;
    } catch (_) {}
  }

  return {
    detected: detected || binaryDetected,
    existingPaths: existing,
    binaryDetected,
    installPath: paths.install,
  };
}

function detectAll() {
  const results = {};
  for (const agent of AGENTS) {
    results[agent.name] = detect(agent.name);
  }
  return results;
}

function detectCapabilities(name) {
  const agent = getAgent(name);
  const baseline = [...agent.capabilities];
  const paths = getAgentPaths()[name];
  const detectPaths = Array.isArray(paths.detect) ? paths.detect : [paths.detect];

  for (const dp of detectPaths) {
    if (!fs.existsSync(dp)) continue;

    if (!baseline.includes('hooks')) {
      const hooksDir = path.join(dp, 'hooks');
      const hooksJson = path.join(dp, 'hooks.json');
      if (fs.existsSync(hooksDir) || fs.existsSync(hooksJson)) {
        console.log(`${name} appears to have gained hook support — upgrading to tier 1. Add hooks to its capabilities array in AGENTS to suppress this message.`);
        baseline.push('hooks');
        break;
      }
    }

    if (!baseline.includes('plugin') && !baseline.includes('hooks')) {
      const pluginJson = path.join(dp, 'plugin.json');
      const pluginJs = path.join(dp, 'plugin.js');
      if (fs.existsSync(pluginJson) || fs.existsSync(pluginJs)) {
        console.log(`${name} appears to have gained plugin support — upgrading. Add plugin to its capabilities array in AGENTS to suppress this message.`);
        baseline.push('plugin');
        break;
      }
    }
  }

  return baseline;
}

function scanUnknownAgents() {
  const home = os.homedir();
  const knownPaths = [
    path.join(home, '.aide'),
    path.join(home, '.continue', 'config'),
    path.join(home, '.roo'),
    path.join(home, '.amp'),
    path.join(home, '.goose'),
    path.join(home, '.kilo'),
    path.join(home, '.pear'),
    path.join(home, '.void'),
    path.join(home, '.melty'),
  ];

  const coveredByAgents = new Set();
  const agentPaths = getAgentPaths();
  for (const name of Object.keys(agentPaths)) {
    const p = agentPaths[name];
    const detectPaths = Array.isArray(p.detect) ? p.detect : [p.detect];
    for (const dp of detectPaths) {
      coveredByAgents.add(path.resolve(dp));
    }
  }

  for (const kp of knownPaths) {
    const resolved = path.resolve(kp);
    if (coveredByAgents.has(resolved)) continue;
    if (!fs.existsSync(kp)) continue;
    console.warn(`Unknown agent detected at ${kp}. BaseMem does not have a profile for this agent. Add it to the AGENTS array for proper support. Defaulting to tier 3 rule file.`);
    const ruleFile = path.join(kp, 'basemem.md');
    writeRuleFile(ruleFile, 'markdown', BASEMEM_RULES_TIER3);
  }

  let entries;
  try { entries = fs.readdirSync(home); } catch { return; }
  for (const entry of entries) {
    if (!entry.startsWith('.') || entry.length < 2) continue;
    if (!/^\.[a-z][a-z0-9-]*$/.test(entry)) continue;
    const fullPath = path.join(home, entry);
    try {
      if (!fs.statSync(fullPath).isDirectory()) continue;
    } catch { continue; }
    const resolved = path.resolve(fullPath);
    if (coveredByAgents.has(resolved)) continue;
    if (knownPaths.some(kp => path.resolve(kp) === resolved)) continue;
    // Skip if this dir is an ancestor of any known agent detect path
    const isAncestor = [...coveredByAgents].some(cp => cp.startsWith(resolved + path.sep));
    if (isAncestor) continue;
    const indicators = ['config.json', 'settings.json', 'mcp.json', 'AGENTS.md', 'hooks.json'];
    const hasIndicator = indicators.some(f => fs.existsSync(path.join(fullPath, f)));
    if (!hasIndicator) continue;
    console.warn(`Unknown agent config directory discovered: ${fullPath}. BaseMem detected a directory that looks like an agent config. Add it to the AGENTS array in bin/lib/install.js to enable full support, or add its path to the scanUnknownAgents list to suppress this message.`);
  }
}

function hookSourceDir(name) {
  if (name === 'cline' || name === 'kilo') {
    return path.join(BASEMEM_ROOT, 'src/agents', name, 'plugins');
  }
  return path.join(BASEMEM_ROOT, 'src/agents', name, 'hooks');
}

function hookInstallDir(name) {
  const home = os.homedir();
  const xdgConfig = process.env.XDG_CONFIG_HOME && process.env.XDG_CONFIG_HOME.trim().length > 0
    ? process.env.XDG_CONFIG_HOME
    : path.join(home, '.config');
  const map = {
    claude:   path.join(home, '.claude', 'hooks'),
    codex:    path.join(home, '.codex', 'hooks'),
    cursor:   path.join(home, '.cursor', 'hooks', 'basemem'),
    opencode: path.join(home, '.config', 'opencode', 'plugins'),
    agy:      path.join(home, '.gemini', 'antigravity-cli', 'plugins', 'basemem', 'hooks'),
    devin:    path.join(xdgConfig, 'devin', 'hooks'),
    cline:    path.join(home, '.cline', 'plugins', 'basemem'),
    kilo:     path.join(home, '.config', 'kilo', 'plugin', 'basemem'),
    kiro:     path.join(home, '.kiro', 'hooks', 'basemem'),
  };
  return map[name];
}

function getSettingsPath(name) {
  const home = os.homedir();
  const map = {
    claude: path.join(home, '.claude', 'settings.json'),
    codex:  path.join(home, '.codex', 'settings.json'),
  };
  return map[name];
}

function getMCPConfigPath(name) {
  const home = os.homedir();
  const xdgConfig = process.env.XDG_CONFIG_HOME && process.env.XDG_CONFIG_HOME.trim().length > 0
    ? process.env.XDG_CONFIG_HOME
    : path.join(home, '.config');

  if (name === 'agy') {
    // Antigravity's shared MCP config lives at ~/.gemini/config/mcp_config.json
    // (read by both the CLI and the IDE). Always use this canonical path.
    return path.join(home, '.gemini', 'config', 'mcp_config.json');
  }
  const map = {
    claude:   path.join(home, '.claude.json'),
    codex:    path.join(home, '.codex', 'config.toml'),
    opencode: path.join(xdgConfig, 'opencode', 'opencode.jsonc'),
    cursor:   path.join(home, '.cursor', 'mcp.json'),
    devin:    path.join(xdgConfig, 'devin', 'mcp_config.json'),
    cline:    path.join(home, '.cline', 'data', 'settings', 'cline_mcp_settings.json'),
    continue: path.join(home, '.continue', 'config.json'),
    zed:      path.join(xdgConfig, 'zed', 'settings.json'),
    gemini:   path.join(home, '.gemini', 'settings.json'),
    vscode:   path.join(xdgConfig, 'Code', 'User', 'mcp.json'),
    kilo:     path.join(xdgConfig, 'kilo', 'kilo.jsonc'),
    kiro:     path.join(home, '.kiro', 'settings', 'mcp.json'),
    hermes:   path.join(home, '.hermes', 'config.yaml'),
    copilot:  path.join(home, '.copilot', 'mcp-config.json'),
    crush:    path.join(xdgConfig, 'crush', 'crush.json'),
    vibe:     path.join(home, '.vibe', 'config.toml'),
    windsurf: path.join(home, '.codeium', 'windsurf', 'mcp_config.json'),
  };
  return map[name];
}

function stripJsonc(str) {
  return str.replace(
    /\\"|"(?:[^"\\]|\\.)*"|\/\/.*|\/\*[\s\S]*?\*\//g,
    m => m.startsWith('"') ? m : ''
  );
}

function mcpOpts() {
  const mcpBin = path.join(os.homedir(), '.local', 'bin', 'basemem-mcp');
  if (fs.existsSync(mcpBin)) {
    return {
      command: mcpBin,
      args: [],
      env: { BASEMEM_DB_PATH: process.env.BASEMEM_DB_PATH || DEFAULT_MCP_DB },
    };
  }
  return {
    command: process.env.BASEMEM_MCP_PYTHON || DEFAULT_MCP_PYTHON,
    args: [process.env.BASEMEM_MCP_SCRIPT || DEFAULT_MCP_SCRIPT],
    env: { BASEMEM_DB_PATH: process.env.BASEMEM_DB_PATH || DEFAULT_MCP_DB },
  };
}

function readJSONSafe(fp) {
  try {
    return JSON.parse(stripJsonc(fs.readFileSync(fp, 'utf-8')));
  } catch { return undefined; }
}

function writeMCPEntry(name, serverName) {
  const configPath = getMCPConfigPath(name);
  if (!configPath) return { written: false, reason: 'no config path' };

  const opts = mcpOpts();
  const entry = {
    command: opts.command,
    args: opts.args,
    env: opts.env,
  };

  // YAML (hermes)
  if (name === 'hermes') {
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    let raw = '';
    try { raw = fs.readFileSync(configPath, 'utf-8'); } catch { raw = ''; }
    
    const lines = raw.split(/\r?\n/);
    const mcpIdx = lines.findIndex(l => l.trim() === 'mcp_servers:');
    
    // Check if basemem already exists and remove its block
    const existingIdx = lines.findIndex(l => l.match(new RegExp(`^  ${serverName}:\\s*`)));
    if (existingIdx !== -1) {
      let endIdx = existingIdx + 1;
      while (endIdx < lines.length && (lines[endIdx].startsWith('    ') || lines[endIdx].trim() === '')) {
        endIdx++;
      }
      lines.splice(existingIdx, endIdx - existingIdx);
    }
    
    const childBlock = [
      `  ${serverName}:`,
      `    command: ${opts.command}`,
      `    args:`,
      ...opts.args.map(a => `      - ${a}`),
      `    env:`,
      ...Object.entries(opts.env).map(([k, v]) => `      ${k}: ${v}`),
      `    enabled: true`,
    ];
    
    if (mcpIdx === -1) {
      if (lines.length > 0 && lines[lines.length - 1] !== '') lines.push('');
      lines.push('mcp_servers:');
      lines.push(...childBlock);
    } else {
      lines.splice(mcpIdx + 1, 0, ...childBlock);
    }
    
    fs.writeFileSync(configPath, lines.join('\n') + '\n', 'utf-8');
    return { written: true, path: configPath };
  }

  // TOML (codex, vibe)
  if (name === 'codex' || name === 'vibe') {
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    let raw = '';
    try { raw = fs.readFileSync(configPath, 'utf-8'); } catch { raw = ''; }
    raw = raw.replace(/^\[mcp_servers\.\w*(?:mem|basemem)\w*(?:\..*?)?\].*\n?(?:[^[\n].*\n?)*/gm, '');
    raw = raw.replace(/\n+\[mcp_servers\.\w*(?:mem|basemem)\w*(?:\..*?)?\].*\n?(?:[^[\n].*\n?)*/g, '');
    raw = raw.replace(/\n{3,}/g, '\n\n');
    raw = raw.trimEnd();
    raw += `\n\n[mcp_servers.${serverName}]\ncommand = ${JSON.stringify(opts.command)}\n`;
    raw += `args = ${JSON.stringify(opts.args)}\n`;
    raw += `\n[mcp_servers.${serverName}.env]\n`;
    raw += `BASEMEM_DB_PATH = ${JSON.stringify(opts.env.BASEMEM_DB_PATH)}\n`;
    fs.writeFileSync(configPath, raw, 'utf-8');
    return { written: true, path: configPath };
  }

  // JSON / JSONC files
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  let data = readJSONSafe(configPath);
  if (data === undefined) data = {};

  if (name === 'opencode' || name === 'kilo') {
    data.mcp = data.mcp || {};
    data.mcp[serverName] = { type: 'local', command: [opts.command, ...opts.args], enabled: true, environment: opts.env };
    // Clean up any stale Claude-style `mcpServers` entry left by older installs.
    if (data.mcpServers) {
      delete data.mcpServers[serverName];
      if (!Object.keys(data.mcpServers).length) delete data.mcpServers;
    }
  } else if (name === 'vscode') {
    data.servers = data.servers || {};
    data.servers[serverName] = { type: 'stdio', ...entry };
  } else {
    data.mcpServers = data.mcpServers || {};
    data.mcpServers[serverName] = entry;
  }

  fs.writeFileSync(configPath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
  return { written: true, path: configPath };
}

function removeMCPEntry(name, serverName) {
  const configPath = getMCPConfigPath(name);
  if (!configPath || !fs.existsSync(configPath)) return { removed: false };

  if (name === 'codex') {
    let raw = fs.readFileSync(configPath, 'utf-8');
    const pat = `\\[mcp_servers\\.${serverName}(?:\\..*?)?\\]`;
    const newRaw = raw
      .replace(new RegExp(`^${pat}.*\\n?(?:[^\\[\\n].*\\n?)*`, 'gm'), '')
      .replace(new RegExp(`\\n+${pat}.*\\n?(?:[^\\[\\n].*\\n?)*`, 'g'), '')
      .replace(/\n{3,}/g, '\n\n')
      .trimEnd() + '\n';
    if (newRaw !== raw) {
      fs.writeFileSync(configPath, newRaw, 'utf-8');
      return { removed: true, path: configPath };
    }
    return { removed: false };
  }

  if (name === 'hermes') {
    let raw = fs.readFileSync(configPath, 'utf-8');
    const lines = raw.split(/\r?\n/);
    const existingIdx = lines.findIndex(l => l.match(new RegExp(`^  ${serverName}:\\s*`)));
    if (existingIdx !== -1) {
      let endIdx = existingIdx + 1;
      while (endIdx < lines.length && (lines[endIdx].startsWith('    ') || lines[endIdx].trim() === '')) {
        endIdx++;
      }
      lines.splice(existingIdx, endIdx - existingIdx);
      fs.writeFileSync(configPath, lines.join('\n') + '\n', 'utf-8');
      return { removed: true, path: configPath };
    }
    return { removed: false };
  }

  const data = readJSONSafe(configPath);
  if (data === undefined) return { removed: false };
  let changed = false;

  if (name === 'opencode' || name === 'kilo') {
    if (data.mcp && data.mcp[serverName]) {
      delete data.mcp[serverName];
      changed = true;
      if (!Object.keys(data.mcp).length) delete data.mcp;
    }
    if (data.mcpServers && data.mcpServers[serverName]) {
      delete data.mcpServers[serverName];
      changed = true;
      if (!Object.keys(data.mcpServers).length) delete data.mcpServers;
    }
  } else if (name === 'vscode') {
    if (data.servers && data.servers[serverName]) {
      delete data.servers[serverName];
      changed = true;
      if (!Object.keys(data.servers).length) delete data.servers;
    }
  } else {
    if (data.mcpServers && data.mcpServers[serverName]) {
      delete data.mcpServers[serverName];
      changed = true;
      if (!Object.keys(data.mcpServers).length) delete data.mcpServers;
    }
  }

  if (changed) {
    fs.writeFileSync(configPath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
    return { removed: true, path: configPath };
  }
  return { removed: false };
}

function buildClaudeHooksAdditions(installDir) {
  return {
    hooks: {
      SessionStart: [
        {
          matcher: 'startup|resume',
          hooks: [
            {
              type: 'command',
              command: `node "${installDir}/session-start.js"`,
              statusMessage: 'Loading BaseMem memory context',
              timeout: 10,
            },
          ],
        },
      ],
      UserPromptSubmit: [
        {
          hooks: [
            {
              type: 'command',
              command: `node "${installDir}/prompt-tracker.js"`,
              timeout: 5,
            },
          ],
        },
      ],
      Stop: [
        {
          hooks: [
            {
              type: 'command',
              command: `node "${installDir}/session-stop.js"`,
              timeout: 5,
            },
          ],
        },
      ],
    },
    statusLine: {
      type: 'command',
      command: `${installDir}/basemem-statusline.sh`,
    },
  };
}

const BASEMEM_CURSOR_SESSION_CMD = 'node ./hooks/basemem/session-start.js';
const BASEMEM_CURSOR_PROMPT_CMD = 'node ./hooks/basemem/prompt-tracker.js';

function isBasememCursorHook(entry) {
  const cmd = entry && entry.command ? entry.command : '';
  return cmd.includes('basemem/session-start') || cmd.includes('basemem/prompt-tracker');
}

function getCursorHooksPath() {
  return path.join(os.homedir(), '.cursor', 'hooks.json');
}

function writeCursorHooksJSON() {
  const hooksPath = getCursorHooksPath();
  fs.mkdirSync(path.dirname(hooksPath), { recursive: true });

  let data = { version: 1, hooks: {} };
  if (fs.existsSync(hooksPath)) {
    try {
      data = JSON.parse(fs.readFileSync(hooksPath, 'utf-8'));
    } catch (_) {}
  }
  if (!data.hooks) data.hooks = {};
  if (!data.version) data.version = 1;

  for (const key of Object.keys(data.hooks)) {
    if (!Array.isArray(data.hooks[key])) continue;
    data.hooks[key] = data.hooks[key].filter(entry => !isBasememCursorHook(entry));
    if (data.hooks[key].length === 0) delete data.hooks[key];
  }

  if (!data.hooks.sessionStart) data.hooks.sessionStart = [];
  data.hooks.sessionStart.unshift({
    command: BASEMEM_CURSOR_SESSION_CMD,
    timeout: 10,
  });

  if (!data.hooks.beforeSubmitPrompt) data.hooks.beforeSubmitPrompt = [];
  data.hooks.beforeSubmitPrompt.unshift({
    command: BASEMEM_CURSOR_PROMPT_CMD,
    timeout: 5,
  });

  fs.writeFileSync(hooksPath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
  return { merged: true, path: hooksPath };
}

function removeCursorHooks() {
  const hooksPath = getCursorHooksPath();
  if (!fs.existsSync(hooksPath)) return { removed: false };

  let data;
  try {
    data = JSON.parse(fs.readFileSync(hooksPath, 'utf-8'));
  } catch {
    return { removed: false };
  }
  if (!data.hooks) return { removed: false };

  let changed = false;
  for (const key of Object.keys(data.hooks)) {
    if (!Array.isArray(data.hooks[key])) continue;
    const before = data.hooks[key].length;
    data.hooks[key] = data.hooks[key].filter(entry => !isBasememCursorHook(entry));
    if (data.hooks[key].length !== before) changed = true;
    if (data.hooks[key].length === 0) delete data.hooks[key];
  }

  if (!changed) return { removed: false };

  if (Object.keys(data.hooks).length === 0) {
    fs.unlinkSync(hooksPath);
  } else {
    fs.writeFileSync(hooksPath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
  }
  return { removed: true, path: hooksPath };
}

function writeCodexHooksTOML(installDir) {
  const configPath = getMCPConfigPath('codex');
  fs.mkdirSync(path.dirname(configPath), { recursive: true });
  let raw = '';
  try { raw = fs.readFileSync(configPath, 'utf-8'); } catch { raw = ''; }

  raw = raw.replace(/^\[{1,2}hooks\..*\]{1,2}\n?(?:[^[\n].*\n?)*/gm, '');
  raw = raw.replace(/\n{3,}/g, '\n\n');
  raw = raw.trimEnd();

  const sessionStartPath = path.join(installDir, 'session-start.js');
  const promptTrackerPath = path.join(installDir, 'prompt-tracker.js');
  const sessionStopPath = path.join(installDir, 'session-stop.js');

  raw += `\n\n[[hooks.SessionStart]]
matcher = "startup|resume"

[[hooks.SessionStart.hooks]]
type = "command"
command = "node \\"${sessionStartPath}\\""
statusMessage = "Loading BaseMem memory context"
timeout = 10

[[hooks.UserPromptSubmit]]

[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "node \\"${promptTrackerPath}\\""
timeout = 5

[[hooks.Stop]]

[[hooks.Stop.hooks]]
type = "command"
command = "node \\"${sessionStopPath}\\""
timeout = 5
`;

  fs.writeFileSync(configPath, raw + '\n', 'utf-8');
  return { merged: true, path: configPath };
}

function removeCodexHooks() {
  const configPath = getMCPConfigPath('codex');
  if (!fs.existsSync(configPath)) return { removed: false };
  let raw = fs.readFileSync(configPath, 'utf-8');
  const newRaw = raw
    .replace(/^\[{1,2}hooks\..*\]{1,2}\n?(?:[^[\n].*\n?)*/gm, '')
    .replace(/\n{3,}/g, '\n\n')
    .trimEnd() + '\n';
  if (newRaw !== raw) {
    fs.writeFileSync(configPath, newRaw, 'utf-8');
    return { removed: true, path: configPath };
  }
  return { removed: false };
}
function copyWithRewrite(srcFile, destFile) {
  if (srcFile.endsWith('.js')) {
    let content = fs.readFileSync(srcFile, 'utf-8');
    // Replace relative paths to shared hook libs with absolute paths to BASEMEM_ROOT
    content = content.replace(/require\(['"]\.\.\/\.\.\/\.\.\/hooks\/lib\/([^'"]+)['"]\)/g, `require('${BASEMEM_ROOT}/src/hooks/lib/$1')`);
    content = content.replace(/require\(['"]\.\.\/\.\.\/hooks\/lib\/([^'"]+)['"]\)/g, `require('${BASEMEM_ROOT}/src/hooks/lib/$1')`);
    content = content.replace(/require\(['"]\.\.\/\.\.\/\.\.\/\.\.\/bin\/lib\/rules\.js['"]\)/g, `require('${BASEMEM_ROOT}/bin/lib/rules.js')`);
    content = content.replace(/require\(['"]\.\.\/\.\.\/\.\.\/bin\/lib\/rules\.js['"]\)/g, `require('${BASEMEM_ROOT}/bin/lib/rules.js')`);
    fs.writeFileSync(destFile, content, 'utf-8');
  } else {
    fs.copyFileSync(srcFile, destFile);
  }
}

function deployAgyPluginTo(pluginRoot) {
  const agyRoot = path.join(BASEMEM_ROOT, 'src', 'agents', 'agy');
  const hooksSrc = path.join(agyRoot, 'hooks');
  const hooksDest = path.join(pluginRoot, 'hooks');

  fs.mkdirSync(hooksDest, { recursive: true });
  if (fs.existsSync(hooksSrc)) {
    for (const entry of fs.readdirSync(hooksSrc)) {
      const full = path.join(hooksSrc, entry);
      if (fs.statSync(full).isFile()) {
        const target = path.join(hooksDest, entry);
        copyWithRewrite(full, target);
        if (entry.endsWith('.sh')) fs.chmodSync(target, 0o755);
      }
    }
  }

  const skillSrc = path.join(agyRoot, 'skills');
  if (fs.existsSync(skillSrc)) {
    const skillDest = path.join(pluginRoot, 'skills');
    fs.mkdirSync(skillDest, { recursive: true });
    for (const entry of fs.readdirSync(skillSrc)) {
      const full = path.join(skillSrc, entry);
      if (fs.statSync(full).isDirectory()) {
        const subDest = path.join(skillDest, entry);
        fs.mkdirSync(subDest, { recursive: true });
        for (const sf of fs.readdirSync(full)) {
          fs.copyFileSync(path.join(full, sf), path.join(subDest, sf));
        }
      }
    }
  }

  const pluginJsonSrc = path.join(agyRoot, 'plugin.json');
  if (fs.existsSync(pluginJsonSrc)) {
    fs.copyFileSync(pluginJsonSrc, path.join(pluginRoot, 'plugin.json'));
  }

  const hooksJsonSrc = path.join(agyRoot, 'hooks.json');
  if (fs.existsSync(hooksJsonSrc)) {
    const raw = fs.readFileSync(hooksJsonSrc, 'utf-8');
    const resolved = raw.replace(/\$\{extensionPath\}/g, pluginRoot);
    fs.writeFileSync(path.join(pluginRoot, 'hooks.json'), resolved, 'utf-8');
  }
}

// Note: Old basemem- prefixed files (e.g. basemem-session-start.js) were removed in this refactor and should not be reintroduced.
function deployHooks(name) {
  const src = hookSourceDir(name);
  const dest = hookInstallDir(name);
  if (!fs.existsSync(src)) return { deployed: false, reason: 'source missing' };

  if (name === 'agy') {
    const cliRoot = path.resolve(dest, '..');
    deployAgyPluginTo(cliRoot);

    const sharedRoot = path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem');
    if (sharedRoot !== cliRoot) {
      deployAgyPluginTo(sharedRoot);
    }

    const agyIdeRoot = path.join(os.homedir(), '.gemini', 'antigravity', 'plugins', 'basemem');
    if (agyIdeRoot !== cliRoot && agyIdeRoot !== sharedRoot) {
      deployAgyPluginTo(agyIdeRoot);
    }

    return { deployed: true, dest };
  }

  if (name === 'cline' || name === 'kilo') {
    // Cline/Kilo use plugins, not hooks
    fs.mkdirSync(dest, { recursive: true });
    const entries = fs.readdirSync(src);
    for (const entry of entries) {
      const full = path.join(src, entry);
      if (fs.statSync(full).isFile()) {
        const target = path.join(dest, entry);
        fs.copyFileSync(full, target);
        if (entry.endsWith('.js')) fs.chmodSync(target, 0o755);
      }
    }
    return { deployed: true, dest };
  }

  fs.mkdirSync(dest, { recursive: true });

  // Shared hook libs (src/hooks/lib/*) must ship alongside the hooks:
  // prompt-tracker.js requires ../../../hooks/lib/prompt-context.js which
  // copyWithRewrite absolutizes to BASEMEM_ROOT — but the deployed copy must
  // ALSO resolve if BASEMEM_ROOT moves. Deploy lib/ next to hooks as backup.
  // Layout: dest/../lib/*.js mirrors src/hooks/lib/*.js.
  try {
    const libSrc = path.join(BASEMEM_ROOT, 'src', 'hooks', 'lib');
    const libDest = path.resolve(dest, '..', 'lib');
    if (fs.existsSync(libSrc)) {
      fs.mkdirSync(libDest, { recursive: true });
      for (const entry of fs.readdirSync(libSrc)) {
        if (!entry.endsWith('.js')) continue;
        copyWithRewrite(path.join(libSrc, entry), path.join(libDest, entry));
        try { fs.chmodSync(path.join(libDest, entry), 0o644); } catch (_) {}
      }
    }
  } catch (_) {}

  const entries = fs.readdirSync(src);
  for (const entry of entries) {
    const full = path.join(src, entry);
    if (fs.statSync(full).isFile()) {
      const target = path.join(dest, entry);
      copyWithRewrite(full, target);
      if (entry.endsWith('.sh') || entry.endsWith('.js')) fs.chmodSync(target, 0o755);
    }
  }

  // Also copy statusline scripts from src/hooks
  if (name === 'claude' || name === 'cursor') {
    const statuslineSrc = path.join(BASEMEM_ROOT, 'src/hooks');
    if (fs.existsSync(statuslineSrc)) {
      for (const entry of fs.readdirSync(statuslineSrc)) {
        if (entry.includes('statusline')) {
          const full = path.join(statuslineSrc, entry);
          if (fs.statSync(full).isFile()) {
            const target = path.join(dest, entry);
            fs.copyFileSync(full, target);
            if (entry.endsWith('.sh')) fs.chmodSync(target, 0o755);
          }
        }
      }
    }
  }

  return { deployed: true, dest };
}

function settingsHasBasemem(settingsPath) {
  try {
    const raw = fs.readFileSync(settingsPath, 'utf-8');
    return raw.toLowerCase().includes('basemem');
  } catch { return false; }
}

function deployOpencodeCommands() {
  const home = os.homedir();
  const srcDir = path.join(BASEMEM_ROOT, 'src', 'agents', 'opencode', 'commands');
  const destDir = path.join(home, '.config', 'opencode', 'commands');
  if (!fs.existsSync(srcDir)) return { deployed: false, reason: 'source missing' };
  fs.mkdirSync(destDir, { recursive: true });
  const files = fs.readdirSync(srcDir).filter(f => f.endsWith('.md'));
  for (const f of files) {
    fs.copyFileSync(path.join(srcDir, f), path.join(destDir, f));
  }
  return { deployed: true, dest: destDir, count: files.length };
}

function removeOpencodeCommands() {
  const home = os.homedir();
  const destDir = path.join(home, '.config', 'opencode', 'commands');
  if (!fs.existsSync(destDir)) return { removed: false };
  const cmdNames = ['ctx.md', 'log.md', 'review.md', 'mem.md', 'compact.md', 'tasks.md'];
  let removed = 0;
  for (const f of cmdNames) {
    const p = path.join(destDir, f);
    if (fs.existsSync(p)) { fs.unlinkSync(p); removed++; }
  }
  return { removed: removed > 0, count: removed };
}

// AGY loads folder-skills (<name>/SKILL.md) via the basemem plugin's skills dir
// (see deployAgyPluginTo). The old flat ctx.md/log.md/... files that were copied
// into ~/.gemini/antigravity-cli/skills/ are never discovered by AGY (that dir is
// not a customization root, and flat .md are not valid AGY skills). This helper
// purges any stale leftovers so they don't shadow/confuse future scans.
function cleanAgyStaleGlobalSkills() {
  const home = os.homedir();
  const staleDir = path.join(home, '.gemini', 'antigravity-cli', 'skills');
  const staleNames = ['ctx.md', 'log.md', 'mem.md', 'review.md', 'compact.md', 'tasks.md'];
  let removed = 0;
  if (fs.existsSync(staleDir)) {
    for (const f of staleNames) {
      const p = path.join(staleDir, f);
      if (fs.existsSync(p)) { fs.unlinkSync(p); removed++; }
    }
  }
  return { removed };
}

function getSkillDestDir(name) {
  const home = os.homedir();
  const map = {
    claude:   path.join(getClaudeDir(), 'skills'),
    codex:    path.join(home, '.codex', 'skills'),
    cursor:   path.join(home, '.cursor', 'skills'),
    devin:    path.join(home, '.config', 'devin', 'skills'),
    kiro:     path.join(home, '.kiro', 'skills'),
    agy:      path.join(home, '.gemini', 'antigravity-cli', 'plugins', 'basemem', 'skills'),
    opencode: path.join(home, '.config', 'opencode', 'skills'),
    cline:    path.join(home, '.cline', 'skills'),
    gemini:   path.join(home, '.gemini', 'skills'),
    kilo:     path.join(home, '.config', 'kilo', 'skills'),
    copilot:  path.join(home, '.copilot', 'skills'),
    vibe:     path.join(home, '.vibe', 'skills'),
    windsurf: path.join(home, '.codeium', 'windsurf', 'skills'),
  };
  return map[name];
}

function installSkills(agentName, customDestDir) {
  const destDir = customDestDir || getSkillDestDir(agentName);
  if (!destDir) return { copied: false };

  const skillsSrc = path.join(BASEMEM_ROOT, 'skills');
  if (!fs.existsSync(skillsSrc)) return { copied: false, reason: 'skills directory missing' };

  // Ensure skill destination directory exists
  fs.mkdirSync(destDir, { recursive: true });

  // Copy each skill folder to top-level in destDir (e.g. destDir/using-basemem, destDir/code-review)
  for (const entry of fs.readdirSync(skillsSrc)) {
    const full = path.join(skillsSrc, entry);
    if (fs.statSync(full).isDirectory()) {
      const targetSkillDir = path.join(destDir, entry);
      fs.mkdirSync(targetSkillDir, { recursive: true });
      for (const sf of fs.readdirSync(full)) {
        const sFull = path.join(full, sf);
        if (fs.statSync(sFull).isFile()) {
          fs.copyFileSync(sFull, path.join(targetSkillDir, sf));
        }
      }
      const skillReadme = path.join(skillsSrc, 'README.md');
      if (fs.existsSync(skillReadme)) {
        fs.copyFileSync(skillReadme, path.join(targetSkillDir, 'README.md'));
      }
      if (entry !== 'using-basemem') {
        const nestedSkillDir = path.join(destDir, 'using-basemem', entry);
        fs.mkdirSync(nestedSkillDir, { recursive: true });
        for (const sf of fs.readdirSync(full)) {
          const sFull = path.join(full, sf);
          if (fs.statSync(sFull).isFile()) {
            fs.copyFileSync(sFull, path.join(nestedSkillDir, sf));
          }
        }
      }
    }
  }

  if (agentName === 'agy') {
    const agyExtraDestDirs = [
      path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem', 'skills'),
      path.join(os.homedir(), '.gemini', 'antigravity', 'plugins', 'basemem', 'skills'),
    ];
    for (const extra of agyExtraDestDirs) {
      fs.mkdirSync(extra, { recursive: true });
      for (const entry of fs.readdirSync(skillsSrc)) {
        const full = path.join(skillsSrc, entry);
        if (fs.statSync(full).isDirectory()) {
          const targetSkillDir = path.join(extra, entry);
          fs.mkdirSync(targetSkillDir, { recursive: true });
          for (const sf of fs.readdirSync(full)) {
            const sFull = path.join(full, sf);
            if (fs.statSync(sFull).isFile()) {
              fs.copyFileSync(sFull, path.join(targetSkillDir, sf));
            }
          }
        }
      }
    }
  }

  return { copied: true, dest: destDir };
}

function install(name) {
  const home = os.homedir();
  const agent = getAgent(name);
  const info = detect(name);
  const paths = getAgentPaths()[name];

  const effectiveCaps = detectCapabilities(name);
  const effectiveTier = deriveTier(effectiveCaps);
  const rulesText = TIER_RULES[effectiveTier];

  const rule = { installed: paths.install, written: false, tier: effectiveTier };
  if (!agent.skipRules) {
    if (name === 'claude') {
      const basememMd = path.join(getClaudeDir(), 'basemem.md');
      writeRuleFile(basememMd, agent.format, rulesText);
      rule.written = true;
      rule.installed = basememMd;
      const claudeMd = path.join(getClaudeDir(), 'CLAUDE.md');
      const importLine = '@~/.claude/basemem.md';
      let content = '';
      try { content = fs.readFileSync(claudeMd, 'utf-8'); } catch (_) {}
      const lines = content.split('\n').map(l => l.trim());
      if (!lines.some(l => l === importLine)) {
        const append = content.length > 0 && !content.endsWith('\n') ? '\n' : '';
        fs.writeFileSync(claudeMd, content + append + importLine + '\n', 'utf-8');
      }
    } else {
      writeRuleFile(paths.install, agent.format, rulesText);
      rule.written = true;
    }
  }

  let hooksResult = { deployed: false, reason: 'no hooks' };
  let settingsResult = { merged: false };
  let mcpResult = { written: false };

  if (effectiveCaps.includes('hooks')) {
    hooksResult = deployHooks(name);

    if (name === 'claude') {
      const settingsPath = getSettingsPath(name);
      if (settingsPath) {
        const installDir = hookInstallDir(name);
        mergeSettings(settingsPath, buildClaudeHooksAdditions(installDir));
        settingsResult = { merged: true, path: settingsPath };
      }
    }

    if (name === 'codex') {
      const installDir = hookInstallDir(name);
      settingsResult = writeCodexHooksTOML(installDir);
      // Clean up stale settings.json hooks entries
      const settingsPath = getSettingsPath(name);
      if (settingsPath && fs.existsSync(settingsPath) && settingsHasBasemem(settingsPath)) {
        removeHookEntries(settingsPath);
      }
    }

    if (name === 'cursor') {
      settingsResult = writeCursorHooksJSON();
    }

    if (name === 'devin') {
      const hooksJsonSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'devin', 'hooks.json');
      if (fs.existsSync(hooksJsonSrc)) {
        const hooksJsonDest = path.join(hookInstallDir(name), 'hooks.json');
        fs.mkdirSync(path.dirname(hooksJsonDest), { recursive: true });
        fs.copyFileSync(hooksJsonSrc, hooksJsonDest);
        settingsResult = { merged: true, path: hooksJsonDest };
      }
    }

    if (name === 'agy') {
      // Register plugin with agy CLI
      const pluginRoot = path.resolve(hookInstallDir('agy'), '..');
      try {
        execSync(`agy plugin install "${pluginRoot}" 2>/dev/null`, { stdio: 'pipe' });
      } catch (_) {}
    }

    if (name === 'kiro') {
      const hookDir = hookInstallDir('kiro');
      // Create agent config that registers BaseMem hooks
      const agentsDir = path.join(home, '.kiro', 'agents');
      fs.mkdirSync(agentsDir, { recursive: true });
      const agentConfig = {
        name: 'basemem',
        description: 'BaseMem memory integration — context injection and memory tracking',
        tools: ['*'],
        includeMcpJson: true,
        hooks: {
          agentSpawn: [
            { command: `node "${hookDir}/session-start.js"`, timeout_ms: 10000 },
          ],
          userPromptSubmit: [
            { command: `node "${hookDir}/prompt-tracker.js"`, timeout_ms: 5000 },
          ],
          stop: [
            { command: `node "${hookDir}/stop.js"`, timeout_ms: 5000 },
          ],
          postToolUse: [
            { command: `node "${hookDir}/capture.js"`, timeout_ms: 5000 },
          ],
        },
      };
      const agentPath = path.join(agentsDir, 'basemem.json');
      fs.writeFileSync(agentPath, JSON.stringify(agentConfig, null, 2) + '\n', 'utf-8');
      settingsResult = { merged: true, path: agentPath };
    }
  }

  if (effectiveCaps.includes('plugin')) {
    if (name === 'opencode') {
      const pluginSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'opencode', 'plugin.js');
      if (fs.existsSync(pluginSrc)) {
        const pluginDest = path.join(hookInstallDir(name), 'basemem.js');
        fs.mkdirSync(path.dirname(pluginDest), { recursive: true });
        copyWithRewrite(pluginSrc, pluginDest);
        settingsResult = { merged: true, path: pluginDest };
      }
    }
    if (name === 'devin') {
      const pluginSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'devin', 'plugin.js');
      if (fs.existsSync(pluginSrc)) {
        const pluginDest = path.join(hookInstallDir(name), 'basemem.js');
        fs.mkdirSync(path.dirname(pluginDest), { recursive: true });
        fs.copyFileSync(pluginSrc, pluginDest);
        settingsResult = { merged: true, path: pluginDest };
      }
    }
    if (name === 'cline') {
      const pluginSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'cline', 'plugins');
      if (fs.existsSync(pluginSrc)) {
        const pluginDest = hookInstallDir('cline');
        fs.mkdirSync(pluginDest, { recursive: true });
        const entries = fs.readdirSync(pluginSrc);
        for (const entry of entries) {
          const full = path.join(pluginSrc, entry);
          if (fs.statSync(full).isFile()) {
            fs.copyFileSync(full, path.join(pluginDest, entry));
          }
        }
        settingsResult = { merged: true, path: pluginDest };
        try {
          execSync(`cline plugin install "${pluginDest}" 2>/dev/null`, { stdio: 'pipe' });
        } catch (_) {}
      }
    }
    if (name === 'kilo') {
      const pluginSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'kilo', 'plugins');
      if (fs.existsSync(pluginSrc)) {
        const pluginDest = hookInstallDir('kilo');
        fs.mkdirSync(pluginDest, { recursive: true });
        const entries = fs.readdirSync(pluginSrc);
        for (const entry of entries) {
          const full = path.join(pluginSrc, entry);
          if (fs.statSync(full).isFile()) {
            fs.copyFileSync(full, path.join(pluginDest, entry));
          }
        }
        settingsResult = { merged: true, path: pluginDest };
      }
    }
  }

  if (name === 'opencode') {
    const configPath = getMCPConfigPath('opencode');
    if (configPath && fs.existsSync(configPath)) {
      const data = readJSONSafe(configPath);
      if (data) {
        if (!data.instructions || !data.instructions.includes('AGENTS.md')) {
          data.instructions = data.instructions || [];
          if (!data.instructions.includes('AGENTS.md')) {
            data.instructions.unshift('AGENTS.md');
          }
          fs.writeFileSync(configPath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
          settingsResult = { merged: true, path: configPath };
        }
      }
    }
    deployOpencodeCommands();
  }
  if (name === 'agy') {
    cleanAgyStaleGlobalSkills();
  }

  if (effectiveCaps.includes('mcp')) {
    const configPath = getMCPConfigPath(name);
    let already = false;
    if (configPath && fs.existsSync(configPath)) {
      try {
        const raw = fs.readFileSync(configPath, 'utf-8');
        if (name === 'codex' || name === 'vibe') {
          already = /^\[mcp_servers\.mem\]/im.test(raw);
        } else {
          const data = readJSONSafe(configPath);
          if (data) {
            if (name === 'opencode') already = !!(data.mcp && data.mcp.mem);
            else if (name === 'vscode') already = !!(data.servers && data.servers.mem);
            else already = !!(data.mcpServers && data.mcpServers.mem);
          }
        }
      } catch (_) { /* parse error */ }
    }
    if (name === 'agy') {
      // Always overwrite agy MCP — stale template may have wrong paths
      mcpResult = writeMCPEntry(name, 'mem');
      // Also write to shared + IDE plugin paths
      const agyPluginBases = [
        path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem'),
        path.join(os.homedir(), '.gemini', 'antigravity', 'plugins', 'basemem'),
      ];
      for (const base of agyPluginBases) {
        const p = path.join(base, 'mcp_config.json');
        const opts = mcpOpts();
        fs.mkdirSync(path.dirname(p), { recursive: true });
        let d = readJSONSafe(p);
        if (d === undefined) d = {};
        d.mcpServers = d.mcpServers || {};
        d.mcpServers.mem = opts;
        fs.writeFileSync(p, JSON.stringify(d, null, 2) + '\n', 'utf-8');
      }
    } else if (name === 'cline') {
      mcpResult = writeMCPEntry(name, 'mem');
      // Also write to ~/.cline/mcp.json
      const clineMcpAlt = path.join(os.homedir(), '.cline', 'mcp.json');
      const opts = mcpOpts();
      fs.mkdirSync(path.dirname(clineMcpAlt), { recursive: true });
      let d = readJSONSafe(clineMcpAlt);
      if (d === undefined) d = {};
      d.mcpServers = d.mcpServers || {};
      d.mcpServers.mem = opts;
      fs.writeFileSync(clineMcpAlt, JSON.stringify(d, null, 2) + '\n', 'utf-8');
    } else if (name === 'kilo') {
      mcpResult = writeMCPEntry(name, 'mem');
      // Also write to ~/.config/kilo/opencode.jsonc if present
      const kiloAlt = path.join(os.homedir(), '.config', 'kilo', 'opencode.jsonc');
      if (fs.existsSync(path.dirname(kiloAlt))) {
        const opts = mcpOpts();
        let d = readJSONSafe(kiloAlt) || {};
        d.mcp = d.mcp || {};
        d.mcp.mem = { type: 'local', command: [opts.command, ...opts.args], enabled: true, environment: opts.env };
        fs.writeFileSync(kiloAlt, JSON.stringify(d, null, 2) + '\n', 'utf-8');
      }
    } else if (!already) {
      mcpResult = writeMCPEntry(name, 'mem');
    }
  }

  let skillsResult = { copied: false };
  if (['claude', 'codex', 'cursor', 'devin', 'kiro', 'agy', 'opencode', 'cline', 'gemini', 'kilo', 'copilot', 'vibe', 'windsurf'].includes(name)) {
    skillsResult = installSkills(name);
  }

  return { agent: name, rule, hooks: hooksResult, settings: settingsResult, mcp: mcpResult, skills: skillsResult, effectiveTier };
}

function ensureEditableInstall() {
  const python = process.env.BASEMEM_MCP_PYTHON || DEFAULT_MCP_PYTHON;
  if (!fs.existsSync(python)) return { ok: false, reason: 'no venv python' };
  try {
    execSync(`${python} -c "import models; import cli; import storage" 2>/dev/null`, { stdio: 'ignore' });
    try {
      execSync(`${python} -c "from indexer.parser import ensure_grammars; ensure_grammars()"`, { stdio: 'ignore' });
    } catch (_) {}
    return { ok: true };
  } catch (_) {}
  try {
    execSync(`${python} -m pip install -q -e "${BASEMEM_ROOT}"`, { stdio: 'pipe' });
  } catch (e) {
    return { ok: false, reason: e.stderr?.toString() || String(e) };
  }
  try {
    execSync(`${python} -c "from indexer.parser import ensure_grammars; ensure_grammars()"`, { stdio: 'ignore' });
  } catch (_) {}
  return { ok: true, reinstalled: true };
}

function writeCLIWrapper() {
  const binDir = path.join(os.homedir(), '.local', 'bin');
  fs.mkdirSync(binDir, { recursive: true });

  // MCP executable wrapper
  const venvMcpBin = path.join(BASEMEM_ROOT, 'venv', 'bin', 'basemem-mcp');
  const mcpBin = path.join(binDir, 'basemem-mcp');
  const python = process.env.BASEMEM_MCP_PYTHON || DEFAULT_MCP_PYTHON;
  const script = process.env.BASEMEM_MCP_SCRIPT || DEFAULT_MCP_SCRIPT;
  if (process.platform === 'win32') {
    const mcpBat = path.join(binDir, 'basemem-mcp.bat');
    fs.writeFileSync(mcpBat, `@echo off\r\n"${python}" "${script}" %*\r\n`, 'utf-8');
  } else if (fs.existsSync(venvMcpBin)) {
    if (fs.existsSync(mcpBin)) try { fs.unlinkSync(mcpBin); } catch (_) {}
    try { fs.symlinkSync(venvMcpBin, mcpBin); }
    catch (_) { fs.copyFileSync(venvMcpBin, mcpBin); fs.chmodSync(mcpBin, 0o755); }
  } else {
    fs.writeFileSync(mcpBin, `#!/bin/bash\nexec "${python}" "${script}" "$@"\n`, 'utf-8');
    fs.chmodSync(mcpBin, 0o755);
  }

  if (process.platform === 'win32') {
    const batPath = path.join(binDir, 'mem.bat');
    if (fs.existsSync(batPath)) return { written: false, reason: 'already exists' };
    const dbPath = process.env.BASEMEM_DB_PATH || DEFAULT_MCP_DB;
    const content = `@echo off\r\n"${DEFAULT_MCP_PYTHON}" "${path.join(BASEMEM_ROOT, 'mem.py')}" --db "${dbPath}" %*\r\n`;
    fs.writeFileSync(batPath, content, 'utf-8');
    return { written: true, path: batPath };
  }

  // Unix: symlink to the pip-installed entry point
  const venvMem = path.join(BASEMEM_ROOT, 'venv', 'bin', 'mem');
  const linkPath = path.join(binDir, 'mem');
  if (fs.existsSync(linkPath)) return { written: false, reason: 'already exists' };
  if (!fs.existsSync(venvMem)) return { written: false, reason: 'venv entry point missing' };

  try { fs.symlinkSync(venvMem, linkPath); }
  catch (_) { fs.copyFileSync(venvMem, linkPath); fs.chmodSync(linkPath, 0o755); }
  return { written: true, path: linkPath };
}

function installAll() {
  const pkg = ensureEditableInstall();
  const results = { _pkg: pkg };
  for (const agent of AGENTS) {
    results[agent.name] = install(agent.name);
  }
  results._cli = writeCLIWrapper();
  scanUnknownAgents();
  return results;
}

function uninstall(name) {
  const agent = getAgent(name);
  const paths = getAgentPaths()[name];

  const removed = [];
  const cleaned = [];

  if (!agent.skipRules) {
    removeRuleBlock(paths.install);
    const stillExists = fs.existsSync(paths.install);
    if (!stillExists) removed.push(paths.install);
  }

  const hasHookOrPlugin = agent.capabilities.includes('hooks') || agent.capabilities.includes('plugin');
  if (hasHookOrPlugin) {
    if (name === 'agy') {
      const cliRoot = path.join(os.homedir(), '.gemini', 'antigravity-cli', 'plugins', 'basemem');
      const sharedRoot = path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem');
      const agyIdeRoot = path.join(os.homedir(), '.gemini', 'antigravity', 'plugins', 'basemem');
      for (const p of [cliRoot, sharedRoot, agyIdeRoot]) {
        if (fs.existsSync(p)) {
          fs.rmSync(p, { recursive: true, force: true });
          removed.push(p);
        }
      }
    } else {
      const installDir = hookInstallDir(name);
      if (fs.existsSync(installDir)) {
        const entries = fs.readdirSync(installDir);
        for (const entry of entries) {
          const full = path.join(installDir, entry);
          const stat = fs.statSync(full);
          if (stat.isDirectory()) {
            fs.rmSync(full, { recursive: true });
          } else {
            fs.unlinkSync(full);
          }
          removed.push(full);
        }
        try { fs.rmdirSync(installDir); } catch (_) {}
      }
    }

    if (name === 'claude') {
      const settingsPath = getSettingsPath(name);
      if (settingsPath && fs.existsSync(settingsPath)) {
        removeHookEntries(settingsPath);
        cleaned.push(settingsPath);
      }
      const claudeDir = getClaudeDir();
      const claudeMd = path.join(claudeDir, 'CLAUDE.md');
      const importLine = '@~/.claude/basemem.md';
      if (fs.existsSync(claudeMd)) {
        let content = fs.readFileSync(claudeMd, 'utf-8');
        const lines = content.split('\n');
        const filtered = lines.filter(l => l.trim() !== importLine);
        if (filtered.length !== lines.length) {
          fs.writeFileSync(claudeMd, filtered.join('\n'), 'utf-8');
          cleaned.push(claudeMd);
        }
      }
      const basememMd = path.join(claudeDir, 'basemem.md');
      if (fs.existsSync(basememMd)) {
        fs.unlinkSync(basememMd);
        removed.push(basememMd);
      }
    }
    if (name === 'codex') {
      const r = removeCodexHooks();
      if (r.removed) cleaned.push(r.path);
      // Also clean stale settings.json
      const settingsPath = getSettingsPath(name);
      if (settingsPath && fs.existsSync(settingsPath)) {
        removeHookEntries(settingsPath);
        cleaned.push(settingsPath);
      }
    }
    if (name === 'cursor') {
      const r = removeCursorHooks();
      if (r.removed) cleaned.push(r.path);
    }
    if (name === 'cline') {
      try {
        execSync(`cline plugin uninstall basemem-cline-plugin 2>/dev/null`, { stdio: 'pipe' });
      } catch (_) {}
    }
    if (name === 'kilo') {
      try {
        execSync(`kilo plugin uninstall basemem-kilo-plugin 2>/dev/null`, { stdio: 'pipe' });
      } catch (_) {}
    }
    if (name === 'kiro') {
      const agentPath = path.join(os.homedir(), '.kiro', 'agents', 'basemem.json');
      if (fs.existsSync(agentPath)) {
        fs.unlinkSync(agentPath);
        removed.push(agentPath);
      }
    }
    if (name === 'opencode') {
      const configPath = getMCPConfigPath('opencode');
      if (configPath && fs.existsSync(configPath)) {
        const data = readJSONSafe(configPath);
        if (data && data.instructions) {
          const filtered = data.instructions.filter(i => i !== 'AGENTS.md');
          if (filtered.length !== data.instructions.length) {
            data.instructions = filtered.length ? filtered : undefined;
            fs.writeFileSync(configPath, JSON.stringify(data, null, 2) + '\n', 'utf-8');
            cleaned.push(configPath);
          }
        }
      }
      removeOpencodeCommands();
    }
    if (name === 'agy') {
      cleanAgyStaleGlobalSkills();
    }
  }

  let mcpRemoved = false;
  if (agent.capabilities.includes('mcp')) {
    const r = removeMCPEntry(name, 'mem');
    mcpRemoved = r.removed;
    if (name === 'cline') {
      removeMCPEntry('cline', 'mem');
      const clineMcpAlt = path.join(os.homedir(), '.cline', 'mcp.json');
      if (fs.existsSync(clineMcpAlt)) {
        const d = readJSONSafe(clineMcpAlt);
        if (d && d.mcpServers && d.mcpServers.mem) {
          delete d.mcpServers.mem;
          if (!Object.keys(d.mcpServers).length) delete d.mcpServers;
          fs.writeFileSync(clineMcpAlt, JSON.stringify(d, null, 2) + '\n', 'utf-8');
        }
      }
    }
    if (name === 'kilo') {
      const kiloAlt = path.join(os.homedir(), '.config', 'kilo', 'opencode.jsonc');
      if (fs.existsSync(kiloAlt)) {
        const d = readJSONSafe(kiloAlt);
        if (d && d.mcp && d.mcp.mem) {
          delete d.mcp.mem;
          if (!Object.keys(d.mcp).length) delete d.mcp;
          fs.writeFileSync(kiloAlt, JSON.stringify(d, null, 2) + '\n', 'utf-8');
        }
      }
    }
  }

  // Remove installed skill folders
  const skillDestDir = getSkillDestDir(name);
  if (skillDestDir && fs.existsSync(skillDestDir)) {
    const basememSkills = ['using-basemem', 'code-review', 'explore-codebase', 'debug-issue', 'session-start', 'task-workflow'];
    for (const sk of basememSkills) {
      const skPath = path.join(skillDestDir, sk);
      if (fs.existsSync(skPath)) {
        try {
          fs.rmSync(skPath, { recursive: true, force: true });
          removed.push(skPath);
        } catch (_) {}
      }
    }
  }

  return { agent: name, removed, cleaned, mcpRemoved };
}

function uninstallAll() {
  const results = {};
  for (const agent of AGENTS) {
    results[agent.name] = uninstall(agent.name);
  }
  return results;
}

module.exports = {
  AGENTS,
  deriveTier,
  detect,
  detectAll,
  detectCapabilities,
  scanUnknownAgents,
  install,
  installAll,
  installSkills,
  uninstall,
  uninstallAll,
  writeMCPEntry,
  removeMCPEntry,
  writeCodexHooksTOML,
  removeCodexHooks,
  writeCursorHooksJSON,
  removeCursorHooks,
  writeCLIWrapper,
  deployOpencodeCommands,
  removeOpencodeCommands,
  cleanAgyStaleGlobalSkills,
};

if (require.main === module || process.argv[2]) {
  const cmd = process.argv[2];

  if (cmd === 'detect') {
    const r = detectAll();
    for (const [name, info] of Object.entries(r)) {
      console.log(`${name}: ${info.detected ? 'detected' : 'not detected'}`);
    }
    const count = Object.values(r).filter(i => i.detected).length;
    console.log(`\n${count}/${AGENTS.length} agents detected`);
    process.exit(0);
  }

  if (cmd === 'capabilities' || cmd === 'caps') {
    console.log('Agent\t\tConfigured\t\tDetected\t\tEffective Tier');
    for (const agent of AGENTS) {
      const configured = agent.capabilities.join(', ');
      const detected = detectCapabilities(agent.name);
      const effectiveTier = deriveTier(detected);
      console.log(`${agent.name}\t\t${configured}\t\t${detected.join(', ')}\t\t${effectiveTier}`);
    }
    scanUnknownAgents();
    process.exit(0);
  }

  if (cmd === 'install-all') {
    const results = installAll();
    for (const [name, res] of Object.entries(results)) {
      if (name === '_cli' || name === '_pkg') continue;
      const parts = [];
      if (res.rule && res.rule.written) parts.push('rules');
      if (res.hooks && res.hooks.deployed) parts.push('hooks');
      if (res.settings && res.settings.merged) parts.push('settings');
      if (res.mcp && res.mcp.written) parts.push('mcp');
      if (res.skills && res.skills.copied) parts.push('skills');
      console.log(`${name}: ${parts.length ? parts.join(', ') : 'no action'}`);
    }
    if (results._pkg && results._pkg.reinstalled) {
      console.log('pkg: pip install -e . (reinstalled)');
    }
    if (results._pkg && !results._pkg.ok) {
      console.log(`pkg: WARNING ${results._pkg.reason}`);
    }
    if (results._cli && results._cli.written) {
      console.log(`cli: mem wrapper at ${results._cli.path}`);
    }
    process.exit(0);
  }

  if (cmd === 'uninstall-all') {
    const results = uninstallAll();
    for (const [name, res] of Object.entries(results)) {
      const parts = [];
      if (res.removed.length) parts.push(`removed ${res.removed.length} files`);
      if (res.cleaned.length) parts.push(`cleaned ${res.cleaned.length} settings`);
      if (res.mcpRemoved) parts.push('mcp');
      console.log(`${name}: ${parts.length ? parts.join(', ') : 'no action'}`);
    }
    process.exit(0);
  }

  if (cmd === 'install') {
    const agentName = process.argv[3];
    if (!agentName) { console.error('usage: install <agent>'); process.exit(1); }
    const res = install(agentName);
    const parts = [];
    if (res.rule && res.rule.written) parts.push('rules');
    if (res.hooks && res.hooks.deployed) parts.push('hooks');
    if (res.settings && res.settings.merged) parts.push('settings');
    if (res.mcp && res.mcp.written) parts.push('mcp');
    if (res.skills && res.skills.copied) parts.push('skills');
    console.log(`${agentName}: ${parts.length ? parts.join(', ') : 'no action'}`);
    process.exit(0);
  }

  if (cmd === 'uninstall') {
    const agentName = process.argv[3];
    if (!agentName) { console.error('usage: uninstall <agent>'); process.exit(1); }
    const res = uninstall(agentName);
    const parts = [];
    if (res.removed.length) parts.push(`removed ${res.removed.length} files`);
    if (res.cleaned.length) parts.push(`cleaned ${res.cleaned.length} settings`);
    if (res.mcpRemoved) parts.push('mcp');
    console.log(`${agentName}: ${parts.length ? parts.join(', ') : 'no action'}`);
    process.exit(0);
  }

  if (cmd === 'repair') {
    const targetName = process.argv[3] && !process.argv[3].startsWith('--') ? process.argv[3] : null;
    const agentsToRepair = targetName ? [getAgent(targetName)] : AGENTS;
    const results = [];
    for (const agent of agentsToRepair) {
      const paths = getAgentPaths()[agent.name];
      const rulesFilePath = agent.name === 'claude' ? path.join(getClaudeDir(), 'basemem.md') : paths.install;
      let missingRules = false;
      let missingImport = false;
      let missingFile = false;

      if (!fs.existsSync(rulesFilePath)) {
        missingFile = true;
      } else {
        const content = fs.readFileSync(rulesFilePath, 'utf-8');
        if (!content.includes(MARKER_COMMENT_START)) {
          missingRules = true;
        }
      }

      if (agent.name === 'claude') {
        const claudeMd = path.join(getClaudeDir(), 'CLAUDE.md');
        if (!fs.existsSync(claudeMd)) {
          missingImport = true;
        } else {
          const content = fs.readFileSync(claudeMd, 'utf-8');
          if (!content.includes('@~/.claude/basemem.md')) {
            missingImport = true;
          }
        }
      }

      const intact = !missingFile && !missingRules && !missingImport;
      const detail = [];
      if (missingFile) detail.push('rules file not found');
      if (missingRules) detail.push('marker missing from rules');
      if (missingImport) detail.push('import line missing from CLAUDE.md');

      install(agent.name);
      
      if (!intact) {
        results.push({ agent: agent.name, status: 'repaired', detail: detail.join(', ') });
      } else {
        results.push({ agent: agent.name, status: 'intact (synced)', detail: '' });
      }
    }
    if (process.argv.includes('--dry-run')) {
      console.log('Agent\t\tStatus\t\tDetail');
      for (const r of results) {
        console.log(`${r.agent}\t\t${r.status}\t\t${r.detail}`);
      }
    } else {
      console.log('Agent\t\tStatus\t\tDetail');
      for (const r of results) {
        console.log(`${r.agent}\t\t${r.status}\t\t${r.detail}`);
      }
    }
    process.exit(0);
  }

  if (cmd === 'install-mcp') {
    const agentName = process.argv[3];
    if (agentName) {
      const r = writeMCPEntry(agentName, 'mem');
      console.log(`${agentName}: ${r.written ? 'mcp' : 'no action'}`);
    } else {
      for (const agent of AGENTS) {
        if (agent.capabilities.includes('mcp')) {
          const r = writeMCPEntry(agent.name, 'mem');
          if (r.written) console.log(`${agent.name}: mcp`);
        }
      }
    }
    process.exit(0);
  }

  if (cmd === 'uninstall-mcp') {
    const agentName = process.argv[3];
    if (agentName) {
      const r = removeMCPEntry(agentName, 'mem');
      console.log(`${agentName}: ${r.removed ? 'removed mcp' : 'no action'}`);
    } else {
      for (const agent of AGENTS) {
        if (agent.capabilities.includes('mcp')) {
          const r = removeMCPEntry(agent.name, 'mem');
          if (r.removed) console.log(`${agent.name}: removed mcp`);
        }
      }
    }
    process.exit(0);
  }

  // default: self-test
  const r = detectAll();
  let count = 0;
  for (const [name, info] of Object.entries(r)) {
    if (info.detected) count++;
  }
  console.log(`detectAll: ${count}/${AGENTS.length} agents detected`);

  const tmp = path.join(os.tmpdir(), 'basemem-install-test');
  const origRoot = BASEMEM_ROOT;
  try { fs.mkdirSync(tmp, { recursive: true }); } catch (_) {}

  const testPaths = {
    claude: path.join(tmp, '.claude'),
    codex: path.join(tmp, '.codex'),
    cursor: path.join(tmp, '.cursor', 'rules'),
  };

  for (const p of Object.values(testPaths)) fs.mkdirSync(p, { recursive: true });

  process.env.BASEMEM_ROOT = BASEMEM_ROOT;

  const testAgent = getAgent('cursor');
  console.assert(testAgent.format === 'mdc', 'cursor is mdc');
  console.assert(testAgent.name === 'cursor', 'name');

  const testAgent2 = getAgent('devin');
  console.assert(testAgent2.format === 'markdown', 'devin is markdown');

  const d = detect('aider');
  console.assert('detected' in d, 'detect returns detected');
  console.assert('existingPaths' in d, 'detect returns paths');
  console.assert('binaryDetected' in d, 'detect returns binaryDetected');

  // deriveTier tests
  console.assert(deriveTier(['rules', 'mcp', 'hooks']) === 1, 'deriveTier: hooks → 1');
  console.assert(deriveTier(['rules', 'mcp', 'plugin']) === 2, 'deriveTier: plugin → 2');
  console.assert(deriveTier(['rules', 'mcp']) === 3, 'deriveTier: rules+mcp → 3');
  console.assert(deriveTier(['rules']) === 3, 'deriveTier: rules only → 3');
  console.assert(deriveTier(['mcp']) === 3, 'deriveTier: mcp only → 3');

  console.log('All self-tests passed');
}
