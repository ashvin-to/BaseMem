"""SQLite storage manager with FTS5 support"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from modelsimport Node, Edge, NodeType, EdgeType, RetrievalResult

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages persistence of nodes, edges, and metadata in SQLite"""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize storage manager"""
        # Auto-detect db in current directory if not provided
        if db_path is None:
            db_path = "basemem.db"
            
        self.db_path = Path(db_path)
        # Ensure we don't accidentally create it in a system folder
        if not self.db_path.is_absolute() and not (Path.cwd() / self.db_path).parent.exists():
             self.db_path.parent.mkdir(parents=True, exist_ok=True)
             
        # Enable thread-safe mode for Flask/multi-threaded use
        self.connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def _initialize_schema(self):
        """Create tables if they don't exist"""
        cursor = self.connection.cursor()

        # Nodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                node_type TEXT NOT NULL,
                keywords TEXT,
                embedding BLOB,
                weight REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                last_accessed TEXT NOT NULL,
                decay_score REAL DEFAULT 1.0,
                metadata TEXT
            )
        """)

        # Full-text search table for nodes
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                id UNINDEXED,
                title,
                content,
                keywords,
                content=nodes,
                content_rowid=rowid
            )
        """)

        # Edges table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                from_id TEXT NOT NULL,
                to_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                confidence REAL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                metadata TEXT,
                PRIMARY KEY (from_id, to_id, edge_type),
                FOREIGN KEY (from_id) REFERENCES nodes(id),
                FOREIGN KEY (to_id) REFERENCES nodes(id)
            )
        """)

        # Chat logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                raw_text TEXT NOT NULL,
                processed_nodes TEXT,
                timestamp TEXT NOT NULL
            )
        """)

        # Node usage stats (for feedback loop)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS node_usage (
                node_id TEXT NOT NULL,
                query TEXT,
                used_in_answer BOOLEAN,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (node_id) REFERENCES nodes(id)
            )
        """)

        self.connection.commit()
        logger.info(f"Storage initialized at {self.db_path}")

    def add_node(self, node: Node) -> None:
        """Add or update a node"""
        cursor = self.connection.cursor()

        # Serialize fields
        keywords_json = json.dumps(node.keywords)
        metadata_json = json.dumps(node.metadata)

        # Insert into main table
        cursor.execute("""
            INSERT OR REPLACE INTO nodes
            (id, title, content, node_type, keywords, embedding, weight,
             created_at, last_accessed, decay_score, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            node.id,
            node.title,
            node.content,
            node.node_type.value,
            keywords_json,
            None,  # embedding stored separately in vector DB
            node.weight,
            node.created_at.isoformat(),
            node.last_accessed.isoformat(),
            node.decay_score,
            metadata_json,
        ))

        # Insert into FTS table
        cursor.execute("""
            INSERT OR REPLACE INTO nodes_fts(id, title, content, keywords)
            VALUES (?, ?, ?, ?)
        """, (
            node.id,
            node.title,
            node.content,
            " ".join(node.keywords),
        ))

        self.connection.commit()
        logger.debug(f"Added node: {node.id}")

    def add_edge(self, edge: Edge) -> None:
        """Add or update an edge"""
        cursor = self.connection.cursor()
        metadata_json = json.dumps(edge.metadata)

        cursor.execute("""
            INSERT OR REPLACE INTO edges
            (from_id, to_id, edge_type, weight, confidence, created_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            edge.from_id,
            edge.to_id,
            edge.edge_type.value,
            edge.weight,
            edge.confidence,
            edge.created_at.isoformat(),
            metadata_json,
        ))

        self.connection.commit()
        logger.debug(f"Added edge: {edge.from_id} -> {edge.to_id}")

    def get_node(self, node_id: str) -> Optional[Node]:
        """Retrieve a node by ID"""
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return self._row_to_node(row)

    def get_all_nodes(self) -> List[Node]:
        """Retrieve all nodes"""
        cursor = self.connection.cursor()
        cursor.execute("SELECT * FROM nodes")
        rows = cursor.fetchall()
        return [self._row_to_node(row) for row in rows]

    def search_nodes_fts(self, query: str, limit: int = 50) -> List[str]:
        """Full-text search on nodes (FTS5)"""
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT id FROM nodes_fts WHERE nodes_fts MATCH ?
            LIMIT ?
        """, (query, limit))
        rows = cursor.fetchall()
        return [row[0] for row in rows]

    def get_neighbors(self, node_id: str, edge_type: Optional[EdgeType] = None) -> List[str]:
        """Get all nodes connected to a given node"""
        cursor = self.connection.cursor()

        if edge_type:
            cursor.execute("""
                SELECT from_id, to_id FROM edges
                WHERE (from_id = ? OR to_id = ?) AND edge_type = ?
            """, (node_id, node_id, edge_type.value))
        else:
            cursor.execute("""
                SELECT from_id, to_id FROM edges
                WHERE from_id = ? OR to_id = ?
            """, (node_id, node_id))

        rows = cursor.fetchall()
        neighbors = set()
        for row in rows:
            if row[0] == node_id:
                neighbors.add(row[1])
            else:
                neighbors.add(row[0])
        return list(neighbors)

    def get_edges(self, from_id: Optional[str] = None, to_id: Optional[str] = None) -> List[Edge]:
        """Get edges matching criteria"""
        cursor = self.connection.cursor()

        if from_id and to_id:
            cursor.execute("""
                SELECT * FROM edges WHERE from_id = ? AND to_id = ?
            """, (from_id, to_id))
        elif from_id:
            cursor.execute("SELECT * FROM edges WHERE from_id = ?", (from_id,))
        elif to_id:
            cursor.execute("SELECT * FROM edges WHERE to_id = ?", (to_id,))
        else:
            cursor.execute("SELECT * FROM edges")

        rows = cursor.fetchall()
        return [self._row_to_edge(row) for row in rows]

    def log_node_usage(self, node_id: str, query: str, used_in_answer: bool) -> None:
        """Log node usage for feedback loop"""
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO node_usage (node_id, query, used_in_answer, timestamp)
            VALUES (?, ?, ?, ?)
        """, (node_id, query, used_in_answer, datetime.utcnow().isoformat()))
        self.connection.commit()

    def update_node_weight(self, node_id: str, weight: float) -> None:
        """Update node weight for ranking"""
        cursor = self.connection.cursor()
        cursor.execute("""
            UPDATE nodes SET weight = ?, last_accessed = ?
            WHERE id = ?
        """, (weight, datetime.utcnow().isoformat(), node_id))
        self.connection.commit()

    def delete_node(self, node_id: str) -> None:
        """Delete a node and its edges"""
        cursor = self.connection.cursor()

        # Delete from FTS table
        cursor.execute("DELETE FROM nodes_fts WHERE id = ?", (node_id,))

        # Delete edges
        cursor.execute("""
            DELETE FROM edges WHERE from_id = ? OR to_id = ?
        """, (node_id, node_id))

        # Delete from main table
        cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

        self.connection.commit()
        logger.debug(f"Deleted node: {node_id}")

    def close(self):
        """Close database connection"""
        self.connection.close()
        logger.info("Storage connection closed")

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        """Convert database row to Node object"""
        return Node(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            node_type=NodeType(row["node_type"]),
            keywords=json.loads(row["keywords"] or "[]"),
            embedding=None,  # Would be loaded from vector DB
            weight=row["weight"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_accessed=datetime.fromisoformat(row["last_accessed"]),
            decay_score=row["decay_score"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        """Convert database row to Edge object"""
        return Edge(
            from_id=row["from_id"],
            to_id=row["to_id"],
            edge_type=EdgeType(row["edge_type"]),
            weight=row["weight"],
            confidence=row["confidence"],
            created_at=datetime.fromisoformat(row["created_at"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )
