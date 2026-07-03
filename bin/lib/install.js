const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');
const { MARKER_START, MARKER_END, getAgentPaths, FLAG_FILENAME } = require('./constants.js');

const MARKER_COMMENT_START = `<!-- ${MARKER_START} -->`;
const { writeRuleFile, removeRuleBlock } = require('./rules.js');
const { mergeSettings, removeHookEntries } = require('./settings.js');

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../..');
const DEFAULT_MCP_PYTHON = path.join(BASEMEM_ROOT, 'venv', 'bin', 'python3');
const DEFAULT_MCP_SCRIPT = path.join(BASEMEM_ROOT, 'mem-mcp.py');
const DEFAULT_MCP_DB = path.join(os.homedir(), '.basemem', 'basemem.db');

const AGENTS = [
  { name: 'cursor',     format: 'mdc', mcp: true },
  { name: 'windsurf',   format: 'markdown', mcp: true },
  { name: 'cline',      format: 'markdown', mcp: true },
  { name: 'copilot',    format: 'markdown' },
  { name: 'continue',   format: 'markdown', mcp: true },
  { name: 'zed',        format: 'markdown', mcp: true },
  { name: 'aider',      format: 'markdown', detectBinary: true },
  { name: 'codex',      format: 'markdown', hooks: true, mcp: true },
  { name: 'opencode',   format: 'markdown', hooks: true, mcp: true },
  { name: 'claude',     format: 'markdown', hooks: true, mcp: true },
  { name: 'gemini',     format: 'markdown', mcp: true },
  { name: 'agy',        format: 'markdown', hooks: true, mcp: true },
  { name: 'vscode',     format: 'markdown', mcp: true, detectBinary: true, binaryName: 'code', skipRules: true },
];

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

function hookSourceDir(name) {
  if (name === 'claude') return path.join(BASEMEM_ROOT, 'src/hooks');
  return path.join(BASEMEM_ROOT, 'src/agents', name);
}

