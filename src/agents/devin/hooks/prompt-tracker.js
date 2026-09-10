#!/usr/bin/env node
const { handlePromptInput } = require('../../../hooks/lib/prompt-context.js');
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  handlePromptInput('devin', input);
});
