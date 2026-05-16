from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from agent_factory.tooling import ToolCompiler, ToolRegistry, ToolSpec, compile_json_schema
from agent_factory.tooling.entrypoint import ToolEntrypointError, ToolEntrypointLoader
from agent_factory.tooling.gateway import ToolApprovalDecision, ToolExecutionGateway


try:
    import jsonschema  # noqa: F401

    JSONSCHEMA_AVAILABLE = True
except ModuleNotFoundError:
    JSONSCHEMA_AVAILABLE = False


class ToolSpecTest(unittest.TestCase):
    def test_tool_spec_requires_snake_case_and_forbids_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ToolSpec(
                id="BadTool",
                description="bad",
                entrypoint="tools/bad/tool.py:run",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                resources={},
                approval_required=False,
                concurrent=True,
            )
        with self.assertRaises(ValidationError):
            ToolSpec(
                id="good_tool",
                description="bad",
                entrypoint="tools/good_tool/tool.py:run",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                resources={},
                approval_required=False,
                concurrent=True,
                extra=True,
            )


@unittest.skipUnless(JSONSCHEMA_AVAILABLE, "jsonschema dependency is not installed")
class SchemaCompilerTest(unittest.TestCase):
    def test_compiles_nested_schema_and_reports_validation_errors(self) -> None:
        compiled = compile_json_schema(
            model_name="NestedArgs",
            schema={
                "type": "object",
                "properties": {
                    "mode": {"enum": ["read", "write"]},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["mode", "items"],
                "additionalProperties": False,
            },
        )
        self.assertEqual(compiled.errors_for({"mode": "read", "items": [{"name": "a"}]}), [])
        self.assertTrue(compiled.errors_for({"mode": "delete", "items": [{}]}))


class EntrypointLoaderTest(unittest.TestCase):
    def test_package_relative_entrypoint_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_tool = root / "tools" / "sample" / "tool.py"
            package_tool.parent.mkdir(parents=True)
            package_tool.write_text(
                "def run(arguments: dict, resources: dict) -> dict:\n"
                "    return {'source': 'package', 'arguments': arguments, 'resources': resources}\n",
                encoding="utf-8",
            )
            loader = ToolEntrypointLoader(package_root=root)
            entrypoint = loader.load("tools/sample/tool.py:run")

        self.assertEqual(entrypoint({"x": 1}, {"r": 2})["source"], "package")

    def test_rejects_invalid_entrypoint_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_tool = root / "tools" / "bad" / "tool.py"
            package_tool.parent.mkdir(parents=True)
            package_tool.write_text("def run(value):\n    return {}\n", encoding="utf-8")
            loader = ToolEntrypointLoader(package_root=root)

            with self.assertRaises(ToolEntrypointError):
                loader.load("tools/bad/tool.py:run")


@unittest.skipUnless(JSONSCHEMA_AVAILABLE, "jsonschema dependency is not installed")
class GatewayAndCompilerTest(unittest.TestCase):
    def test_gateway_returns_observation_for_validation_and_approval_paths(self) -> None:
        spec = _tool_spec(approval_required=True)
        input_schema = compile_json_schema(schema=spec.input_schema, model_name="GatewayArgs")
        output_schema = compile_json_schema(schema=spec.output_schema, model_name="GatewayOutput")
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=input_schema,
            output_schema=output_schema,
            entrypoint=lambda arguments, resources: {"ok": True},
            global_resources={},
            approval_handler=lambda _spec, _args: ToolApprovalDecision(
                action="revise",
                revision_guidance="change the argument",
            ),
        )

        invalid = gateway.execute({}, tool_call_id="call_1")
        self.assertEqual(invalid["status"], "invalid_arguments")
        revised = gateway.execute({"query": "hello"}, tool_call_id="call_2")
        self.assertEqual(revised["status"], "revision_requested")
        self.assertIn("change the argument", revised["user_instruction"])
        exceeded = gateway.execute({"query": "hello"}, tool_call_id="call_3", revision_count=5)
        self.assertEqual(exceeded["status"], "execution_failed")
        self.assertFalse(exceeded["retryable"])

    def test_registry_and_compiler_produce_langchain_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_tool = root / "tools" / "sample_tool" / "tool.py"
            package_tool.parent.mkdir(parents=True)
            package_tool.write_text(
                "def run(arguments: dict, resources: dict) -> dict:\n"
                "    return {'ok': True, 'query': arguments['query']}\n",
                encoding="utf-8",
            )
            spec = _tool_spec(entrypoint="tools/sample_tool/tool.py:run")
            registry = ToolRegistry([spec])
            compiler = ToolCompiler(package_root=root)
            tools = compiler.compile_many(registry.all())

        self.assertEqual(registry.ids(), ["sample_tool"])
        self.assertEqual(tools[0].name, "sample_tool")
        result = tools[0].invoke({"query": "hello"})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"]["query"], "hello")


def _tool_spec(*, approval_required: bool = False, entrypoint: str = "tools/sample_tool/tool.py:run") -> ToolSpec:
    return ToolSpec(
        id="sample_tool",
        description="Sample tool.",
        entrypoint=entrypoint,
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "query": {"type": "string"}},
            "required": ["ok"],
            "additionalProperties": True,
        },
        resources={},
        approval_required=approval_required,
        concurrent=True,
    )


if __name__ == "__main__":
    unittest.main()
