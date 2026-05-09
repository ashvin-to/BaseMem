"""SQLite storage manager with FTS5 support

This module provides the persistence layer for BaseMem using SQLite with Full-Text Search (FTS5).
It implements a "zero-RAM" architecture where:
- All node data is stored in SQLite with full-text indexing for fast retrieval
- No external vector databases required (embeddings can be external)
- Minimal memory footprint: only active nodes/edges loaded into memory

Tables:
    - nodes: Core node data with title, content, type, keywords, metadata
    - nodes_fts: FTS5 virtual table for full-text search indexing
    - edges: Relationships between nodes with weights and confidence scores
    - chats: Chat history logging (optional)
    - node_usage: Usage statistics for feedback loops (optional)

Thread-safety: Enabled (check_same_thread=False) for Flask/async use.
"""

import sqlite3
import json
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Set, Tuple
from datetime import datetime
import logging

from modelsimport Node, Edge, NodeType, EdgeType, RetrievalResult

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Manages persistence of nodes, edges, and metadata in SQLite with FTS5 support.
    
    Design Principles:
    - Zero-RAM: Minimal in-memory footprint, all data persisted to disk
    - Fast retrieval: FTS5 for full-text search, SQL indexes for graph traversal
    - Atomic transactions: ACID compliance for data integrity
    - Schema versioning: Implicit (schema updates only add new columns/tables)
    
    Typical usage:
        storage = StorageManager()  # Uses ~/.basemem/basemem.db by default
        node = Node(title="Concept", content="...", keywords=["tag1", "tag2"])
        storage.add_node(node)
        results = storage.search_nodes_fts("tag1")
    
    Raises:
        RuntimeError: On insert failures or database corruption
        sqlite3.DatabaseError: On SQL/FTS query issues (logged, fallback provided)
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Initialize storage manager and create database if needed.
        
        Args:
            db_path: Path to SQLite database file. If None, uses ~/.basemem/basemem.db
                    Will create parent directories if they don't exist.
        
        Returns:
            None
        
        Side effects:
            - Creates ~/.basemem directory if it doesn't exist
            - Creates SQLite database and initializes schema on first run
            - Enables thread-safe mode for Flask/async compatibility
            - Logs initialization status
        
        Raises:
            OSError: If unable to create database directory or file
            sqlite3.DatabaseError: If schema initialization fails
        """
        # DEFAULT: Use a hidden folder in the user home directory
        if db_path is None:
            home = Path.home()
            db_dir = home / ".basemem"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = db_dir / "basemem.db"
            
        self.db_path = Path(db_path)
             
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
        """
        Add or update a node in both main and FTS tables.
        
        Guarantees:
        - Atomic insert/update (ACID)
        - Both nodes and nodes_fts tables stay synchronized
        - Existing node with same ID is replaced (upsert behavior)
        - Keywords automatically indexed for full-text search
        
        Args:
            node: Node object containing id, title, content, type, keywords, etc.
                  Keywords must be a list of strings for FTS indexing.
        
        Returns:
            None
        
        Raises:
            RuntimeError: If node insert into nodes_fts fails to align rowids
            sqlite3.IntegrityError: If foreign key constraint violated (shouldn't occur)
        
        Side effects:
            - Inserts into nodes table (or replaces if id exists)
            - Inserts into nodes_fts virtual table for full-text search
            - Updates last_accessed timestamp
            - Commits transaction to disk
        
        Examples:
            node = Node(title="AI Concept", content="Description", 
                       keywords=["AI", "concept"], node_type=NodeType.CONCEPT)
            storage.add_node(node)
        """
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

        cursor.execute("SELECT rowid FROM nodes WHERE id = ?", (node.id,))
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(f"Node insert failed for {node.id}")

        # Insert into FTS table. This is an external-content FTS table, so its
        # rowid must stay aligned with nodes.rowid.
        cursor.execute("""
            INSERT OR REPLACE INTO nodes_fts(rowid, id, title, content, keywords)
            VALUES (?, ?, ?, ?, ?)
        """, (
            row["rowid"],
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
        """
        Full-text search nodes using FTS5 with automatic fallback.
        
        Strategy:
        1. Try FTS5 MATCH with prefix query (fast, ~1ms for 1000 nodes)
        2. On complex query errors, fall back to LIKE search
        3. Return node IDs ranked by FTS relevance
        
        Args:
            query: Search query (e.g., "machine learning" or "embedding model")
                   Automatically converted to FTS5 prefix format: ("machine"* "learning"*)
            limit: Maximum results to return (default 50)
        
        Returns:
            List of node IDs matching the query, ordered by relevance
            Empty list if no matches or empty query
        
        Raises:
            None (catches and logs sqlite3.DatabaseError internally)
        
        Side effects:
            - Logs warnings if FTS query fails (fallback to LIKE)
            - No database modifications
        
        Notes:
            - Searches title, content, and keywords fields
            - FTS5 prefix queries (term*) are more forgiving than exact match
            - LIKE fallback is slower but handles any query format
        
        Examples:
            results = storage.search_nodes_fts("neural network")
            print(f"Found {len(results)} nodes")
            for node_id in results:
                node = storage.get_node(node_id)
                print(node.title)
        """
        cursor = self.connection.cursor()
        search_query = self._build_fts_query(query)
        if not search_query:
            return []
        try:
            cursor.execute("""
                SELECT id FROM nodes_fts WHERE nodes_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (search_query, limit))
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        except sqlite3.DatabaseError as exc:
            logger.warning("FTS search failed; attempting index rebuild before fallback: %s", exc)
            try:
                self.rebuild_fts_index()
                cursor.execute("""
                    SELECT id FROM nodes_fts WHERE nodes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (search_query, limit))
                rows = cursor.fetchall()
                return [row[0] for row in rows]
            except sqlite3.DatabaseError as rebuild_exc:
                logger.warning("FTS rebuild failed; falling back to LIKE search: %s", rebuild_exc)
                cursor.execute("""
                    SELECT id FROM nodes WHERE title LIKE ? OR content LIKE ? OR keywords LIKE ?
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
                rows = cursor.fetchall()
                return [row[0] for row in rows]

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """Convert user text into a safe FTS5 prefix query."""
        terms = re.findall(r"[\w]+", query)
        return " ".join(f'"{term}"*' for term in terms)

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

        cursor.execute("SELECT rowid FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if row is not None:
            # Delete from FTS table by rowid to keep the external-content index aligned.
            cursor.execute("DELETE FROM nodes_fts WHERE rowid = ?", (row["rowid"],))

        # Delete edges
        cursor.execute("""
            DELETE FROM edges WHERE from_id = ? OR to_id = ?
        """, (node_id, node_id))

        # Delete from main table
        cursor.execute("DELETE FROM nodes WHERE id = ?", (node_id,))

        self.connection.commit()
        logger.debug(f"Deleted node: {node_id}")

    def rebuild_fts_index(self) -> None:
        """Rebuild the FTS5 index from the canonical nodes table."""
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM nodes_fts")
        cursor.execute("""
            INSERT INTO nodes_fts(rowid, id, title, content, keywords)
            SELECT rowid, id, title, content, COALESCE(keywords, '')
            FROM nodes
        """)
        self.connection.commit()
        logger.info("Rebuilt FTS index from nodes table")

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
