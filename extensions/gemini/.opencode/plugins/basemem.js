/**
 * BaseMem memory plugin for OpenCode
 *
 * Injects BaseMem bootstrap context into the first user message.
 */

import path from 'path';
import fs from 'fs';
import os from 'os';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(__dirname, '../..');

const extractAndStripFrontmatter = (content) => {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { frontmatter: {}, content };
  const frontmatterStr = match[1];
  const body = match[2];
  const frontmatter = {};
  for (const line of frontmatterStr.split('\n')) {
    const colonIdx = line.indexOf(':');
    if (colonIdx > 0) {
      const key = line.slice(0, colonIdx).trim();
      const value = line.slice(colonIdx + 1).trim().replace(/^["']|["']$/g, '');
      frontmatter[key] = value;
    }
  }
  return { frontmatter, content: body };
};

let _bootstrapCache = undefined;

export const BaseMemPlugin = async ({ client, directory }) => {
  const getBootstrapContent = () => {
    if (_bootstrapCache !== undefined) return _bootstrapCache;

    const skillPath = path.join(pluginRoot, 'skills', 'using-basemem', 'SKILL.md');
    if (!fs.existsSync(skillPath)) {
      _bootstrapCache = null;
      return null;
    }

    const fullContent = fs.readFileSync(skillPath, 'utf8');
    const { content } = extractAndStripFrontmatter(fullContent);

    const toolMapping = `**Tool Mapping for OpenCode:**
BaseMem MCP tools are available in your MCP tool palette:
- \`list_planets\` — discover topics
- \`get_agent_context\` — get memory for a topic
- \`add_note\` — persist decisions/facts
- \`update_planet\` — save progress
- \`log_turn\` — lightweight activity tracking
- \`search_nodes\` — full-text search
- \`search_notes\` — search by planet/type
- \`get_node\` — read full node content
- \`read_planet\` — read all details of a topic`;

    _bootstrapCache = `<EXTREMELY_IMPORTANT>
You have BaseMem memory available.

**IMPORTANT: The using-basemem skill content is included below. It is ALREADY LOADED - you are currently following it. Do NOT use the skill tool to load "using-basemem" again.**

${content}

${toolMapping}
</EXTREMELY_IMPORTANT>`;

    return _bootstrapCache;
  };

  return {
    'experimental.chat.messages.transform': async (_input, output) => {
      const bootstrap = getBootstrapContent();
      if (!bootstrap || !output.messages.length) return;
      const firstUser = output.messages.find(m => m.info.role === 'user');
      if (!firstUser || !firstUser.parts.length) return;
      if (firstUser.parts.some(p => p.type === 'text' && p.text.includes('EXTREMELY_IMPORTANT'))) return;
      const ref = firstUser.parts[0];
      firstUser.parts.unshift({ ...ref, type: 'text', text: bootstrap });
    }
  };
};
