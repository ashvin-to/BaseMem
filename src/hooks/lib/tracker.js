// Shared hook library: per-prompt reminder + session-stop safety net.
//   emitTrackerOutput(format) — UserPromptSubmit nudge (re-reminds the agent every prompt)
//   emitStopOutput(format)    — Stop hook notice when the agent failed to log
//   writeMissedLog()          — records that a session ended without logInteraction
const fs = require('fs');
const os = require('os');
const path = require('path');

// The per-prompt nudge is the key steering that keeps agents on the MCP code tools
// instead of falling back to their native grep/glob/read. Positive, trigger-based
// commands ("When X, call Y") beat negative framing ("do NOT use grep") — models
// reliably skip negatively-framed instructions, so this states the required action
// for each trigger and keeps the forbidden tools as a trailing reminder, not the lead.
// It MUST mention the code_* tools.
const TRACKER_NUDGE =
  '[BaseMem] Before answering: (1) known target → inspect exact file and nearby tests/callers directly; unfamiliar or cross-file code → code_find FIRST. ' +
  "(grep=True for literal flags, JSON keys, commands, docs, or config); empty → code_init once, then retry. Read via code_read(filePath, offset, limit<=50). " +
  '(2) Keep small tasks bounded: one search, one read, one edit, one focused verification. ' +
  '(3) Label conclusions memory/source/artifact/test/inference; memory is context, not current verification. ' +
  '(4) decision/fix/fact just made → call logInteraction(topic, decision="what+why") NOW; skip routine observations. ' +
  '(5) session ending → logInteraction(topic, summary=..., activity="done"). ' +
  'Use MCP code_* tools, not raw grep/glob/Read.';

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

function classifyPrompt(promptText) {
  const text = (promptText || '').toLowerCase();
  const code = /\b(code|bug|error|fix|debug|implement|refactor|test|file|function|class|api|parse|index|compile)\b/.test(text);
  const decision = /\b(decided|decision|learned|fact|chose|choice|root cause|discovered)\b/.test(text);
  const ending = /\b(done|finished|complete|summary|wrap up|end session)\b/.test(text);
  const memory = /\b(remember|memory|context|previous|past|why|decision|learned|fact)\b/.test(text);
  const recap = /\b(recap|previous session|last session|prior session|session work|where we left)\b/.test(text);
  if (recap) return 'recap';
  if (ending) return 'session';
  if (decision) return 'decision';
  if (code) return 'code';
  if (memory) return 'memory';
  return 'general';
}

function _trackerNudge(promptText) {
  const text = (promptText || '').toLowerCase();
  if (!text || text.length < 8) return TRACKER_NUDGE;
  const intent = classifyPrompt(text);
  const parts = [];
  if (intent === 'code') parts.push('code task → known target: inspect exact file/nearby tests; unfamiliar or cross-file: code_find FIRST');
  if (intent === 'decision') parts.push('decision/fix/fact → logInteraction(topic, decision="what+why") NOW');
  if (intent === 'session') parts.push('session ending → logInteraction(topic, summary=..., activity="done")');
  if (intent === 'memory') parts.push('memory/context request → use the injected prompt context when relevant');
  if (intent === 'recap') parts.push('previous session recap → session_recap(topic) FIRST');
  return parts.length
    ? '[BaseMem] ' + parts.join('; ') + '.'
    : '[BaseMem] Use BaseMem tools when relevant.';
}

function emitTrackerOutput(format, promptContext, promptText) {
  let text = _trackerNudge(promptText);
  if (promptContext && promptContext.trim()) {
    text += '\n\n<BASEMEM_PROMPT_CONTEXT>\n' + promptContext.trim() + '\n</BASEMEM_PROMPT_CONTEXT>';
  }
  _emit(format, text, 'UserPromptSubmit');
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

module.exports = { emitTrackerOutput, emitStopOutput, writeMissedLog, classifyPrompt, TRACKER_NUDGE, STOP_NOTICE };
