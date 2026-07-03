#!/usr/bin/env node
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try { JSON.parse(input); } catch (_) {}

  const output = {
    hookSpecificOutput: {
      hookEventName: 'UserPromptSubmit',
      additionalContext:
        'Reminder: Use mem_ MCP tools. Call getContext before answering project questions.',
    },
  };
  console.log(JSON.stringify(output));
});
