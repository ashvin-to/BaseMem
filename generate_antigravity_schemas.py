#!/usr/bin/env python3
import os
import sys
import json
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()
MCP_PYTHON = str(BASE_DIR / "venv" / "bin" / "python3")
MCP_SCRIPT = str(BASE_DIR / "mem-mcp.py")

db_path = os.environ.get("BASEMEM_DB_PATH", str(Path.home() / ".basemem" / "basemem.db"))
env = os.environ.copy()
env["BASEMEM_DB_PATH"] = db_path

p = subprocess.Popen([MCP_PYTHON, MCP_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)

def send(msg):
    data = json.dumps(msg) + "\n"
    p.stdin.write(data.encode('utf-8'))
    p.stdin.flush()

def read():
    while True:
        line = p.stdout.readline()
        if not line: return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

send({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "antigravity-extractor", "version": "1.0"}
    }
})

while True:
    res = read()
    if res and res.get("id") == 1:
        break

send({
    "jsonrpc": "2.0",
    "method": "notifications/initialized"
})

send({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
})

tools = []
while True:
    res = read()
    if not res:
        break
    if res.get("id") == 2:
        tools = res.get("result", {}).get("tools", [])
        break

out_dir = Path.home() / ".gemini" / "antigravity" / "mcp" / "basemem-memory"
out_dir.mkdir(parents=True, exist_ok=True)

for tool in tools:
    name = tool.get("name")
    if name:
        schema = {
            "name": name,
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object"})
        }
        (out_dir / f"{name}.json").write_text(json.dumps(schema, indent=2))

p.terminate()
print(f"Schemas for {len(tools)} tools generated in {out_dir}")
