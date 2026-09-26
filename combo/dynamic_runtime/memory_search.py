from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
import logging
from math import isfinite, sqrt
from threading import RLock
from uuid import uuid4

from combo.dynamic_runtime.capability_search import CapabilityEmbeddingRuntime
from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.context_system.hybrid_retrieval import (
    RankedRetrievalCandidate, RetrievalChannelEvidence, fuse_hybrid_rankings,
    lexical_coverage, lexical_tokens,
)
from combo.runtime_protocol import MemoryRevision, MemoryScope


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RankedMemory:
    revision: MemoryRevision
    score: float
    relevance: float
    evidence: tuple[RetrievalChannelEvidence, ...]


class HybridMemorySearchIndex:
    """Versioned FTS index with atomic, optional semantic promotion."""

    def __init__(self, database: DynamicRuntimeDatabase, embedding_runtime=None) -> None:
        self._database = database
        self._embedding_runtime = embedding_runtime
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="memory-embedding") if embedding_runtime else None
        self._lock = RLock()
        self._future: Future[None] | None = None
        self._pending_refresh = False
        self._closed = False

    def version(self, *, principal_id: str, workspace_id: str) -> str:
        runtime = self._resolve_runtime()
        with self._database.connection(query_only=True) as conn:
            conn.execute("begin")
            heads = conn.execute(
                "select memory_id, revision, status from memory_heads where principal_id=? "
                "and (scope='user' or workspace_id=?) order by memory_id",
                (principal_id, workspace_id),
            ).fetchall()
            active = self._active(conn)
        return _digest({
            "heads": [tuple(row) for row in heads],
            "index": dict(active) if active else None,
            "embedding": runtime.fingerprint if runtime else None,
        })

    def refresh(self) -> None:
        with self._lock:
            if self._closed:
                return
            runtime = self._resolve_runtime()
            fingerprint = runtime.fingerprint if runtime else None
            reusable: dict[str, tuple[float, ...]] = {}
            with self._database.transaction() as conn:
                documents = self._documents(conn)
                digest = _dataset_digest(documents)
                active = self._active(conn)
                if active and active["embedding_fingerprint"] == fingerprint and fingerprint:
                    reusable = {
                        str(row["content_digest"]): tuple(json.loads(row["embedding_json"]))
                        for row in conn.execute(
                            "select content_digest, embedding_json from memory_search_documents "
                            "where generation_id=? and embedding_json is not null", (active["generation_id"],),
                        ).fetchall()
                    }
                if active is None or active["dataset_digest"] != digest:
                    generation_id = uuid4().hex
                    conn.execute(
                        "insert into memory_search_generations(generation_id,dataset_digest,search_mode,status,created_at) "
                        "values (?,?,'lexical','building',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                        (generation_id, digest),
                    )
                    self._insert_documents(conn, generation_id, documents)
                    self._activate(conn, generation_id)
                    active = self._active(conn)
                self._prune(conn)
                if not runtime or not documents or self._executor is None:
                    return
                if active["search_mode"] == "hybrid" and active["embedding_fingerprint"] == fingerprint:
                    return
                if self._future is not None:
                    self._pending_refresh = True
                    return
            self._future = self._executor.submit(self._build_hybrid, documents, digest, runtime, reusable)
            self._future.add_done_callback(self._after_build)

    def search(
        self, *, principal_id: str, workspace_id: str, query: str, limit: int,
        min_relevance: float = 0.0, scope: MemoryScope | None = None,
        all_workspaces: bool = False,
    ) -> tuple[RankedMemory, ...]:
        if limit < 1 or not lexical_tokens(query):
            return ()
        self.refresh()
        # Read one SQLite snapshot. Index retirement cannot mix revisions or
        # delete vectors between the lexical and semantic reads of this search.
        with self._database.connection(query_only=True) as conn:
            conn.execute("begin")
            generation = self._active(conn)
            if generation is None:
                return ()
            generation_id = generation["generation_id"]
            if all_workspaces:
                scope_condition = "1 = 1"
                scope_parameters: tuple[str, ...] = ()
            elif scope == "user":
                scope_condition = "head.scope='user'"
                scope_parameters = ()
            elif scope == "workspace":
                scope_condition = "head.scope='workspace' and head.workspace_id=?"
                scope_parameters = (workspace_id,)
            else:
                scope_condition = "(head.scope='user' or head.workspace_id=?)"
                scope_parameters = (workspace_id,)
            rows = conn.execute(
                "select revision.payload_json, document.embedding_json "
                "from memory_search_documents document join memory_heads head "
                "on head.memory_id=document.memory_id and head.revision=document.memory_revision "
                "join memory_revisions revision on revision.memory_id=head.memory_id and revision.revision=head.revision "
                "where document.generation_id=? and head.status='active' and head.principal_id=? "
                f"and {scope_condition}",
                (generation_id, principal_id, *scope_parameters),
            ).fetchall()
            allowed = {}
            vectors = {}
            for row in rows:
                revision = MemoryRevision.model_validate_json(str(row["payload_json"]))
                allowed[revision.memory_id] = revision
                if row["embedding_json"]:
                    vectors[revision.memory_id] = json.loads(row["embedding_json"])
            expression = " OR ".join(f'"{token}"' for token in lexical_tokens(query))
            matches = conn.execute(
                "select memory_id, bm25(memory_search_fts) rank from memory_search_fts "
                "where memory_search_fts match ? and generation_id=? order by rank,memory_id",
                (expression, generation_id),
            ).fetchall()
        lexical = tuple(
            RankedRetrievalCandidate(memory_id, strength)
            for row in matches
            if (memory_id := str(row["memory_id"])) in allowed
            if (strength := lexical_coverage(query, allowed[memory_id].content)) > 0
            and strength >= min_relevance
        )
        semantic = self._semantic(query, vectors, generation, min_relevance)
        fused = fuse_hybrid_rankings({"lexical": lexical, "semantic": semantic})[:limit]
        return tuple(RankedMemory(
            revision=allowed[item.item_id], score=item.fusion_score,
            relevance=max(e.evidence_strength for e in item.evidence), evidence=item.evidence,
        ) for item in fused)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending_refresh = False
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)

    def _resolve_runtime(self) -> CapabilityEmbeddingRuntime | None:
        try:
            return self._embedding_runtime() if self._embedding_runtime else None
        except Exception:
            logger.exception("memory embedding runtime resolution failed; using lexical retrieval")
            return None

    @staticmethod
    def _documents(conn) -> tuple[MemoryRevision, ...]:
        rows = conn.execute(
            "select revision.payload_json from memory_heads head join memory_revisions revision "
            "on revision.memory_id=head.memory_id and revision.revision=head.revision "
            "where head.status='active' order by head.memory_id"
        ).fetchall()
        return tuple(MemoryRevision.model_validate_json(str(row["payload_json"])) for row in rows)

    @staticmethod
    def _active(conn):
        return conn.execute(
            "select generation.generation_id, generation.dataset_digest, generation.search_mode, "
            "generation.embedding_fingerprint from memory_search_active_generation active "
            "join memory_search_generations generation on generation.generation_id=active.generation_id "
            "where active.singleton=1 and generation.status='active'"
        ).fetchone()

    @staticmethod
    def _activate(conn, generation_id: str) -> None:
        conn.execute("update memory_search_generations set status='retired' where status='active'")
        conn.execute(
            "update memory_search_generations set status='active',activated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') where generation_id=?",
            (generation_id,),
        )
        conn.execute(
            "insert into memory_search_active_generation(singleton,generation_id,changed_at) "
            "values (1,?,strftime('%Y-%m-%dT%H:%M:%fZ','now')) on conflict(singleton) do update "
            "set generation_id=excluded.generation_id,changed_at=excluded.changed_at", (generation_id,),
        )

    @staticmethod
    def _prune(conn) -> None:
        # Generation construction and promotion share one transaction, so any
        # committed non-active rows are obsolete, including interrupted legacy builds.
        conn.execute("delete from memory_search_fts where generation_id not in "
                     "(select generation_id from memory_search_generations where status='active')")
        conn.execute("delete from memory_search_generations where status!='active'")

    def _build_hybrid(self, documents, digest, runtime, reusable) -> None:
        generation_id = uuid4().hex
        try:
            vectors = [reusable.get(item.content_digest) for item in documents]
            pending = [index for index, vector in enumerate(vectors) if vector is None]
            embedded = runtime.embed_documents([documents[index].content for index in pending]) if pending else []
            if len(embedded) != len(pending):
                raise RuntimeError("embedding result count differs from memory document count")
            for index, vector in zip(pending, embedded, strict=True):
                vectors[index] = _validated_vector(vector, runtime.dimensions)
        except Exception as exc:
            logger.exception("memory document embedding failed; keeping lexical index")
            with self._database.transaction() as conn:
                conn.execute(
                    "update memory_search_generations set diagnostic=? where status='active' and dataset_digest=?",
                    (f"{type(exc).__name__}: {exc}", digest),
                )
            return
        with self._lock:
            current_runtime = self._resolve_runtime()
            if self._closed or current_runtime is None or current_runtime.fingerprint != runtime.fingerprint:
                return
            with self._database.transaction() as conn:
                if _dataset_digest(self._documents(conn)) != digest:
                    self._pending_refresh = True
                    return
                active = self._active(conn)
                if active and active["dataset_digest"] == digest and active["embedding_fingerprint"] == runtime.fingerprint:
                    return
                self._prune(conn)
                conn.execute(
                    "insert into memory_search_generations(generation_id,dataset_digest,search_mode,"
                    "embedding_fingerprint,embedding_profile_id,embedding_dimensions,status,created_at) "
                    "values (?,?,'hybrid',?,?,?,'building',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                    (generation_id, digest, runtime.fingerprint, runtime.profile_id, runtime.dimensions),
                )
                self._insert_documents(conn, generation_id, documents, vectors)
                self._activate(conn, generation_id)
                self._prune(conn)

    def _after_build(self, future: Future[None]) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("memory index update failed")
        with self._lock:
            pending = self._pending_refresh and not self._closed
            self._pending_refresh = False
            self._future = None
        if pending:
            self.refresh()

    @staticmethod
    def _insert_documents(conn, generation_id, documents, vectors=None) -> None:
        for index, revision in enumerate(documents):
            searchable = " ".join(lexical_tokens(revision.content))
            vector = None if vectors is None else json.dumps(vectors[index], separators=(",", ":"))
            conn.execute(
                "insert into memory_search_documents(generation_id,memory_id,memory_revision,principal_id,scope,"
                "workspace_id,content_digest,searchable_text,embedding_json) values (?,?,?,?,?,?,?,?,?)",
                (generation_id, revision.memory_id, revision.revision, revision.principal_id, revision.scope,
                 revision.workspace_id, revision.content_digest, searchable, vector),
            )
            conn.execute("insert into memory_search_fts(generation_id,memory_id,searchable_text) values (?,?,?)",
                         (generation_id, revision.memory_id, searchable))

    def _semantic(self, query, vectors, generation, minimum) -> tuple[RankedRetrievalCandidate, ...]:
        runtime = self._resolve_runtime()
        if not vectors or runtime is None or generation["embedding_fingerprint"] != runtime.fingerprint:
            return ()
        try:
            query_vector = _validated_vector(runtime.embed_query(query), runtime.dimensions)
        except Exception:
            logger.exception("memory query embedding failed; using lexical ranking")
            return ()
        scored = [(memory_id, _cosine(query_vector, _validated_vector(vector, runtime.dimensions)))
                  for memory_id, vector in vectors.items()]
        return tuple(RankedRetrievalCandidate(memory_id, similarity)
                     for memory_id, similarity in sorted(scored, key=lambda item: (-item[1], item[0]))
                     if similarity > 0 and similarity >= minimum)


def _digest(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _dataset_digest(documents) -> str:
    return _digest([(item.memory_id, item.revision, item.content_digest) for item in documents])


def _validated_vector(values, dimensions: int) -> tuple[float, ...]:
    vector = tuple(float(value) for value in values)
    if len(vector) != dimensions or not all(isfinite(value) for value in vector) or not any(vector):
        raise ValueError("invalid embedding vector")
    return vector


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    denominator = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    return 0.0 if denominator == 0 else max(-1.0, min(1.0, sum(a*b for a,b in zip(left,right)) / denominator))
