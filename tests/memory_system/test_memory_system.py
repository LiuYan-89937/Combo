from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent_factory.memory_system.background import MemoryBackgroundWorker, MemoryJobJournal
from agent_factory.memory_system.config import (
    MemoryBackgroundConfig,
    MemoryRankingConfig,
    MemoryStoreRuntimeConfig,
    MemorySystemConfig,
    should_enqueue_memory_write,
)
from agent_factory.memory_system.extraction import extract_memory_actions
from agent_factory.memory_system.formatting import memory_context_text
from agent_factory.memory_system.injection import MemorySystemRuntime, inject_runtime_cross_session_memory
from agent_factory.memory_system.retrieval import retrieve_memory_context
from agent_factory.memory_system.schema import (
    MemoryContextPack,
    MemoryExtractionAction,
    MemoryExtractionDecision,
    MemoryWriteJob,
    MemoryWriteReport,
)
from agent_factory.memory_system.writer import MemoryStoreWriter
from langgraph.store.base import IndexConfig

from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory, MemoryRecord
from agent_factory.runtime_kernel.state import RuntimeState


class MemorySystemTest(unittest.TestCase):
    def test_task_model_extracts_actions_from_conversation_segment(self) -> None:
        fake_model = _FakeTaskModel(
            MemoryExtractionDecision(
                status="complete",
                actions=[
                    MemoryExtractionAction(
                        action="add",
                        memory_type="semantic",
                        kind="preference",
                        content="Prefer concise answers.",
                        confidence=0.9,
                    )
                ],
            )
        )

        decision = extract_memory_actions(
            segment=_segment("Prefer concise answers."),
            related_memories=MemoryContextPack(namespace=("memory", "agent", "agent_a"), query="concise"),
            model=fake_model,
        )

        self.assertEqual(decision.actions[0].memory_type, "semantic")
        self.assertEqual(fake_model.output_model_names, ["MemoryExtractionDecision"])

    def test_background_enqueue_is_nonblocking_and_queue_full_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
            worker = MemoryBackgroundWorker(
                store=store,
                config=MemorySystemConfig(
                    store=MemoryStoreRuntimeConfig(backend="memory", path=""),
                    background=MemoryBackgroundConfig(journal_root=str(Path(temp_dir) / "jobs"), max_pending_jobs=1),
                ),
            )
            first = worker.enqueue(_job("first"))
            second = worker.enqueue(_job("second"))

            self.assertEqual(first.status, "queued")
            self.assertEqual(second.status, "queued_failed")

    def test_write_interval_defaults_to_every_third_successful_turn(self) -> None:
        config = MemorySystemConfig()

        self.assertFalse(should_enqueue_memory_write(turn_index=1, config=config))
        self.assertFalse(should_enqueue_memory_write(turn_index=2, config=config))
        self.assertTrue(should_enqueue_memory_write(turn_index=3, config=config))
        self.assertFalse(should_enqueue_memory_write(turn_index=4, config=config))
        self.assertTrue(should_enqueue_memory_write(turn_index=6, config=config))

    def test_factory_memory_context_text_only_contains_useful_items(self) -> None:
        self.assertEqual(memory_context_text({"items": []}), "")

        text = memory_context_text(
            {
                "items": [
                    {"kind": "fact", "content": "用户名叫柳严"},
                    {"kind": "preference", "content": "用户喜欢吃布丁"},
                ]
            }
        )

        self.assertIn("- 用户名叫柳严", text)
        self.assertIn("- 用户喜欢吃布丁", text)
        self.assertNotIn("跨会话记忆", text)
        self.assertNotIn("[fact]", text)

    def test_job_journal_records_pending_completed_and_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = MemoryJobJournal(Path(temp_dir) / "jobs")
            job = _job("journal")
            journal.mark_pending(job)
            self.assertEqual(len(journal.pending_records()), 1)

            journal.mark_completed(MemoryWriteReport(job_id=job.job_id, status="completed", namespace=job.namespace))
            self.assertEqual(journal.pending_records(), [])

            failed = _job("failed")
            journal.mark_pending(failed)
            journal.mark_failed(failed.job_id, "boom")
            self.assertEqual(journal.pending_records(), [])

    def test_background_worker_processes_segment_without_explicit_intent_gate(self) -> None:
        store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
        fake_model = _FakeTaskModel(
            MemoryExtractionDecision(
                status="complete",
                actions=[
                    MemoryExtractionAction(
                        action="add",
                        memory_type="procedural",
                        kind="decision",
                        content="Use conversation segments for cross-session memory extraction.",
                        confidence=0.9,
                    )
                ],
            )
        )
        worker = MemoryBackgroundWorker(
            store=store,
            config=MemorySystemConfig(store=MemoryStoreRuntimeConfig(backend="memory", path="")),
            extraction_model=fake_model,
        )

        report = worker._process(_job("Segment extraction should use taskModel directly."))

        self.assertEqual(report.status, "completed")
        self.assertEqual(fake_model.output_model_names, ["MemoryExtractionDecision"])

    def test_writer_add_update_delete_actions(self) -> None:
        store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
        job = _job("writer")
        add = MemoryExtractionDecision(
            status="complete",
            actions=[
                MemoryExtractionAction(
                    action="add",
                    memory_type="semantic",
                    kind="preference",
                    content="Prefer concise answers.",
                    confidence=0.9,
                    importance=0.8,
                )
            ],
        )
        add_report = MemoryStoreWriter(store).apply(job=job, decision=add)
        added = store.search(job.namespace, query="concise")
        self.assertEqual(add_report.status, "completed")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].value["memory_type"], "semantic")

        memory_id = added[0].key
        update = MemoryExtractionDecision(
            status="complete",
            actions=[
                MemoryExtractionAction(
                    action="update",
                    kind="preference",
                    content="Prefer concise engineering answers.",
                    merge_target_id=memory_id,
                )
            ],
        )
        update_report = MemoryStoreWriter(store).apply(job=job, decision=update)
        self.assertEqual(update_report.status, "completed")
        self.assertIn("engineering", store.get(job.namespace, memory_id).value["content"])

        delete = MemoryExtractionDecision(
            status="complete",
            actions=[MemoryExtractionAction(action="delete", merge_target_id=memory_id)],
        )
        delete_report = MemoryStoreWriter(store).apply(job=job, decision=delete)
        self.assertEqual(delete_report.status, "completed")
        self.assertIsNone(store.get(job.namespace, memory_id))

    def test_retrieval_ranking_enforces_total_token_and_kind_limits(self) -> None:
        store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
        namespace = ("memory", "agent", "agent_a")
        for index in range(6):
            record = MemoryRecord(
                scope="agent",
                kind="preference",
                content=f"Prefer concise answer style {index}.",
                metadata={"importance": 1.0},
            )
            store.put(namespace, record.memory_id, record.model_dump(mode="json"))
        config = MemorySystemConfig(
            store=MemoryStoreRuntimeConfig(backend="memory", path=""),
            ranking=MemoryRankingConfig(
                max_items_total=8,
                max_tokens_total=1200,
                min_score=0.0,
                per_kind_limits={"preference": 3},
            ),
        )

        pack = retrieve_memory_context(store=store, namespace=namespace, query="concise", config=config)

        self.assertEqual(len(pack.items), 3)
        self.assertTrue(all(item.kind == "preference" for item in pack.items))

    def test_sqlite_store_uses_configured_embedding_index_for_semantic_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LangGraphStoreFactory().build(
                LangGraphStoreConfig(
                    backend="sqlite",
                    path=Path(temp_dir) / "memory.sqlite",
                    index=IndexConfig(embed=_FakeEmbeddings(), dims=3, fields=["content"]),
                )
            ).store
            namespace = ("memory", "factory", "default")
            record = MemoryRecord(
                scope="factory",
                kind="constraint",
                content="MySQL connections must use a sandbox-visible endpoint.",
                metadata={"importance": 1.0},
            )

            store.put(namespace, record.memory_id, record.model_dump(mode="json"))
            results = store.search(namespace, query="database access", limit=1)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].key, record.memory_id)
            self.assertIsNotNone(results[0].score)

    def test_retrieval_reports_semantic_index_failure_and_lexical_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = LangGraphStoreFactory().build(
                LangGraphStoreConfig(
                    backend="sqlite",
                    path=Path(temp_dir) / "memory.sqlite",
                    index=IndexConfig(embed=_FailingEmbeddings(), dims=3, fields=["content"]),
                )
            ).store
            namespace = ("memory", "factory", "default")
            record = MemoryRecord(
                scope="factory",
                kind="preference",
                content="用户喜欢吃布丁",
                metadata={"importance": 1.0},
            )

            store.put(namespace, record.memory_id, record.model_dump(mode="json"))
            pack = retrieve_memory_context(
                store=store,
                namespace=namespace,
                query="布丁",
                config=MemorySystemConfig(
                    store=MemoryStoreRuntimeConfig(backend="sqlite", path=""),
                    ranking=MemoryRankingConfig(min_score=0.0),
                ),
            )

            self.assertEqual(pack.report["semantic_status"], "semantic_failed")
            self.assertTrue(pack.report["lexical_fallback_used"])
            self.assertTrue(pack.items)
            reasons = {item.get("reason") for item in pack.report["semantic_diagnostics"]}
            self.assertIn("embedding_error", reasons)

    def test_injection_writes_model_context_not_messages(self) -> None:
        store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
        namespace = ("memory", "agent", "agent_a")
        record = MemoryRecord(scope="agent", kind="constraint", content="Never expose secrets.")
        store.put(namespace, record.memory_id, record.model_dump(mode="json"))
        runtime = MemorySystemRuntime(
            config=MemorySystemConfig(
                store=MemoryStoreRuntimeConfig(backend="memory", path=""),
                ranking=MemoryRankingConfig(min_score=0.0),
            ),
            store=store,
            scope="agent",
            namespace=namespace,
        )
        state = RuntimeState()
        state.conversation.current_user_input = "How should I answer?"

        updated, report = inject_runtime_cross_session_memory(state=state, runtime=runtime)

        self.assertEqual(report.status, "injected")
        self.assertIn("cross_session_memory", updated.context.model_context)
        self.assertEqual(state.context.model_context, {})