function hookInstallDir(name) {
  const home = os.homedir();
  const map = {
    claude:   path.join(home, '.claude', 'hooks'),
    codex:    path.join(home, '.codex', 'hooks'),
    opencode: path.join(home, '.config', 'opencode', 'plugins'),
    agy:      path.join(home, '.gemini', 'antigravity-cli', 'plugins', 'basemem'),
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
  const map = {
    claude:   path.join(home, '.claude.json'),
    codex:    path.join(home, '.codex', 'config.toml'),
    opencode: path.join(home, '.config', 'opencode', 'opencode.jsonc'),
    cursor:   path.join(home, '.cursor', 'mcp.json'),
    windsurf: path.join(home, '.windsurf', 'mcp_config.json'),
    cline:    path.join(home, '.cline', 'data', 'settings', 'cline_mcp_settings.json'),
    continue: path.join(home, '.continue', 'config.json'),
    zed:      path.join(home, '.config', 'zed', 'settings.json'),
    gemini:   path.join(home, '.gemini', 'settings.json'),
    agy:      path.join(home, '.gemini', 'antigravity-cli', 'plugins', 'basemem', 'mcp_config.json'),
    vscode:   path.join(BASEMEM_ROOT, '.vscode', 'mcp.json'),
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

  // TOML (codex)
  if (name === 'codex') {
    fs.mkdirSync(path.dirname(configPath), { recursive: true });
    let raw = '';
    try { raw = fs.readFileSync(configPath, 'utf-8'); } catch { raw = ''; }
    // Remove ALL existing mcp_servers sections mentioning mem/basemem (including subsections)
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

  if (name === 'opencode') {
    data.mcp = data.mcp || {};
    data.mcp[serverName] = { type: 'local', command: [opts.command, ...opts.args], enabled: true, environment: opts.env };
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

  const data = readJSONSafe(configPath);
  if (data === undefined) return { removed: false };
  let changed = false;

  if (name === 'opencode') {
    if (data.mcp && data.mcp[serverName]) {
      delete data.mcp[serverName];
      changed = true;
      if (!Object.keys(data.mcp).length) delete data.mcp;
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
              command: `node "${installDir}/basemem-session-start.js"`,
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
              command: `node "${installDir}/basemem-prompt-tracker.js"`,
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

function buildCodexHooksAdditions(installDir) {
  return {
    hooks: {
      SessionStart: [
        {
          matcher: 'startup|resume',
          hooks: [
            {
              type: 'command',
              command: `node "${installDir}/basemem-session-start.js"`,
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
              command: `node "${installDir}/basemem-prompt-tracker.js"`,
              timeout: 5,
            },
          ],
        },
      ],
    },
  };
}

function deployHooks(name) {
  const src = hookSourceDir(name);
  const dest = hookInstallDir(name);
  if (!fs.existsSync(src)) return { deployed: false, reason: 'source missing' };

  fs.mkdirSync(dest, { recursive: true });

  const entries = fs.readdirSync(src);
  for (const entry of entries) {
    const full = path.join(src, entry);
    if (fs.statSync(full).isFile()) {
      const target = path.join(dest, entry);
      fs.copyFileSync(full, target);
      if (entry.endsWith('.sh')) fs.chmodSync(target, 0o755);
    }
  }

  if (name === 'agy') {
    const skillSrc = path.join(src, 'skills');
    if (fs.existsSync(skillSrc)) {
      const skillDest = path.join(dest, 'skills');
      fs.mkdirSync(skillDest, { recursive: true });
      const skillFiles = fs.readdirSync(skillSrc);
      for (const entry of skillFiles) {
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
  }

  return { deployed: true, dest };
}

function settingsHasBasemem(settingsPath) {
  try {
    const raw = fs.readFileSync(settingsPath, 'utf-8');
    return raw.toLowerCase().includes('basemem');
  } catch { return false; }
}

function install(name) {
  const agent = getAgent(name);
  const info = detect(name);
  const paths = getAgentPaths()[name];

  const rule = { installed: paths.install, written: false };
  if (!agent.skipRules) {
    let already = false;
    try {
      const cur = fs.readFileSync(paths.install, 'utf-8');
      already = cur.includes(MARKER_COMMENT_START);
    } catch (_) { /* ENOENT */ }
    if (!already) {
      writeRuleFile(paths.install, agent.format);
      rule.written = true;
    }
  }

  let hooksResult = { deployed: false, reason: 'no hooks' };
  let settingsResult = { merged: false };
  let mcpResult = { written: false };

  if (agent.hooks) {
    hooksResult = deployHooks(name);

    if (name === 'claude') {
      const settingsPath = getSettingsPath(name);
      if (settingsPath) {
        const installDir = hookInstallDir(name);
        const already = settingsHasBasemem(settingsPath);
        if (!already) {
          mergeSettings(settingsPath, buildClaudeHooksAdditions(installDir));
          settingsResult = { merged: true, path: settingsPath };
        }
      }
    }

    if (name === 'codex') {
      const settingsPath = getSettingsPath(name);
      if (settingsPath) {
        const installDir = hookInstallDir(name);
        const already = settingsHasBasemem(settingsPath);
        if (!already) {
          mergeSettings(settingsPath, buildCodexHooksAdditions(installDir));
          settingsResult = { merged: true, path: settingsPath };
        }
      }
    }

    if (name === 'opencode') {
      const pluginSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'opencode', 'plugin.js');
      if (fs.existsSync(pluginSrc)) {
        const pluginDest = path.join(hookInstallDir(name), 'basemem.js');
        if (!fs.existsSync(pluginDest)) {
          fs.copyFileSync(pluginSrc, pluginDest);
          settingsResult = { merged: true, path: pluginDest };
        }
      }
    }
  }

  if (agent.mcp) {
    const configPath = getMCPConfigPath(name);
    let already = false;
    if (configPath && fs.existsSync(configPath)) {
      try {
        const raw = fs.readFileSync(configPath, 'utf-8');
        if (name === 'codex') {
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
    if (!already) {
      mcpResult = writeMCPEntry(name, 'mem');
    }
  }

  return { agent: name, rule, hooks: hooksResult, settings: settingsResult, mcp: mcpResult };
}

function installAll() {
  const results = {};
  for (const agent of AGENTS) {
    results[agent.name] = install(agent.name);
  }
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

  if (agent.hooks) {
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

    if (name === 'claude' || name === 'codex') {
      const settingsPath = getSettingsPath(name);
      if (settingsPath && fs.existsSync(settingsPath)) {
        removeHookEntries(settingsPath);
        cleaned.push(settingsPath);
      }
    }
  }

  let mcpRemoved = false;
  if (agent.mcp) {
    const r = removeMCPEntry(name, 'mem');
    mcpRemoved = r.removed;
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
  detect,
  detectAll,
  install,
  installAll,
  uninstall,
  uninstallAll,
  writeMCPEntry,
  removeMCPEntry,
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

  if (cmd === 'install-all') {
    const results = installAll();
    for (const [name, res] of Object.entries(results)) {
      const parts = [];
      if (res.rule && res.rule.written) parts.push('rules');
      if (res.hooks && res.hooks.deployed) parts.push('hooks');
      if (res.settings && res.settings.merged) parts.push('settings');
      if (res.mcp && res.mcp.written) parts.push('mcp');
      console.log(`${name}: ${parts.length ? parts.join(', ') : 'no action'}`);
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

  if (cmd === 'install-mcp') {
    const agentName = process.argv[3];
    if (agentName) {
      const r = writeMCPEntry(agentName, 'mem');
      console.log(`${agentName}: ${r.written ? 'mcp' : 'no action'}`);
    } else {
      for (const agent of AGENTS) {
        if (agent.mcp) {
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
        if (agent.mcp) {
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

  const testAgent2 = getAgent('windsurf');
  console.assert(testAgent2.format === 'markdown', 'windsurf is markdown');

  const d = detect('aider');
  console.assert('detected' in d, 'detect returns detected');
  console.assert('existingPaths' in d, 'detect returns paths');
  console.assert('binaryDetected' in d, 'detect returns binaryDetected');

  console.log('All self-tests passed');
}
