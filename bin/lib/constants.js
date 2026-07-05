const os = require('os');
const path = require('path');

const MARKER_START = 'basemem-managed-start';
const MARKER_END = 'basemem-managed-end';
const FLAG_FILENAME = '.basemem-active';
const HOOKS_SUBDIR = 'hooks';

function getClaudeDir() {
  if (process.env.CLAUDE_CONFIG_DIR) {
    return process.env.CLAUDE_CONFIG_DIR;
  }

  if (process.platform === 'win32') {
    return path.join(process.env.APPDATA, 'claude');
  }

  return path.join(os.homedir(), '.claude');
}

function getAgentPaths() {
  const home = os.homedir();
  const isWindows = process.platform === 'win32';
  const appData = process.env.APPDATA;

  const cursorBase = isWindows
    ? path.join(appData, 'Cursor', 'rules')
    : path.join(home, '.cursor', 'rules');

  const windsurfBase = isWindows
    ? path.join(appData, 'Windsurf', 'rules')
    : path.join(home, '.windsurf', 'rules');

  const continueBase = isWindows
    ? path.join(appData, 'Continue')
    : path.join(home, '.continue');

  const zedBase = isWindows
    ? path.join(appData, 'Zed')
    : path.join(home, '.config', 'zed');

  const opencodeBase = isWindows
    ? path.join(appData, 'opencode')
    : path.join(home, '.config', 'opencode');

  const claudeDir = getClaudeDir();

  return {
    claude: {
      detect: claudeDir,
      install: path.join(claudeDir, 'CLAUDE.md'),
    },
    cursor: {
      detect: cursorBase,
      install: path.join(cursorBase, 'basemem.mdc'),
    },
    windsurf: {
      detect: windsurfBase,
      install: path.join(windsurfBase, 'basemem.md'),
    },
    cline: {
      detect: [path.join(home, '.clinerules'), path.join(home, '.cline')],
      install: path.join(home, '.clinerules', 'basemem.md'),
    },
    copilot: {
      detect: path.join(home, '.github'),
      install: path.join(home, '.github', 'copilot-instructions.md'),
    },
    continue: {
      detect: continueBase,
      install: path.join(continueBase, 'rules', 'basemem.md'),
    },
    zed: {
      detect: zedBase,
      install: path.join(zedBase, 'rules', 'basemem.md'),
    },
    aider: {
      detect: path.join(home, '.aider.conf.yml'),
      install: path.join(home, '.aider.rules.md'),
    },
    codex: {
      detect: path.join(home, '.codex'),
      install: path.join(home, '.codex', 'AGENTS.md'),
    },
    opencode: {
      detect: opencodeBase,
      install: path.join(opencodeBase, 'AGENTS.md'),
    },
    gemini: {
      detect: path.join(home, '.gemini'),
      install: path.join(home, '.gemini', 'GEMINI.md'),
    },
    agy: {
      detect: path.join(home, '.gemini', 'antigravity-cli'),
      install: path.join(home, '.gemini', 'config', 'rules', 'basemem.md'),
    },
    vscode: {
      detect: path.join(home, '.vscode'),
      install: path.join(home, '.vscode', 'basemem.md'),
    },
    kiro: {
      detect: path.join(home, '.kiro'),
      install: path.join(home, '.kiro', 'steering', 'basemem.md'),
    },
    hermes: {
      detect: path.join(home, '.hermes'),
      install: path.join(home, '.hermes', 'HERMES.md'),
    },
  };
}

module.exports = {
  MARKER_START,
  MARKER_END,
  FLAG_FILENAME,
  HOOKS_SUBDIR,
  getClaudeDir,
  getAgentPaths,
};
