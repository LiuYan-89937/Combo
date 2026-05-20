from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from agent_factory.tooling import ToolCompiler, ToolRegistry, ToolRiskEvaluatorConfig, ToolSpec, compile_json_schema
from agent_factory.tooling.builtins.filesystem.specs import get_filesystem_tool_specs
from agent_factory.tooling.builtins.network.specs import get_network_tool_specs
from agent_factory.tooling.builtins.process.specs import get_process_tool_specs
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

        self.assertEqual(
            entrypoint({"path": "README.md"}, {}),
            {"tool": "read_file", "arguments": {"path": "README.md"}},
        )


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

    def test_gateway_separates_runtime_resources_from_risk_context(self) -> None:
        runtime_resource = _RuntimeOnlyResource()
        risk_contexts = []
        entrypoint_resources = []

        def risk_evaluator(_arguments: dict, context: dict) -> dict:
            risk_contexts.append(context)
            return {"action": "allow", "risk_level": "medium"}

        def entrypoint(arguments: dict, resources: dict) -> dict:
            entrypoint_resources.append(resources)
            return {"ok": True, "query": arguments["query"]}

        spec = _tool_spec(
            risk_level="medium",
            resources={"runtime": "runtime_service"},
            risk_evaluator=ToolRiskEvaluatorConfig(),
        )
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=compile_json_schema(schema=spec.input_schema, model_name="RuntimeResourceArgs"),
            output_schema=compile_json_schema(schema=spec.output_schema, model_name="RuntimeResourceOutput"),
            entrypoint=entrypoint,
            global_resources={"runtime_service": runtime_resource},
            hard_risk_evaluator=risk_evaluator,
        )

        result = gateway.execute({"query": "hello"}, tool_call_id="call_resource")

        self.assertEqual(result["status"], "completed")
        self.assertIs(entrypoint_resources[0]["runtime"], runtime_resource)
        self.assertEqual(
            risk_contexts[0]["resources"]["runtime"],
            {"kind": "runtime_object", "type": f"{__name__}._RuntimeOnlyResource"},
        )

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

    def test_builtin_tool_optional_arguments_are_not_sent_as_null(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_tool = root / "tools" / "argument_echo" / "tool.py"
            package_tool.parent.mkdir(parents=True)
            package_tool.write_text(
                "def run(arguments: dict, resources: dict) -> dict:\n"
                "    return {'arguments': arguments}\n",
                encoding="utf-8",
            )
            compiler = ToolCompiler(package_root=root)
            for spec in _builtin_catalog_specs():
                with self.subTest(tool_id=spec.id):
                    tool = compiler.compile(_echo_spec_for_input_schema(spec))
                    result = tool.invoke(_minimal_arguments_for_tool(spec.id))

                self.assertEqual(result["status"], "completed")
                self.assertFalse(_contains_unexpected_none(result["output"]["arguments"], spec.input_schema))


def _tool_spec(
    *,
    risk_level: str = "low",
    entrypoint: str = "tools/sample_tool/tool.py:run",
    resources: dict[str, str] | None = None,
    risk_evaluator: ToolRiskEvaluatorConfig | None = None,
) -> ToolSpec:
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
        resources=resources or {},
        risk_level=risk_level,
        risk_evaluator=risk_evaluator or ToolRiskEvaluatorConfig(),
        concurrent=True,
    )


class _RuntimeOnlyResource:
    pass


def _builtin_catalog_specs() -> list[ToolSpec]:
    return [
        *get_filesystem_tool_specs(),
        *get_process_tool_specs(),
        *get_network_tool_specs(),
    ]


def _echo_spec_for_input_schema(spec: ToolSpec) -> ToolSpec:
    return spec.model_copy(
        deep=True,
        update={
            "entrypoint": "tools/argument_echo/tool.py:run",
            "output_schema": {
                "type": "object",
                "properties": {"arguments": {"type": "object", "additionalProperties": True}},
                "required": ["arguments"],
                "additionalProperties": False,
            },
            "resources": {},
            "risk_level": "low",
            "risk_evaluator": ToolRiskEvaluatorConfig(),
        },
    )


def _minimal_arguments_for_tool(tool_id: str) -> dict:
    values = {
        "read": {"path": "README.md"},
        "write": {"path": "tmp.txt", "content": "hello"},
        "edit": {"path": "tmp.txt", "old_text": "old", "new_text": "new"},
        "multi_edit": {"path": "tmp.txt", "edits": [{"old_text": "old", "new_text": "new"}]},
        "glob": {"pattern": "*.py"},
        "grep": {"pattern": "ToolSpec"},
        "ls": {"path": "."},
        "bash": {"command": "echo hello"},
        "bash_status": {"process_id": "proc_1"},
        "bash_stop": {"process_id": "proc_1"},
        "web_fetch": {"url": "https://example.com"},
        "web_search": {"query": "example"},
    }
    return values[tool_id]


def _contains_unexpected_none(value: object, schema: dict) -> bool:
    if not isinstance(value, dict) or not isinstance(schema, dict):
        return False
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return False
    required = set(schema.get("required") or [])
    for key, item in value.items():
        field_schema = properties.get(key)
        if not isinstance(field_schema, dict):
            continue
        if item is None and key not in required and not _schema_accepts_null(field_schema):
            return True
        if isinstance(item, dict) and _contains_unexpected_none(item, field_schema):
            return True
    return False


def _schema_accepts_null(schema: dict) -> bool:
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for keyword in ("anyOf", "oneOf"):
        options = schema.get(keyword)
        if isinstance(options, list) and any(
            isinstance(option, dict) and _schema_accepts_null(option) for option in options
        ):
            return True
    return False


if __name__ == "__main__":
    unittest.main()
