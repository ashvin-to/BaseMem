import fs from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rulesPath = path.resolve(__dirname, '../../bin/lib/rules.js');

let BASEMEM_RULES = '';
try {
  ({ BASEMEM_RULES } = await import(rulesPath));
} catch (_) {}

const xdgConfig = process.env.XDG_CONFIG_HOME && process.env.XDG_CONFIG_HOME.trim().length > 0
  ? process.env.XDG_CONFIG_HOME
  : path.join(os.homedir(), '.config');
const flagFile = path.join(xdgConfig, 'devin', '.basemem-active');

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

export const BaseMemPlugin = async ({ client, directory }) => {
  let injectedFirst = false;

  return {
    'chat.message': async (input, output) => {
      const isUser = input?.message?.parts?.some(
        p => p.type === 'text' && p.role === 'user'
      );

      if (!injectedFirst && isUser) {
        injectedFirst = true;

        try {
          const dir = path.dirname(flagFile);
          if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
          fs.writeFileSync(flagFile, 'active', 'utf-8');
        } catch (_) {}

        let memContext = '';
        try {
          const projectName = findProjectName();
          if (projectName) {
            memContext = execSync(`mem agent-context --topic "${projectName}"`, {
              timeout: 3000,
              encoding: 'utf-8',
              stdio: ['ignore', 'pipe', 'pipe'],
            }).trim();
          }
        } catch (_) {}

        if (output?.messages?.length) {
          const firstUser = output.messages.find(m => m.info?.role === 'user');
          if (firstUser && firstUser.parts?.length) {
            let bootstrap = '';
            if (memContext) {
              bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`;
            }
            bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${BASEMEM_RULES}\n</EXTREMELY_IMPORTANT>`;

            if (!firstUser.parts.some(p => p.type === 'text' && p.text.includes('EXTREMELY_IMPORTANT'))) {
              firstUser.parts.unshift({ ...firstUser.parts[0], text: bootstrap });
            }
          }
        }
      }

      if (isUser) {
        const reminder = '\n\n[Memory Reminder] BaseMem memory is active — use mem_*/code_* tools; log edits with logInteraction(topic=<repo>).';
        // Per-prompt recall: FTS5 memory + code hits for THIS user message.
        let recall = '';
        try {
          const promptText = input?.message?.parts?.filter(p => p.type === 'text').map(p => p.text || '').join('\n') || '';
          const topic = findProjectName();
          if (promptText.trim().length >= 8) {
            const { spawnSync } = await import('child_process');
            const res = spawnSync('mem', ['prompt-context', '--topic', topic, '--query', promptText.slice(0, 2000)],
              { timeout: 4000, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
            if (!res.error && res.status === 0 && (res.stdout || '').trim()) {
              recall = `\n\n<BASEMEM_PROMPT_CONTEXT>\n${res.stdout.trim().slice(0, 2000)}\n</BASEMEM_PROMPT_CONTEXT>`;
            }
          }
        } catch (_) { recall = ''; }
        if (output?.messages?.length) {
          const lastUser = output.messages.findLast(m => m.info?.role === 'user');
          if (lastUser && lastUser.parts?.length) {
            const textPart = lastUser.parts.find(p => p.type === 'text');
            if (textPart) textPart.text += reminder + recall;
          }
        }
      }
    },
  };
};
