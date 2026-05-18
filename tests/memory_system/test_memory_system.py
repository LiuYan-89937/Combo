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
)
from agent_factory.memory_system.injection import MemorySystemRuntime, inject_runtime_cross_session_memory
from agent_factory.memory_system.intent import detect_memory_intent
from agent_factory.memory_system.retrieval import retrieve_memory_context
from agent_factory.memory_system.schema import (
    MemoryExtractionAction,
    MemoryExtractionDecision,
    MemoryIntentDecision,
    MemoryWriteJob,
    MemoryWriteReport,
)
from agent_factory.memory_system.writer import MemoryStoreWriter
from agent_factory.runtime_kernel.persistence import LangGraphStoreConfig, LangGraphStoreFactory, MemoryRecord
from agent_factory.runtime_kernel.state import RuntimeState


class MemorySystemTest(unittest.TestCase):
    def test_task_model_intent_detector_uses_structured_model(self) -> None:
        fake_model = _FakeTaskModel(
            MemoryIntentDecision(
                intent="explicit_remember",
                confidence=0.91,
                target_text="keep this preference",
                reason="user explicitly asked",
            )
        )

        decision = detect_memory_intent(
            messages_delta=[{"role": "user", "content": "please remember this"}],
            model=fake_model,
        )

        self.assertEqual(decision.intent, "explicit_remember")
        self.assertEqual(fake_model.output_model_names, ["MemoryIntentDecision"])

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

    def test_writer_add_update_delete_actions(self) -> None:
        store = LangGraphStoreFactory().build(LangGraphStoreConfig(backend="memory")).store
        job = _job("writer")
        add = MemoryExtractionDecision(
            status="complete",
            actions=[
                MemoryExtractionAction(
                    action="add",
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
        message_range={"turn_index": 1},
        messages_delta=[{"role": "user", "content": label}],
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


if __name__ == "__main__":
    unittest.main()
