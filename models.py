"""Core data models for BaseMem

This module defines the fundamental data structures:
- Node: Knowledge base unit with metadata (title, content, type, keywords)
- Edge: Typed relationship between two nodes with confidence scores
- Context packet: Formatted output for LLM consumption
- Retrieval result: Search result with score and source tracking

All models are Pydantic dataclasses with automatic serialization/deserialization.
Node IDs are UUIDs by default (deterministic with given seeds).
All timestamps are stored as ISO format strings.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import uuid


class NodeType(str, Enum):
    """
    Enumeration of node types in the knowledge graph.
    
    Types:
    - CONCEPT: Abstract idea or theory (purple in UI)
    - FACT: Concrete data point or assertion (blue in UI)
    - SUMMARY: Human/AI-generated summary of related information (orange)
    - CONVERSATION: Message or dialog turn from an agent (cyan)
    - TASK: Action item or goal
    - QUESTION: Unanswered or key question
    - EXAMPLE: Concrete example or case study
    """
    CONCEPT = "concept"
    FACT = "fact"
    SUMMARY = "summary"
    CONVERSATION = "conversation"
    TASK = "task"
    QUESTION = "question"
    EXAMPLE = "example"


class EdgeType(str, Enum):
    """
    Enumeration of semantic relationship types.
    
    Types:
    - IS_A: Taxonomic/hierarchical (e.g., "Dog is a Mammal")
    - PART_OF: Compositional relationship (e.g., "Chapter is part of Book")
    - RELATED_TO: General semantic similarity (used by Semantic Gravity)
    - CAUSES: Causal relationship (e.g., "Error causes Crash")
    - DEPENDS_ON: Dependency (e.g., "Task depends on Prerequisites")
    - CONTRADICTS: Logical contradiction (e.g., "AI replaces vs AI augments")
    - DERIVED_FROM: Information provenance (e.g., "Conclusion derived from Study")
    """
    IS_A = "is_a"
    PART_OF = "part_of"
    RELATED_TO = "related_to"
    CAUSES = "causes"
    DEPENDS_ON = "depends_on"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"


@dataclass
class Node:
    """
    Represents a knowledge base unit in the graph.
    
    A node is the atomic unit of knowledge in BaseMem. It can be:
    - A concept (abstract idea)
    - A fact (concrete statement)
    - A summary (condensed information)
    - A conversation turn (AI/human message)
    
    Fields:
        id: Unique identifier (UUID4 by default, deterministic if seeded)
        title: Short label for the node (max 256 chars recommended)
        content: Full content/description (unlimited)
        node_type: Classification (see NodeType enum)
        keywords: List of tags/keywords for retrieval and linking
                 Should be curated by AI (5-10 keywords recommended)
        embedding: Vector representation for semantic search
                  None by default (can be set externally)
        weight: Importance score for ranking (0-1, affects retrieval)
               Increased when node is used in answers
        created_at: Timestamp when node was created (set automatically)
        last_accessed: Timestamp when node was last used/retrieved (updated auto)
        decay_score: Time-based decay multiplier (1.0 = no decay)
                    Decreases score for old nodes (implement manually if needed)
        metadata: Arbitrary JSON-serializable data (source, author, version, etc.)
                 Used for filtering and tracking provenance
    
    Invariants:
    - id is unique across all nodes in a graph
    - id should be deterministic (same input → same id)
    - keywords should be lowercase and normalized
    - weight should be in range [0, 10]
    - decay_score should be in range [0, 1]
    
    Example:
        node = Node(
            title="Machine Learning",
            content="ML is a subset of AI...",
            node_type=NodeType.CONCEPT,
            keywords=["ml", "ai", "learning", "algorithms"],
            metadata={"source": "doc-123", "confidence": 0.95}
        )
        storage.add_node(node)
    """
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
    """
    Represents a typed relationship between two nodes.
    
    Edges are directed (from_id → to_id) and can represent:
    - Taxonomic relationships (IS_A)
    - Compositional relationships (PART_OF)
    - Semantic similarity (RELATED_TO - used by Semantic Gravity)
    - Causal relationships (CAUSES)
    - Dependencies (DEPENDS_ON)
    - Contradictions (CONTRADICTS)
    - Provenance (DERIVED_FROM)
    
    Fields:
        from_id: Source node ID
        to_id: Target node ID
        edge_type: Type of relationship (see EdgeType enum)
        weight: Relationship strength (0-1, affects ranking)
               Default 1.0 (neutral)
        confidence: Confidence in the relationship (0-1)
                   1.0 = certain, 0.5 = uncertain, 0 = unknown
                   Used by orchestrator for probabilistic ranking
        created_at: Timestamp when edge was created
        metadata: Arbitrary JSON data (reason, source, score, etc.)
    
    Invariants:
    - from_id != to_id (no self-loops)
    - (from_id, to_id, edge_type) is unique (no duplicate relationships)
    - weight in [0, 1]
    - confidence in [0, 1]
    
    Example:
        edge = Edge(
            from_id=node1_id,
            to_id=node2_id,
            edge_type=EdgeType.RELATED_TO,
            weight=0.85,
            confidence=0.9,
            metadata={"auto_linked": True, "score": 0.85}
        )
        storage.add_edge(edge)
    """
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
