// Shared hook library: topic derivation + memory context fetch for SessionStart hooks.
// Required by src/agents/<agent>/hooks/session-start.js via an absolute path rewritten
// by bin/lib/install.js#copyWithRewrite. Loaded in place from the repo, so relative
// requires here resolve against the repo layout.
const fs = require('fs');
const os = require('os');
const path = require('path');
const child_process = require('child_process');
const { MARKER_START } = require('../../../bin/lib/constants.js');

// Generic folder/username names that make poor memory topics.
const REJECT_TOPICS = new Set([
  'home', 'user', 'users', 'documents', 'desktop', 'downloads', 'downloads',
  'projects', 'code', 'src', 'tmp', 'temp', 'work', 'workspace', 'dev', 'repos',
  'github', 'storage', 'data', 'config', 'bin', 'lib', 'etc', 'var', 'opt',
]);

function _memPath() {
  const binDir = process.env.BASEMEM_BIN_DIR || path.join(os.homedir(), '.local', 'bin');
  return path.join(binDir, 'mem');
}

function _readProjectName(dir) {
  try {
    const pkgPath = path.join(dir, 'package.json');
    if (fs.existsSync(pkgPath)) {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'));
      if (pkg.name) return pkg.name;
    }
  } catch (_) {}
  try {
    const py = path.join(dir, 'pyproject.toml');
    if (fs.existsSync(py)) {
      const content = fs.readFileSync(py, 'utf-8');
      const m = content.match(/^name\s*=\s*"([^"]+)"/m);
      if (m) return m[1];
    }
  } catch (_) {}
  return null;
}

function _isRejected(candidate) {
  const lower = (candidate || '').toLowerCase();
  if (!lower) return true;
  try {
    if (lower === os.userInfo().username.toLowerCase()) return true;
  } catch (_) {}
  return REJECT_TOPICS.has(lower);
}

// `mem list-planets` prints two-space-indented names, optional "[status]" tags,
// then indented Goal/State lines. Return the first non-archived planet name.
function _firstNonArchivedPlanet(timeout) {
  try {
    const res = child_process.spawnSync(_memPath(), ['list-planets'], {
      timeout: timeout || 3000,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    if (res.error || res.status !== 0) return null;
    const lines = (res.stdout || '').split(/\r?\n/);
    for (const line of lines) {
      const m = line.match(/^\s{2}(\S[^\[]*?)(?:\s+\[(\w+)\])?\s*$/);
      if (!m) continue;
      const status = (m[2] || 'active').toLowerCase();
      if (status === 'archived') continue;
      return m[1].trim();
    }
  } catch (_) {}
  return null;
}

function _deriveTopic(options) {
  const maxDepth = (options && options.maxDepth) || 3;
  const cwd = (process.env.PWD && fs.existsSync(process.env.PWD)) ? process.env.PWD : process.cwd();
  let current = cwd;
  for (let i = 0; i <= maxDepth; i++) {
    const name = _readProjectName(current);
    if (name) return { topic: name, projectRoot: current, fromProjectFile: true };
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  // No project file found — fall back to basename(cwd).
  const candidate = path.basename(cwd);
  if (!_isRejected(candidate)) {
    return { topic: candidate, projectRoot: cwd, fromProjectFile: false };
  }
  // Rejected candidate with no project file: try the active planet, else keep basename.
  const planet = _firstNonArchivedPlanet((options && options.timeout) || 3000);
  if (planet) return { topic: planet, projectRoot: cwd, fromProjectFile: false };
  return { topic: candidate, projectRoot: cwd, fromProjectFile: false };
}

// fetchContext(options?) -> { topic, context, codeStats } | null
//   options.timeout  (default 3000)  spawn timeout in ms
//   options.maxDepth (default 3)     how far up the tree to look for package.json/pyproject.toml
function fetchContext(options) {
  const timeout = (options && options.timeout) || 3000;
  const { topic, projectRoot } = _deriveTopic(options);
  const mem = _memPath();

  const ctxRes = child_process.spawnSync(mem, ['agent-context', '--topic', topic], {
    timeout,
    encoding: 'utf-8',
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (ctxRes.error || ctxRes.status !== 0) {
    return null;
  }
  const context = (ctxRes.stdout || '').trim();

  // Best-effort code intelligence stats — never fatal.
  let codeStats;
  try {
    const cs = child_process.spawnSync(mem, ['code', 'status', '--root', projectRoot], {
      timeout,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    if (!cs.error && cs.status === 0 && (cs.stdout || '').trim()) {
      codeStats =
        cs.stdout.trim() +
        '\nCode navigation: use code_find(\'sym\'), code_read(filePath=, offset=, limit=), ' +
        'code_explore(\'sym\'), code_files(pattern=) — not grep/glob/read.';
    } else {
      codeStats =
        'Code intelligence not initialized — call code_init(projectRoot) to index, ' +
        'then use code_find/code_read/code_explore/code_files.';
    }
  } catch (_) {
    codeStats =
      'Code intelligence not initialized — call code_init(projectRoot) to index, ' +
      'then use code_find/code_read/code_explore/code_files.';
  }

  return { topic, context, codeStats };
}

// checkRulesIntegrity(agentName, rulesFile, importFile?) -> { intact: boolean, message?: string }
// Verifies the managed rules block is present in the agent's rule file, and — when an
// importFile is supplied (e.g. CLAUDE.md) — that the agent's main config references it.
function checkRulesIntegrity(_agentName, rulesFile, importFile) {
  try {
    if (!rulesFile || !fs.existsSync(rulesFile)) {
      return { intact: false, message: `Rules file not found: ${rulesFile}` };
    }
    const content = fs.readFileSync(rulesFile, 'utf-8');
    if (!content.includes(MARKER_START)) {
      return {
        intact: false,
        message: `Rules file is missing the BaseMem marker (${MARKER_START}). Run: node bin/lib/install.js repair`,
      };
    }
  } catch (e) {
    return { intact: false, message: `Could not read rules file: ${e && e.message}` };
  }
  if (importFile) {
    try {
      if (!fs.existsSync(importFile)) {
        return {
          intact: false,
          message: `Import file not found: ${importFile}. Run: node bin/lib/install.js repair`,
        };
      }
      const imp = fs.readFileSync(importFile, 'utf-8');
      const basename = path.basename(rulesFile);
      if (!imp.includes(MARKER_START) && !imp.includes(basename)) {
        return {
          intact: false,
          message: `Import file ${importFile} does not reference the BaseMem rules. Run: node bin/lib/install.js repair`,
        };
      }
    } catch (e) {
      return { intact: false, message: `Could not read import file: ${e && e.message}` };
    }
  }
  return { intact: true };
}

module.exports = { fetchContext, checkRulesIntegrity, _deriveTopic };
