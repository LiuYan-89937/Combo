from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.model import LLMMessage, LLMRequest, ModelConfig, ModelConfigError, ModelService


@unittest.skipUnless(
    os.environ.get("AGENTFACTORY_RUN_PROVIDER_SMOKE") == "1",
    "real provider smoke test is opt-in",
)
class ProviderSmokeTests(unittest.TestCase):
    def test_real_provider_smoke(self) -> None:
        async def run() -> None:
            try:
                config = ModelConfig.from_env()
            except ModelConfigError as error:
                self.skipTest(str(error))
                return

            service = ModelService.from_env()
            response = await service.generate(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="user",
                            content="Reply with exactly: ok",
                        )
                    ],
                    max_output_tokens=min(config.max_output_tokens, 16),
                    temperature=0,
                )
            )
            self.assertTrue(response.ok, response.error)
            if not response.content.strip():
                self.skipTest("real provider returned empty content for minimal smoke prompt")
            self.assertIn("ok", response.content.lower())

        asyncio.run(run())

    def test_real_model_can_generate_agent_package_from_natural_language(self) -> None:
        try:
            ModelConfig.from_env()
        except ModelConfigError as error:
            self.skipTest(str(error))
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            result = CreateAgentService(model_service=ModelService.from_env()).create_agent(
                CreateAgentRequest(
                    prompt="创建一个简洁的资料问答 Agent，只需要根据用户提供的资料回答问题，缺少资料时说明缺口。",
                    start_path=Path(tmpdir),
                    stream=False,
                )
            )

            self.assertTrue(result.implemented, result.error)
            self.assertIsNotNone(result.output_path)
            self.assertTrue((result.output_path / "package.yaml").exists())
            self.assertIn("generate_package_specs", result.stage_history)

    def test_real_model_complex_resource_agent_identifies_local_sqlite(self) -> None:
        try:
            ModelConfig.from_env()
        except ModelConfigError as error:
            self.skipTest(str(error))
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "orders.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, status TEXT)")
                conn.execute("INSERT INTO orders VALUES ('A-001', 'paid')")
            result = CreateAgentService(model_service=ModelService.from_env()).create_agent(
                CreateAgentRequest(
                    prompt=(
                        "创建一个订单查询 Agent，必须使用这个本地 SQLite 数据库回答订单状态；"
                        f"数据库路径是 {db_path}，缺少表或字段时说明缺口。"
                    ),
                    start_path=root,
                    stream=False,
                )
            )

            self.assertTrue(result.implemented, result.error)
            self.assertIsNotNone(result.output_path)
            self.assertIsNotNone(result.readiness_decision)
            self.assertIn("plan_resource_needs", result.stage_history)
            resource_refs = "\n".join(
                str(ref)
                for envelope in result.context_envelopes
                for ref in envelope.get("decision_refs", [])
            )
            self.assertIn("ResourceNeedPlan", resource_refs)


if __name__ == "__main__":
    unittest.main()
