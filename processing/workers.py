"""Async workers for the processing pipeline"""

import asyncio
import logging
import uuid
from typing import List, Optional
from sentence_transformers import SentenceTransformer
import nltk
from nltk.tokenize import sent_tokenize

from modelsimport Node, NodeType, Edge, EdgeType
from storage.db import StorageManager
from graph.engine import GraphEngine

logger = logging.getLogger(__name__)

# Download NLTK data
def _download_nltk_data():
    """Ensure required NLTK data is available"""
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        logger.info("Downloading NLTK punkt_tab tokenizer...")
        nltk.download('punkt_tab', quiet=True)
    
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        logger.info("Downloading NLTK punkt tokenizer...")
        nltk.download('punkt', quiet=True)

_download_nltk_data()


class IngestWorker:
    """Worker for ingesting and processing raw text into knowledge nodes"""

    def __init__(self, storage: StorageManager):
        self.storage = storage
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.graph = GraphEngine(storage)

    async def process_text(
        self,
        text: str,
        source: str = "user_input",
        node_type: NodeType = NodeType.CONVERSATION
    ) -> List[Node]:
        """
        Process raw text into knowledge nodes
        
        Pipeline:
        1. Semantic chunking
        2. Entity extraction
        3. Node creation
        4. Embedding generation
        5. Graph linking
        """
        # Step 1: Semantic chunking
        chunks = self._semantic_chunking(text)
        logger.info(f"Created {len(chunks)} chunks from input text")

        # Step 2-5: Create nodes for each chunk
        created_nodes = []
        for i, chunk in enumerate(chunks):
            # Generate unique node ID using UUID
            node_id = f"{source}_{uuid.uuid4().hex[:8]}"
            node = await self._create_node(chunk, node_id, node_type)
            created_nodes.append(node)
            self.storage.add_node(node)

        # Link nodes by semantic similarity
        await self._link_nodes_semantically(created_nodes)

        logger.info(f"Created {len(created_nodes)} nodes")
        return created_nodes

    def _semantic_chunking(self, text: str, chunk_size: int = 3) -> List[str]:
        """
        Split text into semantic chunks using sentence boundaries
        
        chunk_size: number of sentences per chunk
        """
        sentences = sent_tokenize(text)
        chunks = []

        for i in range(0, len(sentences), chunk_size):
            chunk = " ".join(sentences[i:i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)

        return chunks

    async def _create_node(
        self,
        content: str,
        node_id: str,
        node_type: NodeType
    ) -> Node:
        """Create a node from content"""
        # Extract title (first 50 chars or first sentence)
        title = content[:50] if len(content) > 50 else content

        # Extract keywords (simple: split on spaces, remove common words)
        keywords = self._extract_keywords(content)

        node = Node(
            id=node_id,
            title=title,
            content=content,
            node_type=node_type,
            keywords=keywords,
        )

        return node

    async def _link_nodes_semantically(self, nodes: List[Node]) -> None:
        """Link nodes based on semantic similarity"""
        if len(nodes) < 2:
            return

        # Get embeddings
        texts = [f"{n.title} {n.content}" for n in nodes]
        embeddings = self.model.encode(texts, convert_to_numpy=False)

        # Create links above threshold
        threshold = 0.75
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                # Calculate cosine similarity
                similarity = self._cosine_similarity(embeddings[i], embeddings[j])

                if similarity > threshold:
                    edge = Edge(
                        from_id=nodes[i].id,
                        to_id=nodes[j].id,
                        edge_type=EdgeType.RELATED_TO,
                        weight=similarity,
                        confidence=similarity,
                    )
                    self.storage.add_edge(edge)

        logger.debug(f"Linked {len(nodes)} nodes semantically")

    @staticmethod
    def _extract_keywords(text: str, top_k: int = 5) -> List[str]:
        """Extract keywords from text (simple approach)"""
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "is", "are", "was", "were", "be", "been"
        }

        words = text.lower().split()
        keywords = [
            w for w in words
            if w not in stop_words and len(w) > 3
        ]

        return keywords[:top_k]

    @staticmethod
    def _cosine_similarity(vec1, vec2) -> float:
        """Calculate cosine similarity between two vectors"""
        import numpy as np

        # Handle torch tensors (ensure they are on CPU)
        if hasattr(vec1, 'cpu'):
            vec1 = vec1.cpu().detach().numpy()
        if hasattr(vec2, 'cpu'):
            vec2 = vec2.cpu().detach().numpy()

        if isinstance(vec1, list):
            vec1 = np.array(vec1)
        if isinstance(vec2, list):
            vec2 = np.array(vec2)

        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(np.dot(vec1, vec2) / (norm1 * norm2))
