import fs from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(__dirname);

const BASEMEM_ROOT = process.env.BASEMEM_ROOT || path.resolve(__dirname, '../../..');

const STOP_PHRASES = ['goodbye', 'exit', 'done for today', 'closing', 'end session', "that's all", 'thanks bye'];
const STOP_NUDGE = '\n\n[MEMORY REMINDER] This session is ending. If you made decisions, created or modified files, or changed direction this session, call logInteraction now with a one-paragraph summary before the session closes. If you already called logInteraction this session, ignore this message.';

let BASEMEM_RULES = '';
try {
  const rulesPath = path.resolve(BASEMEM_ROOT, 'bin/lib/rules.js');
  ({ BASEMEM_RULES } = await import(rulesPath));
} catch (_) {}

const flagFile = path.join(os.homedir(), '.config', 'kilo', '.basemem-active');

function findProjectName() {
  const cwd = (process.env.PWD && fs.existsSync(process.env.PWD)) ? process.env.PWD : process.cwd();
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

async function fetchMemContext(topic) {
  try {
    const result = execSync(`mem agent-context --topic "${topic}"`, {
      timeout: 3000,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return result.trim();
  } catch (_) {
    return '';
  }
}

function fetchRecallSync(promptText, topic) {
  if (!promptText || promptText.trim().length < 8) return '';
  try {
    const { spawnSync } = require('child_process');
    const res = spawnSync('mem',
      ['prompt-context', '--topic', topic, '--query', promptText.slice(0, 2000)],
      { timeout: 4000, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
    if (res.error || res.status !== 0) return '';
    return (res.stdout || '').trim().slice(0, 2000);
  } catch (_) {
    return '';
  }
}

const BaseMemPlugin = async ({ client, directory }) => {
  return {
    'experimental.chat.messages.transform': async (_input, output) => {
      if (!output.messages.length) return;
      const firstUser = output.messages.find(m => m.info?.role === 'user');
      if (!firstUser || !firstUser.parts.length) return;
      if (firstUser.parts.some(p => p.type === 'text' && p.text.includes('EXTREMELY_IMPORTANT'))) return;

      try {
        const dir = path.dirname(flagFile);
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(flagFile, 'active', 'utf-8');
      } catch (_) {}

      const projectName = findProjectName();
      const memContext = projectName ? await fetchMemContext(projectName) : '';

      let integrityRules = BASEMEM_RULES;
      const rulesFile = path.join(os.homedir(), '.config', 'kilo', 'basemem.md');
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
      if (memContext) {
        bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`;
      }
      bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${integrityRules}\n</EXTREMELY_IMPORTANT>`;

      const ref = firstUser.parts[0];
      firstUser.parts.unshift({ ...ref, type: 'text', text: bootstrap });
    },
    'chat.message': async (input, output) => {
      const isUser = input?.message?.parts?.some(
        p => p.type === 'text' && p.role === 'user'
      );

      const userText = input?.message?.parts?.filter(p => p.type === 'text').map(p => (p.text || '').toLowerCase()).join(' ') || '';
      if (isUser && STOP_PHRASES.some(phrase => userText.includes(phrase))) {
        if (output?.messages?.length) {
          const lastAssistant = [...output.messages].reverse().find(m => m.info?.role === 'assistant');
          if (lastAssistant && lastAssistant.parts?.length) {
            const textPart = lastAssistant.parts.find(p => p.type === 'text');
            if (textPart) {
              textPart.text = STOP_NUDGE + '\n\n' + textPart.text;
            }
          }
        }
      }

      if (isUser && output?.messages?.length) {
        const lastUser = output.messages.findLast(m => m.info?.role === 'user');
        if (lastUser && lastUser.parts?.length) {
          const textPart = lastUser.parts.find(p => p.type === 'text');
          if (textPart) {
            // Per-prompt recall: FTS5 memory + code hits for THIS user message.
            let recall = '';
            try { recall = fetchRecallSync(textPart.text || '', findProjectName()); } catch (_) { recall = ''; }
            textPart.text += '\n\n[Memory Reminder] BaseMem memory is active — use mem_*/code_* tools; log edits with logInteraction(topic=<repo>).'
              + (recall ? `\n\n<BASEMEM_PROMPT_CONTEXT>\n${recall}\n</BASEMEM_PROMPT_CONTEXT>` : '');
          }
        }
      }
    },
  };
};

export default { id: 'basemem', server: BaseMemPlugin };
