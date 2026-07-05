const fs = require('fs');
const path = require('path');
const os = require('os');
const { execSync } = require('child_process');
const { MARKER_START, MARKER_END, getAgentPaths, FLAG_FILENAME } = require('./constants.js');

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
  { name: 'cursor',    format: 'mdc',      capabilities: ['rules', 'mcp'] },
  { name: 'windsurf',  format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'continue',  format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'cline',     format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'zed',       format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'gemini',    format: 'markdown', capabilities: ['rules', 'mcp', 'plugin'] },
  { name: 'copilot',   format: 'markdown', capabilities: ['rules'] },
  { name: 'aider',     format: 'markdown', capabilities: ['rules'], detectBinary: true },
  { name: 'vscode',    format: 'markdown', capabilities: ['mcp'], detectBinary: true, binaryName: 'code', skipRules: true },
  { name: 'kiro',      format: 'markdown', capabilities: ['rules', 'mcp'] },
  { name: 'hermes',    format: 'markdown', capabilities: ['rules', 'mcp'] },
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
  return path.join(BASEMEM_ROOT, 'src/agents', name, 'hooks');
}

function hookInstallDir(name) {
  const home = os.homedir();
  const map = {
    claude:   path.join(home, '.claude', 'hooks'),
    codex:    path.join(home, '.codex', 'hooks'),
    opencode: path.join(home, '.config', 'opencode', 'plugins'),
    agy:      path.join(home, '.gemini', 'antigravity-cli', 'plugins', 'basemem', 'hooks'),
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
    const unified = path.join(home, '.gemini', 'config', 'mcp_config.json');
    const migratedMarker = path.join(home, '.gemini', 'config', '.migrated');
    const legacy = path.join(home, '.gemini', 'antigravity', 'mcp_config.json');
    return fs.existsSync(migratedMarker) || fs.existsSync(unified) ? unified : legacy;
  }
  const map = {
    claude:   path.join(home, '.claude.json'),
    codex:    path.join(home, '.codex', 'config.toml'),
    opencode: path.join(xdgConfig, 'opencode', 'opencode.jsonc'),
    cursor:   path.join(home, '.cursor', 'mcp.json'),
    windsurf: path.join(home, '.windsurf', 'mcp_config.json'),
    cline:    path.join(home, '.cline', 'data', 'settings', 'cline_mcp_settings.json'),
    continue: path.join(home, '.continue', 'config.json'),
    zed:      path.join(xdgConfig, 'zed', 'settings.json'),
    gemini:   path.join(home, '.gemini', 'settings.json'),
    vscode:   path.join(BASEMEM_ROOT, '.vscode', 'mcp.json'),
    kiro:     path.join(home, '.kiro', 'settings', 'mcp.json'),
    hermes:   path.join(home, '.hermes', 'config.yaml'),
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

  // TOML (codex)
  if (name === 'codex') {
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
    },
    statusLine: {
      type: 'command',
      command: `${installDir}/basemem-statusline.sh`,
    },
  };
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
    content = content.replace(/require\(['"]\.\.\/\.\.\/\.\.\/\.\.\/bin\/lib\/rules\.js['"]\)/g, `require('${BASEMEM_ROOT}/bin/lib/rules.js')`);
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

    const ideRoot = path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem');
    if (ideRoot !== cliRoot) {
      deployAgyPluginTo(ideRoot);
    }

    return { deployed: true, dest };
  }

  fs.mkdirSync(dest, { recursive: true });

  const entries = fs.readdirSync(src);
  for (const entry of entries) {
    const full = path.join(src, entry);
    if (fs.statSync(full).isFile()) {
      const target = path.join(dest, entry);
      copyWithRewrite(full, target);
      if (entry.endsWith('.sh')) fs.chmodSync(target, 0o755);
    }
  }

  // Also copy statusline scripts from src/hooks
  if (name === 'claude') {
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

function install(name) {
  const agent = getAgent(name);
  const info = detect(name);
  const paths = getAgentPaths()[name];

  const effectiveCaps = detectCapabilities(name);
  const effectiveTier = deriveTier(effectiveCaps);
  const rulesText = TIER_RULES[effectiveTier];

  const rule = { installed: paths.install, written: false, tier: effectiveTier };
  if (!agent.skipRules) {
    writeRuleFile(paths.install, agent.format, rulesText);
    rule.written = true;
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
        const already = settingsHasBasemem(settingsPath);
        if (!already) {
          mergeSettings(settingsPath, buildClaudeHooksAdditions(installDir));
          settingsResult = { merged: true, path: settingsPath };
        }
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

    if (name === 'agy') {
      // Register plugin with agy CLI
      const pluginRoot = path.resolve(hookInstallDir('agy'), '..');
      try {
        execSync(`agy plugin install "${pluginRoot}" 2>/dev/null`, { stdio: 'pipe' });
      } catch (_) {}
    }
  }

  if (effectiveCaps.includes('plugin')) {
    if (name === 'opencode') {
      const pluginSrc = path.join(BASEMEM_ROOT, 'src', 'agents', 'opencode', 'plugin.js');
      if (fs.existsSync(pluginSrc)) {
        const pluginDest = path.join(hookInstallDir(name), 'basemem.js');
        fs.mkdirSync(path.dirname(pluginDest), { recursive: true });
        fs.copyFileSync(pluginSrc, pluginDest);
        settingsResult = { merged: true, path: pluginDest };
      }
    }
  }

  if (effectiveCaps.includes('mcp')) {
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
    if (name === 'agy') {
      // Always overwrite agy MCP — stale template may have wrong paths
      mcpResult = writeMCPEntry(name, 'mem');
      // Also write to IDE plugin path
      const ideMcpPath = path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem', 'mcp_config.json');
      const opts = mcpOpts();
      fs.mkdirSync(path.dirname(ideMcpPath), { recursive: true });
      let ideData = readJSONSafe(ideMcpPath);
      if (ideData === undefined) ideData = {};
      ideData.mcpServers = ideData.mcpServers || {};
      ideData.mcpServers.mem = opts;
      fs.writeFileSync(ideMcpPath, JSON.stringify(ideData, null, 2) + '\n', 'utf-8');
    } else if (!already) {
      mcpResult = writeMCPEntry(name, 'mem');
    }
  }

  return { agent: name, rule, hooks: hooksResult, settings: settingsResult, mcp: mcpResult, effectiveTier };
}

function ensureEditableInstall() {
  const python = process.env.BASEMEM_MCP_PYTHON || DEFAULT_MCP_PYTHON;
  if (!fs.existsSync(python)) return { ok: false, reason: 'no venv python' };
  try {
    execSync(`${python} -c "import models; import cli; import storage" 2>/dev/null`, { stdio: 'ignore' });
    return { ok: true };
  } catch (_) {}
  try {
    execSync(`${python} -m pip install -q -e "${BASEMEM_ROOT}"`, { stdio: 'pipe' });
    return { ok: true, reinstalled: true };
  } catch (e) {
    return { ok: false, reason: e.stderr?.toString() || String(e) };
  }
}

function writeCLIWrapper() {
  const binDir = path.join(os.homedir(), '.local', 'bin');
  fs.mkdirSync(binDir, { recursive: true });

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
      const ideRoot = path.join(os.homedir(), '.gemini', 'config', 'plugins', 'basemem');
      for (const p of [cliRoot, ideRoot]) {
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
  }

  let mcpRemoved = false;
  if (agent.capabilities.includes('mcp')) {
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
  deriveTier,
  detect,
  detectAll,
  detectCapabilities,
  scanUnknownAgents,
  install,
  installAll,
  uninstall,
  uninstallAll,
  writeMCPEntry,
  removeMCPEntry,
  writeCodexHooksTOML,
  removeCodexHooks,
  writeCLIWrapper,
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

  const testAgent2 = getAgent('windsurf');
  console.assert(testAgent2.format === 'markdown', 'windsurf is markdown');

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
