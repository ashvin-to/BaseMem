#!/usr/bin/env node
/**
 * Optional, WARNING-ONLY git pre-commit gate for BaseMem.
 *
 * Checks whether a logInteraction has been recorded since the last commit for
 * the current planet. By default it only prints a warning and lets the commit
 * proceed. Set BASEMEM_COMMIT_GATE=1 to make it abort the commit instead.
 *
 * Install via:  node bin/lib/install.js  (opt-in)  or manually:
 *   git config core.hooksPath .git/baseMemHooks
 * and symlink/copy this file there as `pre-commit`.
 */
const path = require('path');
const { spawnSync } = require('child_process');

const ROOT = path.resolve(__dirname, '../..');
const CAPTURE_PY = path.join(ROOT, 'bin/lib/capture_native.py');
const PYTHON = process.env.BASEMEM_PYTHON || process.env.MCP_PYTHON || 'python3';

function topic() {
  const env = process.env.BASEMEM_TOPIC || process.env.BASEMEM_PLANET;
  if (env) return env;
  try {
    const cwd = process.env.PWD || process.cwd();
    const out = spawnSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf-8' });
    const root = (out.stdout || '').trim();
    if (root) return path.basename(root);
  } catch (_) {}
  return path.basename(process.cwd());
}

function main() {
  const t = topic();
  const query = `
import sqlite3, os, sys
sys.path.insert(0, ${JSON.stringify(ROOT)})
from mcp_server.server import get_db_path
p = get_db_path()
if not os.path.isfile(p):
    sys.exit(0)
c = sqlite3.connect(p)
row = c.execute(
    "SELECT count(*) AS n FROM notes WHERE topic=? AND kind IN ('summary','decision','fact')",
    (${JSON.stringify(t.toLowerCase())},)
).fetchone()
print(row['n'] if row else 0)
`;
  let count = 0;
  try {
    const out = spawnSync(PYTHON, ['-c', query], { cwd: ROOT, encoding: 'utf-8' });
    count = parseInt((out.stdout || '').trim(), 10) || 0;
  } catch (_) {}

  const msg = `⚠ BaseMem: no memory log (logInteraction) recorded for '${t}' since your last commit. ` +
    `Consider logging a summary. (set BASEMEM_COMMIT_GATE=1 to block commits without a log)`;

  if (count === 0 && process.env.BASEMEM_COMMIT_GATE === '1') {
    process.stderr.write(msg + '\n');
    process.exit(1);
  }
  if (count === 0) {
    process.stderr.write(msg + '\n');
  }
  process.exit(0);
}

main();
