"""BaseMem: AI Knowledge Base System with Graph + Token-Optimized Memory"""

__version__ = "0.2.0"
__author__ = "BaseMem Contributors"

from .models import Node, Edge, NodeType, EdgeType
from .storage.db import StorageManager
from .retrieval.engine import RetrievalEngine
from .graph.engine import GraphEngine
from .orchestrator.context import ContextOrchestrator

try:
    from .indexer import CodeParser, CodeIndexer
    _has_indexer = True
except ImportError:
    CodeParser = None  # type: ignore
    CodeIndexer = None  # type: ignore
    _has_indexer = False

__all__ = [
    "Node",
    "Edge",
    "NodeType",
    "EdgeType",
    "StorageManager",
    "RetrievalEngine",
    "GraphEngine",
    "ContextOrchestrator",
    "CodeParser",
    "CodeIndexer",
]
