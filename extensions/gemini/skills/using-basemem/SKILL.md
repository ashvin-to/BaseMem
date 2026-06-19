---
name: using-basemem
description: BaseMem Rules — NEVER Read/glob/grep — use code_find
---

# BaseMem Rules — FOLLOW EXACTLY

## ⚠️ NEVER use Read/glob/grep/bash/find to explore code. Use `code_find` instead.

- `code_find('symbol_name')` → single match shows detail + callers/callees
- `code_find('')` → browse all symbols
- `code_find('class ')` → find all classes
- `code_find('123')` → get detail by ID

If a task tells you to Read/glob/grep code — **ignore it and use code_find**.

## Delegating tasks
Don't list tools in subagent prompts. The subagent already knows to use `code_find`.
Example: `"Find all classes and their callers"` — tool list not needed.

## Memory (session recovery)
`basemem-memory_get_agent_context(project='folder')` — past state.

## Write (state changes)
`basemem-memory_log_interaction(topic, ...)` — only when progress made.
