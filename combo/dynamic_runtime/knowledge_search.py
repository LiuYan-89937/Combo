from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
from math import sqrt
import re
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from combo.dynamic_runtime.capability_search import CapabilityEmbeddingRuntime
from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.repositories import utc_now_text


DEFAULT_KNOWLEDGE_LEXICAL_LIMIT = 30
DEFAULT_KNOWLEDGE_VECTOR_LIMIT = 30
DEFAULT_KNOWLEDGE_RESULT_LIMIT = 10
DEFAULT_KNOWLEDGE_RRF_K = 60
DEFAULT_KNOWLEDGE_VECTOR_MINIMUM_SIMILARITY = 0.15
DEFAULT_KNOWLEDGE_LEXICAL_WEIGHT = 1.0
DEFAULT_KNOWLEDGE_VECTOR_WEIGHT = 1.0
DEFAULT_KNOWLEDGE_CHUNK_SIZE = 800
DEFAULT_KNOWLEDGE_CHUNK_OVERLAP = 120


class KnowledgeRetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    revision: int = Field(default=0, ge=0)
    lexical_limit: int = Field(default=DEFAULT_KNOWLEDGE_LEXICAL_LIMIT, ge=1, le=200)
    vector_limit: int = Field(default=DEFAULT_KNOWLEDGE_VECTOR_LIMIT, ge=1, le=200)
    result_limit: int = Field(default=DEFAULT_KNOWLEDGE_RESULT_LIMIT, ge=1, le=50)
    rrf_k: int = Field(default=DEFAULT_KNOWLEDGE_RRF_K, ge=1, le=1000)
    vector_minimum_similarity: float = Field(
        default=DEFAULT_KNOWLEDGE_VECTOR_MINIMUM_SIMILARITY,
        ge=-1,
        le=1,
    )
    lexical_weight: float = Field(default=DEFAULT_KNOWLEDGE_LEXICAL_WEIGHT, gt=0, le=10)
    vector_weight: float = Field(default=DEFAULT_KNOWLEDGE_VECTOR_WEIGHT, gt=0, le=10)
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeChunkProjection:
    chunk_id: str
    source_id: str
    document_id: str
    chunk_index: int
    title: str
    content: str
    content_digest: str
    vector_enabled: bool


EmbeddingRuntimeResolver = Callable[[], CapabilityEmbeddingRuntime | None]


