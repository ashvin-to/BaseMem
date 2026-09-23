#!/usr/bin/env node
// AGY PreInvocation hook — fires before EVERY model call (tool steps included).
// session-start.js handles invocationNum 0-1 (session bootstrap).
// This tracker fires on invocationNum > 1 (every subsequent user turn).
const fs = require("fs");
const path = require("path");
const os = require("os");
const { fetchPromptContext } = require("/mnt/Storage/BaseMem/src/hooks/lib/prompt-context.js");
const { emitTrackerOutput } = require("/mnt/Storage/BaseMem/src/hooks/lib/tracker.js");

function getLastUserPrompt() {
  try {
    const histFile = path.join(os.homedir(), ".gemini", "antigravity-cli", "history.jsonl");
    if (!fs.existsSync(histFile)) return "";
    const lines = fs.readFileSync(histFile, "utf-8").trim().split("\n");
    for (let i = lines.length - 1; i >= 0; i--) {
      try {
        const item = JSON.parse(lines[i]);
        if (item.display && item.type !== "slash_command") {
          return item.display;
        }
      } catch (_) {}
    }
  } catch (_) {}
  return "";
}

let input = "";
process.stdin.on("data", chunk => { input += chunk; });
process.stdin.on("end", () => {
  let invocationNum = 0;
  try {
    if (input.trim()) {
      const payload = JSON.parse(input);
      invocationNum = payload.invocationNum || 0;
    }
  } catch (_) {}

  // session-start.js owns invocationNum 0 and 1 (first model call of session).
  if (invocationNum <= 1) {
    process.stdout.write("{}\n");
    return;
  }

  // Extract actual user prompt from history.jsonl
  const promptText = getLastUserPrompt();
  const context = fetchPromptContext(promptText || "project memory context", {});
  emitTrackerOutput("agy", context, promptText);
});
