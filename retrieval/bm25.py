"""BM25 retriever for keyword-based search"""

from typing import List, Tuple, Dict, Set
from collections import Counter
import math
import logging

from modelsimport Node
from storage.db import StorageManager

logger = logging.getLogger(__name__)


class BM25Retriever:
    """Keyword retriever using TF-IDF (works better than BM25 for small corpora)"""

    def __init__(self, storage: StorageManager):
        self.storage = storage
        self.corpus: List[Node] = []
        self.doc_vectors: List[Dict[str, float]] = []  # TF-IDF vectors
        self._build_index()

    def _build_index(self):
        """Build TF-IDF index from all nodes"""
        self.corpus = self.storage.get_all_nodes()
        
        if not self.corpus:
            return

        # Tokenize all documents
        tokenized_docs = []
        for node in self.corpus:
            tokens = (node.title.lower().split() + 
                     node.content.lower().split() + 
                     [k.lower() for k in node.keywords])
            tokenized_docs.append(tokens)

        # Calculate IDF (Inverse Document Frequency)
        num_docs = len(tokenized_docs)
        idf: Dict[str, float] = {}
        
        for doc_tokens in tokenized_docs:
            unique_tokens = set(doc_tokens)
            for token in unique_tokens:
                if token not in idf:
                    idf[token] = 0
                idf[token] += 1

        # Convert to IDF scores: log((total_docs) / (docs_with_term))
        for token in idf:
            idf[token] = math.log((num_docs + 1) / (idf[token] + 1))

        # Build TF-IDF vectors for each document
        self.doc_vectors = []
        for doc_tokens in tokenized_docs:
            tf = Counter(doc_tokens)
            tfidf = {}
            for token, count in tf.items():
                tfidf[token] = count * idf[token]
            self.doc_vectors.append(tfidf)

        self.idf = idf
        logger.info(f"Built TF-IDF index with {len(self.corpus)} documents")

    def search(self, query: str, top_k: int = 50) -> List[Tuple[str, float]]:
        """
        Search using TF-IDF
        
        Returns list of (node_id, score) tuples (0-1 range)
        """
        if not self.corpus or not self.doc_vectors:
            return []

        # Tokenize query
        query_tokens = query.lower().split()
        if not query_tokens:
            return []

        # Calculate TF-IDF score for each document
        scores = []
        for doc_idx, doc_vector in enumerate(self.doc_vectors):
            score = 0.0
            for token in query_tokens:
                if token in doc_vector:
                    score += doc_vector[token]
            scores.append(score)

        # Get top k results
        ranked = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True
        )[:top_k]

        if not ranked:
            return []

        # Normalize scores to 0-1 range
        min_score = min(s for _, s in ranked)
        max_score = max(s for _, s in ranked)
        
        results = []
        for idx, score in ranked:
            # Normalize to 0-1 range
            if max_score > min_score:
                normalized = (score - min_score) / (max_score - min_score)
            else:
                normalized = 0.5 if score > 0 else 0.0
            
            results.append((self.corpus[idx].id, normalized))

        logger.debug(f"TF-IDF search for '{query}' returned {len(results)} results")
        return results

    def rebuild(self):
        """Rebuild index (call after adding new nodes)"""
        self._build_index()
