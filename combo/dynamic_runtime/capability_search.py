from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from math import sqrt
from threading import Lock
from typing import Callable, Iterable
from uuid import uuid4

from combo.dynamic_runtime.capability_resolution_services import CapabilitySearchConfig
from combo.dynamic_runtime.capability_search_contracts import (
    CapabilitySearchCandidate,
    CapabilitySearchResult,
)
from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.hybrid_retrieval import (
    FusedRetrievalCandidate,
    RankedRetrievalCandidate,
    fuse_hybrid_rankings,
    lexical_coverage,
    lexical_tokens,
)


@dataclass(frozen=True, slots=True)
class CapabilitySearchDocumentProjection:
    capability_id: str
    index_revision_id: str
    kind: str
    search_scope: str
    parent_capability_id: str | None
    display_name: str
    description: str
    keywords: tuple[str, ...]
    parameter_text: str
    embedding_text: str
    lexical_text: str


@dataclass(frozen=True, slots=True)
class CapabilityEmbeddingRuntime:
    profile_id: str
    dimensions: int
    fingerprint: str
    embed_documents: Callable[[list[str]], list[list[float]]]
    embed_query: Callable[[str], list[float]]


@dataclass(frozen=True, slots=True)
class ActiveVectorIndexStatus:
    generation_id: str
    profile_id: str
    capability_ids: frozenset[str]


EmbeddingRuntimeResolver = Callable[[], CapabilityEmbeddingRuntime | None]


