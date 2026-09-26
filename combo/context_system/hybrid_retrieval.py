from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re
from typing import Literal, Mapping, Sequence
import unicodedata


RetrievalChannel = Literal["lexical", "semantic"]


@dataclass(frozen=True, slots=True)
class HybridRetrievalPolicy:
    reciprocal_rank_constant: int = 10
    lexical_weight: float = 0.55
    semantic_weight: float = 0.45

    def __post_init__(self) -> None:
        if self.reciprocal_rank_constant < 1:
            raise ValueError("hybrid retrieval reciprocal-rank constant must be positive")
        weights = (self.lexical_weight, self.semantic_weight)
        if any(not isfinite(value) or value <= 0 for value in weights):
            raise ValueError("hybrid retrieval weights must be finite and positive")

    def weight_for(self, channel: RetrievalChannel) -> float:
        if channel == "lexical":
            return self.lexical_weight
        return self.semantic_weight


DEFAULT_HYBRID_RETRIEVAL_POLICY = HybridRetrievalPolicy()


@dataclass(frozen=True, slots=True)
class RankedRetrievalCandidate:
    item_id: str
    evidence_strength: float

    def __post_init__(self) -> None:
        if not str(self.item_id or "").strip():
            raise ValueError("retrieval candidate item_id must not be empty")
        if not isfinite(self.evidence_strength):
            raise ValueError("retrieval candidate evidence strength must be finite")


@dataclass(frozen=True, slots=True)
class RetrievalChannelEvidence:
    channel: RetrievalChannel
    rank: int
    evidence_strength: float


@dataclass(frozen=True, slots=True)
class FusedRetrievalCandidate:
    item_id: str
    evidence: tuple[RetrievalChannelEvidence, ...]
    fusion_score: float

    @property
    def channels(self) -> tuple[RetrievalChannel, ...]:
        return tuple(item.channel for item in self.evidence)


def fuse_hybrid_rankings(
    rankings: Mapping[RetrievalChannel, Sequence[RankedRetrievalCandidate]],
    *,
    policy: HybridRetrievalPolicy = DEFAULT_HYBRID_RETRIEVAL_POLICY,
) -> tuple[FusedRetrievalCandidate, ...]:
    scores: dict[str, float] = {}
    evidence_by_id: dict[str, list[RetrievalChannelEvidence]] = {}
    for channel in ("lexical", "semantic"):
        ranking = rankings.get(channel, ())
        weight = policy.weight_for(channel)
        for rank, candidate in enumerate(ranking, start=1):
            strength = max(0.0, min(1.0, candidate.evidence_strength))
            if strength == 0:
                continue
            contribution = weight * strength / (policy.reciprocal_rank_constant + rank)
            scores[candidate.item_id] = scores.get(candidate.item_id, 0.0) + contribution
            evidence_by_id.setdefault(candidate.item_id, []).append(
                RetrievalChannelEvidence(
                    channel=channel,
                    rank=rank,
                    evidence_strength=strength,
                )
            )
    return tuple(
        FusedRetrievalCandidate(
            item_id=item_id,
            evidence=tuple(evidence_by_id[item_id]),
            fusion_score=scores[item_id],
        )
        for item_id in sorted(scores, key=lambda value: (-scores[value], value))
    )


def lexical_tokens(value: object) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[_./:\\-]+", " ", normalized)
    tokens: list[str] = []
    for segment in re.findall(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", segment):
            tokens.extend(segment[index:index + 2] for index in range(max(1, len(segment) - 1)))
        else:
            tokens.append(segment)
    return tuple(dict.fromkeys(tokens))


def lexical_coverage(query: object, document: object) -> float:
    query_tokens = frozenset(lexical_tokens(query))
    if not query_tokens:
        return 0.0
    document_tokens = frozenset(lexical_tokens(document))
    return len(query_tokens.intersection(document_tokens)) / len(query_tokens)
