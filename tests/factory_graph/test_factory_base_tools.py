from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_factory.factory_graph.graph import build_factory_graph
from agent_factory.factory_graph.tools import (
    get_factory_base_tool_ids,
    get_factory_base_tools,
    get_factory_graph_tools,
    get_factory_model_tools,
)


def _tool_by_name(name: str):
    tools = {tool.name: tool for tool in get_factory_base_tools()}
    return tools[name]


class FactoryBaseToolsTest(unittest.TestCase):
    def test_file_tools_are_general_filesystem_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "nested" / "note.txt"

            write_result = _tool_by_name("file_write").invoke(
                {"path": str(target), "content": "alpha beta alpha"}
            )
            self.assertEqual(write_result["status"], "written")

            read_result = _tool_by_name("file_read").invoke({"path": str(target)})
            self.assertEqual(read_result["content"], "alpha beta alpha")

            patch_result = _tool_by_name("file_patch").invoke(
                {"path": str(target), "old": "beta", "new": "gamma"}
            )
            self.assertEqual(patch_result["replacements"], 1)

            list_result = _tool_by_name("file_list").invoke({"path": str(root), "recursive": True})
            listed_paths = {entry["path"] for entry in list_result["entries"]}
            self.assertIn(str(target), listed_paths)

    def test_search_tools_are_not_project_specific(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "knowledge.md"
            target.write_text("one\nneedle here\nthree\n", encoding="utf-8")

            file_result = _tool_by_name("search_files").invoke(
                {"root": str(root), "pattern": "*.md", "recursive": True}
            )
            self.assertEqual(file_result["results"][0]["path"], str(target))

            text_result = _tool_by_name("search_text").invoke(
                {"root": str(root), "query": "needle", "glob": "*.md"}
            )
            self.assertEqual(text_result["matches"][0]["line"], 2)

            inspect_result = _tool_by_name("search_inspect_text").invoke({"text": "hello world"})
            self.assertEqual(inspect_result["words"], 2)

    def test_shell_tools_execute_commands_and_probe_environment(self) -> None:
        which_result = _tool_by_name("shell_which").invoke({"command": "python"})
        self.assertIn("found", which_result)

        run_result = _tool_by_name("shell_run").invoke(
            {"command": [sys.executable, "-c", "print('factory-ok')"]}
        )
        self.assertEqual(run_result["exit_code"], 0)
        self.assertEqual(run_result["stdout"].strip(), "factory-ok")

        env_result = _tool_by_name("shell_env").invoke({"names": ["PATH"], "include_values": False})
        self.assertTrue(env_result["variables"]["PATH"]["exists"])
        self.assertNotIn("value", env_result["variables"]["PATH"])

    def test_factory_graph_injects_tools_through_langgraph_tool_node(self) -> None:
        tool_ids = get_factory_base_tool_ids()
        self.assertIn("file_read", tool_ids)
        self.assertIn("search_inspect_text", tool_ids)
        self.assertIn("shell_run", tool_ids)

        app = build_factory_graph(stop_after_stage="capture_requirement")
        result = app.invoke(
            {
                "requirement": "run one tool call",
                "force_manufacture": True,
                "messages": [
                    HumanMessage(content="run one tool call"),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "search_inspect_text",
                                "args": {"text": "alpha beta"},
                                "id": "call_inspect_text",
                            }
                        ],
                    ),
                ],
                "status": "running",
                "stage_log": [],
                "errors": [],
            }
        )

        tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0].name, "search_inspect_text")

    def test_model_tools_are_native_openai_compatible_tools(self) -> None:
        model_tool_ids = {tool.name for tool in get_factory_model_tools()}
        graph_tool_ids = {tool.name for tool in get_factory_graph_tools()}

        self.assertIn("file_read", model_tool_ids)
        self.assertIn("search_inspect_text", model_tool_ids)
        self.assertIn("shell_run", model_tool_ids)
        self.assertNotIn("file.read", model_tool_ids)
        self.assertNotIn("shell.run", graph_tool_ids)
        self.assertIn("file_read", graph_tool_ids)

    def test_tools_include_model_facing_descriptions_and_argument_schema(self) -> None:
        tools = {tool.name: tool for tool in get_factory_model_tools()}

        self.assertIn("Read a text file", tools["file_read"].description)
        self.assertIn("Run a command without shell expansion", tools["shell_run"].description)
        file_read_schema = tools["file_read"].args_schema.model_json_schema()
        shell_run_schema = tools["shell_run"].args_schema.model_json_schema()
        self.assertIn("Absolute or relative path", file_read_schema["properties"]["path"]["description"])
        self.assertIn("Command and arguments", shell_run_schema["properties"]["command"]["description"])


if __name__ == "__main__":
    unittest.main()
