from __future__ import annotations

import unittest

from agent_factory.tooling import compile_json_schema, get_factory_base_tool_ids, get_factory_protected_tool_ids
from agent_factory.tooling.builtins import get_builtin_tool_specs
from agent_factory.tooling.entrypoint import ToolEntrypointLoader


EXPECTED_TOOL_IDS = [
    "read",
    "write",
    "edit",
    "multi_edit",
    "glob",
    "grep",
    "ls",
    "bash",
    "bash_status",
    "bash_stop",
    "scheduler",
    "knowledge",
]

PROTECTED_TOOL_IDS = ["write", "edit", "multi_edit", "bash", "bash_stop", "scheduler", "knowledge"]


class BuiltinToolSpecTest(unittest.TestCase):
    def test_builtin_tool_specs_are_grouped_and_registered(self) -> None:
        specs = get_builtin_tool_specs()

        self.assertEqual([spec.id for spec in specs], EXPECTED_TOOL_IDS)
        self.assertEqual(get_factory_base_tool_ids(), EXPECTED_TOOL_IDS)
        self.assertEqual(get_factory_protected_tool_ids(), PROTECTED_TOOL_IDS)

    def test_builtin_tool_schemas_compile(self) -> None:
        for spec in get_builtin_tool_specs():
            with self.subTest(tool_id=spec.id):
                compile_json_schema(schema=spec.input_schema, model_name=f"{spec.id}_input")
                compile_json_schema(schema=spec.output_schema, model_name=f"{spec.id}_output")

    def test_registered_builtin_tool_entrypoints_are_loadable(self) -> None:
        loader = ToolEntrypointLoader()
        for spec in get_builtin_tool_specs():
            with self.subTest(tool_id=spec.id):
                entrypoint = loader.load(spec.entrypoint)
                self.assertTrue(callable(entrypoint))

    def test_builtin_tool_resources_follow_group_boundaries(self) -> None:
        resources = {spec.id: spec.resources for spec in get_builtin_tool_specs()}

        for tool_id in ["read", "write", "edit", "multi_edit", "glob", "grep", "ls"]:
            self.assertEqual(resources[tool_id], {"filesystem": "filesystem"})

        for tool_id in ["bash", "bash_status", "bash_stop"]:
            self.assertEqual(resources[tool_id], {"process_runtime": "process_runtime"})

        self.assertEqual(resources["scheduler"], {"scheduler_runtime": "scheduler_runtime"})
        self.assertEqual(resources["knowledge"], {"knowledge_runtime": "knowledge_runtime"})


if __name__ == "__main__":
    unittest.main()
