"""Session management for evolving summaries and raw chat logs"""

import logging
from typing import List, Optional, Tuple
from datetime import datetime
import uuid

from modelsimport Node, Edge, NodeType, EdgeType
from .db import StorageManager

logger = logging.getLogger(__name__)

class SessionManager:
    """Manages long-term session memory and chat history in BaseMem"""

    def __init__(self, storage: StorageManager):
        self.storage = storage

    def get_or_create_session(self, topic: str) -> Node:
        """
        Get or create a SUMMARY node for the given topic.
        Title format: "Session: <topic>"
        """
        title = f"Session: {topic}"
        
        # More efficient check: Search all nodes but filter in Python (or use a direct SQL query)
        nodes = self.storage.get_all_nodes()
        for node in nodes:
            # Check for exact title match OR topic in metadata
            if node.node_type == NodeType.SUMMARY:
                if node.title == title or node.metadata.get("topic") == topic:
                    # Update title if it was slightly different
                    if node.title != title:
                        node.title = title
                        self.storage.add_node(node)
                    return node

        # Create new session summary node only if absolutely not found
        logger.info(f"Creating new session node for topic: {topic}")
        session_node = Node(
            title=title,
            content=f"Summary of conversation regarding: {topic}",
            node_type=NodeType.SUMMARY,
            metadata={"topic": topic, "version": 1}
        )
        self.storage.add_node(session_node)
        return session_node

    def log_chat(self, topic: str, content: str, sender: str = "ai") -> Node:
        """
        Append a chat message to a single 'Main History' node for the topic.
        This ensures only one 'Main' node exists per topic.
        """
        session_node = self.get_or_create_session(topic)
        
        # Deterministic ID for the Main History node
        history_node_id = f"main-history-{topic.lower().replace(' ', '-')}"
        
        history_node = self.storage.get_node(history_node_id)
        
        timestamp = datetime.utcnow().isoformat()
        new_entry = f"\n\n--- [{timestamp}] {sender.upper()} ---\n{content}"
        
        # Extract new keywords from the content to keep searchability high
        new_words = [w.lower() for w in content.split() if len(w) > 4 and w.isalnum()]
        
        if history_node:
            # Append to existing history
            history_node.content += new_entry
            history_node.last_accessed = datetime.utcnow()
            
            # Merge keywords (unique set)
            existing_keywords = set(history_node.keywords)
            existing_keywords.update(new_words)
            history_node.keywords = list(existing_keywords)[:50] # Cap at 50
            
            self.storage.add_node(history_node)
        else:
            # Create the first history node
            history_node = Node(
                id=history_node_id,
                title=f"Main History: {topic}",
                content=f"Full conversation history for topic: {topic}{new_entry}",
                node_type=NodeType.CONVERSATION,
                keywords=new_words[:20],
                metadata={"topic": topic, "is_main_history": True}
            )
            self.storage.add_node(history_node)

            # Link it to the summary node once
            edge = Edge(
                from_id=history_node.id,
                to_id=session_node.id,
                edge_type=EdgeType.PART_OF,
                weight=1.0,
                confidence=1.0
            )
            self.storage.add_edge(edge)
            
        # Trigger Global Auto-Linking to connect project islands
        try:
            from graph.engine import GraphEngine
            graph_engine = GraphEngine(self.storage)
            # Find and create semantic connections across the whole graph
            graph_engine.auto_link_nodes(history_node.id, threshold=0.15)
            graph_engine.auto_link_nodes(session_node.id, threshold=0.15)
        except Exception as e:
            logger.warning(f"Auto-linking failed: {e}")
        
        return history_node

    def update_summary(self, topic: str, new_summary: str) -> Node:
        """
        Update the content of the session summary node.
        """
        session_node = self.get_or_create_session(topic)
        session_node.content = new_summary
        session_node.last_accessed = datetime.utcnow()
        
        # Increment version in metadata
        version = session_node.metadata.get("version", 1)
        session_node.metadata["version"] = version + 1
        
        self.storage.add_node(session_node)
        return session_node

    def get_session_history(self, topic: str) -> List[Node]:
        """
        Retrieve all chat nodes linked to a topic session.
        """
        session_node = self.get_or_create_session(topic)
        neighbor_ids = self.storage.get_neighbors(session_node.id, edge_type=EdgeType.PART_OF)
        
        history = []
        for nid in neighbor_ids:
            node = self.storage.get_node(nid)
            if node and node.node_type == NodeType.CONVERSATION:
                history.append(node)
        
        # Sort by creation time
        history.sort(key=lambda x: x.created_at)
        return history

    def ingest_transcript(self, topic: str, content: str) -> Node:
        """
        Save a full transcript as a single node. 
        Uses a deterministic ID based on the topic to ensure re-ingestion 
        updates the existing node instead of creating duplicates.
        """
        session_node = self.get_or_create_session(topic)
        
        # Deterministic ID: Always the same for the same topic
        node_id = f"full-transcript-{topic.lower().replace(' ', '-')}"
        
        transcript_node = Node(
            id=node_id,
            title=f"Full Transcript: {topic}",
            content=content,
            node_type=NodeType.CONVERSATION,
            metadata={"topic": topic, "is_full_transcript": True}
        )
        self.storage.add_node(transcript_node)

        # Link to session summary (Edge creation is also idempotent in our DB)
        edge = Edge(
            from_id=transcript_node.id,
            to_id=session_node.id,
            edge_type=EdgeType.PART_OF,
            weight=1.0,
            confidence=1.0
        )
        self.storage.add_edge(edge)
        
        return transcript_node
