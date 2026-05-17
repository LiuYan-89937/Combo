from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_factory.tooling import FactoryExtensionManager, get_factory_tool_specs, get_factory_tools


class FactoryExtensionTest(unittest.TestCase):
    def test_factory_extension_manager_discovers_skill_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill_extension(root)

            result, report = FactoryExtensionManager(extension_root=root).discover()

        self.assertEqual(report.tool_ids, ["factory_echo"])
        self.assertEqual(result.tool_specs[0].id, "factory_echo")

    def test_factory_tool_specs_merge_builtin_and_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill_extension(root)

            specs = get_factory_tool_specs(tool_ids=["factory_echo"], extension_root=root)
            without_extensions = get_factory_tool_specs(
                tool_ids=["factory_echo"],
                include_extensions=False,
                extension_root=root,
            )

        self.assertEqual([spec.id for spec in specs], ["factory_echo"])
        self.assertEqual(without_extensions, [])

    def test_stage_scoped_factory_tools_ignore_unselected_extension_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill_extension(root, tool_id="read", prefix=None)

            specs = get_factory_tool_specs(tool_ids=["ls"], extension_root=root)

        self.assertEqual([spec.id for spec in specs], ["ls"])

    def test_factory_tools_compile_skill_extension_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill_extension(root)

            tools = get_factory_tools(tool_ids=["factory_echo"], extension_root=root)
            result = tools[0].invoke({"text": "hello"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"], {"echo": "hello"})

    def test_factory_tools_compile_mcp_extension_tool(self) -> None:
        class FakeMCPClient:
            def list_tools(self) -> list[dict]:
                return [
                    {
                        "name": "echo",
                        "description": "Echo through MCP.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"echo": {"type": "string"}},
                            "required": ["echo"],
                            "additionalProperties": False,
                        },
                    }
                ]

            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                return {"echo": arguments["text"]}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "version": "mcp_servers.v0",
                        "servers": [
                            {
                                "server_id": "factory_mcp",
                                "transport": "stdio",
                                "tool_id_prefix": "factory_mcp",
                                "approval_default": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            tools = get_factory_tools(
                tool_ids=["factory_mcp_echo"],
                extension_root=root,
                mcp_catalog_clients={"factory_mcp": FakeMCPClient()},
                mcp_tool_clients={"factory_mcp": FakeMCPClient()},
            )
            result = tools[0].invoke({"text": "hello"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"], {"echo": "hello"})

    def test_factory_mcp_uses_runtime_manager_when_clients_are_not_injected(self) -> None:
        class FakeRuntimeManager:
            def __init__(self, config) -> None:
                self.config = config

            def clients(self) -> dict:
                return {"factory_mcp": FakeMCPClient()}

        class FakeMCPClient:
            def list_tools(self) -> list[dict]:
                return [
                    {
                        "name": "echo",
                        "description": "Echo through MCP.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"echo": {"type": "string"}},
                            "required": ["echo"],
                            "additionalProperties": False,
                        },
                    }
                ]

            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                return {"echo": arguments["text"]}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_mcp_extension(root)
            with patch("agent_factory.tooling.factory_extensions.MCPRuntimeManager", FakeRuntimeManager):
                tools = get_factory_tools(tool_ids=["factory_mcp_echo"], extension_root=root)
                result = tools[0].invoke({"text": "hello"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["output"], {"echo": "hello"})


def _write_skill_extension(root: Path, *, tool_id: str = "echo", prefix: str | None = "factory") -> None:
    skill_root = root / "skills" / "factory"
    (skill_root / "tools").mkdir(parents=True)
    (skill_root / "scripts").mkdir()
    (skill_root / "skill.json").write_text(
        json.dumps(
            {
                "version": "skill.v0",
                "skill_id": "factory",
                "tool_id_prefix": prefix,
                "default_enabled_tools": [tool_id],
                "prompt_fragments": [],
            }
        ),
        encoding="utf-8",
    )
    (skill_root / "tools" / f"{tool_id}.json").write_text(
        json.dumps(
            {
                "id": tool_id,
                "description": "Echo input text.",
                "entrypoint": "scripts/echo.py:run",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"echo": {"type": "string"}},
                    "required": ["echo"],
                    "additionalProperties": False,
                },
                "resources": {},
                "approval_required": False,
                "concurrent": True,
            }
        ),
        encoding="utf-8",
    )
    (skill_root / "scripts" / "echo.py").write_text(
        "def run(arguments: dict, resources: dict) -> dict:\n"
        "    return {'echo': arguments['text']}\n",
        encoding="utf-8",
    )
    (root / "enabled_skills.json").write_text(
        json.dumps(
            {
                "version": "enabled_skills.v0",
                "skills": [
                    {
                        "skill_id": "factory",
                        "path": "skills/factory",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_mcp_extension(root: Path) -> None:
    (root / "mcp_servers.json").write_text(
        json.dumps(
            {
                "version": "mcp_servers.v0",
                "servers": [
                    {
                        "server_id": "factory_mcp",
                        "transport": "stdio",
                        "command": "node",
                        "args": ["server.js"],
                        "tool_id_prefix": "factory_mcp",
                        "approval_default": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
