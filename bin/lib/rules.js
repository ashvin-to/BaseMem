const fs = require('fs');
const path = require('path');
const os = require('os');
const { MARKER_START, MARKER_END } = require('./constants.js');

const BASEMEM_RULES_CORE = `Memory context injected — do not call getContext at session start. Log decisions: logInteraction(topic, decision="what and why"). End sessions: logInteraction(topic, summary="...", activity="done"). Code: use code_find/code_read/code_explore/code_files instead of grep/glob/read — they auto-index on first use. For plain text search use code_find(query, grep=True). Empty results → code_init first. Review: use get_review_context(files). Check skills/ before multi-step tasks. Topic = repo folder name.`;

const BASEMEM_RULES_TIER1 = BASEMEM_RULES_CORE;

const BASEMEM_RULES_TIER2 = `NOTE: BaseMem rules may be incomplete — run: node bin/lib/install.js repair
Call getContext exactly once at session start. Then answer directly — do not call search_notes/search_nodes/read_planets.
${BASEMEM_RULES_CORE}`;

const BASEMEM_RULES_TIER3 = `NOTE: BaseMem rules may be incomplete — run: node bin/lib/install.js repair
Call getContext exactly once at session start. Then answer directly — do not call search_notes/search_nodes/read_planets.
Max one memory read tool call per user message.
${BASEMEM_RULES_CORE}`;

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

module.exports = { BASEMEM_RULES, BASEMEM_RULES_CORE, BASEMEM_RULES_TIER1, BASEMEM_RULES_TIER2, BASEMEM_RULES_TIER3, writeRuleFile, removeRuleBlock };

if (require.main === module) {
  const tmp = path.join(os.tmpdir(), 'basemem-self-test-rules.md');
  try { fs.unlinkSync(tmp); } catch (_) {}

  writeRuleFile(tmp, 'markdown');
  writeRuleFile(tmp, 'markdown');

  const out = fs.readFileSync(tmp, 'utf-8');
  const re = new RegExp(escapeRegex(MARKER_COMMENT_START), 'g');
  const count = (out.match(re) || []).length;
  console.assert(count === 1, `Expected 1 MARKER_START, got ${count}`);

  const tier1Count = (out.match(/logInteraction/g) || []).length;
  console.assert(tier1Count >= 1, `Expected >=1 reference to "logInteraction", got ${tier1Count}`);

  removeRuleBlock(tmp);
  const exists = fs.existsSync(tmp);
  console.assert(!exists, 'File should be deleted after removeRuleBlock');
  console.log('All self-tests passed');

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
}
