"""Context orchestrator for token-budgeted retrieval and ranking"""

from typing import List
import logging

from modelsimport Node, ContextPacket, RetrievalResult
from retrieval.engine import RetrievalEngine
from graph.engine import GraphEngine
from storage.db import StorageManager

logger = logging.getLogger(__name__)


class ContextOrchestrator:
    """
    Orchestrates retrieval, deduplication, ranking, and context formatting
    
    Responsibilities:
    - Token budgeting
    - Deduplication
    - Ranking + diversity control
    - Structured context formatting
    """

    def __init__(
        self,
        storage: StorageManager,
        token_budget: int = 2000,
        avg_tokens_per_node: int = 100,
    ):
        """Initialize orchestrator"""
        self.storage = storage
        self.retrieval = RetrievalEngine(storage)
        self.graph = GraphEngine(storage)
        self.token_budget = token_budget
        self.avg_tokens_per_node = avg_tokens_per_node

    def orchestrate(self, query: str) -> ContextPacket:
        """
        Full orchestration pipeline:
        1. Retrieve relevant nodes
        2. Deduplicate
        3. Rank by relevance and diversity
        4. Pack within token budget
        5. Format for LLM
        """
        # Step 1: Retrieve
        retrieval_results = self.retrieval.retrieve(query, top_k=20)

        if not retrieval_results:
            logger.warning(f"No results found for query: {query}")
            return self._empty_packet(query)

        # Step 2-3: Deduplicate and rank
        ranked_nodes = self._deduplicate_and_rank(query, retrieval_results)

        # Step 4: Pack within token budget
        packed_nodes = self._pack_within_budget(ranked_nodes)

        # Step 5: Format
        packet = self._format_context_packet(query, packed_nodes)

        logger.info(
            f"Orchestrated context: {len(packed_nodes)} nodes, "
            f"{packet.token_count} tokens"
        )
        return packet

    def _deduplicate_and_rank(
        self,
        query: str,
        retrieval_results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """Deduplicate results and apply ranking"""
        seen_ids = set()
        deduplicated = []

        for result in retrieval_results:
            if result.node.id not in seen_ids:
                seen_ids.add(result.node.id)
                deduplicated.append(result)

        # Rank by: retrieval score × node weight × decay_score
        ranked = sorted(
            deduplicated,
            key=lambda r: (
                r.score * r.node.weight * r.node.decay_score
            ),
            reverse=True
        )

        logger.debug(f"Deduplicated to {len(ranked)} unique nodes")
        return ranked

    def _pack_within_budget(self, nodes: List[RetrievalResult]) -> List[Node]:
        """Select nodes that fit within token budget"""
        selected = []
        token_count = 0

        for result in nodes:
            node_tokens = len(result.node.content.split())
            if token_count + node_tokens <= self.token_budget:
                selected.append(result.node)
                token_count += node_tokens
            else:
                break

        logger.debug(f"Packed {len(selected)} nodes within {token_count} tokens")
        return selected

    def _format_context_packet(
        self,
        query: str,
        nodes: List[Node]
    ) -> ContextPacket:
        """Format nodes into structured context packet"""
        concept = ""
        related = []
        facts = []
        examples = []
        source_nodes = []

        for i, node in enumerate(nodes):
            source_nodes.append(node.id)

            if i == 0:
                # First node is main concept
                concept = f"{node.title} → {node.content[:100]}"
            elif node.node_type.value == "fact":
                facts.append(node.title)
            elif node.node_type.value == "example":
                examples.append(node.content[:80])
            else:
                related.append(node.title)

        token_count = sum(len(n.content.split()) for n in nodes)

        packet = ContextPacket(
            concept=concept,
            related=related[:5],  # Limit to 5
            facts=facts[:5],
            examples=examples[:5],
            token_count=token_count,
            source_nodes=source_nodes,
        )

        return packet

    def _empty_packet(self, query: str) -> ContextPacket:
        """Return empty packet when no results found"""
        return ContextPacket(
            concept=f"No information found for: {query}",
            related=[],
            facts=[],
            examples=[],
            token_count=10,
            source_nodes=[],
        )
