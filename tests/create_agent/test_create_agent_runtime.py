from __future__ import annotations

import json
import os
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
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
from agent_factory.create_agent.scripts.export_skill_schemas import (
    EXAMPLE_EXPORTS,
    SCHEMA_EXPORTS,
    SKILLS_ROOT,
    _example_text,
    _schema_text,
)
from agent_factory.create_agent.prompt_builder import build_create_agent_messages
from agent_factory.create_agent.prompt_context import project_messages_for_prompt
from agent_factory.create_agent.tooling import CREATE_AGENT_BUILTIN_TOOL_IDS, CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.validation_progress import validation_event_from_tool_calls
from agent_factory.create_agent.validation_progress import apply_validation_progress
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workflow import CreateAgentWorkflow
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.runtime_contracts.builtins import (
    default_artifact_contract,
    default_context_contract,
    default_dependencies_contract,
    default_knowledge_contract,
    default_memory_contract,
    default_model_contract,
    default_node_provider_contract,
    default_render_contract,
    default_resources_contract,
    default_sandbox_contract,
    default_scheduler_contract,
    default_session_contract,
    default_state_contract,
    default_tools_contract,
    default_trace_contract,
)
from agent_factory.tooling.skills import parse_skill_directory
from agent_factory.tooling.output_store import ToolOutputStore


