"""Session management for 3-Tier Galaxy (Unified Planet, Private Moons)"""

import logging
import re
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid

from modelsimport Node, Edge, NodeType, EdgeType
from .db import StorageManager

logger = logging.getLogger(__name__)

class SessionManager:
    """
    3-Tier Hierarchy:
    Sun (Tier 1): Folder Hub
    Planet (Tier 2): Shared Task/Topic node
    Moon (Tier 3): Private Agent-Session Archives
    """

    def __init__(self, storage: StorageManager):
        self.storage = storage

    @staticmethod
    def normalize_topic(topic: str) -> str:
        """Normalize human topic names into stable planet slugs."""
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        return slug or "general"

    @staticmethod
    def _now() -> str:
        return datetime.utcnow().isoformat()

    @staticmethod
    def _append_recent(items: List[Dict[str, Any]], item: Dict[str, Any], limit: int = 12) -> List[Dict[str, Any]]:
        items.append(item)
        return items[-limit:]

    @staticmethod
    def _list_section(items: List[str], empty: str = "- None") -> str:
        if not items:
            return empty
        return "\n".join(f"- {item}" for item in items)

    def _render_planet_content(self, topic: str, metadata: Dict[str, Any]) -> str:
        activity = metadata.get("recent_activity", [])
        notes = metadata.get("notes", [])
        files = metadata.get("files", [])
        commands = metadata.get("commands", [])
        next_steps = metadata.get("next_steps", [])
        decisions = [n for n in notes if n.get("kind") == "decision"]
        issues = [n for n in notes if n.get("kind") in {"issue", "question"} and n.get("status") != "done"]

        activity_lines = [
            f"- {item.get('timestamp', '')} {item.get('agent_id', 'unknown')}: {item.get('message', '')}"
            for item in activity[-8:]
        ]
        decision_lines = [f"- {n.get('content') or n.get('title')}" for n in decisions[-8:]]
        issue_lines = [f"- {n.get('content') or n.get('title')}" for n in issues[-8:]]

        return "\n".join([
            f"# Topic: {topic}",
            "",
            "## Goal",
            metadata.get("goal") or "Not set.",
            "",
            "## Status",
            metadata.get("status") or "active",
            "",
            "## Current State",
            metadata.get("current_state") or "No current state recorded.",
            "",
            "## Decisions",
            "\n".join(decision_lines) if decision_lines else "- None",
            "",
            "## Open Issues",
            "\n".join(issue_lines) if issue_lines else "- None",
            "",
            "## Next Steps",
            self._list_section(next_steps),
            "",
            "## Important Files",
            self._list_section(files),
            "",
            "## Commands",
            self._list_section(commands),
            "",
            "## Recent Activity",
            "\n".join(activity_lines) if activity_lines else "- None",
            "",
            "## Agent Handoff",
            metadata.get("handoff") or "Read this planet first. Open moons only when detailed transcript history is needed.",
        ])

    @staticmethod
    def _trim_text(value: str, limit: int = 600) -> str:
        """Normalize whitespace and cap long sections for prompt use."""
        compact = " ".join((value or "").split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def get_or_create_folder_hub(self, folder_name: str) -> Node:
        """Get/Create the Sun (Folder Hub)"""
        title = f"Session: {folder_name}"
        nodes = self.storage.get_all_nodes()
        for node in nodes:
            if node.node_type == NodeType.SUMMARY and node.title == title:
                return node

        node = Node(
            title=title,
            content=f"Global hub for project folder: {folder_name}",
            node_type=NodeType.SUMMARY,
            metadata={"is_folder_hub": True, "folder": folder_name}
        )
        self.storage.add_node(node)
        return node

    def get_or_create_task_planet(self, folder_name: str, topic: str) -> Node:
        """Get/Create the Planet (Shared Task) linked to Sun"""
        sun_node = self.get_or_create_folder_hub(folder_name)
        
        topic_slug = self.normalize_topic(topic)
        planet_id = f"planet-{topic_slug}"
        planet_node = self.storage.get_node(planet_id)
        
        if not planet_node:
            metadata = {
                "topic": topic_slug,
                "display_topic": topic,
                "aliases": sorted({topic, topic_slug}),
                "is_task_planet": True,
                "scope": "planet",
                "status": "active",
                "goal": "",
                "current_state": f"Unified task context for: {topic}",
                "next_steps": [],
                "files": [],
                "commands": [],
                "notes": [],
                "recent_activity": [],
                "created_at": self._now(),
                "updated_at": self._now(),
            }
            planet_node = Node(
                id=planet_id,
                title=f"{topic_slug}",
                content=self._render_planet_content(topic_slug, metadata),
                node_type=NodeType.CONVERSATION,
                keywords=[topic_slug, "planet", "task"],
                metadata=metadata,
            )
            self.storage.add_node(planet_node)
            self.storage.add_edge(Edge(from_id=planet_id, to_id=sun_node.id, edge_type=EdgeType.PART_OF, weight=1.0, confidence=1.0))
        else:
            metadata = planet_node.metadata
            aliases = set(metadata.get("aliases", []))
            aliases.update({topic, topic_slug})
            metadata.update({
                "topic": metadata.get("topic") or topic_slug,
                "display_topic": metadata.get("display_topic") or topic,
                "aliases": sorted(aliases),
                "is_task_planet": True,
                "scope": "planet",
                "updated_at": self._now(),
            })
            for key, default in {
                "status": "active",
                "goal": "",
                "current_state": planet_node.content or f"Unified task context for: {topic}",
                "next_steps": [],
                "files": [],
                "commands": [],
                "notes": [],
                "recent_activity": [],
            }.items():
                metadata.setdefault(key, default)
            planet_node.title = topic_slug
            planet_node.content = self._render_planet_content(topic_slug, metadata)
            planet_node.keywords = sorted(set(planet_node.keywords + [topic_slug, "planet", "task"]))
            planet_node.metadata = metadata
            self.storage.add_node(planet_node)
            
        return planet_node

    def log_chat_to_planet(self, folder_name: str, topic: str, content: str, agent_id: str, sender: str = "ai") -> Node:
        """Log turn to the Shared Planet"""
        planet_node = self.get_or_create_task_planet(folder_name, topic)
        timestamp = self._now()
        metadata = planet_node.metadata
        metadata["recent_activity"] = self._append_recent(
            metadata.get("recent_activity", []),
            {"timestamp": timestamp, "agent_id": agent_id, "sender": sender, "message": content},
        )
        metadata["updated_at"] = timestamp
        planet_node.metadata = metadata
        planet_node.content = self._render_planet_content(metadata["topic"], metadata)
        self.storage.add_node(planet_node)
        return planet_node

    def update_planet(
        self,
        folder_name: str,
        topic: str,
        status: Optional[str] = None,
        goal: Optional[str] = None,
        current_state: Optional[str] = None,
        next_step: Optional[str] = None,
        file_path: Optional[str] = None,
        command: Optional[str] = None,
        handoff: Optional[str] = None,
    ) -> Node:
        """Update structured planet fields."""
        planet_node = self.get_or_create_task_planet(folder_name, topic)
        metadata = planet_node.metadata
        if status:
            metadata["status"] = status
        if goal:
            metadata["goal"] = goal
        if current_state:
            metadata["current_state"] = current_state
        if next_step:
            steps = metadata.get("next_steps", [])
            if next_step not in steps:
                steps.append(next_step)
            metadata["next_steps"] = steps
        if file_path:
            files = metadata.get("files", [])
            if file_path not in files:
                files.append(file_path)
            metadata["files"] = files
        if command:
            commands = metadata.get("commands", [])
            if command not in commands:
                commands.append(command)
            metadata["commands"] = commands
        if handoff:
            metadata["handoff"] = handoff
        metadata["updated_at"] = self._now()
        planet_node.metadata = metadata
        planet_node.content = self._render_planet_content(metadata["topic"], metadata)
        self.storage.add_node(planet_node)
        return planet_node

    def add_note(
        self,
        folder_name: str,
        topic: str,
        kind: str,
        content: str,
        agent_id: str = "default",
        title: Optional[str] = None,
        status: str = "open",
    ) -> Node:
        """Create a typed collaboration node and link it to the planet."""
        planet_node = self.get_or_create_task_planet(folder_name, topic)
        topic_slug = planet_node.metadata["topic"]
        kind = kind.lower().strip() or "fact"
        node_type = {
            "decision": NodeType.FACT,
            "fact": NodeType.FACT,
            "task": NodeType.TASK,
            "issue": NodeType.QUESTION,
            "question": NodeType.QUESTION,
            "concept": NodeType.CONCEPT,
            "example": NodeType.EXAMPLE,
        }.get(kind, NodeType.FACT)
        note_id = f"{kind}-{topic_slug}-{uuid.uuid4().hex[:8]}"
        note = Node(
            id=note_id,
            title=title or content[:80],
            content=content,
            node_type=node_type,
            keywords=[topic_slug, kind, status],
            metadata={
                "project": folder_name,
                "topic": topic_slug,
                "scope": kind,
                "kind": kind,
                "status": status,
                "agent_id": agent_id,
                "source": "note",
                "created_by": agent_id,
                "updated_by": agent_id,
                "created_at": self._now(),
                "updated_at": self._now(),
            },
        )
        self.storage.add_node(note)
        self.storage.add_edge(Edge(from_id=note.id, to_id=planet_node.id, edge_type=EdgeType.PART_OF, weight=1.0, confidence=1.0))

        metadata = planet_node.metadata
        metadata["notes"] = self._append_recent(
            metadata.get("notes", []),
            {"id": note.id, "kind": kind, "title": note.title, "content": content, "status": status, "agent_id": agent_id},
            limit=30,
        )
        metadata["updated_at"] = self._now()
        planet_node.metadata = metadata
        planet_node.content = self._render_planet_content(topic_slug, metadata)
        self.storage.add_node(planet_node)
        return note

    def get_planet(self, topic: str) -> Optional[Node]:
        """Read a planet by normalized topic."""
        return self.storage.get_node(f"planet-{self.normalize_topic(topic)}")

    def get_active_planet(self) -> Optional[Node]:
        """Return the most recently updated planet node."""
        planets = [n for n in self.storage.get_all_nodes() if n.metadata.get("is_task_planet")]
        if not planets:
            return None
        return max(planets, key=lambda n: n.metadata.get("updated_at", ""))

    def build_agent_context(self, topic: str, query: Optional[str] = None, result_limit: int = 5) -> str:
        """Build a compact prompt block for agents to read before answering."""
        planet = self.get_planet(topic)
        topic_slug = self.normalize_topic(topic)

        if not planet:
            return "\n".join([
                "# Knowledge Base Context",
                f"Topic: {topic_slug}",
                "",
                "No stored context found for this topic yet.",
                "If you make durable decisions, create notes or log a turn after responding.",
            ])

        metadata = planet.metadata
        lines = [
            "# Knowledge Base Context",
            f"Topic: {metadata.get('display_topic') or topic_slug}",
            f"Status: {metadata.get('status', 'active')}",
            "",
            "## Goal",
            self._trim_text(metadata.get("goal") or "Not set.", 300),
            "",
            "## Current State",
            self._trim_text(metadata.get("current_state") or "No current state recorded.", 500),
        ]

        if metadata.get("next_steps"):
            lines.extend([
                "",
                "## Next Steps",
                *[f"- {self._trim_text(step, 180)}" for step in metadata["next_steps"][-5:]],
            ])

        notes = metadata.get("notes", [])
        if notes:
            lines.extend([
                "",
                "## Key Notes",
                *[
                    f"- [{note.get('kind', 'note')}] {self._trim_text(note.get('content') or note.get('title') or '', 220)}"
                    for note in notes[-8:]
                ],
            ])

        activity = metadata.get("recent_activity", [])
        if activity:
            lines.extend([
                "",
                "## Recent Activity",
                *[
                    f"- {item.get('agent_id', 'unknown')} ({item.get('sender', 'ai')}): {self._trim_text(item.get('message', ''), 220)}"
                    for item in activity[-6:]
                ],
            ])

        if query:
            related_ids = self.storage.search_nodes_fts(f"{topic_slug} {query}", limit=result_limit * 3)
            related_nodes = []
            for node_id in related_ids:
                node = self.storage.get_node(node_id)
                if not node or node.id == planet.id:
                    continue
                node_topic = node.metadata.get("topic")
                if node_topic and node_topic != topic_slug:
                    continue
                related_nodes.append(node)
                if len(related_nodes) >= result_limit:
                    break

            if related_nodes:
                lines.extend([
                    "",
                    "## Query-Relevant Memories",
                    *[
                        f"- [{node.node_type.value}] {node.title}: {self._trim_text(node.content, 220)}"
                        for node in related_nodes
                    ],
                ])

        handoff = metadata.get("handoff")
        if handoff:
            lines.extend([
                "",
                "## Handoff",
                self._trim_text(handoff, 400),
            ])

        lines.extend([
            "",
            "## Instructions",
            "- Use this memory before answering.",
            "- Prefer existing decisions unless the user asks to revisit them.",
            "- After answering, log durable updates back into the knowledge base.",
        ])

        return "\n".join(lines)

    def compact_planet(self, folder_name: str, topic: str, agent_id: str = "default") -> Node:
        """Re-render a planet from metadata and trim recent activity to compact size."""
        planet_node = self.get_or_create_task_planet(folder_name, topic)
        metadata = planet_node.metadata
        metadata["recent_activity"] = metadata.get("recent_activity", [])[-8:]
        metadata["notes"] = metadata.get("notes", [])[-30:]
        metadata["updated_at"] = self._now()
        metadata["compacted_by"] = agent_id
        planet_node.metadata = metadata
        planet_node.content = self._render_planet_content(metadata["topic"], metadata)
        self.storage.add_node(planet_node)
        return planet_node

    def ingest_archive_moon(self, folder_name: str, topic: str, full_transcript: str, agent_id: str) -> Node:
        """Create a UNIQUE Tier 3 Moon for this specific agent/session (Strict Mode)"""
        # Search for existing planet
        topic_slug = self.normalize_topic(topic)
        planet_id = f"planet-{topic_slug}"
        planet_node = self.storage.get_node(planet_id)
        
        # REFUSE to create a ghost planet if it does not exist
        if not planet_node:
            logger.warning(f"Archive rejected: No existing task planet found for topic '{topic}'. Start a turn first.")
            return None
        
        timestamp = self._now()
        moon_id = f"archive-{agent_id}-{topic_slug}-{uuid.uuid4().hex[:8]}"
        
        moon_node = Node(
            id=moon_id,
            title=f"History ({agent_id}): {topic_slug}",
            content=full_transcript,
            node_type=NodeType.CONVERSATION,
            keywords=[topic_slug, agent_id, "archive", "moon"],
            metadata={
                "topic": topic_slug,
                "agent_id": agent_id,
                "is_private_moon": True,
                "scope": "moon",
                "synced_at": timestamp,
            },
        )
        self.storage.add_node(moon_node)
        
        # LINK Private Moon to Shared Planet
        self.storage.add_edge(Edge(from_id=moon_id, to_id=planet_node.id, edge_type=EdgeType.PART_OF, weight=1.0, confidence=1.0))
        metadata = planet_node.metadata
        metadata["last_moon_id"] = moon_id
        metadata["updated_at"] = timestamp
        metadata["recent_activity"] = self._append_recent(
            metadata.get("recent_activity", []),
            {"timestamp": timestamp, "agent_id": agent_id, "sender": "sync", "message": f"Archived moon {moon_id}."},
        )
        planet_node.metadata = metadata
        planet_node.content = self._render_planet_content(topic_slug, metadata)
        self.storage.add_node(planet_node)
        
        return moon_node
    
    def get_neighbors(self, node_id: str):
        return self.storage.get_neighbors(node_id)
