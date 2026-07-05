#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const configDir = process.env.CLAUDE_CONFIG_DIR || (process.platform === 'win32' ? path.join(process.env.APPDATA, 'claude') : path.join(os.homedir(), '.claude'));
writeFlagFile(configDir);
const contextResult = fetchContext();
emitHookOutput('claude', contextResult, BASEMEM_RULES_TIER1);
