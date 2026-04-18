"""Session management for 3-Tier Galaxy (Unified Planet, Private Moons)"""

import logging
from typing import List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import uuid
import hashlib

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
        
        planet_id = f"planet-{topic.lower().replace(' ', '-')}"
        planet_node = self.storage.get_node(planet_id)
        
        if not planet_node:
            planet_node = Node(
                id=planet_id,
                title=f"{topic}",
                content=f"Unified task context for: {topic}",
                node_type=NodeType.CONVERSATION,
                metadata={"topic": topic, "is_task_planet": True}
            )
            self.storage.add_node(planet_node)
            self.storage.add_edge(Edge(from_id=planet_id, to_id=sun_node.id, edge_type=EdgeType.PART_OF, weight=1.0, confidence=1.0))
            
        return planet_node

    def log_chat_to_planet(self, folder_name: str, topic: str, content: str, agent_id: str, sender: str = "ai") -> Node:
        """Log turn to the Shared Planet"""
        planet_node = self.get_or_create_task_planet(folder_name, topic)
        timestamp = datetime.utcnow().isoformat()
        planet_node.content += f"\n\n--- [{timestamp}] {agent_id.upper()} ---\n{content}"
        self.storage.add_node(planet_node)
        return planet_node

    def ingest_archive_moon(self, folder_name: str, topic: str, full_transcript: str, agent_id: str) -> Node:
        """Create a UNIQUE Tier 3 Moon for this specific agent/session (Strict Mode)"""
        # Search for existing planet
        planet_id = f"planet-{topic.lower().replace(' ', '-')}"
        planet_node = self.storage.get_node(planet_id)
        
        # REFUSE to create a ghost planet if it does not exist
        if not planet_node:
            logger.warning(f"Archive rejected: No existing task planet found for topic '{topic}'. Start a turn first.")
            return None
        
        # Unique ID per Agent + Topic to prevent merging
        moon_id = f"archive-{agent_id}-{topic.lower().replace(' ', '-')}"
        
        moon_node = Node(
            id=moon_id,
            title=f"History ({agent_id}): {topic}",
            content=full_transcript,
            node_type=NodeType.CONVERSATION,
            metadata={"topic": topic, "agent_id": agent_id, "is_private_moon": True}
        )
        self.storage.add_node(moon_node)
        
        # LINK Private Moon to Shared Planet
        self.storage.add_edge(Edge(from_id=moon_id, to_id=planet_node.id, edge_type=EdgeType.PART_OF, weight=1.0, confidence=1.0))
        
        return moon_node
    
    def get_neighbors(self, node_id: str):
        return self.storage.get_neighbors(node_id)
