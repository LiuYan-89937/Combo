from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from math import sqrt
import re
from threading import Lock
from typing import Callable, Iterable
import unicodedata
from uuid import uuid4

from agent_factory.dynamic_runtime.capability_resolution_services import CapabilitySearchConfig
from agent_factory.dynamic_runtime.capability_resolver import CapabilitySearchMatch
from agent_factory.dynamic_runtime.capability_store import ActiveCapability
from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase


@dataclass(frozen=True, slots=True)
class CapabilitySearchDocumentProjection:
    capability_id: str
    index_revision_id: str
    kind: str
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
        candidates: tuple[ActiveCapability, ...],
    ) -> tuple[CapabilitySearchMatch, ...]:
        query = " ".join(str(value or "").strip() for value in requirements if str(value or "").strip())
        if not query:
            return ()
        documents = tuple(_project_document(item) for item in candidates)
        generation = self._ensure_lexical_generation(documents)
        self._schedule_embedding_generation(generation[1], documents)
        candidate_ids = frozenset(item.capability_id for item in documents)
        lexical = self._lexical_ranking(generation[0], query, candidate_ids)
        vector: tuple[str, ...] = ()
        mode = generation[2]
        if mode == "hybrid":
            vector = self._vector_ranking(generation[0], query, candidate_ids)
        ranked = _fuse_rankings(
            lexical=lexical,
            vector=vector,
            documents={item.capability_id: item for item in documents},
            query=query,
            config=self._config,
        )
        filtered = tuple(
            (capability_id, score)
            for capability_id, score in ranked
            if score >= self._config.minimum_score
        )[: self._config.maximum_results]
        receipt_id = self._record_receipt(
            generation_id=generation[0],
            query=query,
            candidate_ids=candidate_ids,
            results=filtered,
        )
        return tuple(
            CapabilitySearchMatch(
                capability_id=capability_id,
                score=score,
                reason=f"matched {mode} capability search generation {generation[0]}",
                evidence_id=f"capability-search-receipt:{receipt_id}",
            )
            for capability_id, score in filtered
        )

    def refresh(self, candidates: tuple[ActiveCapability, ...]) -> None:
        documents = tuple(_project_document(item) for item in candidates)
        _, dataset_digest, _ = self._ensure_lexical_generation(documents)
        self._schedule_embedding_generation(dataset_digest, documents)

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
        candidate_ids: frozenset[str],
    ) -> tuple[str, ...]:
        tokens = _lexical_tokens(query)
        if not tokens:
            return ()
        expression = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select capability_id, bm25(capability_search_fts) as rank
                from capability_search_fts
                where capability_search_fts match ? and generation_id = ?
                order by rank, capability_id
                """,
                (expression, generation_id),
            ).fetchall()
        return tuple(str(row["capability_id"]) for row in rows if str(row["capability_id"]) in candidate_ids)

    def _vector_ranking(
        self,
        generation_id: str,
        query: str,
        candidate_ids: frozenset[str],
    ) -> tuple[str, ...]:
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
                    """,
                    (generation_id,),
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
        return tuple(capability_id for _, capability_id in scored)

    def _record_receipt(
        self,
        *,
        generation_id: str,
        query: str,
        candidate_ids: frozenset[str],
        results: tuple[tuple[str, float], ...],
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
                    json.dumps(results, ensure_ascii=False, separators=(",", ":")),
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


def _project_document(capability: ActiveCapability) -> CapabilitySearchDocumentProjection:
    revision = capability.revision
    document = capability.index_revision.document
    parameter_text = _parameter_text(revision.content.definition)
    embedding_text = "\n".join(
        value for value in (
            document.display_name,
            document.description,
            " ".join(document.keywords),
            parameter_text,
        ) if value
    )
    return CapabilitySearchDocumentProjection(
        capability_id=revision.capability_id,
        index_revision_id=capability.index_revision.index_revision_id,
        kind=revision.kind,
        display_name=document.display_name,
        description=document.description,
        keywords=document.keywords,
        parameter_text=parameter_text,
        embedding_text=embedding_text,
        lexical_text=" ".join(_lexical_tokens(embedding_text)),
    )


def _parameter_text(definition: dict[str, object]) -> str:
    schema: object = definition.get("input_schema")
    if isinstance(schema, dict) and isinstance(schema.get("canonical_schema"), dict):
        schema = schema["canonical_schema"]
    if not isinstance(schema, dict):
        return ""
    values: list[str] = []

    def visit(node: object, path: str) -> None:
        if not isinstance(node, dict):
            return
        for key in ("title", "description"):
            value = str(node.get(key) or "").strip()
            if value:
                values.append(value)
        enum = node.get("enum")
        if isinstance(enum, list):
            values.extend(str(value) for value in enum if isinstance(value, (str, int, float, bool)))
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name, child in properties.items():
                child_path = f"{path}.{name}" if path else str(name)
                values.append(child_path)
                visit(child, child_path)
        items = node.get("items")
        if isinstance(items, dict):
            visit(items, f"{path}[]" if path else "items")
        for branch_name in ("oneOf", "anyOf", "allOf"):
            branches = node.get(branch_name)
            if isinstance(branches, list):
                for branch in branches:
                    visit(branch, path)

    visit(schema, "")
    return " ".join(dict.fromkeys(value for value in values if value))


def _insert_documents(conn: object, generation_id: str, documents: tuple[CapabilitySearchDocumentProjection, ...], *, embeddings: tuple[tuple[float, ...], ...] | None) -> None:
    for index, document in enumerate(documents):
        embedding_json = None if embeddings is None else json.dumps(embeddings[index], separators=(",", ":"))
        conn.execute(
            """
            insert into capability_search_documents(
              generation_id, capability_id, index_revision_id, kind, display_name,
              description, keywords_json, parameter_text, searchable_text, embedding_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                document.capability_id,
                document.index_revision_id,
                document.kind,
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
            "embedding_text": item.embedding_text,
        }
        for item in sorted(documents, key=lambda value: value.capability_id)
    ])


def _fuse_rankings(*, lexical: tuple[str, ...], vector: tuple[str, ...], documents: dict[str, CapabilitySearchDocumentProjection], query: str, config: CapabilitySearchConfig) -> tuple[tuple[str, float], ...]:
    configured = tuple(
        (ranking, weight)
        for ranking, weight in (
            (lexical, config.lexical_weight),
            (vector, config.vector_weight),
        )
        if ranking
    )
    if not configured:
        return ()
    scores: dict[str, float] = {}
    total_weight = sum(weight for _, weight in configured)
    normalizer = 1.0 / (config.reciprocal_rank_constant + 1)
    for ranking, configured_weight in configured:
        weight = configured_weight / total_weight
        for rank, capability_id in enumerate(ranking, start=1):
            reciprocal = 1.0 / (config.reciprocal_rank_constant + rank)
            scores[capability_id] = scores.get(capability_id, 0.0) + weight * (reciprocal / normalizer)
    normalized_query = _normalize(query)
    for capability_id, document in documents.items():
        if capability_id not in scores:
            continue
        if normalized_query in {_normalize(document.display_name), _normalize(capability_id)}:
            scores[capability_id] = min(1.0, scores[capability_id] + config.exact_match_bonus)
    return tuple(sorted(scores.items(), key=lambda item: (-item[1], item[0])))


def _lexical_tokens(value: str) -> tuple[str, ...]:
    normalized = _normalize(value)
    tokens: list[str] = []
    for segment in re.findall(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff]+", normalized):
        if re.fullmatch(r"[\u3400-\u4dbf\u4e00-\u9fff]+", segment):
            tokens.extend(segment[index:index + 2] for index in range(max(1, len(segment) - 1)))
        else:
            tokens.append(segment)
    return tuple(dict.fromkeys(tokens))


def _normalize(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(r"[_./:\\-]+", " ", normalized)
    return " ".join(normalized.split())


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
