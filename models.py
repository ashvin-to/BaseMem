"""Core data models for BaseMem"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


class NodeType(str, Enum):
    """Enumeration of node types in the knowledge graph"""
    CONCEPT = "concept"
    FACT = "fact"
    SUMMARY = "summary"
    CONVERSATION = "conversation"
    TASK = "task"
    QUESTION = "question"
    EXAMPLE = "example"


class EdgeType(str, Enum):
    """Enumeration of edge types in the knowledge graph"""
    IS_A = "is_a"
    PART_OF = "part_of"
    RELATED_TO = "related_to"
    CAUSES = "causes"
    DEPENDS_ON = "depends_on"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"


@dataclass
class Node:
    """Represents a knowledge node in the graph"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    content: str = ""
    node_type: NodeType = NodeType.CONCEPT
    keywords: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    weight: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)
    decay_score: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "node_type": self.node_type.value,
            "keywords": self.keywords,
            "embedding": self.embedding,
            "weight": self.weight,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "decay_score": self.decay_score,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        """Create node from dictionary"""
        data_copy = data.copy()
        if isinstance(data_copy.get("node_type"), str):
            data_copy["node_type"] = NodeType(data_copy["node_type"])
        if "created_at" in data_copy and isinstance(data_copy["created_at"], str):
            data_copy["created_at"] = datetime.fromisoformat(data_copy["created_at"])
        if "last_accessed" in data_copy and isinstance(data_copy["last_accessed"], str):
            data_copy["last_accessed"] = datetime.fromisoformat(data_copy["last_accessed"])
        return cls(**data_copy)


@dataclass
class Edge:
    """Represents a relationship between two nodes"""
    from_id: str
    to_id: str
    edge_type: EdgeType
    weight: float = 1.0
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert edge to dictionary"""
        return {
            "from_id": self.from_id,
            "to_id": self.to_id,
            "edge_type": self.edge_type.value,
            "weight": self.weight,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Edge":
        """Create edge from dictionary"""
        data_copy = data.copy()
        if isinstance(data_copy.get("edge_type"), str):
            data_copy["edge_type"] = EdgeType(data_copy["edge_type"])
        if "created_at" in data_copy and isinstance(data_copy["created_at"], str):
            data_copy["created_at"] = datetime.fromisoformat(data_copy["created_at"])
        return cls(**data_copy)


@dataclass
class RetrievalResult:
    """Result from retrieval operation"""
    node: Node
    score: float
    source: str  # "bm25", "vector", or "combined"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextPacket:
    """Formatted context for LLM"""
    concept: str
    related: List[str]
    facts: List[str]
    examples: List[str]
    token_count: int
    source_nodes: List[str]

    def to_prompt_format(self) -> str:
        """Convert to structured prompt format"""
        parts = [
            f"[Concept]\n{self.concept}",
            f"[Related]\n" + "\n".join(f"- {r}" for r in self.related),
            f"[Facts]\n" + "\n".join(f"- {f}" for f in self.facts),
            f"[Example]\n" + "\n".join(f"- {e}" for e in self.examples),
        ]
        return "\n\n".join(parts)
