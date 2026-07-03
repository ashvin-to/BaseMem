const assert = require('assert');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { writeRuleFile, removeRuleBlock, BASEMEM_RULES } = require('../rules.js');

// ── BASEMEM_RULES ────────────────────────────────────────────────
assert.ok(BASEMEM_RULES);
assert.ok(BASEMEM_RULES.includes('getContext'));
assert.ok(BASEMEM_RULES.includes('logInteraction'));
assert.ok(BASEMEM_RULES.includes('code_find'));
assert.ok(BASEMEM_RULES.includes('getContext'));
console.log('PASS BASEMEM_RULES: contains tool references');

// ── writeRuleFile: markdown ───────────────────────────────────────
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'basemem-test-rules-'));
const mdPath = path.join(tmpDir, 'test.md');

writeRuleFile(mdPath, 'markdown');
const mdContent = fs.readFileSync(mdPath, 'utf-8');
assert.ok(mdContent.includes('basemem-managed-start'));
assert.ok(mdContent.includes('basemem-managed-end'));
assert.ok(mdContent.includes('getContext'));
assert.ok(mdContent.includes('logInteraction'));
console.log('PASS writeRuleFile(markdown): markers and rules present');

// Idempotency — writing again doesn't duplicate markers
writeRuleFile(mdPath, 'markdown');
const mdContent2 = fs.readFileSync(mdPath, 'utf-8');
const startCount = (mdContent2.match(/<!-- basemem-managed-start -->/g) || []).length;
assert.strictEqual(startCount, 1, `Expected 1 occurrence, got ${startCount}`);
console.log('PASS writeRuleFile(markdown): idempotent');

// ── writeRuleFile: mdc ───────────────────────────────────────────
const mdcPath = path.join(tmpDir, 'test.mdc');
writeRuleFile(mdcPath, 'mdc');
const mdcContent = fs.readFileSync(mdcPath, 'utf-8');
assert.ok(mdcContent.includes('alwaysApply: true'), 'mdc should have alwaysApply frontmatter');
assert.ok(mdcContent.includes('basemem-managed-start'));
console.log('PASS writeRuleFile(mdc): frontmatter + markers');

// Idempotency — writing again doesn't duplicate
writeRuleFile(mdcPath, 'mdc');
const mdcContent2 = fs.readFileSync(mdcPath, 'utf-8');
const mdcStartCount = (mdcContent2.match(/<!-- basemem-managed-start -->/g) || []).length;
assert.strictEqual(mdcStartCount, 1, 'mdc idempotent');
console.log('PASS writeRuleFile(mdc): idempotent');

// ── removeRuleBlock ──────────────────────────────────────────────
removeRuleBlock(mdPath);
const exists = fs.existsSync(mdPath);
assert.ok(!exists, 'removeRuleBlock should delete file when only basemem content');
console.log('PASS removeRuleBlock: deleted file with only basemem content');

// Removing from non-existent file is safe
removeRuleBlock(path.join(tmpDir, 'nope.md'));
console.log('PASS removeRuleBlock: no-op on missing file');

// Removing from file with user content before markers (single block)
const mixedPath = path.join(tmpDir, 'mixed.md');
fs.writeFileSync(mixedPath, '# My Rules\n\n' +
  '<!-- basemem-managed-start -->\n' +
  'basemem rules here\n' +
  '<!-- basemem-managed-end -->\n' +
  '## Trailer\n', 'utf-8');
removeRuleBlock(mixedPath);
const mixedContent = fs.readFileSync(mixedPath, 'utf-8');
assert.ok(mixedContent.includes('# My Rules'), 'should keep user content before markers');
assert.ok(mixedContent.includes('## Trailer'), 'should keep content after markers');
assert.ok(!mixedContent.includes('basemem rules'), 'should remove basemem content');
console.log('PASS removeRuleBlock: preserves user content, removes basemem blocks');

// ── removeRuleBlock: mdc frontmatter-only gets deleted ──────────
const mdcOnlyPath = path.join(tmpDir, 'only-frontmatter.mdc');
writeRuleFile(mdcOnlyPath, 'mdc');
assert.ok(fs.existsSync(mdcOnlyPath), 'mdc file exists before remove');
removeRuleBlock(mdcOnlyPath);
assert.ok(!fs.existsSync(mdcOnlyPath), 'mdc file deleted when only frontmatter remains');
console.log('PASS removeRuleBlock: deletes mdc file with only frontmatter');

// ── Unknown format defaults to markdown (no throw) ───────────────
const unknownFmtPath = path.join(tmpDir, 'unknown.md');
writeRuleFile(unknownFmtPath, 'txt');
const txtContent = fs.readFileSync(unknownFmtPath, 'utf-8');
assert.ok(txtContent.includes('basemem-managed-start'));
console.log('PASS writeRuleFile: unknown format defaults to markdown');

fs.rmSync(tmpDir, { recursive: true });
console.log('\nAll rules.js tests passed');
