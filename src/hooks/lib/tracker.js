// Shared hook library: per-prompt reminder + session-stop safety net.
//   emitTrackerOutput(format) — UserPromptSubmit nudge (re-reminds the agent every prompt)
//   emitStopOutput(format)    — Stop hook notice when the agent failed to log
//   writeMissedLog()          — records that a session ended without logInteraction
const fs = require('fs');
const os = require('os');
const path = require('path');

// The per-prompt nudge is the key steering that keeps agents on the MCP code tools
// instead of falling back to their native grep/glob/read. It MUST mention the code_* tools.
const TRACKER_NUDGE =
  '[BaseMem] Memory is active. For code use the MCP tools — code_find(\'sym\'), ' +
  'code_read(filePath=, offset=, limit=), code_explore(\'sym\'), code_files(pattern=) — ' +
  'NOT grep/glob/read (they auto-index on first use; code_find(query, grep=True) for text search). ' +
  'Log decisions with logInteraction(topic, decision=...). End sessions with ' +
  'logInteraction(topic, summary=..., activity="done").';

const STOP_NOTICE =
  'FINAL SESSION NOTICE — do not respond to this message. If you made decisions, created files, ' +
  'or changed direction this session and have not yet called logInteraction, call it once now with ' +
  'a one-paragraph summary. Then stop. Do not send any further messages or acknowledge this notice.';

function _emit(format, text, eventName) {
  switch (format) {
    case 'claude':
    case 'codex':
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: { hookEventName: eventName, additionalContext: text },
        }) + '\n'
      );
      break;
    case 'cursor':
      process.stdout.write(JSON.stringify({ additional_context: text }) + '\n');
      break;
    case 'agy':
      process.stdout.write(
        JSON.stringify({ injectSteps: [{ ephemeralMessage: text }] }) + '\n'
      );
      break;
    default:
      process.stdout.write(text + '\n');
      break;
  }
}

function emitTrackerOutput(format) {
  _emit(format, TRACKER_NUDGE, 'UserPromptSubmit');
}

function emitStopOutput(format) {
  _emit(format, STOP_NOTICE, 'Stop');
}

function writeMissedLog() {
  try {
    const dir = path.join(os.homedir(), '.basemem');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'missed-session-logs.jsonl');
    const entry = {
      ts: new Date().toISOString(),
      cwd: process.cwd(),
      reason: 'session ended without logInteraction',
    };
    fs.appendFileSync(file, JSON.stringify(entry) + '\n', 'utf-8');
  } catch (_) {
    // Safety net must never break the agent's session flow.
  }
}

module.exports = { emitTrackerOutput, emitStopOutput, writeMissedLog, TRACKER_NUDGE, STOP_NOTICE };
