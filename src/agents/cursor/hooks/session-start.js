#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const configDir = process.env.CURSOR_CONFIG_DIR || path.join(os.homedir(), '.cursor');
writeFlagFile(configDir);
const contextResult = fetchContext();
emitHookOutput('cursor', contextResult, BASEMEM_RULES_TIER1);
