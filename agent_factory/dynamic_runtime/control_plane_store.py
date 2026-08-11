from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.repositories import utc_now_text


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


class GlobalKnowledgeStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

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

    def search(self, *, query: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("knowledge search query must not be empty")
        bounded_limit = max(1, min(int(limit), 50))
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select document_id, source_id, title, mime_type, content,
                       instr(lower(title), lower(?)) as title_match,
                       instr(lower(content), lower(?)) as content_match
                from knowledge_documents
                where status = 'ready'
                  and (instr(lower(title), lower(?)) > 0 or instr(lower(content), lower(?)) > 0)
                order by (instr(lower(title), lower(?)) > 0) desc, updated_at desc, document_id
                limit ?
                """,
                (
                    normalized_query,
                    normalized_query,
                    normalized_query,
                    normalized_query,
                    normalized_query,
                    bounded_limit,
                ),
            ).fetchall()
        return [
            {
                "document_id": str(row["document_id"]),
                "source_id": str(row["source_id"]),
                "title": str(row["title"]),
                "mime_type": str(row["mime_type"]),
                "snippet": _knowledge_snippet(
                    str(row["content"]),
                    match_position=int(row["content_match"]),
                ),
            }
            for row in rows
        ]

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


def _knowledge_snippet(content: str, *, match_position: int, maximum_chars: int = 800) -> str:
    if len(content) <= maximum_chars:
        return content
    match_index = max(match_position - 1, 0)
    start = max(match_index - maximum_chars // 3, 0)
    end = min(start + maximum_chars, len(content))
    prefix = "…" if start else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{content[start:end]}{suffix}"


class WorkspaceSchedulerStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def jobs(self, workspace_ids: tuple[str, ...]) -> list[dict[str, Any]]:
        if not workspace_ids:
            return []
        placeholders = ",".join("?" for _ in workspace_ids)
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                f"select payload_json, status from scheduler_jobs where workspace_id in ({placeholders}) and status != 'deleted' order by updated_at desc",
                workspace_ids,
            ).fetchall()
        return [{**json.loads(str(row["payload_json"])), "status": str(row["status"])} for row in rows]

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        job_id = uuid4().hex
        now = utc_now_text()
        job = {**payload, "job_id": job_id, "created_at": now, "updated_at": now}
        with self._database.transaction() as connection:
            connection.execute(
                "insert into scheduler_jobs values (?, ?, 1, 'enabled', ?, ?, ?)",
                (job_id, str(payload["workspace_id"]), json.dumps(job, ensure_ascii=False, sort_keys=True), now, now),
            )
        return {**job, "status": "enabled"}

    def require_job(self, job_id: str) -> dict[str, Any]:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                "select payload_json, status from scheduler_jobs where job_id = ? and status != 'deleted'",
                (job_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"scheduler job not found: {job_id}")
        return {**json.loads(str(row["payload_json"])), "status": str(row["status"])}

    def create_run(self, *, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid4().hex
        now = utc_now_text()
        run = {
            **payload,
            "run_id": run_id,
            "job_id": job_id,
            "status": "queued",
            "scheduled_at": now,
            "started_at": None,
            "completed_at": None,
        }
        with self._database.transaction() as connection:
            connection.execute(
                "insert into scheduler_runs values (?, ?, 'queued', null, ?, ?, ?, null)",
                (run_id, job_id, json.dumps(run, ensure_ascii=False, sort_keys=True), now, now),
            )
        return run

    def runs(self, *, job_id: str | None, limit: int) -> list[dict[str, Any]]:
        query = "select payload_json, status from scheduler_runs"
        parameters: list[Any] = []
        if job_id:
            query += " where job_id = ?"
            parameters.append(job_id)
        query += " order by created_at desc limit ?"
        parameters.append(max(1, limit))
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [{**json.loads(str(row["payload_json"])), "status": str(row["status"])} for row in rows]

    def set_status(self, job_id: str, status: str) -> None:
        if status not in {"enabled", "paused", "deleted"}:
            raise ValueError(f"unsupported scheduler status: {status}")
        with self._database.transaction() as connection:
            cursor = connection.execute(
                "update scheduler_jobs set status = ?, revision = revision + 1, updated_at = ? where job_id = ? and status != 'deleted'",
                (status, utc_now_text(), job_id),
            )
            if cursor.rowcount != 1:
                raise LookupError(f"scheduler job not found: {job_id}")
