---
name: using-basemem
description: BaseMem memory protocol — mandatory project context, code graph, and write-back rules
---

## Rule 1: Skip standalone questions
Standalone programming questions, definitions, math, trivia — answer directly. Zero MCP calls.

## Rule 2: You MUST check memory for project context
When the question touches an existing project, topic, past decision, or ongoing work:
1. `list_planets` + `get_agent_context(topic, query)` — read prior context
2. Use what you find. Do not re-ask what's already recorded.

## Rule 3: You MUST use code graph before reading source files
Before opening any source file:
1. Run `code_init(project_root)` if no `.basemem.code.db` exists
2. Use `code_search`/`code_node`/`code_callers`/`code_callees` instead of Read

⚠️ **You will default to `Read` — it's the most basic tool. Break this habit.** A single `code_search` call (~200 tokens) beats reading a source file (~4000+). If you catch yourself thinking "I'll just Read the file" — STOP and check code graph first.

## Rule 4: You MUST log every interaction that used memory
After answering, call all three:
1. `add_note(topic, kind, content)` — decisions, facts, issues
2. `update_planet(topic, current_state, next_step)` — persist progress
3. `log_turn(topic, content)` — activity record

**Failure mode:** If you skip writes, the next session starts from zero. Prior decisions are lost.
