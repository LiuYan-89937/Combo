from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentRecord:
    document_id: str
    source_id: str
    title: str
    mime_type: str
    content: str
    content_digest: str
    created_at: str
    updated_at: str
