from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal
from uuid import uuid4

from langgraph.store.base import BaseStore, GetOp, Item, ListNamespacesOp, PutOp, SearchItem, SearchOp
from pydantic import BaseModel, ConfigDict, Field


LangGraphStoreBackend = Literal["sqlite", "memory"]


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(default_factory=lambda: uuid4().hex)
    scope: Literal["factory", "agent", "user"]
    kind: Literal["fact", "preference", "decision", "constraint", "artifact"]
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True, slots=True)
class LangGraphStoreConfig:
    backend: LangGraphStoreBackend = "sqlite"
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class LangGraphStoreHandle:
    store: BaseStore
    backend: LangGraphStoreBackend
    persistent: bool
    path: Path | None = None


class LangGraphStoreFactory:
    def build(self, config: LangGraphStoreConfig) -> LangGraphStoreHandle:
        if config.backend == "memory":
            from langgraph.store.memory import InMemoryStore

            return LangGraphStoreHandle(store=InMemoryStore(), backend="memory", persistent=False)
        if config.path is None:
            raise ValueError("SQLite memory store requires a store path.")
        config.path.parent.mkdir(parents=True, exist_ok=True)
        return LangGraphStoreHandle(
            store=SqliteBaseStore(config.path),
            backend="sqlite",
            persistent=True,
            path=config.path,
        )


class SqliteBaseStore(BaseStore):
    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def batch(self, ops) -> list[Any]:
        results: list[Any] = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(self.get(op.namespace, op.key, refresh_ttl=op.refresh_ttl))
            elif isinstance(op, PutOp):
                if op.value is None:
                    self.delete(op.namespace, op.key)
                else:
                    self.put(op.namespace, op.key, op.value, op.index, ttl=op.ttl)
                results.append(None)
            elif isinstance(op, SearchOp):
                results.append(
                    self.search(
                        op.namespace_prefix,
                        query=op.query,
                        filter=op.filter,
                        limit=op.limit,
                        offset=op.offset,
                        refresh_ttl=op.refresh_ttl,
                    )
                )
            elif isinstance(op, ListNamespacesOp):
                prefix, suffix = _namespace_match_conditions(op.match_conditions)
                results.append(
                    self.list_namespaces(
                        prefix=prefix,
                        suffix=suffix,
                        max_depth=op.max_depth,
                        limit=op.limit,
                        offset=op.offset,
                    )
                )
            else:
                raise TypeError(f"Unsupported store operation: {type(op).__name__}")
        return results

    async def abatch(self, ops) -> list[Any]:
        return self.batch(ops)

    def get(self, namespace: tuple[str, ...], key: str, *, refresh_ttl: bool | None = None) -> Item | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "select namespace, key, value_json, created_at, updated_at from store_items where namespace = ? and key = ?",
                (_namespace_key(namespace), key),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return _item_from_row(row)

    def put(
        self,
        namespace: tuple[str, ...],
        key: str,
        value: dict[str, Any],
        index: Literal[False] | list[str] | None = None,
        *,
        ttl: float | Any = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        namespace_key = _namespace_key(namespace)
        value_json = json.dumps(value, ensure_ascii=False, sort_keys=True)
        conn = self._connect()
        try:
            existing = conn.execute(
                "select created_at from store_items where namespace = ? and key = ?",
                (namespace_key, key),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                insert into store_items(namespace, key, value_json, created_at, updated_at)
                values(?, ?, ?, ?, ?)
                on conflict(namespace, key) do update set
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (namespace_key, key, value_json, created_at, now),
            )
            conn.commit()
        finally:
            conn.close()

    def search(
        self,
        namespace_prefix: tuple[str, ...],
        /,
        *,
        query: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
        refresh_ttl: bool | None = None,
    ) -> list[SearchItem]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                select namespace, key, value_json, created_at, updated_at
                from store_items
                order by updated_at desc
                """,
            ).fetchall()
        finally:
            conn.close()
        results: list[SearchItem] = []
        for row in rows:
            namespace = _namespace_tuple(row["namespace"])
            if namespace[: len(namespace_prefix)] != tuple(namespace_prefix):
                continue
            item = _search_item_from_row(row)
            if query and query.lower() not in json.dumps(item.value, ensure_ascii=False).lower():
                continue
            if filter and not _matches_filter(item.value, filter):
                continue
            results.append(item)
        return results[int(offset) : int(offset) + int(limit)]

    def delete(self, namespace: tuple[str, ...], key: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "delete from store_items where namespace = ? and key = ?",
                (_namespace_key(namespace), key),
            )
            conn.commit()
        finally:
            conn.close()

    def list_namespaces(
        self,
        *,
        prefix: tuple[str, ...] | None = None,
        suffix: tuple[str, ...] | None = None,
        max_depth: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[str, ...]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "select distinct namespace from store_items order by namespace limit ? offset ?",
                (int(limit), int(offset)),
            ).fetchall()
        finally:
            conn.close()
        namespaces = [_namespace_tuple(row["namespace"]) for row in rows]
        if prefix:
            namespaces = [item for item in namespaces if item[: len(prefix)] == tuple(prefix)]
        if suffix:
            namespaces = [item for item in namespaces if item[-len(suffix) :] == tuple(suffix)]
        if max_depth is not None:
            namespaces = [item for item in namespaces if len(item) <= int(max_depth)]
        return namespaces

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                create table if not exists store_items(
                    namespace text not null,
                    key text not null,
                    value_json text not null,
                    created_at text not null,
                    updated_at text not null,
                    primary key(namespace, key)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _namespace_key(namespace: tuple[str, ...]) -> str:
    return json.dumps(list(namespace), ensure_ascii=False, separators=(",", ":"))


def _namespace_tuple(value: str) -> tuple[str, ...]:
    return tuple(json.loads(value))


def _item_from_row(row: sqlite3.Row) -> Item:
    return Item(
        namespace=_namespace_tuple(row["namespace"]),
        key=row["key"],
        value=json.loads(row["value_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _search_item_from_row(row: sqlite3.Row) -> SearchItem:
    return SearchItem(
        namespace=_namespace_tuple(row["namespace"]),
        key=row["key"],
        value=json.loads(row["value_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        score=None,
    )


def _matches_filter(value: dict[str, Any], filter: dict[str, Any]) -> bool:
    for key, expected in filter.items():
        if value.get(key) != expected:
            return False
    return True


def _namespace_match_conditions(match_conditions) -> tuple[tuple[str, ...] | None, tuple[str, ...] | None]:
    prefix: tuple[str, ...] | None = None
    suffix: tuple[str, ...] | None = None
    for condition in match_conditions or ():
        match_type = getattr(condition, "match_type", None)
        path = tuple(getattr(condition, "path", ()) or ())
        if match_type == "prefix":
            prefix = path
        elif match_type == "suffix":
            suffix = path
    return prefix, suffix
