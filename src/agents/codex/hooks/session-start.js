#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const configDir = process.env.CODEX_CONFIG_DIR || path.join(os.homedir(), '.codex');
writeFlagFile(configDir);
const contextResult = fetchContext();
emitHookOutput('codex', contextResult, BASEMEM_RULES_TIER1);
