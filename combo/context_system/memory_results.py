from __future__ import annotations

from dataclasses import dataclass

from combo.context_system.hybrid_retrieval import RetrievalChannelEvidence
from combo.runtime_protocol.memory import MemoryRevision


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    revision: MemoryRevision
    score: float
    relevance: float = 0.0
    evidence: tuple[RetrievalChannelEvidence, ...] = ()
