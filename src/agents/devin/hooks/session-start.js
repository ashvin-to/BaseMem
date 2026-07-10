#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext, checkRulesIntegrity } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const xdgConfig = process.env.XDG_CONFIG_HOME && process.env.XDG_CONFIG_HOME.trim().length > 0
  ? process.env.XDG_CONFIG_HOME
  : path.join(os.homedir(), '.config');
const rulesFile = path.join(xdgConfig, 'devin', 'rules', 'basemem.md');
const integrity = checkRulesIntegrity('devin', rulesFile);
if (!integrity.intact) {
  process.stderr.write('BaseMem rules missing from devin config — run: node bin/lib/install.js repair\n');
}
let rulesText = BASEMEM_RULES_TIER1;
if (!integrity.intact) {
  rulesText = 'WARNING: BaseMem rules were not found in your config. Memory rules may not be fully active. Ask the user to run node bin/lib/install.js repair to restore them.\n\n' + rulesText;
}
writeFlagFile(path.join(xdgConfig, 'devin'));
const contextResult = fetchContext();
emitHookOutput('devin', contextResult, rulesText);
