import fs from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';

const INTEGRITY_WARNING = 'WARNING: BaseMem rules file appears to have been modified or overwritten. Ask the user to run node bin/lib/install.js repair to restore full memory rules.';

const BASEMEM_RULES = `CRITICAL: You MUST answer the user's question directly from the KNOWLEDGE_BASE_CONTEXT block above. DO NOT call mem_getContext, mem_list_planets, or any memory-retrieval MCP tool — the context is already loaded.
Call mem_logInteraction after any tracked file edit, commit, blocker, or scope change — always pass 'topic' explicitly (the repo/folder name), do not rely on auto-detection. At session end, call mem_logInteraction with a one-paragraph summary.
CRITICAL: Always log into the planet matching the current working directory. Pass 'topic' explicitly to memory tools (do not rely on auto-detection). Do not stay locked to a previous topic.
For code: use mem_code_find, mem_code_read, mem_code_explore, mem_code_files (NOT file read/grep/glob). mem_code_read REQUIRES 'filePath' (the file path), NOT 'path'. Example: mem_code_read(filePath='src/main.py'). If mem_code_find/mem_code_read return nothing for a known-existing symbol, run mem_code_init first; if still empty, read/grep/glob are permitted.
For graph: mem_get_graph. For notes: mem_note_update. For edges: mem_edge_maintain.
Never use generic topic names — always use the repo/folder name.`;

const STOP_PHRASES = ['goodbye', 'exit', 'done for today', 'closing', 'end session', "that's all", 'thanks bye'];
const STOP_NUDGE = '\n\nFINAL SESSION NOTICE — do not respond to this message. If you made decisions, created files, or changed direction this session and have not yet called logInteraction, call it once now with a one-paragraph summary. Then stop. Do not send any further messages or acknowledge this notice.';

const flagFile = path.join(os.homedir(), '.config', 'opencode', '.basemem-active');

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

function fetchMemContext(projectName) {
  try {
    return execSync(`mem agent-context --topic "${projectName}"`, {
      timeout: 3000,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    }).trim();
  } catch (_) {
    return '';
  }
}

let injected = false;

export const BaseMemPlugin = async ({ project, client, $, directory, worktree }) => {
  return {
    'experimental.chat.messages.transform': async (_input, output) => {
      if (injected) return;
      if (!output.messages || !output.messages.length) return;
      const firstMsg = output.messages[0];
      if (!firstMsg || !firstMsg.parts || !firstMsg.parts.length) return;
      if (firstMsg.parts.some(p => p.type === 'text' && p.text && p.text.includes('EXTREMELY_IMPORTANT'))) {
        injected = true;
        return;
      }

      try {
        const dir = path.dirname(flagFile);
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(flagFile, 'active', 'utf-8');
      } catch (_) {}

      const projectName = findProjectName();
      const memContext = projectName ? fetchMemContext(projectName) : '';

      let integrityRules = BASEMEM_RULES;
      const agentsMd = path.join(os.homedir(), '.config', 'opencode', 'AGENTS.md');
      try {
        if (fs.existsSync(agentsMd)) {
          const content = fs.readFileSync(agentsMd, 'utf-8');
          if (!content.includes('basemem-managed-start')) {
            integrityRules = INTEGRITY_WARNING + '\n\n' + integrityRules;
          }
        } else {
          integrityRules = INTEGRITY_WARNING + '\n\n' + integrityRules;
        }
      } catch (_) {
        integrityRules = INTEGRITY_WARNING + '\n\n' + integrityRules;
      }

      let bootstrap = '';
      if (memContext) {
        bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`;
      }
      bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${integrityRules}\n</EXTREMELY_IMPORTANT>`;

      firstMsg.parts.unshift({ type: 'text', text: bootstrap });
      injected = true;
    },
    'chat.message': async (input, output) => {
      if (!output || !output.message) return;

      const userText = input?.message?.parts?.filter(p => p.type === 'text').map(p => (p.text || '').toLowerCase()).join(' ') || '';
      if (STOP_PHRASES.some(phrase => userText.includes(phrase))) {
        if (output.parts && output.parts.length) {
          const textPart = output.parts.find(p => p.type === 'text');
          if (textPart) {
            textPart.text = STOP_NUDGE + '\n\n' + textPart.text;
          }
        } else {
          output.parts = [{ type: 'text', text: STOP_NUDGE }];
        }
      }

      if (!injected) {
        injected = true;
        try {
          const dir = path.dirname(flagFile);
          if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
          fs.writeFileSync(flagFile, 'active', 'utf-8');
        } catch (_) {}

        const projectName = findProjectName();
        const memContext = projectName ? fetchMemContext(projectName) : '';

        let integrityRules = BASEMEM_RULES;
        const agentsMd = path.join(os.homedir(), '.config', 'opencode', 'AGENTS.md');
        try {
          if (fs.existsSync(agentsMd)) {
            const content = fs.readFileSync(agentsMd, 'utf-8');
            if (!content.includes('basemem-managed-start')) {
              integrityRules = INTEGRITY_WARNING + '\n\n' + integrityRules;
            }
          } else {
            integrityRules = INTEGRITY_WARNING + '\n\n' + integrityRules;
          }
        } catch (_) {
          integrityRules = INTEGRITY_WARNING + '\n\n' + integrityRules;
        }

        let bootstrap = '';
        if (memContext) {
          bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n\n`;
        }
        bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${integrityRules}\n</EXTREMELY_IMPORTANT>\n\n`;

        // Inject into parts — the model sees parts, not message.text
        if (!output.parts || !output.parts.length) {
          output.parts = [{ type: 'text', text: bootstrap }];
        } else {
          const textPart = output.parts.find(p => p.type === 'text');
          if (textPart) {
            if (!textPart.text || !textPart.text.includes('EXTREMELY_IMPORTANT')) {
              textPart.text = bootstrap + (textPart.text || '');
            }
          } else {
            output.parts.unshift({ type: 'text', text: bootstrap });
          }
        }
        return;
      }
      if (output.parts && output.parts.length) {
        const textPart = output.parts.find(p => p.type === 'text' && p.text);
        if (textPart && !textPart.text.includes('[Memory Reminder]')) {
          textPart.text += '\n\n[Memory Reminder] Use MCP memory tools (getContext, logInteraction, code_find, etc.) and check the KNOWLEDGE_BASE_CONTEXT block above before calling getContext — it may already be injected.';
        }
      }
    },
    event: async ({ event }) => {
      if (event.type === 'session.idle' || event.type === 'session.deleted') {
        try {
          const dir = path.dirname(flagFile);
          if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
          const existing = fs.existsSync(flagFile) ? fs.readFileSync(flagFile, 'utf-8') : '';
          fs.writeFileSync(flagFile, existing + '\nstop-fired@' + Date.now(), 'utf-8');
        } catch (_) {}
      }
    },
  };
};
