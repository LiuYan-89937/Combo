from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_factory.runtime_kernel.extensions import AgentInstanceExtensionManager


class AgentInstanceExtensionTest(unittest.TestCase):
    def test_missing_extension_files_load_as_empty_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AgentInstanceExtensionManager(extension_root=temp_dir)
            result, report = manager.discover()

        self.assertEqual(result.tool_specs, [])
        self.assertEqual(result.prompt_fragments, [])
        self.assertEqual(report.tool_ids, [])
        self.assertIsNone(report.mcp_servers_path)
        self.assertIsNone(report.enabled_skills_path)

    def test_mcp_extension_config_discovers_tools(self) -> None:
        class FakeMCPClient:
            def list_tools(self) -> list[dict]:
                return [{"name": "search", "description": "Search through MCP."}]

            def call_tool(self, tool_name: str, arguments: dict) -> dict:
                return {"tool": tool_name, "arguments": arguments}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "mcp_servers.json").write_text(
                json.dumps(
                    {
                        "version": "mcp_servers.v0",
                        "servers": [
                            {
                                "server_id": "search_server",
                                "transport": "stdio",
                                "enabled": True,
                                "tool_id_prefix": "search",
                                "risk_level_default": "low",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manager = AgentInstanceExtensionManager(
                extension_root=root,
                mcp_catalog_clients={"search_server": FakeMCPClient()},
                mcp_tool_clients={"search_server": FakeMCPClient()},
            )
            registry, result, report = manager.build_registry()
            tool = manager.create_tool_compiler().compile(registry.get("search_search"))

        self.assertEqual(registry.ids(), ["search_search"])
        self.assertEqual(result.tool_specs[0].entrypoint, "mcp:search_server/search")
        self.assertEqual(report.tool_ids, ["search_search"])
        self.assertEqual(tool.invoke({})["output"], {"tool": "search", "arguments": {}})

    def test_skill_extension_config_loads_progressive_skill_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_root = root / "skills" / "writer"
            (skill_root / "references").mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                "---\n"
                "name: writer\n"
                "description: Prompt-only writing skill.\n"
                "---\n"
                "# Writer\n"
                "Write concise responses.\n",
                encoding="utf-8",
            )
            (skill_root / "references" / "style.md").write_text("Write concise responses.", encoding="utf-8")
            (root / "enabled_skills.json").write_text(
                json.dumps(
                    {
                        "version": "enabled_skills.v0",
                        "skills": [
                            {
                                "skill_id": "writer",
                                "path": "skills/writer",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            manager = AgentInstanceExtensionManager(extension_root=root)
            result, report = manager.discover()

        self.assertEqual([tool.id for tool in result.tool_specs], ["skill"])
        self.assertEqual(result.prompt_fragments, [])
        self.assertEqual(report.prompt_fragment_ids, [])
        self.assertEqual(report.tool_ids, ["skill"])


if __name__ == "__main__":
    unittest.main()
