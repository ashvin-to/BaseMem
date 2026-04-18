"""Local summarization using Transformers (AutoModelForSeq2SeqLM)"""

import logging
from typing import List, Optional
try:
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    import torch
except ImportError:
    AutoModelForSeq2SeqLM = None
    AutoTokenizer = None

logger = logging.getLogger(__name__)

class LocalSummarizer:
    """Uses local HuggingFace models to summarize text chunks"""

    def __init__(self, model_name: str = "facebook/bart-large-cnn"):
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self._init_model()

    def _init_model(self):
        """Initialize or switch the transformers model"""
        if AutoModelForSeq2SeqLM and AutoTokenizer:
            try:
                logger.info(f"Loading local model {self.model_name}...")
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
                logger.info(f"Local model {self.model_name} ready")
            except Exception as e:
                logger.error(f"Failed to load model {self.model_name}: {e}")
        else:
            logger.warning("Transformers library not installed. Local summarization disabled.")

    def summarize(self, text: str, max_length: int = 150, min_length: int = 30) -> Optional[str]:
        """Summarize a block of text using manual tokenization/generation"""
        if not self.model or not self.tokenizer:
            return None
        
        if len(text.split()) < min_length:
            return text
            
        try:
            inputs = self.tokenizer(
                [text], 
                max_length=1024, 
                return_tensors="pt", 
                truncation=True
            )
            
            # Use CPU for generation to ensure compatibility
            summary_ids = self.model.generate(
                inputs["input_ids"], 
                num_beams=4, 
                max_length=max_length, 
                min_length=min_length,
                early_stopping=True
            )
            
            return self.tokenizer.decode(summary_ids[0], skip_special_tokens=True)
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return None

    def summarize_chat_history(self, history_nodes: List) -> Optional[str]:
        """Convert a list of chat nodes into a single summary string"""
        if not history_nodes:
            return None
            
        full_text = ""
        for node in history_nodes:
            sender = node.metadata.get("sender", "unknown").upper()
            full_text += f"{sender}: {node.content}\n"
            
        return self.summarize(full_text)
