from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import uuid4

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.runtime_protocol import MemoryKind, MemoryRevision, MemoryScope


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    revision: MemoryRevision
    score: float


class ScopedMemoryStore:
    """Authoritative user/workspace memory revision store."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def write(
        self,
        *,
        principal_id: str,
        scope: MemoryScope,
        workspace_id: str | None,
        kind: MemoryKind,
        content: str,
        confidence: float,
        source_session_id: str,
        source_turn_id: str,
        runtime_instance_id: str,
    ) -> MemoryRevision:
        candidate = MemoryRevision(
            memory_id=uuid4().hex,
            revision=1,
            principal_id=principal_id,
            scope=scope,
            workspace_id=workspace_id,
            kind=kind,
            content=content,
            confidence=confidence,
            source_session_id=source_session_id,
            source_turn_id=source_turn_id,
            created_by_runtime_instance_id=runtime_instance_id,
        )
        with self._database.transaction() as conn:
            self._validate_source(conn, candidate)
            duplicate = conn.execute(
                """
                select revision.payload_json
                from memory_heads as head
                join memory_revisions as revision
                  on revision.memory_id = head.memory_id and revision.revision = head.revision
                where head.principal_id = ? and head.scope = ?
                  and head.workspace_id is ? and head.status = 'active'
                  and head.content_digest = ?
                order by head.updated_at desc limit 1
                """,
                (
                    candidate.principal_id,
                    candidate.scope,
                    candidate.workspace_id,
                    candidate.content_digest,
                ),
            ).fetchone()
            if duplicate is not None:
                return MemoryRevision.model_validate_json(str(duplicate["payload_json"]))
            self._insert_revision(conn, candidate)
            conn.execute(
                """
                insert into memory_heads(
                  memory_id, revision, principal_id, scope, workspace_id,
                  status, content_digest, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.memory_id,
                    candidate.revision,
                    candidate.principal_id,
                    candidate.scope,
                    candidate.workspace_id,
                    candidate.status,
                    candidate.content_digest,
                    candidate.created_at,
                ),
            )
        return candidate

    def delete(
        self,
        *,
        memory_id: str,
        principal_id: str,
        runtime_instance_id: str,
        source_session_id: str,
        source_turn_id: str,
        expected_revision: int,
    ) -> MemoryRevision:
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select head.*, revision.payload_json
                from memory_heads as head
                join memory_revisions as revision
                  on revision.memory_id = head.memory_id and revision.revision = head.revision
                where head.memory_id = ?
                """,
                (_required_text(memory_id, "memory_id"),),
            ).fetchone()
            if row is None or str(row["principal_id"]) != principal_id:
                raise LookupError(f"memory not found: {memory_id}")
            if str(row["status"]) != "active":
                raise ValueError("memory is already deleted")
            if int(row["revision"]) != expected_revision:
                raise RuntimeError("memory revision changed before deletion")
            current = MemoryRevision.model_validate_json(str(row["payload_json"]))
            deleted = MemoryRevision(
                memory_id=current.memory_id,
                revision=current.revision + 1,
                principal_id=current.principal_id,
                scope=current.scope,
                workspace_id=current.workspace_id,
                kind=current.kind,
                status="deleted",
                content=current.content,
                confidence=current.confidence,
                source_session_id=source_session_id,
                source_turn_id=source_turn_id,
                created_by_runtime_instance_id=runtime_instance_id,
            )
            self._validate_source(conn, deleted)
            self._insert_revision(conn, deleted)
            updated = conn.execute(
                """
                update memory_heads
                set revision = ?, status = 'deleted', updated_at = ?
                where memory_id = ? and revision = ? and status = 'active'
                """,
                (deleted.revision, deleted.created_at, deleted.memory_id, expected_revision),
            )
            if updated.rowcount != 1:
                raise RuntimeError("memory revision changed before deletion")
        return deleted

    def delete_as_owner(
        self,
        *,
        memory_id: str,
        principal_id: str,
    ) -> MemoryRevision:
        """Delete a memory through the authenticated user-management surface."""
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select head.*, revision.payload_json
                from memory_heads as head
                join memory_revisions as revision
                  on revision.memory_id = head.memory_id and revision.revision = head.revision
                where head.memory_id = ?
                """,
                (_required_text(memory_id, "memory_id"),),
            ).fetchone()
            if row is None or str(row["principal_id"]) != principal_id:
                raise LookupError(f"memory not found: {memory_id}")
            if str(row["status"]) != "active":
                raise ValueError("memory is already deleted")
            current = MemoryRevision.model_validate_json(str(row["payload_json"]))
            deleted = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "status": "deleted",
                    "created_at": _now_text(),
                }
            )
            self._insert_revision(conn, deleted)
            changed = conn.execute(
                """
                update memory_heads
                set revision = ?, status = 'deleted', updated_at = ?
                where memory_id = ? and revision = ? and status = 'active'
                """,
                (
                    deleted.revision,
                    deleted.created_at,
                    deleted.memory_id,
                    current.revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("memory revision changed before deletion")
        return deleted

    def list_active(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        scope: MemoryScope | None = None,
        limit: int = 100,
    ) -> tuple[MemoryRevision, ...]:
        if limit < 1:
            raise ValueError("memory list limit must be positive")
        clauses = ["head.principal_id = ?", "head.status = 'active'"]
        parameters: list[object] = [_required_text(principal_id, "principal_id")]
        owner_workspace_id = _required_text(workspace_id, "workspace_id")
        if scope == "user":
            clauses.append("head.scope = 'user'")
        elif scope == "workspace":
            clauses.append("head.scope = 'workspace' and head.workspace_id = ?")
            parameters.append(owner_workspace_id)
        else:
            clauses.append("(head.scope = 'user' or head.workspace_id = ?)")
            parameters.append(owner_workspace_id)
        parameters.append(limit)
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                f"""
                select revision.payload_json
                from memory_heads as head
                join memory_revisions as revision
                  on revision.memory_id = head.memory_id and revision.revision = head.revision
                where {' and '.join(clauses)}
                order by case head.scope when 'workspace' then 0 else 1 end,
                         head.updated_at desc, head.memory_id
                limit ?
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(MemoryRevision.model_validate_json(str(row["payload_json"])) for row in rows)

    def search(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        query: str,
        limit: int,
    ) -> tuple[MemorySearchResult, ...]:
        terms = tuple(dict.fromkeys(_terms(query)))
        if not terms or limit < 1:
            return ()
        results: list[MemorySearchResult] = []
        seen_digests: set[str] = set()
        for revision in self.list_active(
            principal_id=principal_id,
            workspace_id=workspace_id,
            scope=None,
            limit=max(limit * 8, 64),
        ):
            content = revision.content.casefold()
            matched = sum(1 for term in terms if term in content)
            if not matched or revision.content_digest in seen_digests:
                continue
            seen_digests.add(revision.content_digest)
            scope_bonus = 0.1 if revision.scope == "workspace" else 0.0
            score = min(1.0, matched / len(terms) * 0.9 + scope_bonus)
            results.append(MemorySearchResult(revision=revision, score=score))
        results.sort(
            key=lambda item: (
                -item.score,
                0 if item.revision.scope == "workspace" else 1,
                item.revision.memory_id,
            )
        )
        return tuple(results[:limit])

    @staticmethod
    def _insert_revision(conn, revision: MemoryRevision) -> None:
        conn.execute(
            """
            insert into memory_revisions(
              memory_id, revision, principal_id, scope, workspace_id, kind,
              status, content_digest, payload_json, source_session_id,
              source_turn_id, created_by_runtime_instance_id, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.memory_id,
                revision.revision,
                revision.principal_id,
                revision.scope,
                revision.workspace_id,
                revision.kind,
                revision.status,
                revision.content_digest,
                revision.model_dump_json(),
                revision.source_session_id,
                revision.source_turn_id,
                revision.created_by_runtime_instance_id,
                revision.created_at,
            ),
        )

    @staticmethod
    def _validate_source(conn, revision: MemoryRevision) -> None:
        row = conn.execute(
            """
            select runtime.runtime_instance_id, runtime.session_id, runtime.turn_id,
                   conversation.principal_id, conversation.workspace_id
            from runtime_instances as runtime
            join conversations as conversation on conversation.session_id = runtime.session_id
            where runtime.runtime_instance_id = ?
            """,
            (revision.created_by_runtime_instance_id,),
        ).fetchone()
        if row is None:
            raise LookupError("memory source runtime instance not found")
        if (
            str(row["session_id"]) != revision.source_session_id
            or str(row["turn_id"]) != revision.source_turn_id
            or str(row["principal_id"]) != revision.principal_id
        ):
            raise PermissionError("memory source identity does not match runtime ownership")
        if revision.scope == "workspace" and str(row["workspace_id"]) != revision.workspace_id:
            raise PermissionError("workspace memory differs from runtime workspace")


def _terms(value: str) -> list[str]:
    return [item for item in re.findall(r"[\w\-]{2,}", str(value or "").casefold()) if item]


def _now_text() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