class HybridCapabilitySearchIndex:
    """SQLite FTS5 plus revision-bound embedding retrieval for active capabilities."""

    def __init__(
        self,
        *,
        database: DynamicRuntimeDatabase,
        config: CapabilitySearchConfig,
        embedding_runtime: EmbeddingRuntimeResolver | None = None,
    ) -> None:
        self._database = database
        self._config = config
        self._embedding_runtime = embedding_runtime
        self._generation_lock = Lock()
        self._embedding_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="capability-embedding",
        ) if embedding_runtime is not None else None
        self._embedding_future: Future[None] | None = None
        self._pending_embedding: tuple[str, tuple[CapabilitySearchDocumentProjection, ...]] | None = None

    def search(
        self,
        *,
        requirements: tuple[str, ...],
        candidates: tuple[CapabilitySearchCandidate, ...],
    ) -> tuple[CapabilitySearchResult, ...]:
        query = " ".join(str(value or "").strip() for value in requirements if str(value or "").strip())
        if not query:
            return ()
        documents = tuple(_project_document(item) for item in candidates)
        if not documents:
            return ()
        search_scope, parent_capability_id = _search_boundary(documents)
        generation = self._active_generation()
        if generation is None:
            return ()
        candidate_ids = frozenset(item.capability_id for item in documents)
        lexical = self._lexical_ranking(
            generation[0],
            query,
            documents={item.capability_id: item for item in documents},
            search_scope=search_scope,
            parent_capability_id=parent_capability_id,
        )
        vector: tuple[RankedRetrievalCandidate, ...] = ()
        mode = generation[2]
        if mode == "hybrid":
            vector = self._vector_ranking(
                generation[0],
                query,
                candidate_ids,
                search_scope=search_scope,
                parent_capability_id=parent_capability_id,
            )
        ranked = _fuse_rankings(
            lexical=lexical,
            vector=vector,
        )
        selected = ranked[: self._config.maximum_results]
        receipt_id = self._record_receipt(
            generation_id=generation[0],
            query=query,
            candidate_ids=candidate_ids,
            results=selected,
            documents={item.capability_id: item for item in documents},
        )
        documents_by_id = {item.capability_id: item for item in documents}
        return tuple(
            CapabilitySearchResult(
                capability_id=item.item_id,
                retrieval_channels=item.channels,
                matched_fields=_matched_fields(query, documents_by_id[item.item_id]),
                reason=(
                    "retrieved as a capability candidate through "
                    + " and ".join(item.channels)
                ),
                evidence_id=f"capability-search-receipt:{receipt_id}",
            )
            for item in selected
        )

    def refresh(self, candidates: tuple[CapabilitySearchCandidate, ...]) -> None:
        documents = tuple(_project_document(item) for item in candidates)
        _, dataset_digest, _ = self._ensure_lexical_generation(documents)
        self._schedule_embedding_generation(dataset_digest, documents)

    def active_vector_index_status(self) -> ActiveVectorIndexStatus | None:
        """Return only vectors belonging to the currently active hybrid generation."""

        with self._database.connection(query_only=True) as conn:
            generation = conn.execute(
                """
                select generation.generation_id, generation.embedding_profile_id
                from capability_search_active_generation active
                join capability_search_generations generation
                  on generation.generation_id = active.generation_id
                where active.singleton = 1
                  and generation.status = 'active'
                  and generation.search_mode = 'hybrid'
                """
            ).fetchone()
            if generation is None:
                return None
            generation_id = str(generation["generation_id"])
            rows = conn.execute(
                """
                select capability_id from capability_search_documents
                where generation_id = ? and embedding_json is not null
                """,
                (generation_id,),
            ).fetchall()
        return ActiveVectorIndexStatus(
            generation_id=generation_id,
            profile_id=str(generation["embedding_profile_id"] or ""),
            capability_ids=frozenset(str(row["capability_id"]) for row in rows),
        )

    def close(self) -> None:
        if self._embedding_executor is not None:
            self._embedding_executor.shutdown(wait=False, cancel_futures=True)

    def _ensure_lexical_generation(
        self,
        documents: tuple[CapabilitySearchDocumentProjection, ...],
    ) -> tuple[str, str, str]:
        dataset_digest = _dataset_digest(documents)
        with self._generation_lock:
            active = self._active_generation()
            if active is not None and active[1] == dataset_digest:
                return active
            generation_id = uuid4().hex
            now = _utc_now_text()
            with self._database.transaction() as conn:
                conn.execute(
                    """
                    insert into capability_search_generations(
                      generation_id, dataset_digest, search_mode, status, created_at
                    ) values (?, ?, 'lexical', 'building', ?)
                    """,
                    (generation_id, dataset_digest, now),
                )
                _insert_documents(conn, generation_id, documents, embeddings=None)
                conn.execute(
                    "update capability_search_generations set status = 'retired' where status = 'active'"
                )
                conn.execute(
                    """
                    update capability_search_generations
                    set status = 'active', activated_at = ? where generation_id = ?
                    """,
                    (now, generation_id),
                )
                conn.execute(
                    """
                    insert into capability_search_active_generation(singleton, generation_id, changed_at)
                    values (1, ?, ?)
                    on conflict(singleton) do update set generation_id = excluded.generation_id,
                      changed_at = excluded.changed_at
                    """,
                    (generation_id, now),
                )
            return generation_id, dataset_digest, "lexical"

    def _active_generation(self) -> tuple[str, str, str] | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select generation.generation_id, generation.dataset_digest, generation.search_mode
                from capability_search_active_generation active
                join capability_search_generations generation
                  on generation.generation_id = active.generation_id
                where active.singleton = 1 and generation.status = 'active'
                """
            ).fetchone()
        if row is None:
            return None
        return str(row["generation_id"]), str(row["dataset_digest"]), str(row["search_mode"])

    def _schedule_embedding_generation(
        self,
        dataset_digest: str,
        documents: tuple[CapabilitySearchDocumentProjection, ...],
    ) -> None:
        if self._embedding_executor is None or self._embedding_runtime is None:
            return
        try:
            runtime = self._embedding_runtime()
        except Exception:
            return
        if runtime is None:
            return
        future: Future[None] | None = None
        with self._generation_lock:
            if self._embedding_future is not None and not self._embedding_future.done():
                self._pending_embedding = (dataset_digest, documents)
                return
            if self._matching_hybrid_generation(dataset_digest, runtime.fingerprint):
                return
            future = self._embedding_executor.submit(
                self._build_embedding_generation,
                dataset_digest,
                documents,
                runtime,
            )
            self._embedding_future = future
        future.add_done_callback(self._embedding_finished)

    def _embedding_finished(self, _: Future[None]) -> None:
        with self._generation_lock:
            self._embedding_future = None
            pending = self._pending_embedding
            self._pending_embedding = None
        if pending is not None:
            self._schedule_embedding_generation(*pending)

    def _matching_hybrid_generation(self, dataset_digest: str, fingerprint: str) -> bool:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select 1 from capability_search_generations
                where dataset_digest = ? and search_mode = 'hybrid'
                  and embedding_fingerprint = ? and status in ('building', 'active')
                """,
                (dataset_digest, fingerprint),
            ).fetchone()
        return row is not None

    def _build_embedding_generation(
        self,
        dataset_digest: str,
        documents: tuple[CapabilitySearchDocumentProjection, ...],
        runtime: CapabilityEmbeddingRuntime,
    ) -> None:
        generation_id = uuid4().hex
        now = _utc_now_text()
        try:
            with self._database.transaction() as conn:
                failed = conn.execute(
                    """
                    select generation_id from capability_search_generations
                    where dataset_digest = ? and search_mode = 'hybrid'
                      and embedding_fingerprint = ? and status = 'failed'
                    """,
                    (dataset_digest, runtime.fingerprint),
                ).fetchone()
                if failed is not None:
                    generation_id = str(failed["generation_id"])
                    conn.execute(
                        """
                        update capability_search_generations
                        set status = 'building', diagnostic = null, created_at = ?
                        where generation_id = ?
                        """,
                        (now, generation_id),
                    )
                else:
                    conn.execute(
                        """
                        insert into capability_search_generations(
                          generation_id, dataset_digest, search_mode, embedding_fingerprint,
                          embedding_profile_id, embedding_dimensions, status, created_at
                        ) values (?, ?, 'hybrid', ?, ?, ?, 'building', ?)
                        """,
                        (
                            generation_id,
                            dataset_digest,
                            runtime.fingerprint,
                            runtime.profile_id,
                            runtime.dimensions,
                            now,
                        ),
                    )
            vectors = runtime.embed_documents([item.embedding_text for item in documents])
            if len(vectors) != len(documents):
                raise RuntimeError("embedding result count differs from capability document count")
            normalized = tuple(_validated_vector(value, runtime.dimensions) for value in vectors)
            with self._database.transaction() as conn:
                conn.execute("delete from capability_search_documents where generation_id = ?", (generation_id,))
                conn.execute("delete from capability_search_fts where generation_id = ?", (generation_id,))
                _insert_documents(conn, generation_id, documents, embeddings=normalized)
                active = conn.execute(
                    """
                    select generation.dataset_digest
                    from capability_search_active_generation active
                    join capability_search_generations generation
                      on generation.generation_id = active.generation_id
                    where active.singleton = 1
                    """
                ).fetchone()
                if active is None or str(active["dataset_digest"]) != dataset_digest:
                    conn.execute(
                        "update capability_search_generations set status = 'retired' where generation_id = ?",
                        (generation_id,),
                    )
                    return
                activated = _utc_now_text()
                conn.execute("update capability_search_generations set status = 'retired' where status = 'active'")
                conn.execute(
                    """
                    update capability_search_generations set status = 'active', activated_at = ?
                    where generation_id = ?
                    """,
                    (activated, generation_id),
                )
                conn.execute(
                    """
                    update capability_search_active_generation
                    set generation_id = ?, changed_at = ? where singleton = 1
                    """,
                    (generation_id, activated),
                )
        except Exception as exc:
            with self._database.transaction() as conn:
                conn.execute(
                    """
                    update capability_search_generations set status = 'failed', diagnostic = ?
                    where generation_id = ? and status = 'building'
                    """,
                    (f"{type(exc).__name__}: {exc}", generation_id),
                )

    def _lexical_ranking(
        self,
        generation_id: str,
        query: str,
        documents: dict[str, CapabilitySearchDocumentProjection],
        *,
        search_scope: str,
        parent_capability_id: str | None,
    ) -> tuple[RankedRetrievalCandidate, ...]:
        tokens = lexical_tokens(query)
        if not tokens:
            return ()
        expression = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select capability_search_fts.capability_id,
                       bm25(capability_search_fts) as rank
                from capability_search_fts
                join capability_search_documents documents
                  on documents.generation_id = capability_search_fts.generation_id
                 and documents.capability_id = capability_search_fts.capability_id
                where capability_search_fts match ?
                  and capability_search_fts.generation_id = ?
                  and documents.search_scope = ?
                  and documents.parent_capability_id is ?
                order by rank, capability_search_fts.capability_id
                """,
                (expression, generation_id, search_scope, parent_capability_id),
            ).fetchall()
        return tuple(
            RankedRetrievalCandidate(
                item_id=capability_id,
                evidence_strength=_lexical_coverage(query, documents[capability_id]),
            )
            for row in rows
            if (capability_id := str(row["capability_id"])) in documents
        )

    def _vector_ranking(
        self,
        generation_id: str,
        query: str,
        candidate_ids: frozenset[str],
        *,
        search_scope: str,
        parent_capability_id: str | None,
    ) -> tuple[RankedRetrievalCandidate, ...]:
        if self._embedding_runtime is None:
            return ()
        try:
            runtime = self._embedding_runtime()
            if runtime is None:
                return ()
            with self._database.connection(query_only=True) as conn:
                generation = conn.execute(
                    """
                    select embedding_fingerprint, embedding_dimensions
                    from capability_search_generations where generation_id = ?
                    """,
                    (generation_id,),
                ).fetchone()
                if generation is None or str(generation["embedding_fingerprint"] or "") != runtime.fingerprint:
                    return ()
                rows = conn.execute(
                    """
                    select capability_id, embedding_json from capability_search_documents
                    where generation_id = ? and embedding_json is not null
                      and search_scope = ? and parent_capability_id is ?
                    """,
                    (generation_id, search_scope, parent_capability_id),
                ).fetchall()
            query_vector = _validated_vector(runtime.embed_query(query), runtime.dimensions)
        except Exception:
            return ()
        scored = []
        for row in rows:
            capability_id = str(row["capability_id"])
            if capability_id not in candidate_ids:
                continue
            vector = tuple(float(value) for value in json.loads(str(row["embedding_json"])))
            scored.append((_cosine(query_vector, vector), capability_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(
            RankedRetrievalCandidate(
                item_id=capability_id,
                evidence_strength=max(0.0, similarity),
            )
            for similarity, capability_id in scored
        )

    def _record_receipt(
        self,
        *,
        generation_id: str,
        query: str,
        candidate_ids: frozenset[str],
        results: tuple[FusedRetrievalCandidate, ...],
        documents: dict[str, CapabilitySearchDocumentProjection],
    ) -> str:
        receipt_id = uuid4().hex
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into capability_search_receipts(
                  receipt_id, generation_id, query_digest, candidate_digest, result_json, created_at
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    generation_id,
                    _digest(query),
                    _digest(sorted(candidate_ids)),
                    json.dumps(
                        [
                            {
                                "capability_id": item.item_id,
                                "retrieval_channels": item.channels,
                                "channel_evidence": [
                                    (evidence.channel, evidence.rank, evidence.evidence_strength)
                                    for evidence in item.evidence
                                ],
                                "fusion_score": item.fusion_score,
                                "matched_fields": _matched_fields(
                                    query,
                                    documents[item.item_id],
                                ),
                            }
                            for item in results
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    _utc_now_text(),
                ),
            )
            conn.execute(
                """
                delete from capability_search_receipts
                where receipt_id not in (
                  select receipt_id from capability_search_receipts
                  order by created_at desc, receipt_id desc limit ?
                )
                """,
                (self._config.receipt_retention_limit,),
            )
        return receipt_id


def _project_document(candidate: CapabilitySearchCandidate) -> CapabilitySearchDocumentProjection:
    embedding_text = "\n".join(
        value for value in (
            candidate.display_name,
            candidate.description,
            " ".join(candidate.keywords),
        ) if value
    )
    return CapabilitySearchDocumentProjection(
        capability_id=candidate.capability_id,
        index_revision_id=candidate.index_revision_id,
        kind=candidate.kind,
        search_scope=candidate.search_scope,
        parent_capability_id=candidate.parent_capability_id,
        display_name=candidate.display_name,
        description=candidate.description,
        keywords=candidate.keywords,
        parameter_text=candidate.parameter_text,
        embedding_text=embedding_text,
        lexical_text=" ".join(lexical_tokens(embedding_text)),
    )


def _search_boundary(
    documents: tuple[CapabilitySearchDocumentProjection, ...],
) -> tuple[str, str | None]:
    boundaries = {
        (document.search_scope, document.parent_capability_id)
        for document in documents
    }
    if len(boundaries) != 1:
        raise ValueError("capability search candidates must share one catalog boundary")
    return next(iter(boundaries))


def _insert_documents(conn: object, generation_id: str, documents: tuple[CapabilitySearchDocumentProjection, ...], *, embeddings: tuple[tuple[float, ...], ...] | None) -> None:
    for index, document in enumerate(documents):
        embedding_json = None if embeddings is None else json.dumps(embeddings[index], separators=(",", ":"))
        conn.execute(
            """
            insert into capability_search_documents(
              generation_id, capability_id, index_revision_id, kind, search_scope,
              parent_capability_id, display_name,
              description, keywords_json, parameter_text, searchable_text, embedding_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                document.capability_id,
                document.index_revision_id,
                document.kind,
                document.search_scope,
                document.parent_capability_id,
                document.display_name,
                document.description,
                json.dumps(document.keywords, ensure_ascii=False, separators=(",", ":")),
                document.parameter_text,
                document.lexical_text,
                embedding_json,
            ),
        )
        conn.execute(
            "insert into capability_search_fts(generation_id, capability_id, searchable_text) values (?, ?, ?)",
            (generation_id, document.capability_id, document.lexical_text),
        )


