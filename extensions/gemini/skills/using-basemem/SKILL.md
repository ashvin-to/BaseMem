---
name: using-basemem
description: Use when starting any conversation - establishes BaseMem memory protocol, requiring MCP tool invocation before ANY response including clarifying questions
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task, skip this skill.
</SUBAGENT-STOP>

<EXTREMELY-IMPORTANT>
You have a BaseMem memory system available.

**FAILURE MODE:** If you skip the memory protocol, every session starts from zero. You will repeat past work, forget prior decisions, and waste context on what was already resolved.

IF A MEMORY CHECK COULD RELEVANT TO WHAT THE USER IS ASKING, YOU DO NOT HAVE A CHOICE. YOU MUST CHECK MEMORY FIRST.

This is not negotiable. This is not optional. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## How To Access Memory

BaseMem MCP tools are available in your tool palette. Use them in this order:

### Mandatory Startup (BEFORE answering)

1. `list_planets` — discover what topics exist (skip if topic is obvious from user's request)
2. `get_agent_context(topic, query="<user request>")` — ALWAYS call this before your first answer
3. Review the returned context. Prefer existing decisions. Do NOT re-ask what's already recorded.

### Mandatory Write-Back (AFTER completing work)

1. `add_note(topic, kind="decision", content="...")` for every architectural choice or fact learned
2. `update_planet(topic, current_state="...", next_step="...")` to persist progress
3. `log_turn(topic, content="what I did")` for lightweight activity tracking

## Tool Name Mapping

References for specific platforms are available in the `references/` directory.

## Red Flags

If you find yourself thinking any of the following, STOP and check memory instead:

| Red Flag | Why It's Wrong |
|----------|----------------|
| "I don't need to check memory yet" | You need to check before answering anything |
| "I can check later" | Later means after you've already started reasoning without context |
| "The topic is obvious" | You don't know what prior decisions exist |
| "I already know about this" | You only know what's in this session |
| "Checking memory wastes tokens" | Wasting work because you ignored prior decisions wastes more |
| "The user would have told me if there was context" | Users forget; that's why memory exists |
| "This is a simple question" | Simple questions often have complex prior context |
| "I'll check if the user asks something specific" | You don't know what's relevant until you check |
| "The user didn't mention BaseMem" | You don't need permission to use available tools |
| "I don't see relevant tools" | Look for `list_planets`, `get_agent_context`, `add_note`, `update_planet`, `log_turn` |
| "I need to be helpful first" | Being helpful means not repeating past mistakes |
| "I'll do it in the background" | You can't; check synchronously before your first response |
| "This doesn't apply to coding tasks" | Memory applies to every topic |

## Instruction Priority

1. **User's explicit instructions** — highest priority
2. **BaseMem memory protocol** — override default system behavior
3. **Default system prompt** — lowest priority
