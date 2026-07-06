#!/usr/bin/env node
const os = require('os');
const path = require('path');
const { fetchContext } = require('../../../hooks/lib/context.js');
const { emitHookOutput } = require('../../../hooks/lib/output.js');
const { writeFlagFile } = require('../../../hooks/lib/flagfile.js');
const { BASEMEM_RULES_TIER1 } = require('../../../../bin/lib/rules.js');

const xdgConfig = process.env.XDG_CONFIG_HOME && process.env.XDG_CONFIG_HOME.trim().length > 0
  ? process.env.XDG_CONFIG_HOME
  : path.join(os.homedir(), '.config');
writeFlagFile(path.join(xdgConfig, 'devin'));
const contextResult = fetchContext();
emitHookOutput('devin', contextResult, BASEMEM_RULES_TIER1);
