const fs = require('fs');
const path = require('path');
const os = require('os');
const { MARKER_START, MARKER_END } = require('./constants.js');

const BASEMEM_RULES_BODY = `Topic = repo folder name; pass it to every memory tool call.
Code task? Choose the lightest path: for a known target, inspect the exact file and nearby tests/callers directly; for unfamiliar or cross-file work, Call code_find FIRST. Use code_find(grep=True) for literal flags, JSON keys, commands, docs, and config values. Empty result → code_init(projectRoot) once, then retry; reindex after multiple symbol/signature additions, renames, or stale results. Read windows with code_read(filePath, offset, limit<=50); trace callers with code_explore; list files with code_files; review diffs with get_review_context(files).
Keep small tasks bounded: code_find → code_init if empty/stale → code_read exact source → inspect artifacts → run focused tests; use verify_change for an explicit evidence bundle. Memory preserves why and durable constraints; source, artifacts, and tests establish current behavior. Memory is context, not verification. Label conclusions as memory, source, artifact, test, or inference. Log only meaningful decisions/corrections, not routine observations.
Decision made, fix applied, or fact learned? Call logInteraction(topic, decision="what + why") NOW — never defer it to session end.
Session ending? Call logInteraction(topic, summary="...", activity="done").
Check skills/ before multi-step tasks.`;

// NOTE: INJECTED_TAIL must stay identical to PLACEHOLDER in src/hooks/lib/output.js —
// output.js replaces that sentence with the live context. A test pins them equal.
const INJECTED_TAIL = 'Memory context for this project is already injected above — do not call getContext or list_planets at session start. Only use getContext mid-session if you need a refresh or switch topics.';

const BASEMEM_RULES_CORE = `Memory context injected — live context is below, do not re-fetch it.
${BASEMEM_RULES_BODY}
${INJECTED_TAIL}`;

const BASEMEM_RULES_TIER1 = BASEMEM_RULES_CORE;

const BASEMEM_RULES_TIER2 = `NOTE: BaseMem rules may be incomplete — run: node bin/lib/install.js repair
${BASEMEM_RULES_CORE}`;

const BASEMEM_RULES_TIER3 = `NOTE: BaseMem rules may be incomplete — run: node bin/lib/install.js repair
Call getContext exactly once at session start.
${BASEMEM_RULES_BODY}
Max one memory read tool call per user message.`;

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

module.exports = { BASEMEM_RULES, BASEMEM_RULES_CORE, BASEMEM_RULES_BODY, INJECTED_TAIL, BASEMEM_RULES_TIER1, BASEMEM_RULES_TIER2, BASEMEM_RULES_TIER3, writeRuleFile, removeRuleBlock };

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
