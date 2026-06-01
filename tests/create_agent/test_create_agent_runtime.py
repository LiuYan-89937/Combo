from __future__ import annotations

import json
import os
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from agent_factory.create_agent.models import CreateAgentIntentDecision
from agent_factory.create_agent.models import (
    ACTION_FILE,
    PackageValidationIssue,
    PackageValidationReport,
    TODO_FILE,
    TodoItem,
    TodoList,
    TodoStatus,
    initial_todo_list,
)
from agent_factory.create_agent.runtime import CreateAgentRuntime
from agent_factory.create_agent.tooling import CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workflow import CreateAgentWorkflow, _messages_with_system
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.skills import parse_skill_directory


class CreateAgentRuntimeTest(unittest.TestCase):
    def test_validator_reports_missing_manifest_as_repairable_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            report = CreateAgentPackageValidator().validate(tmp)

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.issues[0].where, "package.manifest")
        self.assertEqual(report.issues[0].target_files, ["agent_package.json"])

    def test_todo_list_adds_deduplicated_repair_items(self) -> None:
        todo = initial_todo_list()
        issue = PackageValidationIssue(
            where="package.manifest",
            summary="missing manifest",
            message="agent_package.json is missing",
            target_files=["agent_package.json"],
        )

        updated = todo.upsert_repair_items([issue, issue])

        repair_items = [item for item in updated.items if item.kind == "repair"]
        self.assertEqual(len(repair_items), 1)
        self.assertEqual(repair_items[0].status, TodoStatus.failed_needs_repair)

    def test_required_todo_must_be_done_not_skipped(self) -> None:
        todo = TodoList(
            items=[
                TodoItem(title="required", required=True, status=TodoStatus.skipped_by_user),
                TodoItem(title="optional", required=False, status=TodoStatus.pending),
            ]
        )

        self.assertFalse(todo.all_required_done())

    def test_create_agent_skills_are_system_boundary_granular(self) -> None:
        skill_root = Path(__file__).resolve().parents[2] / "agent_factory" / "create_agent" / "skills"
        skill_names = sorted(path.parent.name for path in skill_root.glob("*/SKILL.md"))

        self.assertEqual(
            skill_names,
            [
                "00-todo-control",
                "01-package-manifest",
                "02-runtime-contract-index",
                "03-context-contract",
                "04-memory-contract",
                "05-knowledge-contract",
                "06-trace-contract",
                "07-state-resources-contract",
                "08-tools-contract",
                "09-package-tools",
                "10-package-nodes",
                "11-scheduler-contract",
                "12-scheduler-seeds",
                "13-assembly-and-patterns",
                "14-render-and-events",
                "15-validation-repair",
            ],
        )

    def test_create_agent_skills_parse_as_standard_skills(self) -> None:
        skill_root = Path(__file__).resolve().parents[2] / "agent_factory" / "create_agent" / "skills"

        packages = [parse_skill_directory(path.parent) for path in sorted(skill_root.glob("*/SKILL.md"))]

        self.assertTrue(packages)
        self.assertEqual([package.name for package in packages], sorted(package.name for package in packages))

    def test_tool_environment_executes_builtin_tool_through_compiled_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            ls_tool = next(tool for tool in env.tools if tool.name == "ls")
            observation = ls_tool.invoke({"path": "."})

        self.assertEqual(observation["status"], "completed")
        self.assertEqual(observation["tool_id"], "ls")

    def test_create_agent_control_tool_writes_valid_action(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            control_tool = next(tool for tool in env.tools if tool.name == "create_agent_control")
            observation = control_tool.invoke(
                {
                    "action": "ask_user",
                    "message": "请告诉我这个 Agent 需要使用的外部资源。",
                    "resource_facts": [{"key": "runtime.preference", "value": "concise"}],
                }
            )
            action = workspace.read_action()

        self.assertIn("create_agent_control", env.system_tool_ids)
        self.assertEqual(observation["status"], "completed")
        self.assertEqual(action.action, "ask_user")
        self.assertEqual(action.message, "请告诉我这个 Agent 需要使用的外部资源。")
        self.assertEqual(action.resource_facts[0].key, "runtime.preference")

    def test_create_agent_todo_tool_updates_todo_list(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            todo_tool = next(tool for tool in env.tools if tool.name == "create_agent_todo")
            added = todo_tool.invoke(
                {
                    "action": "add",
                    "todo_id": "custom_contract",
                    "title": "Materialize a custom contract",
                    "kind": "write",
                    "acceptance": "The contract file is present and validates.",
                }
            )
            updated = todo_tool.invoke(
                {
                    "action": "update",
                    "todo_id": "custom_contract",
                    "status": "done",
                    "evidence": ["contracts/custom.json exists and was validated"],
                }
            )
            listed = todo_tool.invoke({"action": "list"})
            todo = workspace.read_todo()

        self.assertIn("create_agent_todo", env.system_tool_ids)
        self.assertEqual(added["status"], "completed")
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(listed["status"], "completed")
        item = next(item for item in todo.items if item.todo_id == "custom_contract")
        self.assertEqual(item.status, TodoStatus.done)
        self.assertEqual(item.details["evidence"], ["contracts/custom.json exists and was validated"])

    def test_generic_filesystem_tools_cannot_write_create_agent_action(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            write_tool = next(tool for tool in env.tools if tool.name == "write")
            observation = write_tool.invoke(
                {
                    "path": ACTION_FILE,
                    "content": json.dumps({"action": "ask_user", "question": "bad"}, ensure_ascii=False),
                }
            )
            action = workspace.read_action()

        self.assertEqual(observation["status"], "denied")
        self.assertEqual(action.action, "continue")

    def test_generic_filesystem_tools_cannot_write_create_agent_todo(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            write_tool = next(tool for tool in env.tools if tool.name == "write")
            observation = write_tool.invoke(
                {
                    "path": TODO_FILE,
                    "content": json.dumps({"version": "create_agent_todo.v0", "items": []}, ensure_ascii=False),
                }
            )
            todo = workspace.read_todo()

        self.assertEqual(observation["status"], "denied")
        self.assertTrue(todo.items)

    def test_malformed_action_file_does_not_crash_workspace_context(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            workspace.action_path.write_text(
                json.dumps({"action": "ask_user", "question": "wrong field"}, ensure_ascii=False),
                encoding="utf-8",
            )

            action = workspace.read_action()
            summary = workspace.context_summary()

        self.assertEqual(action.action, "continue")
        self.assertIn("managed by create_agent_control", summary)

    def test_tool_environment_exposes_create_agent_skills_through_skill_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            skill_tool = next(tool for tool in env.tools if tool.name == "skill")
            listed = skill_tool.invoke({"action": "list"})
            described = skill_tool.invoke({"action": "describe", "name": "05-knowledge-contract"})
            loaded = skill_tool.invoke({"action": "load", "name": "05-knowledge-contract"})
            searched = skill_tool.invoke({"action": "search", "query": "memory contract"})
            denied = skill_tool.invoke(
                {
                    "action": "read_resource",
                    "name": "05-knowledge-contract",
                    "path": "../outside.md",
                }
            )

        self.assertIn("skill", env.system_tool_ids)
        self.assertEqual(listed["status"], "completed")
        skill_names = [item["name"] for item in listed["output"]["skills"]]
        self.assertIn("03-context-contract", skill_names)
        self.assertIn("05-knowledge-contract", skill_names)
        self.assertIn("15-validation-repair", skill_names)
        self.assertEqual(described["status"], "completed")
        self.assertFalse(described["output"]["skill"]["loaded_content"])
        self.assertNotIn("content", described["output"]["skill"])
        self.assertEqual(loaded["status"], "completed")
        self.assertIn("Knowledge Contract", loaded["output"]["skill"]["content"])
        self.assertEqual(searched["status"], "completed")
        self.assertIn("04-memory-contract", [item["name"] for item in searched["output"]["skills"]])
        self.assertEqual(denied["status"], "denied")

    def test_create_agent_system_prompt_uses_skill_gateway_not_skill_body_injection(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            messages = _messages_with_system(
                {
                    "workspace_path": str(workspace.root),
                    "messages": [HumanMessage(content="build an agent")],
                },
                env.tools,
            )

        system_prompt = messages[0].content
        self.assertIn("skill gateway", system_prompt)
        self.assertIn("skill list/search/describe", system_prompt)
        self.assertIn("create_agent_todo", system_prompt)
        self.assertNotIn("# Knowledge Contract", system_prompt)
        self.assertNotIn("Create-agent manufacturing skills", system_prompt)

    def test_validation_repair_context_is_hidden_state_not_chat_message(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            workflow = CreateAgentWorkflow(
                tools=[],
                validator=CreateAgentPackageValidator(),
                model=_NoToolModel(),
            )
            update = workflow._validate(
                {
                    "request": "build an agent",
                    "workspace_path": str(workspace.root),
                    "iteration": 1,
                    "done": False,
                    "messages": [HumanMessage(content="build an agent")],
                }
            )
            messages = _messages_with_system(
                {
                    "workspace_path": str(workspace.root),
                    "messages": [HumanMessage(content="build an agent")],
                    "repair_context": update["repair_context"],
                },
                [],
            )

        self.assertNotIn("messages", update)
        self.assertIn("repair_context", update)
        self.assertIn("Package validation/todo gate is not complete", update["repair_context"])
        self.assertIn("Package validation/todo gate is not complete", messages[0].content)

    def test_workflow_continues_when_validation_and_todo_remain_unfinished(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            workflow = CreateAgentWorkflow(
                tools=[],
                validator=CreateAgentPackageValidator(),
                model=_NoToolModel(),
            )
            update = workflow._validate(
                {
                    "request": "build an agent",
                    "workspace_path": str(workspace.root),
                    "iteration": 100,
                    "done": False,
                    "messages": [HumanMessage(content="build an agent")],
                }
            )

        self.assertFalse(update["done"])
        self.assertIn("repair_context", update)
        self.assertNotIn("messages", update)

    def test_workflow_continues_when_validation_passes_but_required_todo_is_unfinished(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            workflow = CreateAgentWorkflow(
                tools=[],
                validator=_PassingValidator(),
                model=_NoToolModel(),
            )
            update = workflow._validate(
                {
                    "request": "build an agent",
                    "workspace_path": str(workspace.root),
                    "iteration": 100,
                    "done": False,
                    "messages": [HumanMessage(content="build an agent")],
                }
            )

        self.assertFalse(update["done"])
        self.assertIn("repair_context", update)
        self.assertNotIn("messages", update)

    def test_validation_gate_reuses_cached_report_when_package_files_do_not_change(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            validator = _CountingValidator()
            workflow = CreateAgentWorkflow(tools=[], validator=validator, model=_NoToolModel())
            state = {
                "request": "build an agent",
                "workspace_path": str(workspace.root),
                "iteration": 1,
                "done": False,
                "messages": [HumanMessage(content="build an agent")],
            }

            first = workflow._validate(state)
            second = workflow._validate({**state, "iteration": 2})

        self.assertEqual(validator.calls, 1)
        self.assertFalse(first["validation"]["cached"])
        self.assertTrue(second["validation"]["cached"])
        self.assertTrue(second["validation"]["skipped"])
        self.assertEqual(second["validation"]["validation_scope"], "unchanged")

    def test_validation_gate_runs_scoped_validation_after_package_file_change(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            validator = _CountingValidator()
            workflow = CreateAgentWorkflow(tools=[], validator=validator, model=_NoToolModel())
            state = {
                "request": "build an agent",
                "workspace_path": str(workspace.root),
                "iteration": 1,
                "done": False,
                "messages": [HumanMessage(content="build an agent")],
            }

            workflow._validate(state)
            contract_path = workspace.root / "contracts" / "state.json"
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_path.write_text("{}", encoding="utf-8")
            updated = workflow._validate({**state, "iteration": 2})

        self.assertEqual(validator.calls, 2)
        self.assertEqual(validator.scopes[-1], "runtime_contract_build")
        self.assertEqual(updated["validation"]["changed_files"], ["contracts/state.json"])

    def test_finalize_forces_full_validation_even_when_package_files_do_not_change(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            validator = _CountingValidator()
            workflow = CreateAgentWorkflow(tools=[], validator=validator, model=_NoToolModel())
            state = {
                "request": "build an agent",
                "workspace_path": str(workspace.root),
                "iteration": 1,
                "done": False,
                "messages": [HumanMessage(content="build an agent")],
            }

            workflow._validate(state)
            control_tool = next(
                tool for tool in CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp).tools if tool.name == "create_agent_control"
            )
            control_tool.invoke({"action": "finalize"})
            finalized = workflow._validate({**state, "iteration": 2})

        self.assertEqual(validator.calls, 2)
        self.assertEqual(validator.scopes[-1], "full_static")
        self.assertFalse(finalized["validation"]["cached"])

    def test_runtime_routes_non_manufacturing_message_to_assist_without_package_validation(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"AGENTFACTORY_PROJECT_ROOT": tmp}):
            runtime = CreateAgentRuntime(
                validator=_ExplodingValidator(),
                checkpointer=MemorySaver(),
                model=_IntentModel(intent="chat", answer="这是 create-agent 辅助回答。"),
            )
            run = runtime.stream(user_input="你现在有什么 skill 可以用", session_id="assist-session", request_id="req")
            events = [item for mode, item in run.events if mode == "frontend_event"]
            todo_exists = (run.workspace.root / TODO_FILE).exists()

        self.assertEqual(events[0].graph_id, "create_agent_assist")
        self.assertEqual(events[-1].event_type, "run_completed")
        self.assertEqual(events[-1].payload["graph_kind"], "assist")
        self.assertFalse(todo_exists)

    def test_runtime_routes_manufacturing_message_to_react_workspace(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"AGENTFACTORY_PROJECT_ROOT": tmp}):
            runtime = CreateAgentRuntime(
                checkpointer=MemorySaver(),
                model=_IntentModel(intent="manufacture_agent", answer="I need to keep working."),
            )
            run = runtime.stream(user_input="创建一个 Agent", session_id="manufacture-session", request_id="req")
            events = [item for mode, item in run.events if mode == "frontend_event"]
            todo_exists = (run.workspace.root / TODO_FILE).exists()

        self.assertEqual(events[0].graph_id, "create_agent_react")
        self.assertTrue(todo_exists)


class _NoToolModel:
    def bind_tools(self, _tools, tool_choice: str = "auto"):
        return self

    def invoke(self, _messages):
        return AIMessage(content="I need to keep working.")


class _PassingValidator:
    def validate(self, package_root, **_kwargs):
        return PackageValidationReport(status="passed", package_root=str(package_root))


class _CountingValidator:
    def __init__(self) -> None:
        self.calls = 0
        self.scopes: list[str] = []

    def validate(self, package_root, *, scope="full_static", changed_files=None):
        self.calls += 1
        self.scopes.append(scope)
        return PackageValidationReport(
            status="failed",
            package_root=str(package_root),
            validation_scope=scope,
            changed_files=list(changed_files or []),
            summary=f"{scope} failed for test",
            issues=[
                PackageValidationIssue(
                    where="test.validation",
                    summary="test issue",
                    message="test issue",
                    target_files=["agent_package.json"],
                )
            ],
        )


class _ExplodingValidator:
    def validate(self, package_root):
        raise AssertionError("non-manufacturing create-agent requests must not run package validation")


class _IntentModel:
    def __init__(self, *, intent: str, answer: str) -> None:
        self.intent = intent
        self.answer = answer

    def with_structured_output(self, output_model, method: str = "json_mode"):
        return _StructuredIntentModel(self.intent)

    def bind_tools(self, _tools, tool_choice: str = "auto"):
        return self

    def invoke(self, _messages):
        return AIMessage(content=self.answer)


class _StructuredIntentModel:
    def __init__(self, intent: str) -> None:
        self.intent = intent

    def invoke(self, _messages):
        return CreateAgentIntentDecision(intent=self.intent, rationale="test")


if __name__ == "__main__":
    unittest.main()
