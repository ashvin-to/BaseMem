// Shared hook library: writes the .basemem-active sentinel into an agent config dir.
const fs = require('fs');
const path = require('path');
const { FLAG_FILENAME } = require('../../../bin/lib/constants.js');

function writeFlagFile(configDir) {
  try {
    if (!configDir) return;
    // Symlink-resolve safety: write into the real target, never a dangling symlink elsewhere.
    let dir = configDir;
    try {
      dir = fs.realpathSync(configDir);
    } catch (_) {
      dir = configDir;
    }
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, FLAG_FILENAME), 'active\n', 'utf-8');
  } catch (_) {
    // Flag file is best-effort; missing it only disables statusline detection.
  }
}

module.exports = { writeFlagFile };