def _dataset_digest(documents: Iterable[CapabilitySearchDocumentProjection]) -> str:
    return _digest([
        {
            "capability_id": item.capability_id,
            "index_revision_id": item.index_revision_id,
            "search_scope": item.search_scope,
            "parent_capability_id": item.parent_capability_id,
            "embedding_text": item.embedding_text,
            "lexical_text": item.lexical_text,
        }
        for item in sorted(documents, key=lambda value: value.capability_id)
    ])


def _fuse_rankings(
    *,
    lexical: tuple[RankedRetrievalCandidate, ...],
    vector: tuple[RankedRetrievalCandidate, ...],
) -> tuple[FusedRetrievalCandidate, ...]:
    return fuse_hybrid_rankings(
        {
            "lexical": lexical,
            "semantic": vector,
        }
    )


def _matched_fields(query: str, document: CapabilitySearchDocumentProjection) -> tuple[str, ...]:
    query_tokens = frozenset(lexical_tokens(query))
    if not query_tokens:
        return ()
    fields = (
        ("display_name", document.display_name),
        ("keywords", " ".join(document.keywords)),
        ("description", document.description),
    )
    return tuple(
        field_name
        for field_name, value in fields
        if query_tokens.intersection(lexical_tokens(value))
    )


def _lexical_coverage(query: str, document: CapabilitySearchDocumentProjection) -> float:
    return lexical_coverage(query, document.lexical_text)


def _validated_vector(values: Iterable[float], dimensions: int) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if len(vector) != dimensions:
        raise ValueError(f"embedding dimensions mismatch: expected {dimensions}, got {len(vector)}")
    if not any(vector):
        raise ValueError("embedding vector must not be all zero")
    return vector


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        return -1.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    if denominator == 0:
        return -1.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / denominator


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()
