**Tool Mapping for Antigravity Agents:**

BaseMem tools are loaded lazily. You MUST use the `call_mcp_tool` tool to invoke them. 
Set `ServerName` to `"basemem-memory"`.

- `list_planets` — `call_mcp_tool(ServerName="basemem-memory", ToolName="list_planets", Arguments={})`
- `get_agent_context(topic, query)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="get_agent_context", Arguments={"topic": topic, "query": query})`
- `add_note(topic, kind, content)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="add_note", Arguments={"topic": topic, "kind": kind, "content": content})`
- `update_planet(topic, current_state, next_step)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="update_planet", Arguments={"topic": topic, "current_state": current_state, "next_step": next_step})`
- `log_turn(topic, content)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="log_turn", Arguments={"topic": topic, "content": content})`
- `search_nodes(query, limit)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="search_nodes", Arguments={"query": query, "limit": limit})`
- `search_notes(topic, kind, query, limit)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="search_notes", Arguments={"topic": topic, "kind": kind, "query": query, "limit": limit})`
- `get_node(node_id)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="get_node", Arguments={"node_id": node_id})`
- `read_planet(topic)` — `call_mcp_tool(ServerName="basemem-memory", ToolName="read_planet", Arguments={"topic": topic})`
