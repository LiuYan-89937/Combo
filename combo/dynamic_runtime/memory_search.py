from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
from math import sqrt
import re
from threading import Lock
import unicodedata
from uuid import uuid4

from combo.dynamic_runtime.capability_search import CapabilityEmbeddingRuntime
from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.runtime_protocol import MemoryRevision


@dataclass(frozen=True, slots=True)
class RankedMemory:
    revision: MemoryRevision
    score: float


class HybridMemorySearchIndex:
    """Authoritative active-memory index with FTS5 fallback and optional embeddings."""

    def __init__(self, database: DynamicRuntimeDatabase, embedding_runtime=None) -> None:
        self._database = database
        self._embedding_runtime = embedding_runtime
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-embedding") if embedding_runtime else None
        self._lock = Lock()
        self._future: Future[None] | None = None

    def refresh(self) -> None:
        documents = self._documents()
        generation_id, dataset_digest = self._ensure_lexical(documents)
        self._schedule_hybrid(generation_id, dataset_digest, documents)

    def search(self, *, principal_id: str, workspace_id: str, query: str, limit: int) -> tuple[RankedMemory, ...]:
        if limit < 1 or not _tokens(query):
            return ()
        self.refresh()
        generation = self._active_generation()
        if generation is None:
            return ()
        generation_id, mode = generation
        allowed = self._owned_documents(generation_id, principal_id, workspace_id)
        lexical = self._lexical(generation_id, query, frozenset(allowed))
        vector = self._vector(generation_id, query, frozenset(allowed)) if mode == "hybrid" else ()
        rankings = [(lexical, 0.45), (vector, 0.55)]
        active = [(ranking, weight) for ranking, weight in rankings if ranking]
        if not active:
            return ()
        scores: dict[str, float] = {}
        total_weight = sum(weight for _, weight in active)
        for ranking, configured_weight in active:
            weight = configured_weight / total_weight
            for rank, memory_id in enumerate(ranking, start=1):
                scores[memory_id] = scores.get(memory_id, 0.0) + weight / rank
        for memory_id, revision in allowed.items():
            if memory_id in scores and revision.scope == "workspace":
                scores[memory_id] = min(1.0, scores[memory_id] + 0.1)
        ordered = sorted(scores, key=lambda memory_id: (-scores[memory_id], memory_id))[:limit]
        return tuple(RankedMemory(revision=allowed[memory_id], score=min(1.0, scores[memory_id])) for memory_id in ordered)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _documents(self) -> tuple[MemoryRevision, ...]:
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select revision.payload_json from memory_heads head
                join memory_revisions revision on revision.memory_id = head.memory_id and revision.revision = head.revision
                where head.status = 'active' order by head.memory_id
                """
            ).fetchall()
        return tuple(MemoryRevision.model_validate_json(str(row["payload_json"])) for row in rows)

    def _ensure_lexical(self, documents: tuple[MemoryRevision, ...]) -> tuple[str, str]:
        digest = _digest([(item.memory_id, item.revision, item.content_digest) for item in documents])
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select generation_id from memory_search_generations where dataset_digest = ? and search_mode = 'lexical' and status = 'active'",
                (digest,),
            ).fetchone()
        if row is not None:
            return str(row["generation_id"]), digest
        generation_id = uuid4().hex
        with self._database.transaction() as conn:
            conn.execute("update memory_search_generations set status = 'retired' where status = 'active'")
            conn.execute(
                "insert into memory_search_generations(generation_id,dataset_digest,search_mode,status,created_at,activated_at) values (?,?,'lexical','active',strftime('%Y-%m-%dT%H:%M:%fZ','now'),strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (generation_id, digest),
            )
            self._insert_documents(conn, generation_id, documents, None)
            conn.execute(
                "insert into memory_search_active_generation(singleton,generation_id,changed_at) values (1,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) on conflict(singleton) do update set generation_id=excluded.generation_id,changed_at=excluded.changed_at",
                (generation_id,),
            )
        return generation_id, digest

    def _schedule_hybrid(self, lexical_id: str, digest: str, documents: tuple[MemoryRevision, ...]) -> None:
        if self._executor is None or self._embedding_runtime is None or not documents:
            return
        try:
            runtime = self._embedding_runtime()
        except Exception:
            return
        if runtime is None:
            return
        with self._database.connection(query_only=True) as conn:
            exists = conn.execute(
                "select 1 from memory_search_generations where dataset_digest=? and search_mode='hybrid' and embedding_fingerprint=? and status in ('building','active')",
                (digest, runtime.fingerprint),
            ).fetchone()
        if exists is not None:
            return
        with self._lock:
            if self._future is not None and not self._future.done():
                return
            self._future = self._executor.submit(self._build_hybrid, lexical_id, digest, documents, runtime)

    def _build_hybrid(self, lexical_id: str, digest: str, documents: tuple[MemoryRevision, ...], runtime: CapabilityEmbeddingRuntime) -> None:
        generation_id = uuid4().hex
        try:
            with self._database.transaction() as conn:
                conn.execute(
                    "insert into memory_search_generations(generation_id,dataset_digest,search_mode,embedding_fingerprint,embedding_profile_id,embedding_dimensions,status,created_at) values (?,?,'hybrid',?,?,?,'building',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (generation_id, digest, runtime.fingerprint, runtime.profile_id, runtime.dimensions),
                )
            vectors = runtime.embed_documents([item.content for item in documents])
            normalized = tuple(_validated_vector(vector, runtime.dimensions) for vector in vectors)
            if len(normalized) != len(documents):
                raise RuntimeError("embedding result count differs from memory document count")
            with self._database.transaction() as conn:
                active = conn.execute("select generation_id from memory_search_active_generation where singleton=1").fetchone()
                if active is None or str(active["generation_id"]) != lexical_id:
                    conn.execute("update memory_search_generations set status='retired' where generation_id=?", (generation_id,))
                    return
                self._insert_documents(conn, generation_id, documents, normalized)
                conn.execute("update memory_search_generations set status='retired' where status='active'")
                conn.execute("update memory_search_generations set status='active',activated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where generation_id=?", (generation_id,))
                conn.execute("update memory_search_active_generation set generation_id=?,changed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where singleton=1", (generation_id,))
        except Exception as exc:
            with self._database.transaction() as conn:
                conn.execute("update memory_search_generations set status='failed',diagnostic=? where generation_id=?", (f"{type(exc).__name__}: {exc}", generation_id))

    def _insert_documents(self, conn, generation_id: str, documents: tuple[MemoryRevision, ...], vectors) -> None:
        for index, revision in enumerate(documents):
            searchable = " ".join(_tokens(revision.content))
            vector = None if vectors is None else json.dumps(vectors[index], separators=(",", ":"))
            conn.execute(
                "insert into memory_search_documents(generation_id,memory_id,memory_revision,principal_id,scope,workspace_id,content_digest,searchable_text,embedding_json) values (?,?,?,?,?,?,?,?,?)",
                (generation_id, revision.memory_id, revision.revision, revision.principal_id, revision.scope, revision.workspace_id, revision.content_digest, searchable, vector),
            )
            conn.execute("insert into memory_search_fts(generation_id,memory_id,searchable_text) values (?,?,?)", (generation_id, revision.memory_id, searchable))

    def _active_generation(self) -> tuple[str, str] | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select generation.generation_id,generation.search_mode from memory_search_active_generation active join memory_search_generations generation on generation.generation_id=active.generation_id where active.singleton=1"
            ).fetchone()
        return None if row is None else (str(row["generation_id"]), str(row["search_mode"]))

    def _owned_documents(self, generation_id: str, principal_id: str, workspace_id: str) -> dict[str, MemoryRevision]:
        active = {item.memory_id: item for item in self._documents() if item.principal_id == principal_id and (item.scope == "user" or item.workspace_id == workspace_id)}
        with self._database.connection(query_only=True) as conn:
            ids = {str(row["memory_id"]) for row in conn.execute("select memory_id from memory_search_documents where generation_id=? and principal_id=? and (scope='user' or workspace_id=?)", (generation_id, principal_id, workspace_id)).fetchall()}
        return {memory_id: revision for memory_id, revision in active.items() if memory_id in ids}

    def _lexical(self, generation_id: str, query: str, allowed: frozenset[str]) -> tuple[str, ...]:
        expression = " OR ".join(f'"{token}"' for token in _tokens(query))
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute("select memory_id,bm25(memory_search_fts) rank from memory_search_fts where memory_search_fts match ? and generation_id=? order by rank,memory_id", (expression, generation_id)).fetchall()
        return tuple(str(row["memory_id"]) for row in rows if str(row["memory_id"]) in allowed)

    def _vector(self, generation_id: str, query: str, allowed: frozenset[str]) -> tuple[str, ...]:
        try:
            runtime = self._embedding_runtime()
            if runtime is None:
                return ()
            with self._database.connection(query_only=True) as conn:
                generation = conn.execute("select embedding_fingerprint from memory_search_generations where generation_id=?", (generation_id,)).fetchone()
                rows = conn.execute("select memory_id,embedding_json from memory_search_documents where generation_id=? and embedding_json is not null", (generation_id,)).fetchall()
            if generation is None or str(generation["embedding_fingerprint"] or "") != runtime.fingerprint:
                return ()
            query_vector = _validated_vector(runtime.embed_query(query), runtime.dimensions)
        except Exception:
            return ()
        ranked = [(_cosine(query_vector, tuple(json.loads(str(row["embedding_json"])))), str(row["memory_id"])) for row in rows if str(row["memory_id"]) in allowed]
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(memory_id for _, memory_id in ranked)


def _tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    result: list[str] = []
    for segment in re.findall(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", segment):
            result.extend(
                segment[index : index + 2]
                for index in range(max(1, len(segment) - 1))
            )
        else:
            result.append(segment)
    return tuple(dict.fromkeys(result))


def _digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _validated_vector(values, dimensions: int) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if len(vector) != dimensions or not any(vector):
        raise ValueError("invalid embedding vector")
    return vector


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    return 0.0 if denominator == 0 else sum(a * b for a, b in zip(left, right)) / denominator
