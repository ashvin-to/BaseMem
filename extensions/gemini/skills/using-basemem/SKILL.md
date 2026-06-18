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

### Mandatory Code-Graph Check (BEFORE reading any source file)

Before you open any source file (`.py`, `.ts`, `.rs`, `.js`, etc.):

1. Check if `.basemem.code.db` exists in the project root: `ls <project_root>/.basemem.code.db` or `execute_command`
2. If it exists → use `code_search`/`code_node`/`code_callers`/`code_callees` instead of reading files
3. If it doesn't exist → run `code_init(project_root)` first, then query

**FAILURE MODE:** You will default to `Read` because it's the most basic tool. Do NOT. The code graph almost certainly exists — check it first. A single `code_search` call (~200 tokens) beats reading a source file (~4000+ tokens).

### Mandatory Write-Back (AFTER completing work)

1. `call_mcp_tool(ServerName="basemem-memory", ToolName="add_note", Arguments={"topic": "...", "kind": "decision", "content": "..."})`
2. `call_mcp_tool(ServerName="basemem-memory", ToolName="update_planet", Arguments={"topic": "...", "current_state": "...", "next_step": "..."})`
3. `call_mcp_tool(ServerName="basemem-memory", ToolName="log_turn", Arguments={"topic": "...", "content": "what I did"})`

### Other Tools
- `search_nodes` -> Arguments: `{"query": "...", "limit": 10}`
- `search_notes` -> Arguments: `{"topic": "...", "kind": "...", "query": "...", "limit": 10}`
- `get_node` -> Arguments: `{"node_id": "..."}`
- `read_planet` -> Arguments: `{"topic": "..."}`

## Code Intelligence (tree-sitter) — Token Efficiency Rule

The project has a code indexer (`basemem.indexer`) that parses source code into a symbol graph via tree-sitter (306 languages). Custom queries for Python/JS/TS/TSX/Rust give richer extraction — all other languages get basic symbols via the language-pack's auto-fallback.

### ⚠️ CRITICAL RULE: Use Code Tools, NOT File Reads

When you need to understand code structure (find a function, trace callers, check what a function calls, list symbols in a file):

**DO**: `code_search("/path/to/project", "function_name")` — 1 MCP call, ~200 tokens

**DO NOT**: Read source files directly — that dumps hundreds of lines into context

**Why**: Code MCP tools return compact output (1-10 lines). Reading source files costs 5-20x more tokens.

**Workflow**:
1. `code_search` to find the symbol
2. `code_node` to get full details (signature, location, callers, callees)
3. Only read the file if you actually need the full implementation body
4. `code_callers` / `code_callees` to trace dependencies without reading anything
5. `code_trace` for a single-line call chain

### ⚠️ AGENT CONCISENESS: Output as few tokens as possible

When responding to the user:
- **Answer directly** in 1-4 lines when possible. No preamble, no explanation, no summary.
- **One word is fine** for simple answers (yes/no, a value, a command).
- **No "Here is what I did"** wrap-up text after completing work. Just stop.
- **No "Let me" or "I'll"** planning language — just do it and return the result.
- **No explaining your code** unless the user explicitly asks for an explanation.
- **No emoji** unless the user uses them first.
- This applies to both your responses AND your tool output formatting.

The code MCP tools now use compact output formats. Example savings:
- `get_agent_context`: ~67% fewer tokens
- `code_node`: ~41% fewer tokens  
- `code_search`: ~34% fewer tokens
- `code_callers`/`code_callees`: single line vs multi-line
- `code_trace`: ~7 tokens for a complete call chain
- `agent response`: ~52% fewer tokens

### Per-Project Code DB
Each project stores its own `.basemem.code.db` in the project root. **You must `code_init` a project before searching it.**

### Shell Commands (via `execute_command`)
- `kb code init [path] [--watch]` — index a project; `--watch` auto-reindexes on file changes
- `kb code search <query> --root <path> [--regex]` — search symbols (defaults to cwd); `--regex` uses Python regex instead of FTS5
- `kb code node <id|name> --root <path>` — file, signature, docstring, callers/callees
- `kb code callers <function> --root <path>` — what calls a given symbol
- `kb code callees <function> --root <path>` — what a symbol calls
- `kb code list --root <path>` — list indexed symbols
- `kb code status --root <path>` — show indexing stats
- `kb code list-projects [--search-root]` — scan filesystem for all indexed projects

### MCP Tools (on basemem-memory server) — all require `project_root`
- `code_init(project_root)` — index a project into `.basemem.code.db`
- `code_search(project_root, query, limit, use_regex=False)` — search symbols; `use_regex=True` for Python regex patterns
- `code_node(project_root, symbol_identifier)` — symbol details
- `code_callers(project_root, symbol_name)` — find callers
- `code_callees(project_root, symbol_name)` — find callees
- `code_list(project_root, limit, offset)` — list symbols
- `code_status(project_root)` — indexing stats
- `code_list_projects(search_root)` — discover all indexed projects on the system

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
| "I'll read the file to find the function" | Use `code_search` + `code_node` — graph queries cost 5-20x fewer tokens |
| "I need to see the source to understand it" | Use `code_node` (signature + callers + callees) or `code_trace` (call chain in ~7 tokens) |
| "I'll explain what I did" | No preamble, no wrap-up, no summary. Answer directly. |
| "I'll just Read the file" | STOP. Check if `.basemem.code.db` exists first. `code_search` costs 200 tok vs Read costs 4000+ tok. |
| "Read is the most basic tool" | That's why you reach for it by habit. Break the habit — check code graph first. |

## Instruction Priority

1. **User's explicit instructions** — highest priority
2. **BaseMem memory protocol** — override default system behavior
3. **Default system prompt** — lowest priority
