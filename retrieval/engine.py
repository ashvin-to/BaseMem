"""Hybrid retrieval engine combining BM25 and vector search"""

from typing import List, Dict, Set
import logging

from modelsimport Node, RetrievalResult
from storage.db import StorageManager
from .bm25 import BM25Retriever
from .vector import VectorRetriever

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """Orchestrates hybrid retrieval from keyword and vector indices"""

    def __init__(self, storage: StorageManager):
        self.storage = storage
        self.bm25 = BM25Retriever(storage)
        self.vector = VectorRetriever(storage)

    def retrieve(self, query: str, top_k: int = 10) -> List[RetrievalResult]:
        """
        Hybrid retrieval combining BM25 and vector search (Optional)
        """
        # 1. Get Keyword results
        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        
        # 2. Get Vector results (with lazy-load check)
        vector_results = []
        try:
            vector_results = self.vector.search(query, top_k=top_k * 2)
        except Exception:
            pass # Fallback to keyword only

        # 3. Merge results
        if not vector_results:
            merged = []
            for node_id, score in bm25_results:
                node = self.storage.get_node(node_id)
                if node:
                    merged.append(RetrievalResult(node=node, score=score, source="bm25"))
            return merged[:top_k]

        return self._merge_results(bm25_results, vector_results, top_k)

    def _merge_results(
        self,
        bm25_results: List[tuple],
        vector_results: List[tuple],
        top_k: int
    ) -> List[RetrievalResult]:
        """Merge and rank results from both methods"""
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
