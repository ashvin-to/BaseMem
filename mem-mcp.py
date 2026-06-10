#!/usr/bin/env python3
"""MCP server entry point for BaseMem agent memory."""
import sys
from pathlib import Path
BASE_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(BASE_DIR / "src"))
from basemem.mcp.server import server
if __name__ == "__main__":
    server.run()
