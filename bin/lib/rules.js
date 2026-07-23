const fs = require('fs');
const path = require('path');
const os = require('os');
const { MARKER_START, MARKER_END } = require('./constants.js');

const BASEMEM_RULES_TIER1 = `Memory context injected above — do not call getContext or list_planets at session start. After any decision, edit, or blocker: call logInteraction(topic, decision='full sentence explaining what was decided and why'). Always include the decision field with a complete sentence — never call logInteraction with topic only. End every session with a one-paragraph logInteraction summary. Code exploration: use code_find, code_read, code_explore, code_files instead of grep, glob, read, or directory listing. Load the explore-codebase skill (skills/explore-codebase/SKILL.md) before any multi-file exploration task — it gives the exact tool call sequence. If code tools return empty run code_init first. For review and blast radius: use get_review_context(files, query) — replaces code_find + code_impact + code_trace for common review tasks. Skills: before multi-step tasks check if a skill exists (code-review, session-start, explore-codebase, debug-issue, task-workflow) — read its SKILL.md and follow the workflow table. Topic must be the repo or folder name, never generic names like task, work, project, or chat.`;

const BASEMEM_RULES_TIER2 = `NOTE: This block is managed by BaseMem. If it appears incomplete or you cannot see the full rules below, ask the user to run: node bin/lib/install.js repair
Call getContext exactly once at session start with the project topic and user's first question. After that single call answer directly — do not call search_notes, search_nodes, read_planet, or list_planets to supplement it.
Memory context injected above — do not call getContext or list_planets at session start. After any decision, edit, or blocker: call logInteraction(topic, decision='full sentence explaining what was decided and why'). Always include the decision field with a complete sentence — never call logInteraction with topic only. End every session with a one-paragraph logInteraction summary. Code exploration: use code_find, code_read, code_explore, code_files instead of grep, glob, read, or directory listing. Load the explore-codebase skill (skills/explore-codebase/SKILL.md) before any multi-file exploration task — it gives the exact tool call sequence. If code tools return empty run code_init first. For review and blast radius: use get_review_context(files, query) — replaces code_find + code_impact + code_trace for common review tasks. Skills: before multi-step tasks check if a skill exists (code-review, session-start, explore-codebase, debug-issue, task-workflow) — read its SKILL.md and follow the workflow table. Topic must be the repo or folder name, never generic names like task, work, project, or chat.`;

const BASEMEM_RULES_TIER3 = `NOTE: This block is managed by BaseMem. If it appears incomplete or you cannot see the full rules below, ask the user to run: node bin/lib/install.js repair
Call getContext exactly once at session start with the project topic and user's first question. After that single call answer directly — do not call search_notes, search_nodes, read_planet, or list_planets to supplement it.
Never make more than one memory read tool call per user message.
Memory context injected above — do not call getContext or list_planets at session start. After any decision, edit, or blocker: call logInteraction(topic, decision='full sentence explaining what was decided and why'). Always include the decision field with a complete sentence — never call logInteraction with topic only. End every session with a one-paragraph logInteraction summary. Code exploration: use code_find, code_read, code_explore, code_files instead of grep, glob, read, or directory listing. Load the explore-codebase skill (skills/explore-codebase/SKILL.md) before any multi-file exploration task — it gives the exact tool call sequence. If code tools return empty run code_init first. For review and blast radius: use get_review_context(files, query) — replaces code_find + code_impact + code_trace for common review tasks. Skills: before multi-step tasks check if a skill exists (code-review, session-start, explore-codebase, debug-issue, task-workflow) — read its SKILL.md and follow the workflow table. Topic must be the repo or folder name, never generic names like task, work, project, or chat.`;

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
