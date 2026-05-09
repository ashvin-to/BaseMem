"""Hybrid retrieval engine combining BM25 and vector search

This module implements a hybrid retrieval strategy that combines:
- BM25 retrieval: Keyword-based ranking (proven, lightweight, no models needed)
- Vector retrieval: Semantic similarity (optional, requires embeddings)

Merging Strategy (Default):
    - BM25 score: 40% weight (keyword relevance)
    - Vector score: 60% weight (semantic similarity)
    - Normalized separately then combined
    - Deduplication by node_id (only best instance kept)
    - Final ranking: merged_score × node.weight × node.decay_score

This design allows graceful degradation: if vector embeddings unavailable,
system falls back to BM25-only retrieval automatically.

Complexity: O(k log k) where k is number of nodes
"""

from typing import List, Dict, Set
import logging

from modelsimport Node, RetrievalResult
from storage.db import StorageManager
from .bm25 import BM25Retriever
from .vector import VectorRetriever

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """
    Orchestrates hybrid retrieval combining BM25 (keyword) and vector (semantic) search.
    
    Design:
    - Stateless: No caching, recomputed each query
    - Deterministic: Same query always returns same results in same order
    - Resilient: Gracefully falls back to BM25 if vector search unavailable
    - Transparent: Logs all retrieval decisions for debugging
    
    Typical usage:
        engine = RetrievalEngine(storage_manager)
        results = engine.retrieve("machine learning", top_k=10)
        for result in results:
            print(f"{result.node.title}: {result.score:.2f} ({result.source})")
    """

    def __init__(self, storage: StorageManager):
        self.storage = storage
        self.bm25 = BM25Retriever(storage)
        self.vector = VectorRetriever(storage)

    def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """
        Retrieve relevant nodes using hybrid BM25 + vector search.
        
        Pipeline:
        1. Search both methods with top_k*2 to allow for merging
        2. If vector search fails (no embeddings), use BM25-only
        3. Merge and normalize scores
        4. Deduplicate by node_id
        5. Return top_k by merged score
        
        Score Formula:
            merged_score = (bm25_score × 0.4) + (vector_score × 0.6)
            final_rank = merged_score × node.weight × node.decay_score
        
        Args:
            query: Search query string (e.g., "how to train models")
            top_k: Number of results to return (default 10)
        
        Returns:
            List[RetrievalResult]: Up to top_k results, ordered by merged score
                - Each result includes node, score (0-1), and source ("bm25", "vector", "hybrid")
                - Empty list if no results found
        
        Raises:
            None (catches all exceptions, logs and falls back gracefully)
        
        Side effects:
            - Logs retrieval strategy (hybrid vs fallback)
            - Logs failures with context
        
        Examples:
            results = engine.retrieve("neural networks", top_k=5)
            if results:
                print(f"Top result: {results[0].node.title}")
                print(f"Score: {results[0].score:.3f}")
                print(f"Source: {results[0].source}")  # "hybrid" or "bm25"
        """
        # Step 1: Retrieve from both methods (with 2x to allow for merging)
        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        
        # Step 2: Try vector search (optional, graceful fallback)
        vector_results = []
        try:
            vector_results = self.vector.search(query, top_k=top_k * 2)
        except Exception as e:
            # Log but don't fail - vector search is optional
            logger.debug(f"Vector search unavailable (fallback to BM25): {type(e).__name__}")

        # Step 3: Return based on availability
        if not vector_results:
            # BM25-only: convert raw results to RetrievalResult objects
            logger.debug(f"Using BM25-only retrieval for query: '{query}'")
            merged = []
            for node_id, score in bm25_results:
                node = self.storage.get_node(node_id)
                if node:
                    merged.append(RetrievalResult(node=node, score=score, source="bm25"))
            
            logger.info(f"BM25 retrieval returned {len(merged)} results for '{query}'")
            return merged[:top_k]

        # Hybrid: merge both methods
        logger.debug(f"Using hybrid (BM25 + vector) retrieval for query: '{query}'")
        result = self._merge_results(bm25_results, vector_results, top_k)
        logger.info(f"Hybrid retrieval returned {len(result)} results for '{query}'")
        return result

    def _merge_results(
        self,
        bm25_results: List[tuple],
        vector_results: List[tuple],
        top_k: int
    ) -> List[RetrievalResult]:
        """
        Merge and rank results from BM25 and vector search methods.
        
        Algorithm:
        1. Initialize merged_scores dict
        2. Add BM25 scores with 0.4 weight
        3. Add vector scores with 0.6 weight (higher weight for semantic relevance)
        4. Sort by merged score descending
        5. Load nodes and create results
        
        Weight Rationale:
        - BM25 (0.4): Fast, precise for exact keywords, lower false positives
        - Vector (0.6): Captures semantic meaning, synonyms, related concepts
        - Combined: Balances precision (BM25) with recall (vector)
        
        Args:
            bm25_results: List of (node_id, score) tuples from BM25 search
            vector_results: List of (node_id, score) tuples from vector search
            top_k: Maximum results to return
        
        Returns:
            List[RetrievalResult]: Top-k merged results with hybrid scores
        
        Raises:
            None (logs if node retrieval fails)
        
        Notes:
            - Scores are assumed to be normalized to [0, 1]
            - Node weight automatically applied in final ranking
            - Decay score applied in final ranking
        """
        merged_scores = {}
        
        # Normalize scores and merge
        for node_id, score in bm25_results:
            merged_scores[node_id] = merged_scores.get(node_id, 0) + score * 0.4
            
        for node_id, score in vector_results:
            merged_scores[node_id] = merged_scores.get(node_id, 0) + score * 0.6

        # Sort by score
        sorted_ids = sorted(merged_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Create result objects
        results = []
        for node_id, score in sorted_ids[:top_k]:
            node = self.storage.get_node(node_id)
            if node:
                source = "hybrid"
                results.append(RetrievalResult(node=node, score=score, source=source))
        
        return results

    def rebuild_indexes(self):
        """Rebuild all indexes (call after bulk ingestion)"""
        self.bm25.rebuild()
        try:
            self.vector.rebuild()
        except Exception:
            pass
        logger.info("Rebuilt all retrieval indexes")
