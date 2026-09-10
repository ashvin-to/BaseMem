import fs from 'fs';
import path from 'path';
import os from 'os';
import { execSync } from 'child_process';

const INTEGRITY_WARNING = 'WARNING: BaseMem rules file appears to have been modified or overwritten. Ask the user to run node bin/lib/install.js repair to restore full memory rules.';

const { BASEMEM_RULES_CORE: BASEMEM_RULES } = require('../../../bin/lib/rules.js');

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

function fetchPromptContextSync(promptText, topic) {
  if (!promptText || promptText.trim().length < 8) return '';
  try {
    const { spawnSync } = require('child_process');
    const memBin = process.env.BASEMEM_BIN_DIR
      ? path.join(process.env.BASEMEM_BIN_DIR, 'mem')
      : 'mem';
    const res = spawnSync(memBin,
      ['prompt-context', '--topic', topic || findProjectName(), '--query', promptText.slice(0, 2000)],
      { timeout: 4000, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
    if (res.error || res.status !== 0) return '';
    return (res.stdout || '').trim().slice(0, 2000);
  } catch (_) {
    return '';
  }
}

function recallBlock(promptText, topic) {
  const hits = fetchPromptContextSync(promptText, topic);
  return hits ? `\n\n<BASEMEM_PROMPT_CONTEXT>\n${hits}\n</BASEMEM_PROMPT_CONTEXT>` : '';
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
          // Query-aware recall: FTS5 memory + code hits for THIS prompt.
          const projectName = findProjectName();
          let recall = '';
          try { recall = recallBlock(textPart.text, projectName); } catch (_) { recall = ''; }
          textPart.text += '\n\n[Memory Reminder] BaseMem memory is active — use mem_*/code_* tools; log edits with logInteraction(topic=<repo>).' + recall;
        }
      }
    },
    'chat.tool.result': async (input, output) => {
      try {
        const toolName = input?.tool?.name || input?.name || '';
        const toolInput = input?.tool?.input || input?.input || {};
        if (!toolName) return;
        const payload = JSON.stringify({ tool: toolName, params: toolInput, agent_id: 'opencode' });
        const { spawnSync } = await import('child_process');
        const path = await import('path');
        const ROOT = path.resolve(__dirname, '../../..');
        const CAPTURE_PY = path.join(ROOT, 'bin/lib/capture_native.py');
        const PYTHON = process.env.BASEMEM_PYTHON || process.env.MCP_PYTHON || 'python3';
        spawnSync(PYTHON, [CAPTURE_PY], { input: payload, stdio: ['pipe', 'ignore', 'ignore'] });
      } catch (_) {
        // Silent: capture must never break the agent's tool flow.
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
