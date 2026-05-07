from __future__ import annotations

import unittest

from agent_factory.prompts import CaptureIntentOutput, PromptId, get_prompt, output_json_schema


class PromptTest(unittest.TestCase):
    def test_capture_intent_prompt_has_json_schema(self) -> None:
        prompt = get_prompt(PromptId.CAPTURE_REQUIREMENT_INTENT)
        prompt_value = prompt.invoke(
            {
                "user_input": "创建一个记账 Agent",
                "output_json_schema": output_json_schema(CaptureIntentOutput),
            }
        )
        messages = prompt_value.to_messages()
        joined = "\n".join(message.content for message in messages)

        self.assertIn("JSON", joined)
        self.assertIn("Output JSON schema", joined)
        self.assertIn("manufacture_agent", joined)
        self.assertNotIn("Output JSON example", joined)

    def test_capture_intent_output_uses_pydantic_validation(self) -> None:
        output = CaptureIntentOutput.model_validate(
            {
                "intent": "manufacture_agent",
                "confidence": 0.95,
                "reason": "用户明确要求创建 Agent",
                "extracted_requirement": "创建一个记账 Agent",
                "reply_hint": None,
                "entry_stage": "capture_requirement",
                "should_run_graph": True,
            }
        )

        self.assertIsInstance(output, CaptureIntentOutput)
        self.assertEqual(output.intent, "manufacture_agent")


if __name__ == "__main__":
    unittest.main()
