from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from langgraph.store.memory import InMemoryStore

from agent_factory.knowledge_system import (
    KnowledgeCatalog,
    KnowledgeContractConfig,
    KnowledgeIngestionPlan,
    KnowledgeRuntime,
)
from agent_factory.knowledge_system.schema import KnowledgeSplitterRule


class KnowledgeSystemTest(unittest.TestCase):
    def test_index_only_manual_note_writes_catalog_and_keyword_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = _runtime(Path(temp_dir), store=None)
            job = runtime.confirm_source(
                {
                    "source_type": "manual_note",
                    "source_id": "team_note",
                    "display_name": "Team note",
                    "mount_mode": "index_only",
                    "content": "用户偏好使用中文进行工程讨论。",
                }
            )

            completed = runtime.run_job(job.job_id)
            results = runtime.search(query="中文", source_id="team_note", mode="keyword")

            self.assertEqual(completed.status, "completed")
            self.assertEqual(len(runtime.list_sources()), 1)
            self.assertGreaterEqual(len(results), 1)
            self.assertIn("中文", results[0].content)

    def test_rag_manual_note_writes_base_store_and_hybrid_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = InMemoryStore()
            runtime = _runtime(Path(temp_dir), store=store)
            job = runtime.confirm_source(
                {
                    "source_type": "manual_note",
                    "source_id": "rag_note",
                    "display_name": "RAG note",
                    "mount_mode": "rag",
                    "content": "RuntimeKernel 通过 Contract 和 Builder 装配基础能力。",
                }
            )

            completed = runtime.run_job(job.job_id)
            results = runtime.search(query="Contract Builder", mode="hybrid", top_k=5)

            self.assertEqual(completed.status, "completed")
            self.assertGreaterEqual(completed.counts["chunks_embedded"], 1)
            self.assertTrue(any(item.source_id == "rag_note" for item in results))

    def test_prepare_supports_declared_source_types_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_dir = root / "docs"
            source_dir.mkdir()
            (source_dir / "README.md").write_text("# Docs\n\nFastAgentFactory knowledge.", encoding="utf-8")
            runtime = _runtime(root, store=None)

            previews = [
                runtime.prepare_source({"source_type": "filesystem", "source_id": "local_docs", "path": str(source_dir)}),
                runtime.prepare_source({"source_type": "codebase", "source_id": "local_code", "path": str(source_dir)}),
                runtime.prepare_source({"source_type": "skill", "source_id": "local_skill", "path": str(source_dir)}),
                runtime.prepare_source({"source_type": "artifact_report", "source_id": "local_report", "path": str(source_dir)}),
                runtime.prepare_source({"source_type": "database", "source_id": "db_docs", "uri": "readonly://db", "metadata": {"description": "readonly schema"}}),
                runtime.prepare_source({"source_type": "mcp", "source_id": "mcp_docs", "uri": "mcp://server", "metadata": {"description": "managed mcp source"}}),
                runtime.prepare_source({"source_type": "manual_note", "source_id": "note_docs", "content": "manual note"}),
            ]

            self.assertEqual({preview.source_type for preview in previews}, {"filesystem", "codebase", "skill", "artifact_report", "database", "mcp", "manual_note"})
            self.assertIn("ingestion_plan", previews[0].metadata)
            self.assertEqual(runtime.list_sources(), [])

    def test_confirm_source_freezes_ingestion_plan_for_rag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = _runtime(root, store=InMemoryStore())
            plan = KnowledgeIngestionPlan(
                default_splitter="recursive",
                default_chunk_size=300,
                default_chunk_overlap=30,
                rules=[
                    KnowledgeSplitterRule(
                        match="markdown",
                        splitter="markdown",
                        chunk_size=420,
                        chunk_overlap=42,
                        reason="preserve markdown headings",
                    )
                ],
                rationale="test plan",
            )

            job = runtime.confirm_source(
                {
                    "source_type": "manual_note",
                    "source_id": "planned_note",
                    "display_name": "Planned note",
                    "mount_mode": "rag",
                    "content": "RuntimeKernel 通过 Contract 和 Builder 装配基础能力。",
                    "ingestion_plan": plan.model_dump(mode="json"),
                }
            )
            runtime.run_job(job.job_id)
            source = runtime.catalog.get_source("planned_note")

            self.assertIsNotNone(source)
            self.assertEqual(source.metadata["ingestion_plan"]["default_chunk_size"], 300)
            self.assertEqual(source.metadata["ingestion_plan"]["rules"][0]["splitter"], "markdown")

    def test_remove_source_deletes_catalog_and_keeps_external_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            external_file = root / "external.md"
            external_file.write_text("External source content.", encoding="utf-8")
            runtime = _runtime(root / "runtime", store=InMemoryStore())
            job = runtime.confirm_source(
                {
                    "source_type": "filesystem",
                    "source_id": "external_docs",
                    "display_name": "External docs",
                    "mount_mode": "rag",
                    "path": str(external_file),
                }
            )
            runtime.run_job(job.job_id)

            self.assertTrue(runtime.remove_source("external_docs"))

            self.assertTrue(external_file.exists())
            self.assertEqual(runtime.list_sources(), [])
            self.assertEqual(runtime.search(query="External", mode="hybrid"), [])


def _runtime(root: Path, *, store) -> KnowledgeRuntime:
    config = KnowledgeContractConfig(
        root=str(root / "knowledge"),
        catalog_path=str(root / "knowledge" / "catalog" / "knowledge.sqlite"),
        rag_store={
            "backend": "memory",
            "path": str(root / "knowledge" / "catalog" / "knowledge_store.sqlite"),
            "namespace_prefix": ["knowledge"],
            "index_fields": ["content", "title", "summary"],
        },
    )
    return KnowledgeRuntime(
        config=config,
        owner_type="agent",
        owner_id="test_agent",
        catalog=KnowledgeCatalog(config.catalog_path),
        store=store,
    )


if __name__ == "__main__":
    unittest.main()
