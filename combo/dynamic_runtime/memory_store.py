from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from uuid import uuid4

from combo.context_system.memory_results import MemorySearchResult
from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.runtime_protocol import MemoryKind, MemoryRevision, MemoryScope
from combo.runtime_protocol.contracts import utc_now_text
from combo.dynamic_runtime.memory_search import HybridMemorySearchIndex
from combo.runtime_protocol.memory_operations import (
    DeleteMemory, MemoryChangeSet, MemoryDraft, MemorySelector, MergeMemories,
    UpdateMemory, WriteMemory, memory_target,
)
from combo.tooling.targets import select_target


class ScopedMemoryStore:
    """Authoritative workspace/session memory revision store."""

    def __init__(self, database: DynamicRuntimeDatabase, search_index: HybridMemorySearchIndex | None = None) -> None:
        self._database = database
        self._search_index = search_index

    def close(self) -> None:
        if self._search_index is not None:
            self._search_index.close()

    def legacy_user_memories(self, *, principal_id: str) -> tuple[dict[str, str], ...]:
        """Expose retired global memories for explicit user review, never recall."""
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select archived.payload_json from legacy_user_memory_revisions archived
                where archived.revision = (
                  select max(revision) from legacy_user_memory_revisions
                  where memory_id = archived.memory_id
                )
                and archived.principal_id = ? and archived.status = 'active'
                order by archived.created_at desc
                """,
                (_required_text(principal_id, "principal_id"),),
            ).fetchall()
        return tuple({
            "memory_id": str(value["memory_id"]),
            "kind": str(value["kind"]),
            "content": str(value["content"]),
            "source_session_id": str(value.get("source_session_id") or ""),
        } for row in rows if isinstance(value := json.loads(str(row["payload_json"])), dict))

    def apply_changes(
        self, *, principal_id: str, workspace_id: str, session_id: str | None,
        changes: MemoryChangeSet, source_session_id: str | None = None,
        source_turn_id: str | None = None, runtime_instance_id: str | None = None,
        expected_references: dict[str, tuple[int, str]] | None = None,
        expected_revisions: dict[str, int] | None = None,
        finalize: Callable[[sqlite3.Connection], None] | None = None,
    ) -> tuple[MemoryRevision, ...]:
        """Apply one scoped, validated change set and its progress commit atomically."""
        with self._database.transaction() as conn:
            workspace = _require_workspace(conn, principal_id, workspace_id)
            if session_id is not None:
                _require_session(conn, principal_id, workspace_id, session_id)
            visible = _visible_memories(conn, principal_id, workspace_id, session_id)
            if expected_revisions is not None:
                actual_revisions = {item.memory_id: item.revision for item in visible}
                for memory_id, expected in expected_revisions.items():
                    if memory_id not in actual_revisions:
                        raise LookupError(f"memory not found: {memory_id}")
                    if actual_revisions[memory_id] != expected:
                        raise RuntimeError("memory revision changed before mutation")
            if expected_references is not None:
                actual = {item.memory_id: (item.revision, item.content_digest) for item in visible}
                if actual != expected_references:
                    raise RuntimeError("memory revisions changed during extraction")
            provenance = dict(source_session_id=source_session_id, source_turn_id=source_turn_id,
                              created_by_runtime_instance_id=runtime_instance_id)
            results = []
            for operation in changes.operations:
                selected: list[MemoryRevision] = []
                if isinstance(operation, (UpdateMemory, DeleteMemory)):
                    selected = [_select_memory(visible, operation.memory)]
                elif isinstance(operation, MergeMemories):
                    selected = [_select_memory(visible, selector) for selector in operation.memories]
                    if len({item.memory_id for item in selected}) != len(selected):
                        raise ValueError("merge requires distinct memories")
                    if any(item.scope != operation.scope or item.kind != operation.kind for item in selected):
                        raise ValueError("merge requires memories of the same scope and kind")
                if isinstance(operation, DeleteMemory):
                    revision = _next_revision(selected[0], status="deleted", **provenance)
                else:
                    if operation.scope == "workspace" and workspace["mode"] != "project":
                        raise ValueError("workspace memory requires a shared workspace")
                    if operation.scope == "session" and not session_id:
                        raise ValueError("session memory requires the current session")
                    if selected and selected[0].scope != operation.scope:
                        raise ValueError("update cannot move memory into another scope")
                    duplicate = next((item for item in visible if item.scope == operation.scope
                                      and item.content == operation.content), None)
                    if not selected and duplicate is not None:
                        results.append(duplicate)
                        continue
                    if (isinstance(operation, UpdateMemory) and duplicate == selected[0]
                            and selected[0].kind == operation.kind):
                        results.append(selected[0])
                        continue
                    if (duplicate is not None and selected and duplicate.memory_id != selected[0].memory_id
                            and duplicate.kind != operation.kind):
                        raise ValueError("the conclusion already exists under another kind; update that entry instead")
                    if selected:
                        revision = _next_revision(selected[0], kind=operation.kind, content=operation.content,
                                                  **provenance)
                    else:
                        revision = MemoryRevision(
                            memory_id=uuid4().hex, revision=1, principal_id=principal_id,
                            scope=operation.scope, workspace_id=workspace_id,
                            session_id=session_id if operation.scope == "session" else None,
                            kind=operation.kind, content=operation.content, **provenance,
                        )
                    if duplicate is not None and duplicate.memory_id != revision.memory_id:
                        selected.append(duplicate)
                if runtime_instance_id is not None:
                    self._validate_source(conn, revision)
                self._save_head(conn, revision, previous=selected[0] if selected else None)
                visible = [item for item in visible if item.memory_id != revision.memory_id]
                if revision.status == "active":
                    visible.append(revision)
                results.append(revision)
                for obsolete in {item.memory_id: item for item in selected[1:]}.values():
                    deleted = _next_revision(obsolete, status="deleted", **provenance)
                    self._save_head(conn, deleted, previous=obsolete)
                    visible = [item for item in visible if item.memory_id != obsolete.memory_id]
                    results.append(deleted)
            if finalize is not None:
                finalize(conn)
        return tuple(results)

    def write_as_owner(
        self, *, principal_id: str, workspace_id: str, session_id: str | None,
        draft: MemoryDraft,
    ) -> MemoryRevision:
        return self.apply_changes(
            principal_id=principal_id, workspace_id=workspace_id, session_id=session_id,
            changes=MemoryChangeSet(operations=(WriteMemory(**draft.model_dump()),)),
        )[0]

    def update_as_owner(
        self, *, memory_id: str, principal_id: str, workspace_id: str,
        session_id: str | None, draft: MemoryDraft, expected_revision: int,
    ) -> MemoryRevision:
        current = self.require_visible(memory_id=memory_id, principal_id=principal_id,
                                       workspace_id=workspace_id, session_id=session_id)
        if current.revision != expected_revision:
            raise RuntimeError("memory revision changed before update")
        selector = MemorySelector(**memory_target(current))
        return self.apply_changes(
            principal_id=principal_id, workspace_id=workspace_id, session_id=session_id,
            changes=MemoryChangeSet(operations=(UpdateMemory(memory=selector, **draft.model_dump()),)),
            expected_revisions={memory_id: expected_revision},
        )[0]

    def delete_as_owner(
        self, *, memory_id: str, principal_id: str, workspace_id: str, session_id: str | None,
    ) -> MemoryRevision:
        current = self.require_visible(memory_id=memory_id, principal_id=principal_id,
                                       workspace_id=workspace_id, session_id=session_id)
        return self.apply_changes(
            principal_id=principal_id, workspace_id=workspace_id, session_id=session_id,
            changes=MemoryChangeSet(operations=(DeleteMemory(memory=MemorySelector(**memory_target(current))),)),
        )[0]

    def merge_as_owner(
        self, *, principal_id: str, workspace_id: str, session_id: str | None,
        drafts: tuple[tuple[str, int], ...], draft: MemoryDraft,
    ) -> tuple[MemoryRevision, ...]:
        selected = [self.require_visible(memory_id=memory_id, principal_id=principal_id,
                                         workspace_id=workspace_id, session_id=session_id)
                    for memory_id, _ in drafts]
        if any(item.revision != revision for item, (_, revision) in zip(selected, drafts)):
            raise RuntimeError("memory revision changed before merge")
        operation = MergeMemories(memories=tuple(MemorySelector(**memory_target(item)) for item in selected),
                                  **draft.model_dump())
        return self.apply_changes(principal_id=principal_id, workspace_id=workspace_id,
                                  session_id=session_id, changes=MemoryChangeSet(operations=(operation,)),
                                  expected_revisions=dict(drafts))

    def require_visible(
        self, *, memory_id: str, principal_id: str, workspace_id: str, session_id: str | None,
    ) -> MemoryRevision:
        with self._database.connection(query_only=True) as conn:
            _require_workspace(conn, principal_id, workspace_id)
            if session_id is not None:
                _require_session(conn, principal_id, workspace_id, session_id)
            item = next((item for item in _visible_memories(conn, principal_id, workspace_id, session_id)
                         if item.memory_id == memory_id), None)
        if item is None:
            raise LookupError(f"memory not found: {memory_id}")
        return item

    @classmethod
    def _save_head(cls, conn: sqlite3.Connection, revision: MemoryRevision,
                   *, previous: MemoryRevision | None) -> None:
        cls._insert_revision(conn, revision)
        if previous is None:
            conn.execute(
                "insert into memory_heads(memory_id,revision,principal_id,scope,workspace_id,session_id,status,"
                "content_digest,updated_at) values (?,?,?,?,?,?,?,?,?)",
                (revision.memory_id, revision.revision, revision.principal_id, revision.scope,
                 revision.workspace_id, revision.session_id, revision.status, revision.content_digest,
                 revision.created_at),
            )
        else:
            changed = conn.execute(
                "update memory_heads set revision=?,status=?,content_digest=?,updated_at=? "
                "where memory_id=? and revision=? and status='active'",
                (revision.revision, revision.status, revision.content_digest, revision.created_at,
                 revision.memory_id, previous.revision),
            ).rowcount
            if changed != 1:
                raise RuntimeError("memory revision changed before mutation")

    def list_active(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        session_id: str | None,
        scope: MemoryScope | None = None,
        kind: MemoryKind | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> tuple[MemoryRevision, ...]:
        if limit is not None and limit < 1:
            raise ValueError("memory list limit must be positive")
        if offset < 0:
            raise ValueError("memory list offset must not be negative")
        clauses = ["head.principal_id = ?", "head.status = 'active'", "head.workspace_id = ?"]
        parameters: list[object] = [
            _required_text(principal_id, "principal_id"),
            _required_text(workspace_id, "workspace_id"),
        ]
        if kind is not None:
            clauses.append("revision.kind = ?")
            parameters.append(kind)
        if scope == "workspace":
            clauses.append("head.scope = 'workspace'")
        elif scope == "session":
            clauses.append("head.scope = 'session' and head.session_id = ?")
            parameters.append(_required_text(session_id, "session_id"))
        else:
            clauses.append("(head.scope = 'workspace' or (head.scope = 'session' and head.session_id = ?))")
            parameters.append(_required_text(session_id, "session_id"))
        limit_clause = "limit ? offset ?" if limit is not None else ""
        order_clause = "case head.scope when 'session' then 0 else 1 end, head.updated_at desc, head.memory_id"
        if limit is not None:
            parameters.extend((limit, offset))
        with self._database.connection(query_only=True) as conn:
            workspace = _require_workspace(conn, principal_id, workspace_id)
            if session_id is not None:
                _require_session(conn, principal_id, workspace_id, session_id)
            if scope == "workspace" and workspace["mode"] != "project":
                return ()
            if workspace["mode"] != "project":
                clauses.append("head.scope = 'session'")
            rows = conn.execute(
                f"""
                select revision.payload_json
                from memory_heads as head
                join memory_revisions as revision
                  on revision.memory_id = head.memory_id and revision.revision = head.revision
                where {' and '.join(clauses)}
                order by {order_clause}
                {limit_clause}
                """,
                tuple(parameters),
            ).fetchall()
        return tuple(MemoryRevision.model_validate_json(str(row["payload_json"])) for row in rows)

    def recalled_revisions(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        session_id: str,
        references: tuple[tuple[str, int], ...],
    ) -> tuple[MemoryRevision, ...]:
        """Resolve exact model-input revisions within the requesting conversation's scope."""
        if not references:
            return ()
        with self._database.connection(query_only=True) as conn:
            workspace = _require_workspace(conn, principal_id, workspace_id)
            _require_session(conn, principal_id, workspace_id, session_id)
            revisions = []
            for memory_id, revision in references:
                row = conn.execute(
                    """
                    select payload_json from memory_revisions
                    where memory_id = ? and revision = ? and principal_id = ?
                      and workspace_id = ?
                      and ((scope = 'workspace' and ?) or (scope = 'session' and session_id = ?))
                    """,
                    (memory_id, revision, principal_id, workspace_id, workspace["mode"] == "project", session_id),
                ).fetchone()
                if row is not None:
                    revisions.append(MemoryRevision.model_validate_json(str(row["payload_json"])))
        return tuple(revisions)

    def search(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        session_id: str | None,
        query: str,
        limit: int,
        min_relevance: float = 0.0,
        scope: MemoryScope | None = None,
        kind: MemoryKind | None = None,
    ) -> tuple[MemorySearchResult, ...]:
        if self._search_index is None:
            raise RuntimeError("memory search index is not configured")
        with self._database.connection(query_only=True) as conn:
            _require_workspace(conn, principal_id, workspace_id)
            if session_id is not None:
                _require_session(conn, principal_id, workspace_id, session_id)
        return tuple(
            MemorySearchResult(revision=item.revision, score=item.score, relevance=item.relevance, evidence=item.evidence)
            for item in self._search_index.search(
                principal_id=principal_id,
                workspace_id=workspace_id,
                session_id=session_id,
                query=query,
                limit=limit,
                min_relevance=min_relevance,
                scope=scope,
                kind=kind,
            )
        )

    def search_version(self, *, principal_id: str, workspace_id: str, session_id: str) -> str:
        if self._search_index is None:
            raise RuntimeError("memory search index is not configured")
        return self._search_index.version(principal_id=principal_id, workspace_id=workspace_id, session_id=session_id)

    def active_references(self, *, principal_id: str, workspace_id: str, session_id: str) -> dict[str, tuple[int, str]]:
        with self._database.connection(query_only=True) as conn:
            _require_workspace(conn, principal_id, workspace_id)
            _require_session(conn, principal_id, workspace_id, session_id)
            memories = _visible_memories(conn, principal_id, workspace_id, session_id)
        return {item.memory_id: (item.revision, item.content_digest) for item in memories}

    @staticmethod
    def _insert_revision(conn, revision: MemoryRevision) -> None:
        conn.execute(
            """
            insert into memory_revisions(
              memory_id, revision, principal_id, scope, workspace_id, session_id, kind,
              status, content_digest, payload_json, source_session_id,
              source_turn_id, created_by_runtime_instance_id, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                revision.memory_id,
                revision.revision,
                revision.principal_id,
                revision.scope,
                revision.workspace_id,
                revision.session_id,
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
                   conversation.principal_id, conversation.workspace_id, workspace.mode as workspace_mode
            from runtime_instances as runtime
            join conversations as conversation on conversation.session_id = runtime.session_id
            join workspaces as workspace on workspace.workspace_id = conversation.workspace_id
            where runtime.runtime_instance_id = ? and conversation.status = 'active'
              and workspace.status = 'active'
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
        if str(row["workspace_id"]) != revision.workspace_id:
            raise PermissionError("workspace memory differs from runtime workspace")
        if revision.scope == "workspace" and str(row["workspace_mode"]) != "project":
            raise ValueError("workspace memory requires a shared workspace")
        if revision.scope == "session" and str(row["session_id"]) != revision.session_id:
            raise PermissionError("session memory differs from runtime session")


def _required_text(value: str | None, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _require_workspace(conn: sqlite3.Connection, principal_id: str, workspace_id: str) -> sqlite3.Row:
    row = conn.execute("select mode from workspaces where workspace_id=? and principal_id=? and status='active'",
                       (workspace_id, principal_id)).fetchone()
    if row is None:
        raise LookupError("memory workspace not found")
    return row


def _require_session(conn: sqlite3.Connection, principal_id: str, workspace_id: str, session_id: str) -> None:
    if conn.execute("select 1 from conversations where session_id=? and principal_id=? and workspace_id=? and status='active'",
                    (session_id, principal_id, workspace_id)).fetchone() is None:
        raise LookupError("memory session not found in the workspace")


def _visible_memories(conn: sqlite3.Connection, principal_id: str, workspace_id: str,
                      session_id: str | None) -> list[MemoryRevision]:
    rows = conn.execute(
        "select revision.payload_json from memory_heads head "
        "join memory_revisions revision on revision.memory_id=head.memory_id and revision.revision=head.revision "
        "join workspaces workspace on workspace.workspace_id=head.workspace_id "
        "where head.principal_id=? and head.workspace_id=? and head.status='active' "
        "and ((head.scope='workspace' and workspace.mode='project') or (head.scope='session' and head.session_id=?))",
        (principal_id, workspace_id, session_id),
    ).fetchall()
    return [MemoryRevision.model_validate_json(str(row["payload_json"])) for row in rows]


def _select_memory(items: list[MemoryRevision], selector: MemorySelector) -> MemoryRevision:
    return select_target(items, selector=selector.model_dump(exclude_none=True),
                         describe=memory_target, kind="memory")


def _next_revision(current: MemoryRevision, **changes: object) -> MemoryRevision:
    return MemoryRevision.model_validate({
        **current.model_dump(), "revision": current.revision + 1, "created_at": utc_now_text(),
        "content_digest": "", **changes,
    })
