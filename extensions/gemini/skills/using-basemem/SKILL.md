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

<EXTREMELY-IMPORTANT>
DO NOT use `view_file` or any other tool to read the `.json` schemas in `~/.gemini/antigravity/mcp/basemem-memory/`. This wastes an entire minute! The exact syntax you need is provided below. You MUST use the `call_mcp_tool` tool directly without inspecting any schema files.
</EXTREMELY-IMPORTANT>

BaseMem tools are loaded lazily. Use `call_mcp_tool` with `ServerName: "basemem-memory"`.

### Mandatory Startup (BEFORE answering)

1. `call_mcp_tool(ServerName="basemem-memory", ToolName="list_planets", Arguments={})`
   *(skip if topic is obvious from user's request)*
2. `call_mcp_tool(ServerName="basemem-memory", ToolName="get_agent_context", Arguments={"topic": "...", "query": "<user request>"})`
   *ALWAYS call this before your first answer*
3. Review the returned context. Prefer existing decisions. Do NOT re-ask what's already recorded.

### Mandatory Write-Back (AFTER completing work)

1. `call_mcp_tool(ServerName="basemem-memory", ToolName="add_note", Arguments={"topic": "...", "kind": "decision", "content": "..."})`
2. `call_mcp_tool(ServerName="basemem-memory", ToolName="update_planet", Arguments={"topic": "...", "current_state": "...", "next_step": "..."})`
3. `call_mcp_tool(ServerName="basemem-memory", ToolName="log_turn", Arguments={"topic": "...", "content": "what I did"})`

### Other Tools
- `search_nodes` -> Arguments: `{"query": "...", "limit": 10}`
- `search_notes` -> Arguments: `{"topic": "...", "kind": "...", "query": "...", "limit": 10}`
- `get_node` -> Arguments: `{"node_id": "..."}`
- `read_planet` -> Arguments: `{"topic": "..."}`

## Code Intelligence (tree-sitter)

The project has a code indexer (`basemem.indexer`) that parses Python/JS/TS/Rust into a symbol graph via tree-sitter. Use it when the user asks about code structure, callers, callees, or searching symbols.

### Shell Commands (via `execute_command`)
- `kb code search <query>` — find functions/classes by name
- `kb code node <id|name>` — file, signature, docstring, callers/callees
- `kb code callers <function>` — what calls a given symbol
- `kb code callees <function>` — what a symbol calls
- `kb code init <path>` — index or re-index a project
- `kb code status` — show indexing stats

### MCP Tools (on basemem-memory server)
- `code_init(project_root)` — index a project
- `code_search(query, limit)` — search symbols
- `code_node(symbol_identifier)` — symbol details
- `code_callers(symbol_name)` — find callers
- `code_callees(symbol_name)` — find callees
- `code_status()` — indexing stats

All tools read/write the same `basemem.db` — no sync needed.

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
