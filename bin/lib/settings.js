const fs = require('fs');
const { MARKER_START, MARKER_END } = require('./constants.js');

function validateHookEntry(entry, label) {
  if (entry.hooks && Array.isArray(entry.hooks)) {
    for (let j = 0; j < entry.hooks.length; j++) {
      validateHookEntry(entry.hooks[j], `${label}.hooks[${j}]`);
    }
    return;
  }
  if (!entry.type) {
    throw new Error(`Hook entry ${label} is missing required field "type"`);
  }
  if (!entry.command) {
    throw new Error(`Hook entry ${label} is missing required field "command"`);
  }
}

function validateHookFields(hooks) {
  for (const eventKey of Object.keys(hooks)) {
    const entries = hooks[eventKey];
    if (!Array.isArray(entries)) continue;
    for (let i = 0; i < entries.length; i++) {
      validateHookEntry(entries[i], `${eventKey}[${i}]`);
    }
  }
}

function stripJsonc(str) {
  return str.replace(
    /\\"|"(?:[^"\\]|\\.)*"|\/\/.*|\/\*[\s\S]*?\*\//g,
    m => m.startsWith('"') ? m : ''
  );
}

function readJson(filePath) {
  const raw = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(stripJsonc(raw));
}

function hookContainsBasemem(entry) {
  if (entry.command && typeof entry.command === 'string' && entry.command.toLowerCase().includes('basemem')) return true;
  if (entry.hooks && Array.isArray(entry.hooks)) {
    for (const sub of entry.hooks) {
      if (hookContainsBasemem(sub)) return true;
    }
  }
  return false;
}

function mergeSettings(settingsPath, additions) {
  let config;
  try {
    config = readJson(settingsPath);
  } catch (err) {
    if (err.code === 'ENOENT') {
      config = {};
    } else {
      return;
    }
  }

  let changed = false;

  if (additions.hooks) {
    config.hooks = config.hooks || {};
    for (const eventKey of Object.keys(additions.hooks)) {
      const existing = config.hooks[eventKey] || [];
      const newEntries = additions.hooks[eventKey];
      const filtered = existing.filter(e => !hookContainsBasemem(e));
      if (filtered.length !== existing.length || newEntries.length > 0) {
        config.hooks[eventKey] = filtered;
        for (const entry of newEntries) {
          config.hooks[eventKey].push(entry);
        }
        changed = true;
      }
    }
  }

  if (additions.statusLine) {
    const cur = config.statusLine || {};
    if (cur.type !== additions.statusLine.type || cur.command !== additions.statusLine.command) {
      config.statusLine = additions.statusLine;
      changed = true;
    }
  }

  if (changed) {
    if (config.hooks) {
      validateHookFields(config.hooks);
    }
    fs.writeFileSync(settingsPath, JSON.stringify(config, null, 2) + '\n', 'utf-8');
  }
}

function removeHookEntries(settingsPath) {
  let config;
  try {
    config = readJson(settingsPath);
  } catch {
    return;
  }

  if (config.hooks) {
    for (const eventKey of Object.keys(config.hooks)) {
      const entries = config.hooks[eventKey];
      if (Array.isArray(entries)) {
        config.hooks[eventKey] = entries.filter(e => !hookContainsBasemem(e));
      }
    }
  }

  if (
    config.statusLine &&
    config.statusLine.command &&
    config.statusLine.command.toLowerCase().includes('basemem')
  ) {
    delete config.statusLine;
  }

  fs.writeFileSync(settingsPath, JSON.stringify(config, null, 2) + '\n', 'utf-8');
}

module.exports = { validateHookFields, mergeSettings, removeHookEntries };

if (require.main === module) {
  const os = require('os');
  const path = require('path');
  const tmp = path.join(os.tmpdir(), 'basemem-test-settings.json');
  try { fs.unlinkSync(tmp); } catch (_) {}

  const hooks = {
    SessionStart: [
      { type: 'command', command: 'basemem session-start' }
    ]
  };
  mergeSettings(tmp, { hooks, statusLine: { command: 'basemem status' } });
  let c = JSON.parse(fs.readFileSync(tmp, 'utf-8'));
  console.assert(c.hooks.SessionStart.length === 1, 'initial hook');
  console.assert(c.statusLine.command === 'basemem status', 'initial statusLine');

  mergeSettings(tmp, { hooks, statusLine: { command: 'basemem status' } });
  c = JSON.parse(fs.readFileSync(tmp, 'utf-8'));
  console.assert(c.hooks.SessionStart.length === 1, 'idempotent: no duplicate');
  console.assert(c.statusLine.command === 'basemem status', 'statusLine preserved');

  removeHookEntries(tmp);
  c = JSON.parse(fs.readFileSync(tmp, 'utf-8'));
  console.assert(c.hooks.SessionStart.length === 0, 'removed hook');
  console.assert(!c.statusLine, 'removed statusLine');

  try { fs.unlinkSync(tmp); } catch (_) {}

  let threw = false;
  try {
    validateHookFields({ SessionStart: [{ type: 'cmd' }] });
  } catch (e) {
    threw = true;
    console.assert(e.message.includes('command'), 'error mentions missing command');
  }
  console.assert(threw, 'validate throws on missing command');

  let threw2 = false;
  try {
    validateHookFields({ SessionStart: [{ matcher: 'x', hooks: [{ type: 'cmd' }] }] });
  } catch (e) {
    threw2 = true;
    console.assert(e.message.includes('command'), 'nested: error mentions missing command');
  }
  console.assert(threw2, 'nested validate throws on missing command');

  console.log('All self-tests passed');
}
