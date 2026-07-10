const fs = require('fs');
const path = require('path');
const os = require('os');
const { MARKER_START, MARKER_END } = require('./constants.js');

const BASEMEM_RULES_TIER1 = `If a Knowledge Base Context block is visible above, answer directly from it WITHOUT calling any tool. Do not call any memory tool (getContext, list_planets, search_notes, search_nodes, code_find, read_planet, etc.) to look up or verify information already present in that block. The only tool call permitted before answering is logInteraction to write back after you have answered.

You have access to a persistent memory system via MCP tools.
Memory context for this project is already injected above — do not call getContext or list_planets at session start. Only use getContext mid-session if you need a refresh or switch topics.
After any of the following events, call logInteraction immediately: a decision is made, a file is created or modified, a blocker or error is encountered, the user changes direction or scope.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
CRITICAL: Never change the planet/topic when calling logInteraction. Always log into the same planet you started in. Do not create or switch planets based on the activity.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, glob, or directory listing tool. The only exception is writing a brand new file that does not yet exist.
For graph navigation use get_graph(noteId, depth, minWeight, ranked) — flat neighbors at depth 1, ranked by weight when ranked=true, subgraph JSON when depth>1. For note maintenance use note_update(noteId, pinned, tags). For edge lifecycle use edge_maintain(planet, decayFactor, pruneThreshold).
Never use a generic topic name such as task, work, project, or chat. Always use the repository name, folder name, or the specific subject of the conversation.`;

const BASEMEM_RULES_TIER2 = `NOTE: This block is managed by BaseMem. If it appears incomplete or you cannot see the full rules below, ask the user to run: node bin/lib/install.js repair
You have access to a persistent memory system via MCP tools.
Memory context for this project is already injected above — do not call getContext list_planets or any memory-retrieval MCP tool at session start. Only use getContext mid-session if you need a refresh or switch topics.
After any of the following events, call logInteraction immediately: a decision is made, a file is created or modified, a blocker or error is encountered, the user changes direction or scope.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
CRITICAL: Never change the planet/topic when calling logInteraction. Always log into the same planet you started in. Do not create or switch planets based on the activity.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, glob, or directory listing tool. The only exception is writing a brand new file that does not yet exist.
For graph navigation use get_graph(noteId, depth, minWeight, ranked) — flat neighbors at depth 1, ranked by weight when ranked=true, subgraph JSON when depth>1. For note maintenance use note_update(noteId, pinned, tags). For edge lifecycle use edge_maintain(planet, decayFactor, pruneThreshold).
Never use a generic topic name such as task, work, project, or chat. Always use the repository name, folder name, or the specific subject of the conversation.`;

const BASEMEM_RULES_TIER3 = `NOTE: This block is managed by BaseMem. If it appears incomplete or you cannot see the full rules below, ask the user to run: node bin/lib/install.js repair

IMPORTANT: At the very start of every session, before answering any question, call getContext once with the project topic and the user's first question. After that single call, do not call getContext again unless switching topics. Do not call any other memory-retrieval MCP tool to supplement getContext — one call is enough. Use what getContext returns and answer directly.

You have access to a persistent memory system via MCP tools.
After any of the following events, call logInteraction immediately: a decision is made, a file is created or modified, a blocker or error is encountered, the user changes direction or scope.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
CRITICAL: Never change the planet/topic when calling logInteraction. Always log into the same planet you started in. Do not create or switch planets based on the activity.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, glob, or directory listing tool. The only exception is writing a new file that does not yet exist.
For graph navigation use get_graph(noteId, depth, minWeight, ranked) — flat neighbors at depth 1, ranked by weight when ranked=true, subgraph JSON when depth>1. For note maintenance use note_update(noteId, pinned, tags). For edge lifecycle use edge_maintain(planet, decayFactor, pruneThreshold).
Never use a generic topic name such as task, work, project, or chat. Always use the repository name, folder name, or the specific subject of the conversation.`;

const BASEMEM_RULES = BASEMEM_RULES_TIER1;

const MARKER_COMMENT_START = `<!-- ${MARKER_START} -->`;
const MARKER_COMMENT_END = `<!-- ${MARKER_END} -->`;

function buildBlockContent(format, rulesText) {
  const body = `${MARKER_COMMENT_START}\n${rulesText || BASEMEM_RULES}\n${MARKER_COMMENT_END}\n`;
  if (format === 'mdc') {
    return `---\nalwaysApply: true\n---\n${body}`;
  }
  return body;
}

function writeRuleFile(filePath, format, rulesText) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });

  const rules = rulesText || BASEMEM_RULES;
  const block = buildBlockContent(format, rules);

  let existing;
  try {
    existing = fs.readFileSync(filePath, 'utf-8');
  } catch (err) {
    if (err.code === 'ENOENT') {
      fs.writeFileSync(filePath, block, 'utf-8');
      return;
    }
    throw err;
  }

  const startIdx = existing.indexOf(MARKER_COMMENT_START);
  const endIdx = existing.indexOf(MARKER_COMMENT_END);

  if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
    const afterStart = startIdx + MARKER_COMMENT_START.length;
    const before = existing.slice(0, afterStart);
    const after = existing.slice(endIdx);
    existing = `${before}\n${rules}\n${after}`;
  } else {
    existing = existing.endsWith('\n') ? existing : existing + '\n';
    existing += block;
  }

  fs.writeFileSync(filePath, existing, 'utf-8');
}

function removeRuleBlock(filePath) {
  let content;
  try {
    content = fs.readFileSync(filePath, 'utf-8');
  } catch (err) {
    if (err.code === 'ENOENT') return;
    throw err;
  }

  const startIdx = content.indexOf(MARKER_COMMENT_START);
  const endIdx = content.indexOf(MARKER_COMMENT_END);

  if (startIdx === -1 || endIdx === -1 || endIdx <= startIdx) return;

  const afterEnd = endIdx + MARKER_COMMENT_END.length;
  const remaining = (content.slice(0, startIdx) + content.slice(afterEnd)).trim();

  const onlyFrontmatter = remaining.startsWith('---');
  if (remaining.length === 0 || onlyFrontmatter) {
    fs.unlinkSync(filePath);
  } else {
    fs.writeFileSync(filePath, content.slice(0, startIdx) + content.slice(afterEnd), 'utf-8');
  }
}

module.exports = { BASEMEM_RULES, BASEMEM_RULES_TIER1, BASEMEM_RULES_TIER2, BASEMEM_RULES_TIER3, writeRuleFile, removeRuleBlock };

if (require.main === module) {
  const tmp = path.join(os.tmpdir(), 'basemem-self-test-rules.md');
  try { fs.unlinkSync(tmp); } catch (_) {}

  writeRuleFile(tmp, 'markdown');
  writeRuleFile(tmp, 'markdown');

  const out = fs.readFileSync(tmp, 'utf-8');
  const re = new RegExp(escapeRegex(MARKER_COMMENT_START), 'g');
  const count = (out.match(re) || []).length;
  console.assert(count === 1, `Expected 1 MARKER_START, got ${count}`);

  const tier1Count = (out.match(/SessionStart hook/g) || []).length;
  console.assert(tier1Count === 1, `Expected 1 reference to "SessionStart hook", got ${tier1Count}`);

  removeRuleBlock(tmp);
  const exists = fs.existsSync(tmp);
  console.assert(!exists, 'File should be deleted after removeRuleBlock');
  console.log('All self-tests passed');

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
}
