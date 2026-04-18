"""Graph traversal and relationship management"""

from typing import List, Dict, Set, Tuple, Optional
from collections import deque
import logging
import math

from modelsimport Node, Edge, EdgeType
from storage.db import StorageManager

logger = logging.getLogger(__name__)


class GraphEngine:
    """Manages graph traversal and relationship inference"""

    def __init__(self, storage: StorageManager):
        self.storage = storage

    def get_neighbors(
        self, 
        node_id: str, 
        depth: int = 1,
        edge_type: Optional[EdgeType] = None
    ) -> Dict[str, Node]:
        """
        Get all neighbors within depth
        
        Returns dict mapping node_id -> Node
        """
        visited: Set[str] = set()
        to_visit = deque([(node_id, 0)])
        neighbors = {}

        while to_visit:
            current_id, current_depth = to_visit.popleft()

            if current_id in visited or current_depth > depth:
                continue

            visited.add(current_id)

            if current_id != node_id:  # Don't include the root node
                node = self.storage.get_node(current_id)
                if node:
                    neighbors[current_id] = node

            if current_depth < depth:
                adjacent = self.storage.get_neighbors(current_id, edge_type)
                for adj_id in adjacent:
                    if adj_id not in visited:
                        to_visit.append((adj_id, current_depth + 1))

        logger.debug(f"Found {len(neighbors)} neighbors for {node_id} at depth {depth}")
        return neighbors

    def get_subgraph(
        self,
        node_ids: List[str],
        depth: int = 1
    ) -> Tuple[List[Node], List[Edge]]:
        """
        Get induced subgraph from set of node IDs
        
        Returns (nodes, edges)
        """
        # Collect all nodes within depth
        all_nodes: Dict[str, Node] = {}
        all_node_ids: Set[str] = set(node_ids)

        for node_id in node_ids:
            node = self.storage.get_node(node_id)
            if node:
                all_nodes[node_id] = node

            neighbors = self.get_neighbors(node_id, depth)
            all_nodes.update(neighbors)
            all_node_ids.update(neighbors.keys())

        # Get edges between these nodes
        edges = []
        for from_id in all_node_ids:
            for edge in self.storage.get_edges(from_id=from_id):
                if edge.to_id in all_node_ids:
                    edges.append(edge)

        logger.debug(f"Subgraph has {len(all_nodes)} nodes and {len(edges)} edges")
        return list(all_nodes.values()), edges

    def get_shortest_path(self, from_id: str, to_id: str) -> Optional[List[str]]:
        """
        Find shortest path between two nodes using BFS
        
        Returns list of node IDs or None if no path exists
        """
        if from_id == to_id:
            return [from_id]

        visited: Set[str] = set()
        to_visit = deque([(from_id, [from_id])])

        while to_visit:
            current_id, path = to_visit.popleft()

            if current_id in visited:
                continue
            visited.add(current_id)

            neighbors = self.storage.get_neighbors(current_id)
            for neighbor_id in neighbors:
                if neighbor_id == to_id:
                    return path + [to_id]

                if neighbor_id not in visited:
                    to_visit.append((neighbor_id, path + [neighbor_id]))

        logger.debug(f"No path found from {from_id} to {to_id}")
        return None

    def get_clusters(self, resolution: float = 1.0) -> List[List[str]]:
        """
        Detect communities/clusters in graph using a simple approach
        (more sophisticated algorithms could be added)
        
        Returns list of clusters (each cluster is a list of node IDs)
        """
        # For now, use connected components
        nodes = self.storage.get_all_nodes()
        node_ids = {n.id for n in nodes}
        
        visited: Set[str] = set()
        clusters: List[List[str]] = []

        for node_id in node_ids:
            if node_id in visited:
                continue

            # BFS to find connected component
            cluster = []
            to_visit = deque([node_id])

            while to_visit:
                current_id = to_visit.popleft()

                if current_id in visited:
                    continue

                visited.add(current_id)
                cluster.append(current_id)

                neighbors = self.storage.get_neighbors(current_id)
                for neighbor_id in neighbors:
                    if neighbor_id not in visited:
                        to_visit.append(neighbor_id)

            if cluster:
                clusters.append(cluster)

        logger.info(f"Found {len(clusters)} clusters")
        return clusters

    def link_nodes(self, from_id: str, to_id: str, edge_type: EdgeType) -> Edge:
        """Create an edge between nodes"""
        edge = Edge(
            from_id=from_id,
            to_id=to_id,
            edge_type=edge_type,
        )
        self.storage.add_edge(edge)
        logger.debug(f"Linked {from_id} -> {to_id} ({edge_type})")
        return edge

    def calculate_edge_weight(
        self,
        from_id: str,
        to_id: str,
        similarity: float,
        usage: int = 0,
        recency: float = 1.0
    ) -> float:
        """
        Calculate edge weight using formula:
        weight = similarity × usage × recency
        """
        weight = similarity * (1 + usage * 0.1) * recency
        return min(weight, 1.0)  # Cap at 1.0

    def auto_link_nodes(self, new_node_id: str, threshold: float = 0.5, limit: int = 3) -> List[Edge]:
        """
        Auto-link a new node to related nodes using vector similarity and keyword overlap.
        Includes a limit per node to prevent graph spaghetti.
        """
        new_node = self.storage.get_node(new_node_id)
        if not new_node:
            return []

        # 1. Get Semantic Similarities
        try:
            from ..retrieval.vector import VectorRetriever
            vector_engine = VectorRetriever(self.storage)
            semantic_results = vector_engine.search(new_node.content, top_k=50)
            semantic_scores = {node_id: score for node_id, score in semantic_results if node_id != new_node_id}
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            semantic_scores = {}

        existing_nodes = self.storage.get_all_nodes()
        existing_nodes = [n for n in existing_nodes if n.id != new_node_id]
        
        candidates = []
        new_keywords = set(new_node.keywords)
        
        for existing_node in existing_nodes:
            semantic_score = semantic_scores.get(existing_node.id, 0.0)
            
            keyword_score = 0.0
            existing_keywords = set(existing_node.keywords)
            if new_keywords and existing_keywords:
                overlap = len(new_keywords & existing_keywords)
                union_size = len(new_keywords | existing_keywords)
                keyword_score = overlap / union_size if union_size > 0 else 0
            
            hybrid_score = (semantic_score * 0.7) + (keyword_score * 0.3)
            
            if hybrid_score >= threshold:
                candidates.append((existing_node.id, hybrid_score))
        
        # 2. Sort by score and take only the Top K (Limit)
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:limit]

        created_edges = []
        for target_id, score in top_candidates:
            edge = self.link_nodes(new_node_id, target_id, EdgeType.RELATED_TO)
            created_edges.append(edge)
            logger.info(f"Auto-linked {new_node_id} <-> {target_id} (score: {score:.2f})")
        
        return created_edges

    def get_graph_stats(self) -> Dict:
        """Get comprehensive graph statistics"""
        nodes = self.storage.get_all_nodes()
        all_edges = []
        
        for node in nodes:
            all_edges.extend(self.storage.get_edges(from_id=node.id))
        
        # Calculate clustering coefficient
        total_triangles = 0
        for node in nodes:
            neighbors = set(self.storage.get_neighbors(node.id))
            if len(neighbors) < 2:
                continue
            
            # Count edges between neighbors
            edges_between = 0
            for n1 in neighbors:
                n1_neighbors = set(self.storage.get_neighbors(n1))
                edges_between += len(neighbors & n1_neighbors)
            
            # Local clustering = edges_between / (k * (k-1))
            k = len(neighbors)
            if k > 1:
                total_triangles += edges_between / (k * (k - 1))
        
        avg_clustering = total_triangles / len(nodes) if nodes else 0
        
        return {
            "total_nodes": len(nodes),
            "total_edges": len(all_edges),
            "avg_edges_per_node": len(all_edges) / len(nodes) if nodes else 0,
            "clusters": len(self.get_clusters()),
            "avg_clustering_coeff": avg_clustering,
            "edge_types": {et.value: sum(1 for e in all_edges if e.edge_type == et) 
                          for et in EdgeType},
        }
