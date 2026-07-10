#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext, checkRulesIntegrity } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const configDir = process.env.CLAUDE_CONFIG_DIR || (process.platform === 'win32' ? path.join(process.env.APPDATA, 'claude') : path.join(os.homedir(), '.claude'));
const basememMd = path.join(configDir, 'basemem.md');
const claudeMd = path.join(configDir, 'CLAUDE.md');
const integrity = checkRulesIntegrity('claude', basememMd, claudeMd);
if (!integrity.intact) {
  process.stderr.write('BaseMem rules missing from claude config — run: node bin/lib/install.js repair\n');
}
let rulesText = BASEMEM_RULES_TIER1;
if (!integrity.intact) {
  rulesText = 'WARNING: BaseMem rules were not found in your config. Memory rules may not be fully active. Ask the user to run node bin/lib/install.js repair to restore them.\n\n' + rulesText;
}
writeFlagFile(configDir);
const contextResult = fetchContext();
emitHookOutput('claude', contextResult, rulesText);
