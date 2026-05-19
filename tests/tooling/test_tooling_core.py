from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from agent_factory.tooling import ToolCompiler, ToolRegistry, ToolRiskEvaluatorConfig, ToolSpec, compile_json_schema
from agent_factory.tooling.entrypoint import ToolEntrypointError, ToolEntrypointLoader
from agent_factory.tooling.gateway import ToolApprovalDecision, ToolExecutionGateway
from agent_factory.tooling.langgraph_node import build_tool_node_runner


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
                risk_level="low",
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
                risk_level="low",
                concurrent=True,
                extra=True,
            )

    def test_tool_spec_accepts_protocol_entrypoints(self) -> None:
        for entrypoint in [
            "python:tools/sample/tool.py:run",
            "python-import:agent_factory.tooling.builtins.filesystem.read:run",
            "mcp:filesystem/read_file",
        ]:
            with self.subTest(entrypoint=entrypoint):
                self.assertEqual(_tool_spec(entrypoint=entrypoint).entrypoint, entrypoint)

        with self.assertRaises(ValidationError):
            _tool_spec(entrypoint="mcp:filesystem")


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

    def test_protocol_package_entrypoint_and_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_tool = root / "tools" / "sample" / "tool.py"
            package_tool.parent.mkdir(parents=True)
            package_tool.write_text(
                "def run(arguments: dict, resources: dict) -> dict:\n"
                "    return {'source': 'protocol', 'arguments': arguments}\n",
                encoding="utf-8",
            )
            loader = ToolEntrypointLoader(package_root=root)
            relative = loader.load("python:tools/sample/tool.py:run")
            absolute = ToolEntrypointLoader(allowed_python_roots=[root]).load(f"python:{package_tool}:run")

        self.assertEqual(relative({"x": 1}, {})["source"], "protocol")
        self.assertEqual(absolute({"x": 1}, {})["source"], "protocol")

    def test_mcp_entrypoint_uses_configured_client(self) -> None:
        class FakeMCPClient:
            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                return {"tool": tool_name, "arguments": arguments}

        loader = ToolEntrypointLoader(mcp_clients={"filesystem": FakeMCPClient()})
        entrypoint = loader.load("mcp:filesystem/read_file")

        self.assertEqual(entrypoint({"path": "README.md"}, {}), {"tool": "read_file", "arguments": {"path": "README.md"}})


@unittest.skipUnless(JSONSCHEMA_AVAILABLE, "jsonschema dependency is not installed")
class GatewayAndCompilerTest(unittest.TestCase):
    def test_gateway_returns_observation_for_validation_and_approval_paths(self) -> None:
        spec = _tool_spec(risk_level="medium")
        input_schema = compile_json_schema(schema=spec.input_schema, model_name="GatewayArgs")
        output_schema = compile_json_schema(schema=spec.output_schema, model_name="GatewayOutput")
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=input_schema,
            output_schema=output_schema,
            entrypoint=lambda arguments, resources: {"ok": True},
            global_resources={},
            approval_handler=lambda _spec, _args, _risk: ToolApprovalDecision(
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

    def test_langgraph_tool_node_adapter_preserves_tool_call_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_tool = root / "tools" / "sample_tool" / "tool.py"
            package_tool.parent.mkdir(parents=True)
            package_tool.write_text(
                "def run(arguments: dict, resources: dict) -> dict:\n"
                "    return {'ok': True, 'query': arguments['query']}\n",
                encoding="utf-8",
            )
            compiler = ToolCompiler(package_root=root)
            tool = compiler.compile(_tool_spec(entrypoint="tools/sample_tool/tool.py:run"))

        runner = build_tool_node_runner([tool], node_id="tools")
        output = runner.invoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "sample_tool",
                                "args": {"query": "hello"},
                                "id": "call_sample",
                            }
                        ],
                    )
                ]
            }
        )

        message = output["messages"][0]
        self.assertEqual(message.tool_call_id, "call_sample")
        self.assertIn('"tool_call_id": "call_sample"', message.content)


def _tool_spec(*, risk_level: str = "low", entrypoint: str = "tools/sample_tool/tool.py:run") -> ToolSpec:
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
        risk_level=risk_level,
        risk_evaluator=ToolRiskEvaluatorConfig(),
        concurrent=True,
    )


if __name__ == "__main__":
    unittest.main()
