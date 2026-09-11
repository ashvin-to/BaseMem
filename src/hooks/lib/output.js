// Shared hook library: protocol-correct JSON output for SessionStart hooks.
// emitHookOutput(format, contextResult, rulesText) writes the JSON the agent expects.
// contextResult is the { topic, context, codeStats } | null returned by context.js#fetchContext.

const PLACEHOLDER = require('../../../bin/lib/rules.js').INJECTED_TAIL ||
  'Memory context for this project is already injected above — do not call getContext or ' +
  'list_planets at session start. Only use getContext mid-session if you need a refresh or switch topics.';

function _hasContext(ctx) {
  return (
    !!ctx &&
    !ctx.includes('No stored context found') &&
    !ctx.includes('No memory exists for this project yet')
  );
}

// Merge the live context + code stats into the rules text for single-block formats.
function _mergeFull(rulesText, contextResult) {
  let combined = rulesText || '';
  const ctx = contextResult && contextResult.context ? contextResult.context.trim() : '';
  const replacement = _hasContext(ctx)
    ? 'Project memory context is already injected above — do not call getContext or list_planets ' +
      'at session start. Only use getContext mid-session if you need a refresh or switch topics.' +
      `\n\n**Memory data:**\n${ctx}`
    : 'No context was automatically fetched. Call getContext at session start with your current ' +
      'project topic to retrieve available memory. Do not call list_planets.';
  combined = combined.includes(PLACEHOLDER)
    ? combined.replace(PLACEHOLDER, replacement)
    : combined + '\n\n' + replacement;
  if (contextResult && contextResult.codeStats) {
    combined += '\n\n**Code intelligence:**\n' + contextResult.codeStats;
  }
  return combined;
}

// Rules line that just points to the context emitted on a separate system line.
function _mergePointer(rulesText, contextResult) {
  let combined = rulesText || '';
  const ctx = contextResult && contextResult.context ? contextResult.context.trim() : '';
  const replacement = _hasContext(ctx)
    ? 'Project memory context is already injected above — do not call getContext or list_planets ' +
      'at session start. Only use getContext mid-session if you need a refresh or switch topics.'
    : 'No context was automatically fetched. Call getContext at session start with your current ' +
      'project topic to retrieve available memory. Do not call list_planets.';
  combined = combined.includes(PLACEHOLDER)
    ? combined.replace(PLACEHOLDER, replacement)
    : combined + '\n\n' + replacement;
  if (contextResult && contextResult.codeStats) {
    combined += '\n\n**Code intelligence:**\n' + contextResult.codeStats;
  }
  return combined;
}

function emitHookOutput(format, contextResult, rulesText) {
  const ctx = contextResult && contextResult.context ? contextResult.context.trim() : '';
  const hasData = _hasContext(ctx);

  switch (format) {
    case 'claude':
    case 'codex': {
      // Two-line protocol: system context line (if any) + rules hookSpecificOutput line.
      if (hasData) {
        process.stdout.write(JSON.stringify({ type: 'system', content: ctx }) + '\n');
      }
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: 'SessionStart',
            additionalContext: _mergePointer(rulesText, contextResult),
          },
        }) + '\n'
      );
      break;
    }
    case 'cursor': {
      process.stdout.write(
        JSON.stringify({ additional_context: _mergeFull(rulesText, contextResult) }) + '\n'
      );
      break;
    }
    case 'devin': {
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: 'SessionStart',
            additionalContext: _mergeFull(rulesText, contextResult),
          },
        }) + '\n'
      );
      break;
    }
    default: {
      // agy and any other plugin-style agent: ephemeral inject step.
      process.stdout.write(
        JSON.stringify({
          injectSteps: [
            {
              ephemeralMessage:
                '<EXTREMELY_IMPORTANT>\n' +
                _mergeFull(rulesText, contextResult) +
                '\n</EXTREMELY_IMPORTANT>',
            },
          ],
        }) + '\n'
      );
      break;
    }
  }
}

module.exports = { emitHookOutput, PLACEHOLDER };
