import fs from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';

const BASEMEM_RULES = `CRITICAL: You MUST answer the user's question directly from the KNOWLEDGE_BASE_CONTEXT block above. DO NOT call mem_getContext, mem_list_planets, or any memory-retrieval MCP tool — the context is already loaded.
Call mem_logInteraction after any decision, file change, blocker, or scope change. At session end, call mem_logInteraction with a one-paragraph summary.
For code: use mem_code_find, mem_code_read, mem_code_explore, mem_code_files (NOT file read/grep/glob).
For graph: mem_get_graph. For notes: mem_note_update. For edges: mem_edge_maintain.
Never use generic topic names — always use the repo/folder name.`;

const STOP_PHRASES = ['goodbye', 'exit', 'done for today', 'closing', 'end session', "that's all", 'thanks bye'];
const STOP_NUDGE = '\n\n[MEMORY REMINDER] This session is ending. If you made decisions, created or modified files, or changed direction this session, call logInteraction now with a one-paragraph summary before the session closes. If you already called logInteraction this session, ignore this message.';

const flagFile = path.join(os.homedir(), '.config', 'opencode', '.basemem-active');

function findProjectName() {
  const cwd = process.cwd();
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

      let bootstrap = '';
      if (memContext) {
        bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n</KNOWLEDGE_BASE_CONTEXT>\n\n`;
      }
      bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${BASEMEM_RULES}\n</EXTREMELY_IMPORTANT>`;

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

        let bootstrap = '';
        if (memContext) {
          bootstrap += `<KNOWLEDGE_BASE_CONTEXT>\n${memContext}\n\n`;
        }
        bootstrap += `<EXTREMELY_IMPORTANT>\nYou have BaseMem memory available via MCP tools.\n\n${BASEMEM_RULES}\n</EXTREMELY_IMPORTANT>\n\n`;

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
  };
};