def _job(label: str) -> MemoryWriteJob:
    return MemoryWriteJob(
        scope="agent",
        namespace=("memory", "agent", "agent_a"),
        source={"session_id": "session_1", "thread_id": "thread_1", "run_id": label},
        segment=_segment(label),
    )


def _segment(label: str):
    from agent_factory.memory_system.schema import MemoryConversationMessage, MemoryConversationSegment

    return MemoryConversationSegment(
        scope="agent",
        namespace=("memory", "agent", "agent_a"),
        start_turn=1,
        end_turn=1,
        source={"session_id": "session_1", "thread_id": "thread_1", "run_id": label},
        messages=[
            MemoryConversationMessage(role="user", content=label, turn_index=1, message_index=0),
            MemoryConversationMessage(role="assistant", content="收到。", turn_index=1, message_index=1),
        ],
    )


class _FakeTaskModel:
    def __init__(self, result) -> None:
        self.result = result
        self.output_model_names: list[str] = []

    def with_structured_output(self, output_model, method: str):
        self.output_model_names.append(output_model.__name__)
        return _FakeStructured(self.result)


class _FakeStructured:
    def __init__(self, result) -> None:
        self.result = result

    def with_config(self, **_kwargs):
        return self

    def bind(self, **_kwargs):
        return self

    def invoke(self, _messages):
        return self.result


class _FakeEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        normalized = text.lower()
        if "mysql" in normalized or "database" in normalized:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


class _FailingEmbeddings:
    def embed_documents(self, _texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding service unavailable")

    def embed_query(self, _text: str) -> list[float]:
        raise RuntimeError("embedding service unavailable")


if __name__ == "__main__":
    unittest.main()
