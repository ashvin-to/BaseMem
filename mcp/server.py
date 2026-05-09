"""MCP server for BaseMem shared agent memory."""

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from storage.db import StorageManager
from storage.sessions import SessionManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("BaseMem")


def _db_path() -> str:
    """Resolve the database path using the same default as the CLI."""
    return os.getenv("BASEMEM_DB_PATH", str(Path.home() / ".basemem" / "basemem.db"))


def _with_manager():
    storage = StorageManager(_db_path())
    return storage, SessionManager(storage)


@mcp.tool()
def get_agent_context(topic: str, query: str = "") -> str:
    """Return the compact pre-answer memory block for a topic."""
    logger.info("MCP: get_agent_context topic=%s query=%s", topic, query)
    storage, manager = _with_manager()
    try:
        return manager.build_agent_context(topic, query=query or None)
    finally:
        storage.close()


@mcp.tool()
def read_planet(topic: str) -> str:
    """Read the canonical shared task state for a topic."""
    logger.info("MCP: read_planet topic=%s", topic)
    storage, manager = _with_manager()
    try:
        node = manager.get_planet(topic)
        return node.content if node else f"Planet not found for topic '{topic}'."
    finally:
        storage.close()


@mcp.tool()
def log_turn(topic: str, content: str, agent_id: str = "default", sender: str = "ai") -> str:
    """Append a turn to the shared planet activity log."""
    logger.info("MCP: log_turn topic=%s agent_id=%s sender=%s", topic, agent_id, sender)
    storage, manager = _with_manager()
    try:
        folder_name = Path.cwd().name
        node = manager.log_chat_to_planet(folder_name, topic, content, agent_id, sender=sender)
        return f"Logged turn to {node.id}"
    finally:
        storage.close()


@mcp.tool()
def update_planet(
    topic: str,
    status: str = "",
    goal: str = "",
    current_state: str = "",
    next_step: str = "",
    file_path: str = "",
    command: str = "",
    handoff: str = "",
) -> str:
    """Update the structured shared memory for a topic."""
    logger.info("MCP: update_planet topic=%s", topic)
    storage, manager = _with_manager()
    try:
        folder_name = Path.cwd().name
        node = manager.update_planet(
            folder_name,
            topic,
            status=status or None,
            goal=goal or None,
            current_state=current_state or None,
            next_step=next_step or None,
            file_path=file_path or None,
            command=command or None,
            handoff=handoff or None,
        )
        return f"Updated planet {node.id}"
    finally:
        storage.close()


@mcp.tool()
def add_note(
    topic: str,
    kind: str,
    content: str,
    agent_id: str = "default",
    title: str = "",
    status: str = "open",
) -> str:
    """Add a typed durable note linked to a topic."""
    logger.info("MCP: add_note topic=%s kind=%s agent_id=%s", topic, kind, agent_id)
    storage, manager = _with_manager()
    try:
        folder_name = Path.cwd().name
        node = manager.add_note(
            folder_name,
            topic,
            kind,
            content,
            agent_id=agent_id,
            title=title or None,
            status=status,
        )
        return f"Added note {node.id}"
    finally:
        storage.close()


if __name__ == "__main__":
    mcp.run()