class CreateAgentRuntimeTest(unittest.TestCase):
    def test_validator_reports_missing_manifest_as_repairable_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            report = CreateAgentPackageValidator().validate(tmp)

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.issues[0].where, "package.manifest")
        self.assertEqual(report.issues[0].target_files, ["agent_package.json"])
        self.assertEqual(report.issues[0].recommended_skill, "01-package-manifest")
        self.assertIn("references/agent_package.schema.json", report.issues[0].recommended_resources)

    def test_validator_registers_package_local_patterns_before_compile(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_minimal_package_with_local_pattern(root)

            report = CreateAgentPackageValidator().validate(root)

        self.assertEqual(report.status, "passed", report.summary)

    def test_create_agent_scaffold_runtime_contracts_build_inside_workspace(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")

            report = CreateAgentPackageValidator().validate(tmp, scope="runtime_contract_build")

        self.assertEqual(report.status, "passed", report.summary)
        self.assertFalse((Path("/runtime") / "scheduler" / "scheduler.sqlite").exists())

    def test_validator_reports_absolute_runtime_contract_path_as_machine_repair(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            scheduler_path = workspace.root / "contracts" / "scheduler.json"
            payload = json.loads(scheduler_path.read_text(encoding="utf-8"))
            payload["config"]["store_path"] = "/runtime/scheduler/scheduler.sqlite"
            _write_json(scheduler_path, payload)

            report = CreateAgentPackageValidator().validate(tmp, scope="runtime_contract_build")

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.issues[0].where, "runtime_contracts.path")
        self.assertEqual(report.issues[0].details["contract_key"], "scheduler")
        self.assertEqual(report.issues[0].details["field_path"], "config.store_path")
        self.assertTrue(report.issues[0].repair_bundle)
        self.assertTrue(report.issues[0].repair_bundle.machine_applicable)
        self.assertEqual(report.issues[0].repair_bundle.repair_action, "normalize_runtime_contract_paths")

    def test_scaffold_applies_runtime_path_machine_repair(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            scheduler_path = workspace.root / "contracts" / "scheduler.json"
            payload = json.loads(scheduler_path.read_text(encoding="utf-8"))
            payload["config"]["store_path"] = "/runtime/scheduler/scheduler.sqlite"
            _write_json(scheduler_path, payload)
            report = CreateAgentPackageValidator().validate(tmp, scope="runtime_contract_build")
            workspace.write_validation(report)
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            scaffold_tool = next(tool for tool in env.tools if tool.name == "create_agent_scaffold")

            repair = scaffold_tool.invoke({"action": "apply_machine_repair"})
            repaired_payload = json.loads(scheduler_path.read_text(encoding="utf-8"))
            repaired_report = CreateAgentPackageValidator().validate(tmp, scope="runtime_contract_build")

        self.assertEqual(repair["status"], "completed")
        self.assertEqual(repaired_payload["config"]["store_path"], ".agent_runtime/scheduler/scheduler.sqlite")
        self.assertEqual(repaired_report.status, "passed", repaired_report.summary)

    def test_failed_validation_does_not_mark_todo_done(self) -> None:
        todo = initial_todo_list()
        failed = PackageValidationReport(
            status="failed",
            package_root="/tmp/package",
            validation_scope="full_static",
            summary="runtime path failed",
            issues=[
                PackageValidationIssue(
                    where="runtime_contracts.path",
                    summary="path escapes",
                    message="path escapes",
                    target_files=["contracts/scheduler.json"],
                )
            ],
        )

        updated = apply_validation_progress(todo, failed)

        statuses = {item.todo_id: item.status for item in updated.items}
        self.assertEqual(statuses["package_manifest"], TodoStatus.pending)
        self.assertTrue(any(item.kind == "repair" for item in updated.items))

    def test_create_agent_skill_schema_examples_do_not_default_to_runtime_root(self) -> None:
        skill_root = Path(__file__).resolve().parents[2] / "agent_factory" / "create_agent" / "skills"
        checked = [
            path
            for path in skill_root.glob("**/*")
            if path.is_file() and path.suffix in {".json", ".md"}
        ]

        offenders = [path for path in checked if "/runtime/" in path.read_text(encoding="utf-8")]

        self.assertEqual(offenders, [])

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
        self.assertIn("issue_id", repair_items[0].details)
        self.assertEqual(repair_items[0].details["where"], "package.manifest")
        self.assertNotIn("message", repair_items[0].details)

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
                "16-session-contract",
            ],
        )

    def test_create_agent_skills_parse_as_standard_skills(self) -> None:
        skill_root = Path(__file__).resolve().parents[2] / "agent_factory" / "create_agent" / "skills"

        packages = [parse_skill_directory(path.parent) for path in sorted(skill_root.glob("*/SKILL.md"))]

        self.assertTrue(packages)
        self.assertEqual([package.name for package in packages], sorted(package.name for package in packages))
        for package in packages:
            self.assertNotIn('"$schema"', package.body)
            self.assertTrue(package.resources, package.name)

    def test_create_agent_skill_schemas_are_generated_from_runtime_models(self) -> None:
        for relative, model in SCHEMA_EXPORTS.items():
            target = SKILLS_ROOT / relative
            self.assertEqual(target.read_text(encoding="utf-8"), _schema_text(model), relative)

    def test_create_agent_skill_examples_are_generated_from_runtime_models(self) -> None:
        for relative, model in EXAMPLE_EXPORTS.items():
            target = SKILLS_ROOT / relative
            self.assertEqual(target.read_text(encoding="utf-8"), _example_text(model), relative)

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
                    "action": "upsert",
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

    def test_workspace_context_summary_includes_completed_todo_summaries(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            todo_tool = next(tool for tool in env.tools if tool.name == "create_agent_todo")
            todo_tool.invoke(
                {
                    "action": "upsert",
                    "todo_id": "custom_contract",
                    "title": "Materialize custom contract",
                    "kind": "write",
                    "status": "done",
                    "target_files": ["agent_package.json"],
                    "evidence": ["agent_package.json references package-relative files"],
                    "source": "test",
                }
            )

            summary = workspace.context_summary()

        self.assertIn("Completed todo summaries:", summary)
        self.assertIn("custom_contract", summary)
        self.assertIn("agent_package.json references package-relative files", summary)

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

    def test_generic_filesystem_read_of_create_agent_todo_points_to_todo_tool(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            read_tool = next(tool for tool in env.tools if tool.name == "read")

            observation = read_tool.invoke({"path": TODO_FILE})

        self.assertEqual(observation["status"], "denied")
        self.assertIn("cannot be read", observation["message"])
        self.assertIn("create_agent_todo", observation["message"])
        self.assertNotIn("cannot be modified", observation["message"])

    def test_invalid_action_file_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            workspace.action_path.write_text(
                json.dumps({"action": "ask_user", "question": "wrong field"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as caught:
                workspace.read_action()

        self.assertIn("invalid managed create-agent file", str(caught.exception))
        self.assertIn("create_agent_control", str(caught.exception))

    def test_tool_environment_exposes_create_agent_skills_through_skill_gateway(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            skill_tool = next(tool for tool in env.tools if tool.name == "skill")
            listed = skill_tool.invoke({"action": "list"})
            described = skill_tool.invoke(
                {"action": "describe", "name": "05-knowledge-contract", "current_todo": "runtime_contracts"}
            )
            loaded = skill_tool.invoke(
                {
                    "action": "load",
                    "name": "05-knowledge-contract",
                    "current_todo": "runtime_contracts",
                    "reason": "The active todo is deciding whether a knowledge contract is needed.",
                }
            )
            loaded_state = skill_tool.invoke({"action": "list_loaded", "current_todo": "runtime_contracts"})
            searched = skill_tool.invoke({"action": "search", "query": "memory contract"})
            denied = skill_tool.invoke(
                {
                    "action": "read_resource",
                    "name": "05-knowledge-contract",
                    "path": "../outside.md",
                    "current_todo": "runtime_contracts",
                }
            )
            resource = skill_tool.invoke(
                {
                    "action": "read_resource",
                    "name": "05-knowledge-contract",
                    "path": "references/knowledge_contract.schema.json",
                    "current_todo": "runtime_contracts",
                }
            )

        self.assertIn("skill", env.system_tool_ids)
        self.assertEqual(listed["status"], "completed")
        skill_names = [item["name"] for item in listed["output"]["skills"]]
        self.assertIn("03-context-contract", skill_names)
        self.assertIn("05-knowledge-contract", skill_names)
        self.assertIn("15-validation-repair", skill_names)
        self.assertNotIn("resource_index", listed["output"]["skills"][0])
        self.assertEqual(described["status"], "completed")
        self.assertFalse(described["output"]["skill"]["loaded_content"])
        self.assertNotIn("content", described["output"]["skill"])
        self.assertEqual(loaded["status"], "completed")
        self.assertIn("Knowledge Contract", loaded["output"]["skill"]["content"])
        self.assertEqual(loaded_state["status"], "completed")
        self.assertEqual(loaded_state["output"]["loaded_state"]["primary_skill"], "05-knowledge-contract")
        self.assertEqual(searched["status"], "completed")
        self.assertIn("04-memory-contract", [item["name"] for item in searched["output"]["skills"]])
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(resource["status"], "completed")
        self.assertEqual(resource["output"]["resource"]["path"], "references/knowledge_contract.schema.json")
        self.assertEqual(resource["output"]["resource"]["mode"], "outline")
        self.assertIn("outline", resource["output"]["resource"])
        self.assertEqual(resource["output"]["resource"]["content"], "")

    def test_skill_gateway_requires_describe_before_resource_read_with_clear_guidance(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            skill_tool = next(tool for tool in env.tools if tool.name == "skill")
            denied = skill_tool.invoke(
                {
                    "action": "read_resource",
                    "name": "05-knowledge-contract",
                    "path": "references/knowledge_contract.schema.json",
                    "current_todo": "runtime_contracts",
                }
            )

        self.assertEqual(denied["status"], "denied")
        self.assertIn("Protocol violation", denied["message"])
        self.assertIn("action='describe'", denied["message"])

    def test_skill_gateway_reports_invalid_fragment_without_resource_path_confusion(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            skill_tool = next(tool for tool in env.tools if tool.name == "skill")
            described = skill_tool.invoke(
                {"action": "describe", "name": "13-assembly-and-patterns", "current_todo": "assembly_and_patterns"}
            )
            denied = skill_tool.invoke(
                {
                    "action": "read_resource",
                    "name": "13-assembly-and-patterns",
                    "path": "references/assembly_spec.schema.json",
                    "mode": "fragment",
                    "pointer": "/assembly",
                    "current_todo": "assembly_and_patterns",
                }
            )

        self.assertEqual(described["status"], "completed")
        self.assertEqual(denied["status"], "denied")
        self.assertIn("Invalid resource fragment", denied["message"])
        self.assertIn("available_top_level_keys", denied["message"])
        self.assertNotIn("Unknown skill resource path", denied["message"])

    def test_create_agent_skill_gateway_state_survives_tool_environment_rebuild(self) -> None:
        with TemporaryDirectory() as tmp:
            first_env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            first_skill_tool = next(tool for tool in first_env.tools if tool.name == "skill")
            described = first_skill_tool.invoke(
                {"action": "describe", "name": "05-knowledge-contract", "current_todo": "runtime_contracts"}
            )
            self.assertEqual(described["status"], "completed")
            self.assertTrue((Path(tmp) / ".factory" / "skill_gateway_state.json").is_file())

            second_env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            second_skill_tool = next(tool for tool in second_env.tools if tool.name == "skill")
            resource = second_skill_tool.invoke(
                {
                    "action": "read_resource",
                    "name": "05-knowledge-contract",
                    "path": "references/knowledge_contract.schema.json",
                    "current_todo": "runtime_contracts",
                }
            )

        self.assertEqual(resource["status"], "completed")
        self.assertEqual(resource["output"]["resource"]["mode"], "outline")

    def test_skill_gateway_rejects_load_without_context_and_unguarded_second_primary(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            skill_tool = next(tool for tool in env.tools if tool.name == "skill")
            missing_context = skill_tool.invoke({"action": "load", "name": "05-knowledge-contract"})
            first = skill_tool.invoke(
                {
                    "action": "load",
                    "name": "05-knowledge-contract",
                    "current_todo": "runtime_contracts",
                    "reason": "The active todo needs the knowledge contract manufacturing guide.",
                }
            )
            second_without_describe = skill_tool.invoke(
                {
                    "action": "load",
                    "name": "04-memory-contract",
                    "current_todo": "runtime_contracts",
                    "reason": "Need to compare memory against knowledge for the same contract-selection todo.",
                }
            )
            described = skill_tool.invoke(
                {"action": "describe", "name": "04-memory-contract", "current_todo": "runtime_contracts"}
            )
            second_after_describe = skill_tool.invoke(
                {
                    "action": "load",
                    "name": "04-memory-contract",
                    "current_todo": "runtime_contracts",
                    "reason": "The primary knowledge guide is insufficient because this todo must decide memory ownership too.",
                }
            )

        self.assertNotEqual(missing_context["status"], "completed")
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second_without_describe["status"], "denied")
        self.assertEqual(described["status"], "completed")
        self.assertEqual(second_after_describe["status"], "completed")

    def test_create_agent_default_tools_do_not_include_generic_bash(self) -> None:
        with TemporaryDirectory() as tmp:
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)

        self.assertNotIn("bash", CREATE_AGENT_BUILTIN_TOOL_IDS)
        self.assertNotIn("bash_status", CREATE_AGENT_BUILTIN_TOOL_IDS)
        self.assertNotIn("bash_stop", CREATE_AGENT_BUILTIN_TOOL_IDS)
        self.assertNotIn("bash", env.tool_ids)
        self.assertIn("create_agent_validate", env.system_tool_ids)

    def test_create_agent_system_prompt_uses_skill_gateway_not_skill_body_injection(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            messages = build_create_agent_messages(
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

    def test_create_agent_context_summary_lists_real_tool_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            ref = ToolOutputStore(workspace.tool_outputs_path).write_output(
                tool_id="read",
                tool_call_id="call_read",
                output={"content": "large result"},
            )

            summary = workspace.context_summary()

        self.assertIn("Available tool outputs:", summary)
        self.assertIn(ref["id"], summary)
        self.assertIn("tool=read", summary)

    def test_tool_output_unknown_id_returns_recoverable_observation_with_available_refs(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            real_ref = ToolOutputStore(workspace.tool_outputs_path).write_output(
                tool_id="grep",
                tool_call_id="call_grep",
                output={"matches": []},
            )
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            tool_output = next(tool for tool in env.tools if tool.name == "tool_output")

            listed = tool_output.invoke({"action": "list"})
            missing = tool_output.invoke(
                {"action": "read", "output_id": "toolout_00000000000000000000000000000000"}
            )

        self.assertEqual(listed["status"], "completed")
        self.assertEqual(listed["output"]["status"], "completed")
        self.assertEqual(listed["output"]["outputs"][0]["id"], real_ref["id"])
        self.assertEqual(missing["status"], "completed")
        self.assertEqual(missing["output"]["status"], "output_ref_not_found")
        self.assertEqual(missing["output"]["available_outputs"][0]["id"], real_ref["id"])

    def test_create_agent_system_prompt_compacts_old_history(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            old_tool_output = "old tool output " + ("x" * 5000)
            history = [
                HumanMessage(content="initial user request"),
                AIMessage(content="older assistant"),
                ToolMessage(content=old_tool_output, tool_call_id="old_call", name="read"),
                *[AIMessage(content=f"older message {index}") for index in range(10)],
                HumanMessage(content="recent user correction"),
            ]
            messages = build_create_agent_messages(
                {
                    "workspace_path": str(workspace.root),
                    "messages": history,
                },
                [],
            )

        rendered = "\n".join(str(message.content) for message in messages)
        self.assertIn("Compacted prior create-agent history", rendered)
        self.assertIn("recent user correction", rendered)
        self.assertNotIn(old_tool_output, rendered)
        self.assertLessEqual(len(messages), 12)

    def test_create_agent_prompt_compaction_preserves_real_tool_output_refs(self) -> None:
        output_id = "toolout_11111111111111111111111111111111"
        compacted_payload = {
            "type": "tool_observation",
            "status": "completed",
            "tool_id": "grep",
            "output": {
                "_tool_output_compacted": {
                    "output_ref": {
                        "type": "tool_output_ref",
                        "id": output_id,
                        "tool_id": "grep",
                        "tool_call_id": "call_grep",
                        "size_chars": 50000,
                    }
                }
            },
        }
        messages = [
            HumanMessage(content="request"),
            ToolMessage(content=json.dumps(compacted_payload), tool_call_id="call_grep", name="grep"),
            *[AIMessage(content=f"recent {index}") for index in range(10)],
        ]

        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            projected = project_messages_for_prompt(messages, workspace=workspace)
            rendered = "\n".join(str(message.content) for message in projected)

        self.assertIn("Available output refs preserved from compacted history", rendered)
        self.assertIn(output_id, rendered)

    def test_create_agent_prompt_compacts_completed_todo_history_even_when_recent(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            env = CreateAgentToolEnvironmentBuilder().build(workspace_root=tmp)
            todo_tool = next(tool for tool in env.tools if tool.name == "create_agent_todo")
            todo_tool.invoke(
                {
                    "action": "add",
                    "todo_id": "custom_manifest",
                    "title": "Materialize custom manifest",
                    "kind": "write",
                    "acceptance": "custom manifest exists",
                }
            )
            todo_output = todo_tool.invoke(
                {
                    "action": "update",
                    "todo_id": "custom_manifest",
                    "status": "done",
                    "target_files": ["agent_package.json"],
                    "evidence": ["agent_package.json was materialized"],
                }
            )
            history = [
                HumanMessage(content="manifest phase user detail that should not be replayed"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "create_agent_todo",
                            "args": {"action": "update", "todo_id": "custom_manifest", "status": "done"},
                            "id": "todo_done",
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps(
                        {
                            "type": "tool_observation",
                            "status": "completed",
                            "tool_id": "create_agent_todo",
                            "tool_call_id": "todo_done",
                            "message": "Todo updated",
                            "retryable": False,
                            "arguments": {},
                            "output": todo_output,
                            "errors": [],
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="todo_done",
                    name="create_agent_todo",
                ),
                AIMessage(content="working on next active todo"),
                HumanMessage(content="current active todo correction"),
            ]

            messages = build_create_agent_messages(
                {
                    "workspace_path": str(workspace.root),
                    "messages": history,
                },
                env.tools,
            )

        rendered = "\n".join(str(message.content) for message in messages)
        self.assertIn("Completed todo history compacted", rendered)
        self.assertIn("Completed todo summaries:", rendered)
        self.assertIn("agent_package.json was materialized", rendered)
        self.assertIn("current active todo correction", rendered)
        self.assertNotIn("manifest phase user detail that should not be replayed", rendered)

    def test_prompt_projection_preserves_tool_message_pair_boundary(self) -> None:
        messages = [
            HumanMessage(content="request"),
            AIMessage(content="older"),
            HumanMessage(content="older user"),
            AIMessage(content="", tool_calls=[{"name": "read", "args": {"path": "."}, "id": "call_1"}]),
            ToolMessage(content="tool result", tool_call_id="call_1", name="read"),
            *[AIMessage(content=f"recent {index}") for index in range(9)],
        ]

        with TemporaryDirectory() as tmp:
            workspace = CreateAgentWorkspace(tmp)
            workspace.initialize(user_input="build an agent")
            projected = project_messages_for_prompt(messages, workspace=workspace)

        self.assertIsInstance(projected[0], SystemMessage)
        self.assertIsInstance(projected[1], AIMessage)
        self.assertIsInstance(projected[2], ToolMessage)
        self.assertEqual(projected[2].tool_call_id, "call_1")

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
            messages = build_create_agent_messages(
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
        self.assertIn("Validation digest:", update["repair_context"])
        self.assertNotIn("Validation report:", update["repair_context"])

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
        self.assertIn("issues", second["validation"])
        self.assertIn("issue_id", second["validation"]["issues"][0])

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

    def test_validation_events_are_triggered_only_by_state_changing_tools(self) -> None:
        self.assertEqual(validation_event_from_tool_calls([{"name": "read"}]), "none")
        self.assertEqual(validation_event_from_tool_calls([{"name": "skill"}]), "none")
        self.assertEqual(validation_event_from_tool_calls([{"name": "write"}]), "package_change")
        self.assertEqual(validation_event_from_tool_calls([{"name": "edit"}]), "package_change")
        self.assertEqual(validation_event_from_tool_calls([{"name": "multi_edit"}]), "package_change")
        self.assertEqual(validation_event_from_tool_calls([{"name": "create_agent_scaffold"}]), "package_change")
        self.assertEqual(validation_event_from_tool_calls([{"name": "create_agent_todo"}]), "todo")
        self.assertEqual(validation_event_from_tool_calls([{"name": "create_agent_control"}]), "control")
        self.assertEqual(validation_event_from_tool_calls([{"name": "create_agent_validate"}]), "explicit_validation")

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


def _write_minimal_package_with_local_pattern(root: Path) -> None:
    contracts_dir = root / "contracts"
    patterns_dir = root / "patterns"
    contracts_dir.mkdir(parents=True)
    patterns_dir.mkdir(parents=True)

    manifest = {
        "version": "agent_package.v0",
        "factory_run_id": "test_run",
        "agent": {},
        "runtime": {},
        "assembly_spec_path": "assembly_spec.json",
        "render_manifest_path": "render_manifest.json",
        "resources_path": "resources.json",
        "sandbox_contract_path": "sandbox_contract.json",
        "contracts": {
            "artifact": "contracts/artifact.json",
            "context": "contracts/context.json",
            "dependencies": "contracts/dependencies.json",
            "knowledge": "contracts/knowledge.json",
            "memory": "contracts/memory.json",
            "model": "contracts/model.json",
            "node_provider": "contracts/node_provider.json",
            "render": "contracts/render.json",
            "resources": "contracts/resources.json",
            "sandbox": "contracts/sandbox.json",
            "scheduler": "contracts/scheduler.json",
            "session": "contracts/session.json",
            "state": "contracts/state.json",
            "tools": "contracts/tools.json",
            "trace": "contracts/trace.json",
        },
        "bindings": {},
        "patterns": ["patterns/main.yaml"],
        "prompts": [],
        "tools": [],
        "policies": [],
        "strategies": [],
        "formatters": [],
    }
    assembly_spec = {
        "schema_version": "0.1",
        "agent": {"id": "test_agent", "name": "Test Agent", "version": "0.1.0"},
        "runtime": {"pattern_id": "main", "user_config": {}, "agent_config": {}},
        "graph_overrides": {"node_wrappers": []},
        "bindings": {"hooks": [], "node_bindings": [], "services": []},
        "tools": [],
        "output": {"citations_required": False, "format": "text"},
        "harness": [],
        "metadata": {},
    }
    pattern = {
        "pattern_id": "main",
        "kind": "main",
        "embeddable": False,
        "version": 1,
        "name": "Main",
        "description": "Minimal executable pattern.",
        "metadata": {"summary": "", "use_when": [], "avoid_when": [], "selection_notes": [], "tags": []},
        "entry_node": "ingress",
        "nodes": [
            {"id": "ingress", "type": "reserved", "impl": "ingress", "config": {}, "wrappers": []},
            {"id": "finalize", "type": "terminal", "impl": "finalize", "config": {}, "wrappers": []},
        ],
        "edges": [{"from": "ingress", "to": "finalize", "when": "always"}],
        "interrupt_points": [],
        "termination": {"success_nodes": ["finalize"], "failure_nodes": []},
        "constraints": {"allowed_node_types": [], "required_capabilities": []},
        "input_contract": {"readable_sections": [], "writable_sections": []},
        "output_contract": {"readable_sections": [], "writable_sections": []},
        "slots": [],
        "exit_routes": [],
        "state_mode": "shared",
    }
    render_manifest = {
        "version": "render_manifest.v0",
        "graph_id": "test_agent",
        "producer_type": "agent",
        "nodes": {
            "ingress": {
                "node_id": "ingress",
                "label": "Ingress",
                "kind": "reserved",
                "purpose": "Accept input.",
                "doing": "Preparing the run.",
                "expected_output": "Initial state is ready.",
                "visible_to_user": True,
            },
            "finalize": {
                "node_id": "finalize",
                "label": "Finalize",
                "kind": "terminal",
                "purpose": "Complete the run.",
                "doing": "Finalizing output.",
                "expected_output": "Run is complete.",
                "visible_to_user": True,
            },
        },
    }
    disabled_contracts = {
        "artifact": default_artifact_contract(),
        "context": default_context_contract(),
        "dependencies": default_dependencies_contract(),
        "knowledge": default_knowledge_contract(),
        "memory": default_memory_contract(),
        "model": default_model_contract(),
        "node_provider": default_node_provider_contract(),
        "sandbox": default_sandbox_contract(),
        "scheduler": default_scheduler_contract(),
        "state": default_state_contract(),
        "tools": default_tools_contract(),
        "trace": default_trace_contract(),
    }
    session_contract = default_session_contract()
    session_contract = session_contract.model_copy(
        update={
            "config": session_contract.config.model_copy(
                update={"checkpointer_backend": "memory", "checkpoint_path": ".agent_runtime/checkpoints/test.sqlite"}
            )
        }
    )

    _write_json(root / "agent_package.json", manifest)
    _write_json(root / "assembly_spec.json", assembly_spec)
    _write_json(root / "patterns" / "main.yaml", pattern)
    _write_json(root / "render_manifest.json", render_manifest)
    _write_json(root / "resources.json", {"resources": {}})
    _write_json(root / "sandbox_contract.json", {})
    _write_json(root / "contracts" / "render.json", default_render_contract().model_dump(mode="json"))
    _write_json(root / "contracts" / "resources.json", default_resources_contract().model_dump(mode="json"))
    _write_json(root / "contracts" / "session.json", session_contract.model_dump(mode="json"))
    for name, contract in disabled_contracts.items():
        _write_json(root / "contracts" / f"{name}.json", contract.model_copy(update={"enabled": False}).model_dump(mode="json"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
