#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const os = require('os');
const { spawnSync } = require('child_process');
const { checkRulesIntegrity } = require('../../../hooks/lib/context.js');

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../../..');
const memBinDir = process.env.BASEMEM_BIN_DIR || path.join(os.homedir(), '.local', 'bin');
const memPath = path.join(memBinDir, 'mem');

const flagFile = path.join(os.homedir(), '.kiro', '.basemem-active');

function writeFlag() {
  try {
    const dir = path.dirname(flagFile);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(flagFile, 'active', 'utf-8');
  } catch (_) {}
}

function getContext() {
  let cwd = (process.env.PWD && fs.existsSync(process.env.PWD)) ? process.env.PWD : process.cwd();

  let current = cwd;
  let topic = null;
  for (let i = 0; i <= 3; i++) {
    try {
      const pkgPath = path.join(current, 'package.json');
      if (fs.existsSync(pkgPath)) {
        const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
        if (pkg.name) { topic = pkg.name; break; }
      }
      const pyprojectPath = path.join(current, 'pyproject.toml');
      if (fs.existsSync(pyprojectPath)) {
        const content = fs.readFileSync(pyprojectPath, 'utf-8');
        const match = content.match(/^name\s*=\s*"([^"]+)"/m);
        if (match) { topic = match[1]; break; }
      }
    } catch (_) {}
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  if (!topic) topic = path.basename(cwd);

  try {
    const result = spawnSync(memPath, ['agent-context', '--topic', topic], {
      timeout: 3000,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    if (!result.error && result.status === 0) {
      const ctx = result.stdout.trim();
      if (ctx && !ctx.includes('No stored context found')) return ctx;
    }
  } catch (_) {}
  return '';
}

writeFlag();
const ctx = getContext();

const rulesFile = path.join(os.homedir(), '.kiro', 'steering', 'basemem.md');
const integrity = checkRulesIntegrity('kiro', rulesFile);
if (!integrity.intact) {
  process.stderr.write('BaseMem rules missing from kiro config — run: node bin/lib/install.js repair\n');
}

let BASEMEM_RULES = '';
try {
  ({ BASEMEM_RULES } = require(path.resolve(BASEMEM_ROOT, 'bin/lib/rules.js')));
} catch (_) {}

let output = '';
if (!integrity.intact) {
  output = 'WARNING: BaseMem rules were not found in your config. Memory rules may not be fully active. Ask the user to run node bin/lib/install.js repair to restore them.\n\n';
}
if (ctx) {
  output += `<KNOWLEDGE_BASE_CONTEXT>\n${ctx}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`;
}
output += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${BASEMEM_RULES}\n</EXTREMELY_IMPORTANT>`;

// Kiro: STDOUT is added to agent context
process.stdout.write(output + '\n');
