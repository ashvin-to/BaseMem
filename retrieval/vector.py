"""Vector retriever for semantic search"""

from typing import List, Tuple, Optional
import logging
from pathlib import Path

from modelsimport Node
from storage.db import StorageManager

logger = logging.getLogger(__name__)

class VectorRetriever:
    """Vector-based retriever for semantic similarity search with lazy loading"""

    def __init__(self, storage: StorageManager, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize vector retriever
        """
        self.storage = storage
        self.model_name = model_name
        self.model = None # Lazy load
        self.embedding_dim = 384 # Default for all-MiniLM-L6-v2
        self.node_embeddings: Optional[any] = None
        self.node_ids: List[str] = []
        self.index: Optional[any] = None
        
        # Removed auto-index build to save RAM

    def _get_model(self):
        """Lazy load the model only when needed"""
        if self.model is None:
            logger.info(f"Loading embedding model {self.model_name} into RAM...")
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
            self.embedding_dim = self.model.get_embedding_dimension()
        return self.model

    def _unload_model(self):
        """Unload the model to free up RAM/CUDA memory immediately"""
        if self.model is not None:
            logger.info(f"Unloading embedding model {self.model_name} from RAM...")
            del self.model
            self.model = None
            
            # Force PyTorch and System to release all memory
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
                
            import gc
            gc.collect()
            logger.info("RAM Purge Complete.")

    def _build_index(self):
        """Build FAISS index from node embeddings and UNLOAD model"""
        import numpy as np
        try:
            import faiss
        except ImportError:
            faiss = None

        nodes = self.storage.get_all_nodes()
        
        if not nodes:
            logger.info("No nodes to index")
            return

        # 1. Load model lazily
        model = self._get_model()
        texts = [f"{n.title} {n.content}" for n in nodes]
        embeddings = model.encode(texts, convert_to_numpy=True)

        # 2. Build index
        self.node_embeddings = embeddings.astype(np.float32)
        self.node_ids = [n.id for n in nodes]

        if faiss:
            self.index = faiss.IndexFlatL2(self.embedding_dim)
            self.index.add(self.node_embeddings)
            logger.info(f"Built FAISS index with {len(nodes)} documents")
        
        # 3. Unload immediately to save RAM
        self._unload_model()

    def search(self, query: str, top_k: int = 50) -> List[Tuple[str, float]]:
        """
        Search using vector similarity (Builds index and Loads model on demand)
        """
        import numpy as np
        try:
            import faiss
        except ImportError:
            faiss = None

        # Build index ONLY if it does not exist yet
        if self.index is None and (faiss or self.node_embeddings is None):
            self._build_index()

        if not self.node_ids:
            return []

        # 1. Load model for encoding the query
        model = self._get_model()
        query_embedding = model.encode(query, convert_to_numpy=True).astype(np.float32)
        
        # 2. Unload model (we only need the index/embeddings now)
        self._unload_model()

        if faiss and self.index:
            # FAISS search (L2 distance)
            distances, indices = self.index.search(
                np.array([query_embedding]),
                min(top_k, len(self.node_ids))
            )

            results = []
            for idx, distance in zip(indices[0], distances[0]):
                if idx >= 0:  # Valid result
                    similarity = 1.0 / (1.0 + distance)
                    results.append((self.node_ids[idx], similarity))

            logger.debug(f"Vector search returned {len(results)} results")
            return results
        else:
            # Fallback: numpy cosine similarity
            if self.node_embeddings is None:
                return []

            similarities = np.dot(self.node_embeddings, query_embedding) / (
                np.linalg.norm(self.node_embeddings, axis=1) * 
                np.linalg.norm(query_embedding) + 1e-8
            )

            top_indices = np.argsort(similarities)[-top_k:][::-1]
            
            results = []
            for idx in top_indices:
                sim = float(similarities[idx])
                normalized_sim = (sim + 1.0) / 2.0
                if normalized_sim > 0:
                    results.append((self.node_ids[idx], normalized_sim))

            return results

    def rebuild(self):
        """Rebuild index"""
        self.index = None
        self._build_index()
