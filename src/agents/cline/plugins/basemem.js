import fs from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../../..');

const STOP_PHRASES = ['goodbye', 'exit', 'done for today', 'closing', 'end session', "that's all", 'thanks bye'];
const STOP_NUDGE = '\n\n[MEMORY REMINDER] This session is ending. If you made decisions, created or modified files, or changed direction this session, call logInteraction now with a one-paragraph summary before the session closes. If you already called logInteraction this session, ignore this message.';

let BASEMEM_RULES = '';
try {
  const rulesPath = path.resolve(BASEMEM_ROOT, 'bin/lib/rules.js');
  // rules.js is CJS — use createRequire for interop
  const { createRequire } = await import('module');
  const req = createRequire(rulesPath);
  const rules = req(rulesPath);
  BASEMEM_RULES = rules.BASEMEM_RULES || '';
} catch (_) {}

const memBinDir = process.env.BASEMEM_BIN_DIR || path.join(os.homedir(), '.local', 'bin');
const memPath = path.join(memBinDir, 'mem');

function findProjectName(cwd) {
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

function fetchMemContext(topic) {
  try {
    const result = execSync(`"${memPath}" agent-context --topic "${topic}"`, {
      timeout: 3000,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return result.trim();
  } catch (_) {
    return '';
  }
}

const basememPlugin = {
  name: 'basemem',
  manifest: {
    capabilities: ['hooks'],
  },
  hooks: {
    before_agent_start(context) {
      const cwd = context?.cwd || (process.env.PWD && fs.existsSync(process.env.PWD) ? process.env.PWD : process.cwd());
      const topic = findProjectName(cwd);

      const memContext = fetchMemContext(topic);

      let integrityRules = BASEMEM_RULES;
      const rulesFile = path.join(os.homedir(), '.clinerules', 'basemem.md');
      try {
        if (fs.existsSync(rulesFile)) {
          const content = fs.readFileSync(rulesFile, 'utf-8');
          if (!content.includes('basemem-managed-start')) {
            integrityRules = 'WARNING: BaseMem rules file appears to have been modified or overwritten. Ask the user to run node bin/lib/install.js repair to restore full memory rules.\n\n' + integrityRules;
          }
        } else {
          integrityRules = 'WARNING: BaseMem rules file appears to have been modified or overwritten. Ask the user to run node bin/lib/install.js repair to restore full memory rules.\n\n' + integrityRules;
        }
      } catch (_) {
        integrityRules = 'WARNING: BaseMem rules file appears to have been modified or overwritten. Ask the user to run node bin/lib/install.js repair to restore full memory rules.\n\n' + integrityRules;
      }

      let bootstrap = '';
      if (memContext && !memContext.includes('No stored context found')) {
        bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`;
      }
      bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${integrityRules}\n</EXTREMELY_IMPORTANT>`;
      bootstrap += STOP_NUDGE;

      return {
        type: 'context_injection',
        context: bootstrap,
      };
    },
  },
};

export default basememPlugin;
