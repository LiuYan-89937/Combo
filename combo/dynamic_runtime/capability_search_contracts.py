from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CapabilitySearchScope = Literal["capability_catalog", "mcp_catalog"]
CapabilityRetrievalChannel = Literal["exact", "lexical", "semantic"]


@dataclass(frozen=True, slots=True)
class CapabilitySearchCandidate:
    capability_id: str
    index_revision_id: str
    kind: str
    search_scope: CapabilitySearchScope
    parent_capability_id: str | None
    display_name: str
    description: str
    keywords: tuple[str, ...] = ()
    parameter_text: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "capability_id",
            "index_revision_id",
            "kind",
            "search_scope",
            "display_name",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"capability search candidate {field_name} must not be empty")
        if self.search_scope == "capability_catalog" and self.parent_capability_id is not None:
            raise ValueError("top-level capability search candidate cannot have a parent")
        if self.search_scope == "mcp_catalog":
            parent = str(self.parent_capability_id or "").strip()
            if not parent:
                raise ValueError("MCP catalog search candidate requires a parent capability")
            object.__setattr__(self, "parent_capability_id", parent)
        object.__setattr__(self, "description", str(self.description or "").strip())
        normalized_keywords = tuple(str(value or "").strip() for value in self.keywords)
        if any(not value for value in normalized_keywords):
            raise ValueError("capability search candidate keywords must not be empty")
        object.__setattr__(self, "keywords", tuple(dict.fromkeys(normalized_keywords)))
        object.__setattr__(self, "parameter_text", str(self.parameter_text or "").strip())


@dataclass(frozen=True, slots=True)
class CapabilitySearchResult:
    capability_id: str
    retrieval_channels: tuple[CapabilityRetrievalChannel, ...]
    matched_fields: tuple[str, ...]
    reason: str
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not str(self.capability_id or "").strip():
            raise ValueError("capability search result capability_id must not be empty")
        channels = tuple(dict.fromkeys(self.retrieval_channels))
        if not channels:
            raise ValueError("capability search result requires retrieval channels")
        if any(value not in {"exact", "lexical", "semantic"} for value in channels):
            raise ValueError("capability search result contains an unsupported retrieval channel")
        fields = tuple(dict.fromkeys(str(value or "").strip() for value in self.matched_fields))
        if any(not value for value in fields):
            raise ValueError("capability search result matched fields must not be empty")
        object.__setattr__(self, "retrieval_channels", channels)
        object.__setattr__(self, "matched_fields", fields)
        if not str(self.reason or "").strip():
            raise ValueError("capability search result reason must not be empty")
        if self.evidence_id is not None and not str(self.evidence_id or "").strip():
            raise ValueError("capability search result evidence_id must not be empty")
