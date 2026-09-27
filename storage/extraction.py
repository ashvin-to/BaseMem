"""Dependency-free memory extraction interfaces and heuristic implementation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractedMemory:
    content: str
    kind: str
    type: str
    importance: float
    confidence: float
    source: str
    provenance: dict


class MemoryExtractor(Protocol):
    def extract(self, text: str, agent_id: str = "default") -> list[ExtractedMemory]: ...


class ModelExtractor(MemoryExtractor, Protocol):
    """Optional future seam for a model-backed extractor."""

    def extract(self, text: str, agent_id: str = "default") -> list[ExtractedMemory]: ...


class HeuristicExtractor:
    def extract(self, text: str, agent_id: str = "default") -> list[ExtractedMemory]:
        memories = []
        for raw_line in text.split("\n"):
            content = raw_line.strip()
            if not content or len(content) < 10:
                continue
            metadata = self._classify(content, agent_id)
            if metadata["kind"] == "HYPOTHESIS":
                memory_type = "hypothesis"
            elif re.search(
                r"\b(decided|decide|agreed|agree|chose|choose|selected|select|opted|opt|will use|we will|should|must|plan to|decision|decision is|arch)\b",
                content,
                re.IGNORECASE,
            ):
                memory_type = "decision"
            elif re.search(
                r"\b(note|fact|key|config|setting|path|bug|error|issue|fail|failed|failure|broken|"
                r"crash|regression|root cause|unexpected|doesn.t work|not working)\b",
                content,
                re.IGNORECASE,
            ):
                memory_type = metadata["kind"].lower()
            else:
                continue
            memories.append(ExtractedMemory(content, memory_type, memory_type, **{
                "importance": metadata["importance"],
                "confidence": metadata["confidence"],
                "source": metadata["source"],
                "provenance": metadata["provenance"],
            }))
        return memories

    @staticmethod
    def _classify(text: str, agent_id: str) -> dict:
        modal = bool(re.search(r"\b(might|may|could|perhaps|possibly|likely|unlikely|probably|we think|i think)\b", text, re.I))
        if modal:
            kind, confidence, importance = "HYPOTHESIS", 0.45, 0.4
        elif re.search(r"\b(decided|agreed|chose|selected|opted|adopt|will use|decision)\b", text, re.I):
            kind, confidence, importance = "DECISION", 0.9, 0.85
        elif re.search(r"\b(must|never|always|required|constraint|forbidden)\b", text, re.I):
            kind, confidence, importance = "CONSTRAINT", 0.85, 0.8
        elif re.search(r"\b(discovered|found|root cause|learned)\b", text, re.I):
            kind, confidence, importance = "DISCOVERY", 0.75, 0.7
        else:
            kind, confidence, importance = "FACT", 0.6, 0.5
        return {
            "kind": kind,
            "confidence": confidence,
            "importance": importance,
            "source": "heuristic",
            "provenance": {
                "method": "heuristic",
                "agent_id": agent_id,
                "signals": ["modal" if modal else "explicit"],
            },
        }
