"""Main processing pipeline orchestration"""

import asyncio
import logging
from typing import List
from queue import Queue

from modelsimport Node
from storage.db import StorageManager
from .workers import IngestWorker

logger = logging.getLogger(__name__)


class ProcessingPipeline:
    """Async processing pipeline with workers"""

    def __init__(self, storage: StorageManager, num_workers: int = 4):
        self.storage = storage
        self.num_workers = num_workers
        self.ingest_worker = IngestWorker(storage)
        self.task_queue: Queue = Queue()

    async def ingest_text(self, text: str, source: str = "user") -> List[Node]:
        """Process text through ingestion pipeline"""
        logger.info(f"Starting ingestion from {source}")
        nodes = await self.ingest_worker.process_text(text, source=source)
        logger.info(f"Ingestion complete: {len(nodes)} nodes created")
        return nodes

    async def run(self):
        """Run the pipeline (placeholder for more sophisticated async execution)"""
        logger.info("Pipeline running")
        # In a more complete implementation, this would manage a pool of workers
        pass
