// Shared hook library: query-aware per-prompt recall.
// Reads the user's prompt text (from UserPromptSubmit stdin), runs
// `mem prompt-context --topic <topic> --query <prompt> --root <projectRoot>`
// which FTS5-searches BOTH databases (memory notes + code symbols), and
// returns the trimmed context string ('' when nothing relevant).
// Never throws — hooks must never break the agent's session flow.
const child_process = require('child_process');
const os = require('os');
const path = require('path');

const MAX_PROMPT_CHARS = 2000;
const HOOK_TIMEOUT = 4000;

function _memPath() {
  const binDir = process.env.BASEMEM_BIN_DIR || path.join(os.homedir(), '.local', 'bin');
  return path.join(binDir, 'mem');
}

// Extract the user prompt text from a UserPromptSubmit stdin payload.
// Handles Claude/Codex ({prompt}), Cursor (beforeSubmitPrompt {prompt}),
// agy ({prompt} / {userPrompt}), and raw-text fallback. Returns '' if none.
function extractPromptText(rawInput) {
  if (!rawInput || !rawInput.trim()) return '';
  let data = null;
  try {
    data = JSON.parse(rawInput);
  } catch (_) {
    // Not JSON — treat the raw stdin as the prompt itself (cap length).
    const t = rawInput.trim();
    return t.length > MAX_PROMPT_CHARS ? t.slice(0, MAX_PROMPT_CHARS) : t;
  }
  if (typeof data === 'string') {
    const t = data.trim();
    return t.length > MAX_PROMPT_CHARS ? t.slice(0, MAX_PROMPT_CHARS) : t;
  }
  if (!data || typeof data !== 'object') return '';
  const candidates = [
    data.prompt,
    data.userPrompt,
    data.user_prompt,
    data.message,
    data.text,
    data.input,
  ];
  // Nested shapes: {input:{prompt}}, {message:{parts:[{text}]}}, {parts:[...]}
  try {
    if (data.input && typeof data.input === 'object' && typeof data.input.prompt === 'string') {
      candidates.push(data.input.prompt);
    }
    const partLists = [data.parts, data.message && data.message.parts];
    for (const parts of partLists) {
      if (Array.isArray(parts)) {
        for (const p of parts) {
          if (p && typeof p.text === 'string') candidates.push(p.text);
          else if (typeof p === 'string') candidates.push(p);
        }
      }
    }
  } catch (_) {}
  let best = '';
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim().length > best.length) best = c.trim();
  }
  if (best.length > MAX_PROMPT_CHARS) best = best.slice(0, MAX_PROMPT_CHARS);
  return best;
}

// Run the recall query. topic/projectRoot come from _deriveTopic-compatible
// {topic, projectRoot}; falls back to deriving via context.js when omitted.
function fetchPromptContext(promptText, options) {
  try {
    const text = (promptText || '').trim();
    if (text.length < 8) return '';
    let topic = options && options.topic;
    let projectRoot = options && options.projectRoot;
    if (!topic || !projectRoot) {
      try {
        const { _deriveTopic } = require('./context.js');
        const derived = _deriveTopic({ timeout: HOOK_TIMEOUT });
        topic = topic || derived.topic;
        projectRoot = projectRoot || derived.projectRoot;
      } catch (_) {
        if (!topic) topic = path.basename(process.cwd());
        if (!projectRoot) projectRoot = process.cwd();
      }
    }
    const args = ['prompt-context', '--topic', topic, '--query', text, '--root', projectRoot || process.cwd()];
    const res = child_process.spawnSync(_memPath(), args, {
      timeout: (options && options.timeout) || HOOK_TIMEOUT,
      encoding: 'utf-8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    if (res.error || res.status !== 0) return '';
    const out = (res.stdout || '').trim();
    // Guard against accidental huge output; CLI already caps at ~1500 chars.
    return out.length > 2000 ? out.slice(0, 1997) + '...' : out;
  } catch (_) {
    return '';
  }
}

// Full stdin→stdout handler for UserPromptSubmit hooks:
// emits the standard tracker nudge plus <BASEMEM_PROMPT_CONTEXT> when recall hits.
// rawInput is the complete stdin string; format is 'claude'|'codex'|'cursor'|'agy'|'devin'|other.
function handlePromptInput(format, rawInput) {
  let extra = '';
  try {
    const prompt = extractPromptText(rawInput || '');
    if (prompt) extra = fetchPromptContext(prompt);
  } catch (_) {
    extra = '';
  }
  const { emitTrackerOutput } = require('./tracker.js');
  emitTrackerOutput(format, extra);
}

module.exports = { extractPromptText, fetchPromptContext, handlePromptInput, MAX_PROMPT_CHARS };