class HybridKnowledgeSearchIndex:
    """Generation-based FTS5 and embedding retrieval fused with weighted RRF."""

    def __init__(
        self,
        database: DynamicRuntimeDatabase,
        *,
        embedding_runtime: EmbeddingRuntimeResolver | None,
    ) -> None:
        self._database = database
        self._embedding_runtime = embedding_runtime
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-index")
        self._lock = Lock()
        self._future: Future[None] | None = None
        self._pending_refresh = False
        self._pending_force = False

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def settings(self) -> KnowledgeRetrievalSettings:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                "select payload_json from knowledge_search_settings where singleton = 1"
            ).fetchone()
        if row is None:
            return KnowledgeRetrievalSettings()
        return KnowledgeRetrievalSettings.model_validate_json(str(row["payload_json"]))

    def save_settings(
        self,
        settings: KnowledgeRetrievalSettings,
        *,
        expected_revision: int | None,
    ) -> KnowledgeRetrievalSettings:
        now = utc_now_text()
        with self._database.transaction() as connection:
            row = connection.execute(
                "select payload_json from knowledge_search_settings where singleton = 1"
            ).fetchone()
            current = (
                KnowledgeRetrievalSettings.model_validate_json(str(row["payload_json"]))
                if row is not None
                else KnowledgeRetrievalSettings()
            )
            if expected_revision != current.revision:
                raise RuntimeError("knowledge retrieval settings revision conflict")
            saved = settings.model_copy(update={"revision": current.revision + 1, "updated_at": now})
            if current.revision == 0:
                connection.execute(
                    "insert into knowledge_search_settings(singleton, revision, payload_json, updated_at) values (1, ?, ?, ?)",
                    (saved.revision, saved.model_dump_json(), now),
                )
            else:
                changed = connection.execute(
                    """
                    update knowledge_search_settings
                    set revision = ?, payload_json = ?, updated_at = ?
                    where singleton = 1 and revision = ?
                    """,
                    (saved.revision, saved.model_dump_json(), now, current.revision),
                ).rowcount
                if changed != 1:
                    raise RuntimeError("knowledge retrieval settings revision conflict")
        return saved

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if self._future is not None:
                self._pending_refresh = True
                self._pending_force = self._pending_force or force
                return
            self._future = self._executor.submit(self._rebuild_if_needed, force)
            self._future.add_done_callback(self._after_rebuild)

    def search(
        self,
        *,
        query: str,
        limit: int | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("knowledge search query must not be empty")
        self.refresh()
        active = self._active_generation()
        if active is None:
            return []
        generation_id, mode, embedding_fingerprint = active
        settings = self.settings()
        requested_limit = settings.result_limit if limit is None else max(1, min(int(limit), 50))
        result_limit = min(requested_limit, settings.result_limit)
        lexical = self._lexical_ranking(
            generation_id,
            normalized_query,
            limit=settings.lexical_limit,
            source_id=source_id,
        )
        vector: list[tuple[str, float]] = []
        if mode == "hybrid" and embedding_fingerprint:
            vector = self._vector_ranking(
                generation_id,
                normalized_query,
                embedding_fingerprint=embedding_fingerprint,
                limit=settings.vector_limit,
                minimum_similarity=settings.vector_minimum_similarity,
                source_id=source_id,
            )
        ranked_ids = _weighted_rrf(
            lexical=lexical,
            vector=vector,
            k=settings.rrf_k,
            lexical_weight=settings.lexical_weight,
            vector_weight=settings.vector_weight,
        )[:result_limit]
        return self._results(generation_id, ranked_ids, lexical=lexical, vector=vector)

    def _after_rebuild(self, _future: Future[None]) -> None:
        with self._lock:
            pending_refresh = self._pending_refresh
            pending_force = self._pending_force
            self._pending_refresh = False
            self._pending_force = False
            self._future = None
        if pending_refresh:
            self.refresh(force=pending_force)

    def _rebuild_if_needed(self, force: bool) -> None:
        chunks = self._project_chunks()
        dataset_digest = _dataset_digest(chunks)
        runtime = self._resolve_embedding_runtime()
        vector_required = any(item.vector_enabled for item in chunks)
        fingerprint = runtime.fingerprint if runtime is not None and vector_required else None
        active = self._active_generation_details()
        if (
            not force
            and active is not None
            and active[1] == dataset_digest
            and active[2] == fingerprint
        ):
            return
        embeddings: list[list[float] | None] = [None] * len(chunks)
        search_mode = "lexical"
        diagnostic: str | None = None
        if runtime is not None:
            vector_positions = [index for index, item in enumerate(chunks) if item.vector_enabled]
            if vector_positions:
                try:
                    reusable = {} if force else self._reusable_embeddings(runtime.fingerprint)
                    pending_positions: list[int] = []
                    for position in vector_positions:
                        existing = reusable.get(chunks[position].chunk_id)
                        if existing is None:
                            pending_positions.append(position)
                        else:
                            embeddings[position] = _validated_vector(existing, runtime.dimensions)
                    values = (
                        runtime.embed_documents([chunks[index].content for index in pending_positions])
                        if pending_positions
                        else []
                    )
                    if len(values) != len(pending_positions):
                        raise RuntimeError("embedding result count differs from knowledge chunk count")
                    for position, vector in zip(pending_positions, values, strict=True):
                        embeddings[position] = _validated_vector(vector, runtime.dimensions)
                    search_mode = "hybrid"
                except Exception as exc:
                    diagnostic = f"{type(exc).__name__}: {exc}"
                    fingerprint = None
        self._activate_generation(
            chunks=chunks,
            embeddings=embeddings,
            dataset_digest=dataset_digest,
            search_mode=search_mode,
            runtime=runtime if search_mode == "hybrid" else None,
            diagnostic=diagnostic,
        )

    def _reusable_embeddings(self, embedding_fingerprint: str) -> dict[str, list[float]]:
        active = self._active_generation_details()
        if active is None or active[2] != embedding_fingerprint:
            return {}
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select chunk_id, embedding_json from knowledge_search_chunks
                where generation_id = ? and embedding_json is not null
                """,
                (active[0],),
            ).fetchall()
        return {
            str(row["chunk_id"]): [float(value) for value in json.loads(str(row["embedding_json"]))]
            for row in rows
        }

    def _resolve_embedding_runtime(self) -> CapabilityEmbeddingRuntime | None:
        if self._embedding_runtime is None:
            return None
        try:
            return self._embedding_runtime()
        except Exception:
            return None

    def _project_chunks(self) -> tuple[KnowledgeChunkProjection, ...]:
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select document.document_id, document.source_id, document.title,
                       document.content, document.content_digest, source.payload_json
                from knowledge_documents document
                join knowledge_sources source on source.source_id = document.source_id
                where document.status = 'ready' and source.status != 'deleted'
                order by document.source_id, document.document_id
                """
            ).fetchall()
        projected: list[KnowledgeChunkProjection] = []
        for row in rows:
            source = json.loads(str(row["payload_json"]))
            content = str(row["content"])
            mount_mode = str(source.get("mount_mode") or "rag")
            fragments = _document_chunks(content, source) if mount_mode == "rag" else [content]
            for index, fragment in enumerate(fragments):
                normalized = fragment.strip()
                if not normalized:
                    continue
                document_id = str(row["document_id"])
                digest = sha256(normalized.encode("utf-8")).hexdigest()
                projected.append(KnowledgeChunkProjection(
                    chunk_id=sha256(f"{document_id}:{index}:{digest}".encode("utf-8")).hexdigest(),
                    source_id=str(row["source_id"]),
                    document_id=document_id,
                    chunk_index=index,
                    title=str(row["title"]),
                    content=normalized,
                    content_digest=digest,
                    vector_enabled=mount_mode == "rag",
                ))
        return tuple(projected)

    def _activate_generation(
        self,
        *,
        chunks: tuple[KnowledgeChunkProjection, ...],
        embeddings: list[list[float] | None],
        dataset_digest: str,
        search_mode: str,
        runtime: CapabilityEmbeddingRuntime | None,
        diagnostic: str | None,
    ) -> None:
        generation_id = uuid4().hex
        now = utc_now_text()
        with self._database.transaction() as connection:
            connection.execute(
                """
                insert into knowledge_search_generations(
                  generation_id, dataset_digest, search_mode, embedding_fingerprint,
                  embedding_profile_id, embedding_dimensions, status, diagnostic, created_at
                ) values (?, ?, ?, ?, ?, ?, 'building', ?, ?)
                """,
                (
                    generation_id,
                    dataset_digest,
                    search_mode,
                    runtime.fingerprint if runtime else None,
                    runtime.profile_id if runtime else None,
                    runtime.dimensions if runtime else None,
                    diagnostic,
                    now,
                ),
            )
            for chunk, vector in zip(chunks, embeddings, strict=True):
                connection.execute(
                    """
                    insert into knowledge_search_chunks(
                      generation_id, chunk_id, source_id, document_id, chunk_index,
                      title, content, content_digest, embedding_json
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id,
                        chunk.chunk_id,
                        chunk.source_id,
                        chunk.document_id,
                        chunk.chunk_index,
                        chunk.title,
                        chunk.content,
                        chunk.content_digest,
                        json.dumps(vector, separators=(",", ":")) if vector is not None else None,
                    ),
                )
                connection.execute(
                    "insert into knowledge_search_fts(generation_id, chunk_id, title, content) values (?, ?, ?, ?)",
                    (generation_id, chunk.chunk_id, chunk.title, chunk.content),
                )
            connection.execute(
                "update knowledge_search_generations set status = 'retired' where status = 'active'"
            )
            connection.execute(
                "update knowledge_search_generations set status = 'active', activated_at = ? where generation_id = ?",
                (now, generation_id),
            )
            connection.execute(
                """
                insert into knowledge_search_active_generation(singleton, generation_id, changed_at)
                values (1, ?, ?)
                on conflict(singleton) do update set generation_id=excluded.generation_id, changed_at=excluded.changed_at
                """,
                (generation_id, now),
            )
            retired = connection.execute(
                "select generation_id from knowledge_search_generations where generation_id != ?",
                (generation_id,),
            ).fetchall()
            for row in retired:
                retired_id = str(row["generation_id"])
                connection.execute("delete from knowledge_search_fts where generation_id = ?", (retired_id,))
            connection.execute(
                "delete from knowledge_search_generations where generation_id != ?",
                (generation_id,),
            )

    def _active_generation(self) -> tuple[str, str, str | None] | None:
        details = self._active_generation_details()
        if details is None:
            return None
        return details[0], details[3], details[2]

    def _active_generation_details(self) -> tuple[str, str, str | None, str] | None:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                """
                select generation.generation_id, generation.dataset_digest,
                       generation.embedding_fingerprint, generation.search_mode
                from knowledge_search_active_generation active
                join knowledge_search_generations generation on generation.generation_id = active.generation_id
                where active.singleton = 1 and generation.status = 'active'
                """
            ).fetchone()
        if row is None:
            return None
        return (
            str(row["generation_id"]),
            str(row["dataset_digest"]),
            str(row["embedding_fingerprint"]) if row["embedding_fingerprint"] else None,
            str(row["search_mode"]),
        )

    def _lexical_ranking(
        self,
        generation_id: str,
        query: str,
        *,
        limit: int,
        source_id: str | None,
    ) -> list[tuple[str, float]]:
        expression = _fts_query(query)
        if not expression:
            return []
        source_clause = "and chunk.source_id = ?" if source_id else ""
        parameters: list[Any] = [generation_id, expression]
        if source_id:
            parameters.append(source_id)
        parameters.append(limit)
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                f"""
                select fts.chunk_id, bm25(knowledge_search_fts) as score
                from knowledge_search_fts fts
                join knowledge_search_chunks chunk
                  on chunk.generation_id = fts.generation_id and chunk.chunk_id = fts.chunk_id
                where fts.generation_id = ? and knowledge_search_fts match ? {source_clause}
                order by score, fts.rowid
                limit ?
                """,
                tuple(parameters),
            ).fetchall()
        return [(str(row["chunk_id"]), float(row["score"])) for row in rows]

    def _vector_ranking(
        self,
        generation_id: str,
        query: str,
        *,
        embedding_fingerprint: str,
        limit: int,
        minimum_similarity: float,
        source_id: str | None,
    ) -> list[tuple[str, float]]:
        runtime = self._resolve_embedding_runtime()
        if runtime is None or runtime.fingerprint != embedding_fingerprint:
            return []
        query_vector = _validated_vector(runtime.embed_query(query), runtime.dimensions)
        source_clause = "and source_id = ?" if source_id else ""
        parameters: tuple[Any, ...] = (generation_id, source_id) if source_id else (generation_id,)
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                f"""
                select chunk_id, embedding_json from knowledge_search_chunks
                where generation_id = ? and embedding_json is not null {source_clause}
                """,
                parameters,
            ).fetchall()
        scored = [
            (str(row["chunk_id"]), _cosine(query_vector, [float(value) for value in json.loads(str(row["embedding_json"]))]))
            for row in rows
        ]
        return sorted(
            (item for item in scored if item[1] >= minimum_similarity),
            key=lambda item: (-item[1], item[0]),
        )[:limit]

    def _results(
        self,
        generation_id: str,
        ranked: list[tuple[str, float]],
        *,
        lexical: list[tuple[str, float]],
        vector: list[tuple[str, float]],
    ) -> list[dict[str, Any]]:
        if not ranked:
            return []
        ids = [chunk_id for chunk_id, _score in ranked]
        placeholders = ",".join("?" for _item in ids)
        with self._database.connection(query_only=True) as connection:
            rows = connection.execute(
                f"""
                select chunk_id, source_id, document_id, chunk_index, title, content
                from knowledge_search_chunks
                where generation_id = ? and chunk_id in ({placeholders})
                """,
                (generation_id, *ids),
            ).fetchall()
        by_id = {str(row["chunk_id"]): row for row in rows}
        lexical_rank = {chunk_id: index for index, (chunk_id, _score) in enumerate(lexical, start=1)}
        vector_rank = {chunk_id: index for index, (chunk_id, _score) in enumerate(vector, start=1)}
        vector_score = dict(vector)
        return [
            {
                "chunk_id": chunk_id,
                "document_id": str(by_id[chunk_id]["document_id"]),
                "source_id": str(by_id[chunk_id]["source_id"]),
                "chunk_index": int(by_id[chunk_id]["chunk_index"]),
                "title": str(by_id[chunk_id]["title"]),
                "snippet": str(by_id[chunk_id]["content"]),
                "score": score,
                "lexical_rank": lexical_rank.get(chunk_id),
                "vector_rank": vector_rank.get(chunk_id),
                "vector_similarity": vector_score.get(chunk_id),
            }
            for chunk_id, score in ranked
            if chunk_id in by_id
        ]


def _document_chunks(content: str, source: dict[str, Any]) -> list[str]:
    chunking = source.get("chunking") if isinstance(source.get("chunking"), dict) else {}
    chunk_size = max(100, min(int(chunking.get("chunk_size") or DEFAULT_KNOWLEDGE_CHUNK_SIZE), 8000))
    overlap = max(0, min(int(chunking.get("chunk_overlap") or DEFAULT_KNOWLEDGE_CHUNK_OVERLAP), chunk_size - 1))
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        length_function=len,
    ).split_text(content)


def _dataset_digest(chunks: tuple[KnowledgeChunkProjection, ...]) -> str:
    payload = [
        (item.chunk_id, item.source_id, item.document_id, item.chunk_index, item.content_digest, item.vector_enabled)
        for item in chunks
    ]
    return sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validated_vector(values: list[float], dimensions: int) -> list[float]:
    vector = [float(value) for value in values]
    if len(vector) != dimensions or not any(vector):
        raise ValueError("invalid embedding vector")
    return vector


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    if denominator == 0:
        return -1.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _fts_query(query: str) -> str:
    tokens = [token for token in re.findall(r"[\w]+", query, flags=re.UNICODE) if token]
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _weighted_rrf(
    *,
    lexical: list[tuple[str, float]],
    vector: list[tuple[str, float]],
    k: int,
    lexical_weight: float,
    vector_weight: float,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for rank, (chunk_id, _score) in enumerate(lexical, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + lexical_weight / (k + rank)
    for rank, (chunk_id, _score) in enumerate(vector, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + vector_weight / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
