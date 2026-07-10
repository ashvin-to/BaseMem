#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext, checkRulesIntegrity } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const configDir = process.env.CODEX_CONFIG_DIR || path.join(os.homedir(), '.codex');
const rulesFile = path.join(configDir, 'AGENTS.md');
const integrity = checkRulesIntegrity('codex', rulesFile);
if (!integrity.intact) {
  process.stderr.write('BaseMem rules missing from codex config — run: node bin/lib/install.js repair\n');
}
let rulesText = BASEMEM_RULES_TIER1;
if (!integrity.intact) {
  rulesText = 'WARNING: BaseMem rules were not found in your config. Memory rules may not be fully active. Ask the user to run node bin/lib/install.js repair to restore them.\n\n' + rulesText;
}
writeFlagFile(configDir);
const contextResult = fetchContext();
emitHookOutput('codex', contextResult, rulesText);
