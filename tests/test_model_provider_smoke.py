from __future__ import annotations

import asyncio
import os
import unittest

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
            self.assertIn("ok", response.content.lower())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

