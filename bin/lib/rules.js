const fs = require('fs');
const path = require('path');
const os = require('os');
const { MARKER_START, MARKER_END } = require('./constants.js');

const BASEMEM_RULES_TIER1 = `Memory context for this project is already injected above by the SessionStart hook — do not call getContext, list_planets, or any memory-retrieval MCP tool.

BaseMem memory is active — use mem_*/code_* MCP tools so actions are remembered.
After any file edit, commit, blocker, or direction change: call logInteraction(topic=<repo/folder>, ...). End each session with a one-paragraph logInteraction summary.
For code: use code_find/code_read/code_explore/code_files (not native read/grep/glob). If they return empty for a known symbol, run code_init first, then native tools are allowed. code_read needs filePath (NOT 'path'). For blast radius and review context: use get_review_context(files, query) — one call replaces code_find + code_impact + code_trace for the common review workflow. Use code_impact or code_trace directly only for deep analysis.
SKILLS: Named workflows are available as skills. Before starting a multi-step task, check if a skill exists: code-review, session-start, explore-codebase, debug-issue, task-workflow. Using a skill reduces tool calls and token usage. Skills are installed at ~/.claude/skills/ (or agent equivalent). Load a skill by reading its SKILL.md and following the workflow table.
Pass 'topic' explicitly to memory tools; never use generic names like task/project/chat.`;

const BASEMEM_RULES_TIER2 = `NOTE: This block is managed by BaseMem. If it appears incomplete or you cannot see the full rules below, ask the user to run: node bin/lib/install.js repair
You have access to a persistent memory system via MCP tools.
Memory context for this project is already injected above — do not call getContext list_planets or any memory-retrieval MCP tool at session start. Only use getContext mid-session if you need a refresh or switch topics.
After any of the following events, call logInteraction immediately: a tracked source/config/doc file is created or modified, a commit is made, a blocker or error occurs, or the user changes direction or scope. Always pass 'topic' explicitly (e.g. the repo/folder name) rather than relying on auto-detection.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
CRITICAL: Always log into the planet matching the current working directory. Pass 'topic' explicitly to memory tools (do not rely on auto-detection). Do not stay locked to a previous topic.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, glob, or directory listing tool. The only exception is writing a brand new file that does not yet exist. If code_find/code_read return nothing for a known-existing symbol, run code_init first; if still empty, read/grep/glob are permitted. For blast radius and review context: use get_review_context(files, query) — one call replaces code_find + code_impact + code_trace for the common review workflow. Use code_impact or code_trace directly only for deep analysis.
  IMPORTANT: code_read REQUIRES a 'filePath' argument (the file path to read) — NOT 'path'. Example: code_read(filePath='src/main.py'). code_find takes an optional 'filePath' to filter to one file.
SKILLS: Named workflows are available as skills. Before starting a multi-step task, check if a skill exists: code-review, session-start, explore-codebase, debug-issue, task-workflow. Using a skill reduces tool calls and token usage.
For graph navigation use get_graph(noteId, depth, minWeight, ranked) — flat neighbors at depth 1, ranked by weight when ranked=true, subgraph JSON when depth>1. For note maintenance use note_update(noteId, pinned, tags). For edge lifecycle use edge_maintain(planet, decayFactor, pruneThreshold).
Never use a generic topic name such as task, work, project, or chat. Always use the repository name, folder name, or the specific subject of the conversation.`;

const BASEMEM_RULES_TIER3 = `NOTE: This block is managed by BaseMem. If it appears incomplete or you cannot see the full rules below, ask the user to run: node bin/lib/install.js repair

IMPORTANT: At the very start of every session, before answering any question, call getContext once with the project topic and the user's first question. After that single call, do not call getContext again unless switching topics. Do not call any other memory-retrieval MCP tool to supplement getContext — one call is enough. Use what getContext returns and answer directly.

You have access to a persistent memory system via MCP tools.
After any of the following events, call logInteraction immediately: a tracked source/config/doc file is created or modified, a commit is made, a blocker or error occurs, or the user changes direction or scope. Always pass 'topic' explicitly (e.g. the repo/folder name) rather than relying on auto-detection.
At the end of every session: call logInteraction with a one-paragraph summary of what was done.
CRITICAL: Always log into the planet matching the current working directory. Pass 'topic' explicitly to memory tools (do not rely on auto-detection). Do not stay locked to a previous topic.
For all code exploration: use code_find, code_read, code_explore, code_files instead of any file read, grep, glob, or directory listing tool. The only exception is writing a new file that does not yet exist. If code_find/code_read return nothing for a known-existing symbol, run code_init first; if still empty, read/grep/glob are permitted. For blast radius and review context: use get_review_context(files, query) — one call replaces code_find + code_impact + code_trace for the common review workflow. Use code_impact or code_trace directly only for deep analysis.
  IMPORTANT: code_read REQUIRES a 'filePath' argument (the file path to read) — NOT 'path'. Example: code_read(filePath='src/main.py'). code_find takes an optional 'filePath' to filter to one file.
SKILLS: Named workflows are available as skills. Before starting a multi-step task, check if a skill exists: code-review, session-start, explore-codebase, debug-issue, task-workflow. Using a skill reduces tool calls and token usage.
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
