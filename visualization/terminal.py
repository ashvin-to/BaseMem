"""Terminal-based graph visualization using ASCII art"""

import os
from typing import Dict, List, Set
from collections import defaultdict
import textwrap
from modelsimport Node
from storage.db import StorageManager
from graph.engine import GraphEngine


class TerminalGraphVisualizer:
    """ASCII-based graph visualization for terminal"""

    def __init__(self, storage: StorageManager, graph: GraphEngine):
        self.storage = storage
        self.graph = graph
        self.colors = {
            "reset": "\033[0m",
            "bold": "\033[1m",
            "green": "\033[92m",
            "blue": "\033[94m",
            "yellow": "\033[93m",
            "magenta": "\033[95m",
            "cyan": "\033[96m",
            "gray": "\033[90m",
        }

    def _colorize(self, text: str, color: str) -> str:
        """Apply terminal color"""
        if os.environ.get("NO_COLOR"):
            return text
        return f"{self.colors.get(color, '')}{text}{self.colors['reset']}"

    def _node_symbol(self, node_type: str) -> str:
        """Get symbol for node type"""
        symbols = {
            "concept": "◇",
            "fact": "■",
            "summary": "▲",
            "conversation": "●",
            "task": "[x]",
            "question": "?",
            "example": "*",
        }
        return symbols.get(node_type, "○")

    def visualize_node(self, node_id: str, depth: int = 2) -> str:
        """Visualize a single node with context"""
        node = self.storage.get_node(node_id)
        if not node:
            return self._colorize("Node not found", "red")

        output = []

        # Node header
        symbol = self._node_symbol(node.node_type.value)
        title = self._colorize(f"{symbol} {node.title}", "bold")
        output.append(title)
        output.append(self._colorize("─" * len(node.title), "gray"))

        # Node details
        output.append(f"{self._colorize('Type:', 'cyan')} {node.node_type.value}")
        output.append(f"{self._colorize('Weight:', 'cyan')} {node.weight:.2f}")
        
        if node.keywords:
            keywords_str = ", ".join(node.keywords)
            output.append(f"{self._colorize('Keywords:', 'cyan')} {keywords_str}")

        # Content preview
        if node.content:
            preview = node.content[:200]
            if len(node.content) > 200:
                preview += "..."
            output.append(f"\n{self._colorize('Content:', 'cyan')}")
            for line in textwrap.wrap(preview, width=60):
                output.append(f"  {line}")

        # Neighbors
        neighbors = self.graph.get_neighbors(node_id, depth=1)
        edges = self.storage.get_edges(from_id=node_id)

        if edges:
            output.append(f"\n{self._colorize('Connected to:', 'green')} ({len(edges)} edges)")
            for edge in edges[:5]:  # Show first 5
                target = self.storage.get_node(edge.to_id)
                if target:
                    arrow = "→"
                    edge_type = self._colorize(f"[{edge.edge_type.value}]", "yellow")
                    confidence = f"({edge.confidence:.2f})"
                    output.append(f"  {arrow} {target.title} {edge_type} {confidence}")
            
            if len(edges) > 5:
                output.append(f"  ... and {len(edges) - 5} more")

        return "\n".join(output)

    def visualize_graph_summary(self) -> str:
        """Visualize full graph statistics"""
        stats = self.graph.get_graph_stats()
        nodes = self.storage.get_all_nodes()

        output = []
        output.append(self._colorize("╔════════════════════════════════════════╗", "bold"))
        output.append(self._colorize("║          BASEMEM KNOWLEDGE BASE       ║", "bold"))
        output.append(self._colorize("╚════════════════════════════════════════╝", "bold"))
        output.append("")

        # Statistics
        output.append(self._colorize("[*] Statistics", "green"))
        output.append(f"  Nodes:              {self._colorize(str(stats['total_nodes']), 'cyan')}")
        output.append(f"  Edges:              {self._colorize(str(stats['total_edges']), 'cyan')}")
        avg_edges = f"{stats['avg_edges_per_node']:.2f}"
        output.append(f"  Avg Edges/Node:     {self._colorize(avg_edges, 'cyan')}")
        output.append(f"  Clusters:           {self._colorize(str(stats['clusters']), 'cyan')}")
        avg_coeff = f"{stats['avg_clustering_coeff']:.3f}"
        output.append(f"  Clustering Coeff:   {self._colorize(avg_coeff, 'cyan')}")

        # Node types
        if stats["edge_types"]:
            output.append(f"\n{self._colorize('Edge Types', 'green')}")
            for edge_type, count in sorted(stats["edge_types"].items(), key=lambda x: x[1], reverse=True):
                if count > 0:
                    output.append(f"  {edge_type:20s} {self._colorize(str(count), 'yellow')}")

        # Top nodes
        if nodes:
            output.append(f"\n{self._colorize('Most Important Nodes', 'green')}")
            sorted_nodes = sorted(nodes, key=lambda n: n.weight, reverse=True)[:5]
            for i, node in enumerate(sorted_nodes, 1):
                symbol = self._node_symbol(node.node_type.value)
                weight = self._colorize(f"{node.weight:.2f}", "yellow")
                output.append(f"  {i}. {symbol} {node.title} ({weight})")

        # Clusters
        clusters = self.graph.get_clusters()
        if clusters:
            output.append(f"\n{self._colorize('Connected Components', 'green')}")
            sorted_clusters = sorted(clusters, key=len, reverse=True)[:5]
            for i, cluster in enumerate(sorted_clusters, 1):
                cluster_nodes = [self.storage.get_node(nid) for nid in cluster]
                cluster_nodes = [n for n in cluster_nodes if n]
                titles = ", ".join([n.title[:20] for n in cluster_nodes[:3]])
                size = self._colorize(str(len(cluster)), "cyan")
                output.append(f"  {i}. [{size} nodes] {titles}")

        return "\n".join(output)

    def visualize_neighborhood(self, node_id: str, depth: int = 1) -> str:
        """Visualize node and its neighborhood as a tree"""
        node = self.storage.get_node(node_id)
        if not node:
            return self._colorize("Node not found", "red")

        output = []
        symbol = self._node_symbol(node.node_type.value)
        output.append(self._colorize(f"{symbol} {node.title}", "bold"))

        # Get neighbors at each depth
        visited: Set[str] = {node_id}
        current_level = {node_id}

        for d in range(1, depth + 1):
            next_level: Set[str] = set()
            
            for current_id in current_level:
                neighbors = self.graph.get_neighbors(current_id, depth=1)
                for neighbor_id, neighbor_node in neighbors.items():
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_level.add(neighbor_id)
                        
                        # Add with indentation
                        indent = "  " * d
                        symbol = self._node_symbol(neighbor_node.node_type.value)
                        title_colored = self._colorize(neighbor_node.title, "cyan")
                        output.append(f"{indent}├─ {symbol} {title_colored}")

            current_level = next_level

        return "\n".join(output)

    def visualize_path(self, from_id: str, to_id: str) -> str:
        """Visualize shortest path between two nodes"""
        path = self.graph.get_shortest_path(from_id, to_id)
        
        if not path:
            return self._colorize(f"No path found from {from_id} to {to_id}", "yellow")

        output = []
        output.append(self._colorize(f"Shortest Path ({len(path)} steps)", "green"))
        output.append(self._colorize("─" * 40, "gray"))

        for i, node_id in enumerate(path):
            node = self.storage.get_node(node_id)
            if node:
                symbol = self._node_symbol(node.node_type.value)
                title = self._colorize(node.title, "cyan")
                
                if i == 0:
                    prefix = "START"
                    prefix_color = "green"
                elif i == len(path) - 1:
                    prefix = "END"
                    prefix_color = "magenta"
                else:
                    prefix = str(i)
                    prefix_color = "yellow"
                
                prefix_str = self._colorize(f"[{prefix}]", prefix_color)
                
                if i < len(path) - 1:
                    output.append(f"{prefix_str} {symbol} {title}")
                    output.append("  ↓")
                else:
                    output.append(f"{prefix_str} {symbol} {title}")

        return "\n".join(output)

    def visualize_network_ascii(self) -> str:
        """Simple ASCII network visualization (limited to small graphs)"""
        nodes = self.storage.get_all_nodes()
        
        if len(nodes) == 0:
            return "Empty graph"
        
        if len(nodes) > 15:
            return "Graph too large for ASCII visualization (>15 nodes). Use web interface."

        output = []
        output.append(self._colorize("Network Graph (ASCII)", "bold"))
        output.append(self._colorize("─" * 40, "gray"))

        # Create simple text grid
        for i, node in enumerate(nodes, 1):
            symbol = self._node_symbol(node.node_type.value)
            edges = self.storage.get_edges(from_id=node.id)
            edge_count = self._colorize(f"[{len(edges)} edges]", "yellow")
            
            weight = self._colorize(f"{node.weight:.2f}w", "cyan")
            output.append(f"{i:2}. {symbol} {node.title:30s} {edge_count} {weight}")

        # Show connections
        output.append("")
        output.append(self._colorize("Connections:", "green"))
        edge_count = 0
        for node in nodes:
            for edge in self.storage.get_edges(from_id=node.id):
                edge_count += 1
                if edge_count <= 10:
                    target = self.storage.get_node(edge.to_id)
                    if target:
                        edge_type = self._colorize(edge.edge_type.value, "yellow")
                        output.append(f"  {node.title} → {target.title} ({edge_type})")
        
        if edge_count > 10:
            output.append(f"  ... and {edge_count - 10} more connections")

        return "\n".join(output)
