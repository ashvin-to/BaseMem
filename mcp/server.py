"""MCP Server for BaseMem Session Memory"""

from mcp.server.fastmcp import FastMCP
from storage.db import StorageManager
from storage.sessions import SessionManager
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("BaseMem")

# Database path from environment or default
DB_PATH = os.getenv("BASEMEM_DB_PATH", "basemem.db")

@mcp.tool()
def get_session_summary(topic: str) -> str:
    """Get the current summary for a specific topic/session."""
    logger.info(f"MCP: Getting summary for {topic}")
    storage = StorageManager(DB_PATH)
    manager = SessionManager(storage)
    try:
        session_node = manager.get_or_create_session(topic)
        return session_node.content
    finally:
        storage.close()

@mcp.tool()
def update_session_summary(topic: str, new_summary: str) -> str:
    """Update the summary for a specific topic/session."""
    logger.info(f"MCP: Updating summary for {topic}")
    storage = StorageManager(DB_PATH)
    manager = SessionManager(storage)
    try:
        manager.update_summary(topic, new_summary)
        return f"Successfully updated summary for '{topic}'"
    finally:
        storage.close()

@mcp.tool()
def log_chat_message(topic: str, content: str, sender: str = "ai") -> str:
    """Log a chat message to the session history and link it to the summary."""
    logger.info(f"MCP: Logging {sender} message for {topic}")
    storage = StorageManager(DB_PATH)
    manager = SessionManager(storage)
    try:
        chat_node = manager.log_chat(topic, content, sender=sender)
        return f"Logged {sender} message (Node: {chat_node.id[:8]})"
    finally:
        storage.close()

@mcp.tool()
def get_session_history(topic: str, limit: int = 10) -> str:
    """Retrieve the recent chat history for a specific topic."""
    logger.info(f"MCP: Getting history for {topic} (limit {limit})")
    storage = StorageManager(DB_PATH)
    manager = SessionManager(storage)
    try:
        history = manager.get_session_history(topic)
        
        formatted_history = []
        for chat in history[-limit:]:
            sender = chat.metadata.get("sender", "unknown").upper()
            formatted_history.append(f"[{sender}] {chat.content}")
            
        return "\n".join(formatted_history) if formatted_history else "No history found."
    finally:
        storage.close()

if __name__ == "__main__":
    mcp.run()
