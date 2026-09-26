from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.knowledge_search import HybridKnowledgeSearchIndex, KnowledgeRetrievalSettings
from combo.dynamic_runtime.repositories.shared import utc_now_text
from combo.runtime_protocol.knowledge import KnowledgeDocumentRecord


class GlobalKnowledgeStore:
    def __init__(
        self,
        database: DynamicRuntimeDatabase,
        *,
        search_index: HybridKnowledgeSearchIndex,
    ) -> None:
        self._database = database
        self._search_index = search_index

    def close(self) -> None:
        self._search_index.close()

    def refresh_index(self, *, force: bool = False) -> None:
        self._search_index.refresh(force=force)

    def retrieval_settings(self) -> KnowledgeRetrievalSettings:
        return self._search_index.settings()

    def save_retrieval_settings(
        self,
        settings: KnowledgeRetrievalSettings,
        *,
        expected_revision: int | None,
    ) -> KnowledgeRetrievalSettings:
        return self._search_index.save_settings(settings, expected_revision=expected_revision)

    def sources(self) -> list[dict[str, Any]]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select payload_json from knowledge_sources
                where status != 'deleted' order by updated_at desc, source_id
                """
            ).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    def create_source(self, payload: dict[str, Any], documents: list[dict[str, str]]) -> dict[str, Any]:
        source_id = uuid4().hex
        now = utc_now_text()
        source = {
            **payload,
            "source_id": source_id,
            "status": "ready",
            "document_count": len(documents),
            "created_at": now,
            "updated_at": now,
        }
        with self._database.transaction() as connection:
            connection.execute(
                "insert into knowledge_sources values (?, 1, 'ready', ?, ?, ?)",
                (source_id, json.dumps(source, ensure_ascii=False, sort_keys=True), now, now),
            )
            for document in documents:
                content = str(document.get("content") or "")
                document_id = uuid4().hex
                connection.execute(
                    """
                    insert into knowledge_documents(
                      document_id, source_id, revision, status, title, mime_type,
                      content, content_digest, created_at, updated_at
                    ) values (?, ?, 1, 'ready', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        source_id,
                        str(document.get("title") or source.get("display_name") or "document"),
                        str(document.get("mime_type") or "text/plain"),
                        content,
                        sha256(content.encode("utf-8")).hexdigest(),
                        now,
                        now,
                    ),
                )
        self.refresh_index()
        return source

    def documents(self, source_id: str) -> list[KnowledgeDocumentRecord]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select * from knowledge_documents
                where source_id = ? and status = 'ready'
                order by updated_at desc, document_id
                """,
                (source_id,),
            ).fetchall()
        return [self._document(row) for row in rows]

    def search(
        self,
        *,
        query: str,
        limit: int | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._search_index.search(query=query, limit=limit, source_id=source_id)

    def require_document(self, document_id: str) -> KnowledgeDocumentRecord:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                "select * from knowledge_documents where document_id = ? and status = 'ready'",
                (document_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"knowledge document not found: {document_id}")
        return self._document(row)

    def delete_source(self, source_id: str) -> None:
        now = utc_now_text()
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "update knowledge_sources set status = 'deleted', revision = revision + 1, updated_at = ? where source_id = ? and status != 'deleted'",
                (now, source_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"knowledge source not found: {source_id}")
            connection.execute(
                "update knowledge_documents set status = 'deleted', revision = revision + 1, updated_at = ? where source_id = ? and status = 'ready'",
                (now, source_id),
            )
        self.refresh_index()

    @staticmethod
    def _document(row: Any) -> KnowledgeDocumentRecord:
        return KnowledgeDocumentRecord(
            document_id=str(row["document_id"]),
            source_id=str(row["source_id"]),
            title=str(row["title"]),
            mime_type=str(row["mime_type"]),
            content=str(row["content"]),
            content_digest=str(row["content_digest"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
