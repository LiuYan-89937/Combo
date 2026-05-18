from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_factory.tooling.providers import (
    MCPServerConfig,
    MCPServersConfig,
    MCPToolProvider,
    PackageToolProvider,
    SkillProvider,
    ToolProviderContext,
)


class ToolProviderTest(unittest.TestCase):
    def test_package_provider_loads_tool_manifest_and_normalizes_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "tools" / "sample" / "manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps(_tool_manifest(entrypoint="tools/sample/tool.py:run")),
                encoding="utf-8",
            )

            result = PackageToolProvider().discover(ToolProviderContext(package_root=root))

        self.assertEqual(result.diagnostics, [])
        self.assertEqual(result.tool_specs[0].id, "sample_tool")
        self.assertEqual(result.tool_specs[0].entrypoint, "python:tools/sample/tool.py:run")

    def test_mcp_provider_converts_discovered_tools_to_tool_specs(self) -> None:
        class FakeCatalogClient:
            def list_tools(self) -> list[dict]:
                return [
                    {
                        "name": "read_file",
                        "description": "Read a file from MCP.",
                        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
                    }
                ]

        provider = MCPToolProvider(
            config=MCPServersConfig(
                servers=[
                    MCPServerConfig(
                        server_id="filesystem",
                        transport="stdio",
                        tool_id_prefix="fs",
                        risk_level_default="medium",
                    )
                ]
            ),
            clients={"filesystem": FakeCatalogClient()},
        )

        result = provider.discover(ToolProviderContext())

        self.assertEqual(result.diagnostics, [])
        self.assertEqual(result.tool_specs[0].id, "fs_read_file")
        self.assertEqual(result.tool_specs[0].entrypoint, "mcp:filesystem/read_file")
        self.assertEqual(result.tool_specs[0].risk_level, "medium")
        self.assertEqual(result.runtime_dependencies[0].dependency_id, "mcp.filesystem")

    def test_skill_provider_registers_progressive_skill_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_root = root / "skills" / "db"
            (skill_root / "references").mkdir(parents=True)
            (skill_root / "scripts").mkdir()
            (skill_root / "SKILL.md").write_text(
                "---\n"
                "name: db\n"
                "description: Use read-only SQL.\n"
                "---\n"
                "# DB\n"
                "Use read-only SQL.\n",
                encoding="utf-8",
            )
            (skill_root / "references" / "dialects.md").write_text("SQL dialect notes.", encoding="utf-8")
            (skill_root / "scripts" / "query.py").write_text("print('readonly')\n", encoding="utf-8")

            result = SkillProvider(
                config={
                    "skills": [
                        {
                            "skill_id": "db",
                            "path": "skills/db",
                        }
                    ]
                }
            ).discover(ToolProviderContext(extension_root=root))

        self.assertEqual(result.diagnostics, [])
        self.assertEqual(result.prompt_fragments, [])
        self.assertEqual(result.tool_specs[0].id, "skill")
        self.assertIn("db", result.tool_specs[0].description)
        self.assertEqual(result.runtime_resources["skills"]["skills"][0]["metadata"]["name"], "db")


def _tool_manifest(
    *,
    tool_id: str = "sample_tool",
    entrypoint: str = "tools/sample/tool.py:run",
) -> dict:
    return {
        "id": tool_id,
        "description": "Sample tool.",
        "entrypoint": entrypoint,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object", "additionalProperties": True},
        "resources": {},
        "risk_level": "low",
        "risk_evaluator": {},
        "concurrent": True,
    }


if __name__ == "__main__":
    unittest.main()
