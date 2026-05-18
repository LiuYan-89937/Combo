from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import math
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
    memory_type: Literal["semantic", "episodic", "procedural"] = "semantic"
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True, slots=True)
class LangGraphStoreConfig:
    backend: LangGraphStoreBackend = "sqlite"
    path: Path | None = None
    index: "LangGraphStoreIndexConfig | None" = None


@dataclass(frozen=True, slots=True)
class LangGraphStoreIndexConfig:
    embed: Any
    dims: int
    fields: tuple[str, ...] = ("$",)


@dataclass(frozen=True, slots=True)
class LangGraphStoreHandle:
    store: BaseStore
    backend: LangGraphStoreBackend
    persistent: bool
    path: Path | None = None
    semantic_index_enabled: bool = False


class LangGraphStoreFactory:
    def build(self, config: LangGraphStoreConfig) -> LangGraphStoreHandle:
        if config.backend == "memory":
            from langgraph.store.memory import InMemoryStore

            return LangGraphStoreHandle(
                store=InMemoryStore(index=_index_payload(config.index)),
                backend="memory",
                persistent=False,
                semantic_index_enabled=config.index is not None,
            )
        if config.path is None:
            raise ValueError("SQLite memory store requires a store path.")
        config.path.parent.mkdir(parents=True, exist_ok=True)
        return LangGraphStoreHandle(
            store=SqliteBaseStore(config.path, index=config.index),
            backend="sqlite",
            persistent=True,
            path=config.path,
            semantic_index_enabled=config.index is not None,
        )


class SqliteBaseStore(BaseStore):
    def __init__(self, path: str | Path, *, index: LangGraphStoreIndexConfig | None = None) -> None:
        super().__init__()
        self.path = Path(path)
        self.index = index
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
        indexed_text = _indexed_text(value, _index_fields(self.index, index))
        embedding_json = _embedding_json(self.index, indexed_text) if indexed_text else None
        conn = self._connect()
        try:
            existing = conn.execute(
                "select created_at from store_items where namespace = ? and key = ?",
                (namespace_key, key),
            ).fetchone()
            created_at = existing["created_at"] if existing else now
            conn.execute(
                """
                insert into store_items(namespace, key, value_json, created_at, updated_at, indexed_text, embedding_json)
                values(?, ?, ?, ?, ?, ?, ?)
                on conflict(namespace, key) do update set
                    value_json = excluded.value_json,
                    indexed_text = excluded.indexed_text,
                    embedding_json = excluded.embedding_json,
                    updated_at = excluded.updated_at
                """,
                (namespace_key, key, value_json, created_at, now, indexed_text, embedding_json),
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
        query_embedding = _embed_query(self.index, query) if query else None
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                select namespace, key, value_json, indexed_text, embedding_json, created_at, updated_at
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
            item = _search_item_from_row(row, score=_row_score(row, query=query, query_embedding=query_embedding))
            if query and item.score is None:
                continue
            if filter and not _matches_filter(item.value, filter):
                continue
            results.append(item)
        if query_embedding is not None:
            results.sort(key=lambda item: (item.score or 0.0, item.updated_at or ""), reverse=True)
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
                    indexed_text text,
                    embedding_json text,
                    created_at text not null,
                    updated_at text not null,
                    primary key(namespace, key)
                )
                """
            )
            _ensure_column(conn, "store_items", "indexed_text", "text")
            _ensure_column(conn, "store_items", "embedding_json", "text")
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


def _search_item_from_row(row: sqlite3.Row, *, score: float | None = None) -> SearchItem:
    return SearchItem(
        namespace=_namespace_tuple(row["namespace"]),
        key=row["key"],
        value=json.loads(row["value_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        score=score,
    )


def _matches_filter(value: dict[str, Any], filter: dict[str, Any]) -> bool:
    for key, expected in filter.items():
        if value.get(key) != expected:
            return False
    return True


def _index_payload(index: LangGraphStoreIndexConfig | None) -> dict[str, Any] | None:
    if index is None:
        return None
    payload: dict[str, Any] = {
        "embed": index.embed,
        "dims": index.dims,
    }
    if index.fields:
        payload["fields"] = list(index.fields)
    return payload


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {column_type}")


def _index_fields(
    index_config: LangGraphStoreIndexConfig | None,
    put_index: Literal[False] | list[str] | None,
) -> tuple[str, ...]:
    if index_config is None or put_index is False:
        return ()
    if isinstance(put_index, list):
        return tuple(str(item) for item in put_index if str(item).strip())
    return index_config.fields


def _indexed_text(value: dict[str, Any], fields: tuple[str, ...]) -> str:
    if not fields:
        return ""
    if fields == ("$",):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    parts: list[str] = []
    for field in fields:
        selected = _select_field(value, field)
        if selected is None:
            continue
        if isinstance(selected, str):
            parts.append(selected)
        else:
            parts.append(json.dumps(selected, ensure_ascii=False, sort_keys=True))
    return "\n".join(part for part in parts if part.strip())


def _select_field(value: dict[str, Any], field: str) -> Any:
    current: Any = value
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def _embedding_json(index_config: LangGraphStoreIndexConfig | None, text: str) -> str | None:
    if index_config is None or not text.strip():
        return None
    try:
        vectors = index_config.embed.embed_documents([text])
    except Exception:
        return None
    if not vectors:
        return None
    vector = [float(item) for item in vectors[0]]
    if len(vector) != index_config.dims:
        return None
    return json.dumps(vector, separators=(",", ":"))


def _embed_query(index_config: LangGraphStoreIndexConfig | None, query: str | None) -> list[float] | None:
    if index_config is None or not query or not query.strip():
        return None
    try:
        vector = [float(item) for item in index_config.embed.embed_query(query)]
    except Exception:
        return None
    return vector if len(vector) == index_config.dims else None


def _row_score(row: sqlite3.Row, *, query: str | None, query_embedding: list[float] | None) -> float | None:
    if not query:
        return None
    if query_embedding is not None and row["embedding_json"]:
        try:
            embedding = [float(item) for item in json.loads(row["embedding_json"])]
        except Exception:
            embedding = []
        score = _cosine_similarity(query_embedding, embedding)
        if score is not None:
            return score
    haystack = f"{row['indexed_text'] or ''}\n{row['value_json'] or ''}".lower()
    return 0.5 if query.lower() in haystack else None


def _cosine_similarity(left: list[float], right: list[float]) -> float | None:
    if not left or len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return None
    return max(0.0, min(1.0, (dot / (left_norm * right_norm) + 1.0) / 2.0))


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
