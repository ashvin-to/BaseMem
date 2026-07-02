"""Graph traversal and relationship management

This module implements core graph operations:
- Node/edge linking with explicit relationship types
- Neighbor traversal up to N hops
- Shortest path finding (BFS)
- Cluster detection (connected components)
- Automatic node linking using "Semantic Gravity" (keyword overlap)
- Node importance calculation (centrality + weight + recency)

Semantic Gravity Algorithm:
    Auto-links new nodes to existing nodes without ML models (zero-RAM):
    1. For each existing node, compute two similarity scores:
       - Keyword overlap: shared tags / total tags (Jaccard similarity)
       - Text overlap: shared tokens / total tokens (set similarity)
    2. Hybrid score = (keyword_score × 0.8) + (text_score × 0.2)
       - Keywords weighted higher because they're human/AI-curated
       - Text is secondary signal (can have common English words)
    3. Filter: Keep only candidates above threshold (default 0.3)
    4. Top-K: Limit to top 3 connections to avoid "spaghetti graph"
    5. Create RELATED_TO edges with the computed scores

Complexity: O(n) for new node auto-linking where n = existing nodes
"""

import logging
from collections import deque

from models import Edge, EdgeType, Node
from storage.db import StorageManager

logger = logging.getLogger(__name__)


class GraphEngine:
    """Manages graph-based operations and relationship discovery"""

    def __init__(self, storage: StorageManager):
        self.storage = storage

    def link_nodes(self, from_id: str, to_id: str, edge_type: EdgeType, weight: float = 1.0) -> Edge:
        """Create a relationship between two nodes"""
        edge = Edge(
            from_id=from_id,
            to_id=to_id,
            edge_type=edge_type,
            weight=weight,
            confidence=1.0,
        )
        self.storage.add_edge(edge)
        return edge

    def get_neighbors(self, node_id: str, depth: int = 1) -> dict[str, Node]:
        """Get all neighboring nodes up to a certain depth"""
        visited = {node_id}
        queue = deque([(node_id, 0)])
        neighbors = {}

        while queue:
            current_id, current_depth = queue.popleft()

            if current_depth >= depth:
                continue

            neighbor_ids = self.storage.get_neighbors(current_id)
            for nid in neighbor_ids:
                if nid not in visited:
                    visited.add(nid)
                    node = self.storage.get_node(nid)
                    if node:
                        neighbors[nid] = node
                        queue.append((nid, current_depth + 1))

        return neighbors

    def find_path(self, start_id: str, end_id: str) -> list[str]:
        """Find the shortest path between two nodes (BFS)"""
        if start_id == end_id:
            return [start_id]

        visited = {start_id}
        parent: dict = {}
        queue = deque([start_id])

        while queue:
            current_id = queue.popleft()
            if current_id == end_id:
                path = []
                while current_id in parent:
                    path.append(current_id)
                    current_id = parent[current_id]
                path.append(start_id)
                return path[::-1]

            neighbor_ids = self.storage.get_neighbors(current_id)
            for nid in neighbor_ids:
                if nid not in visited:
                    visited.add(nid)
                    parent[nid] = current_id
                    queue.append(nid)

        return []

    def get_shortest_path(self, from_id: str, to_id: str) -> list[str] | None:
        """Compatibility wrapper for callers that expect None when no path exists."""
        path = self.find_path(from_id, to_id)
        return path or None

    def get_clusters(self) -> list[set[str]]:
        """Identify disconnected components in the graph"""
        all_nodes = self.storage.get_all_nodes()
        unvisited = {n.id for n in all_nodes}
        clusters = []

        while unvisited:
            start_node = next(iter(unvisited))
            visited = {start_node}
            queue = deque([start_node])

            while queue:
                current_id = queue.popleft()
                neighbor_ids = self.storage.get_neighbors(current_id)
                for nid in neighbor_ids:
                    if nid in unvisited and nid not in visited:
                        visited.add(nid)
                        queue.append(nid)

            clusters.append(visited)
            unvisited -= visited

        return clusters

    def auto_link_nodes(self, new_node_id: str, threshold: float = 0.3, limit: int = 3) -> list[Edge]:
        """
        Auto-link a new node to existing nodes using Semantic Gravity (keyword-based).

        Algorithm (Zero-RAM, No Models):
        1. Extract keywords from new node
        2. For each existing node:
           a. Compute keyword Jaccard similarity: overlap / union
           b. Compute text token similarity: shared tokens / total tokens
           c. Combine: score = (keyword × 0.8) + (text × 0.2)
        3. Filter by threshold (default 0.3)
        4. Sort by score and take top `limit` (default 3)
        5. Create RELATED_TO edges to top candidates

        Rationale for Weights:
        - Keywords 0.8: AI-curated tags, high signal-to-noise
        - Text 0.2: Fallback signal, catches common English overlap
        - This prevents over-linking while catching semantic relationships

        Why Top-K = 3:
        - Prevents "spaghetti ball" dense graphs
        - 3 connections per new node is sufficient for discoverability
        - Maintains sparsity and query performance

        Args:
            new_node_id: ID of the node to link
            threshold: Minimum similarity score to create a link (0-1, default 0.3)
                      Increase to 0.5+ for stricter links
                      Decrease to 0.1 for aggressive linking
            limit: Maximum number of edges to create per node (default 3)
                  Increase to allow denser graphs (slower queries)
                  Decrease to maintain sparsity

        Returns:
            List[Edge]: Edges created, empty if new_node not found or no matches

        Raises:
            None (logs errors internally)

        Side effects:
            - Creates edges in storage (committed to DB)
            - Logs each auto-link with score for debugging

        Examples:
            # Auto-link with defaults (0.3 threshold, top 3)
            edges = graph_engine.auto_link_nodes("node-123")
            print(f"Created {len(edges)} auto-links")

            # Stricter linking (higher threshold, fewer connections)
            edges = graph_engine.auto_link_nodes("node-123", threshold=0.5, limit=2)

            # Aggressive linking (lower threshold, more connections)
            edges = graph_engine.auto_link_nodes("node-123", threshold=0.2, limit=5)

        Notes:
            - Keywords treated as ground truth (weighted 0.8)
            - If new node has no keywords, only text similarity used
            - Existing node's weight and decay_score not used in linking decision
            - Linking is directional (new → existing only)

        DEPRECATED: Use SessionManager._auto_link_note or recompute_links instead.
        This method operates on the legacy `Node`/`Edge` model (UUID keys).
        """
        import warnings
        warnings.warn(
            "GraphEngine.auto_link_nodes is deprecated. "
            "Use SessionManager.recompute_links() instead.",
            DeprecationWarning, stacklevel=2,
        )
        new_node = self.storage.get_node(new_node_id)
        if not new_node:
            return []

        existing_nodes = self.storage.get_all_nodes()
        existing_nodes = [n for n in existing_nodes if n.id != new_node_id]

        if not existing_nodes:
            return []

        candidates = []
        new_keywords = set(new_node.keywords)
        new_text = (new_node.title + " " + new_node.content).lower()

        for existing_node in existing_nodes:
            # 1. Keyword/Tag Overlap (Primary Signal)
            existing_keywords = set(existing_node.keywords)
            keyword_score = 0.0
            if new_keywords and existing_keywords:
                overlap = len(new_keywords & existing_keywords)
                union_size = len(new_keywords | existing_keywords)
                keyword_score = overlap / union_size if union_size > 0 else 0

            # 2. Text Overlap (Secondary Signal)
            existing_text = (existing_node.title + " " + existing_node.content).lower()
            text_score = 0.0
            new_tokens = set(new_text.split())
            existing_tokens = set(existing_text.split())

            if new_tokens and existing_tokens:
                overlap = len(new_tokens & existing_tokens)
                union_size = len(new_tokens | existing_tokens)
                text_score = overlap / union_size if union_size > 0 else 0

            # Hybrid score (No models needed)
            final_score = (keyword_score * 0.8) + (text_score * 0.2)

            if final_score >= threshold:
                candidates.append((existing_node.id, final_score))

        # Sort and take Top K
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:limit]

        created_edges = []
        for target_id, score in top_candidates:
            edge = self.link_nodes(new_node_id, target_id, EdgeType.RELATED_TO)
            created_edges.append(edge)
            logger.info(f"Auto-linked {new_node_id} <-> {target_id} (keyword score: {score:.2f})")

        return created_edges

    def get_graph_stats(self) -> dict:
        """Get comprehensive graph statistics"""
        nodes = self.storage.get_all_nodes()
        all_edges = self.storage.get_edges()

        if not nodes:
            return {"nodes": 0, "edges": 0, "clusters": 0, "avg_clustering_coeff": 0}

        # Calculate average clustering (simplified)
        total_clustering = 0.0
        for node in nodes:
            neighbor_ids = self.storage.get_neighbors(node.id)
            if len(neighbor_ids) < 2:
                continue

            # Find edges between neighbors
            possible_edges = len(neighbor_ids) * (len(neighbor_ids) - 1) / 2
            actual_edges = 0
            for i in range(len(neighbor_ids)):
                for j in range(i + 1, len(neighbor_ids)):
                    if self.storage.get_edges(from_id=neighbor_ids[i], to_id=neighbor_ids[j]):
                        actual_edges += 1

            total_clustering += actual_edges / possible_edges

        avg_clustering = total_clustering / len(nodes)

        return {
            "nodes": len(nodes),
            "edges": len(all_edges),
            "clusters": len(self.get_clusters()),
            "avg_clustering_coeff": avg_clustering,
            "edge_types": {et.value: sum(1 for e in all_edges if e.edge_type == et)
                          for et in EdgeType},
        }
