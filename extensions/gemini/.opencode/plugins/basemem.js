// BaseMem memory plugin for OpenCode. v2 requires `export default { id, setup }`.

import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(__dirname, '../..');

const extractAndStripFrontmatter = (content) => {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { frontmatter: {}, content };
  const frontmatter = {};
  for (const line of match[1].split('\n')) {
    const colonIdx = line.indexOf(':');
    if (colonIdx > 0) {
      frontmatter[line.slice(0, colonIdx).trim()] = line
        .slice(colonIdx + 1)
        .trim()
        .replace(/^["']|["']$/g, '');
    }
  }
  return { frontmatter, content: match[2] };
};

let cache;

const bootstrapContent = () => {
  if (cache !== undefined) return cache;
  const skillPath = path.join(pluginRoot, 'skills', 'using-basemem', 'SKILL.md');
  if (!fs.existsSync(skillPath)) {
    cache = null;
    return cache;
  }
  const { content } = extractAndStripFrontmatter(fs.readFileSync(skillPath, 'utf8'));
  cache = `<EXTREMELY_IMPORTANT>
You have BaseMem memory available.

**IMPORTANT: The using-basemem skill content is included below. It is ALREADY LOADED - you are currently following it. Do NOT use the skill tool to load "using-basemem" again.**

${content}

**BaseMem tools:**
- \`getContext\` — load memory at session start
- \`log_interaction\` — persist decisions, facts, state, activity
- \`update_planet\` — create/update topic
- \`read_planet\` — planet details
- \`list_planets\` — discover topics
- \`search_nodes\` — full-text search
</EXTREMELY_IMPORTANT>`;
  return cache;
};

export default {
  id: 'basemem.gemini-extension',

  async setup(ctx) {
    const bootstrapped = new Set();
    const onModelRequest = (event) => {
      try {
        if (!event.sessionID || bootstrapped.has(event.sessionID)) return;
        const text = bootstrapContent();
        if (!text) return;
        bootstrapped.add(event.sessionID);
        event.system.push({ type: 'text', text });
      } catch (_) {}
    };

    await ctx.session.hook('context', onModelRequest);
    await ctx.session.hook('compaction', onModelRequest);
    await ctx.session.hook('generate', onModelRequest);

    const controller = new AbortController();
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          if (event?.type === 'session.deleted' && event.data?.sessionID) {
            bootstrapped.delete(event.data.sessionID);
          }
        }
      } catch (_) {}
    })();

    return () => controller.abort();
  },
};
