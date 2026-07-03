import fs from 'fs';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rulesPath = path.resolve(__dirname, '../../bin/lib/rules.js');

let BASEMEM_RULES = '';
try {
  ({ BASEMEM_RULES } = await import(rulesPath));
} catch (_) {}

const flagFile = path.join(os.homedir(), '.config/opencode/.basemem-active');

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

        if (output?.messages?.length) {
          const firstUser = output.messages.find(m => m.info?.role === 'user');
          if (firstUser && firstUser.parts?.length) {
            const bootstrap = `<EXTREMELY_IMPORTANT>
You have BaseMem memory available via MCP tools.

${BASEMEM_RULES}
</EXTREMELY_IMPORTANT>`;

            if (!firstUser.parts.some(p => p.type === 'text' && p.text.includes('EXTREMELY_IMPORTANT'))) {
              firstUser.parts.unshift({ ...firstUser.parts[0], text: bootstrap });
            }
          }
        }
      }

      if (isUser) {
        const reminder = '\n\n[Memory Reminder] Use MCP memory tools (getContext, logInteraction, code_find, etc.) and call getContext before answering project questions.';
        if (output?.messages?.length) {
          const lastUser = output.messages.findLast(m => m.info?.role === 'user');
          if (lastUser && lastUser.parts?.length) {
            const textPart = lastUser.parts.find(p => p.type === 'text');
            if (textPart) textPart.text += reminder;
          }
        }
      }
    },
  };
};
