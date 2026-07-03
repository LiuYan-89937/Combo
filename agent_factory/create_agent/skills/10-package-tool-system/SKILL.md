---
name: 10-package-tool-system
description: Guides adding executable package tools and their ToolSpec declarations.
metadata:
  system_id: package_tool_system
  stage_order: 10
  load_when: package_tool_system
---
# Package Tool System

## Role
Guides adding executable package tools and their ToolSpec declarations.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The requested capability needs package-owned executable logic rather than existing built-in tools.
- The agent needs user-facing actions such as list management, transformation, lookup through confirmed resources, or package state updates.
- Validator reports ToolSpec, entrypoint, syntax, or binding issues.

## Focus Files
- `contracts/tools.json`
- `assembly_spec.json`
- `agent_package.json`
- `tools/<tool_id>/manifest.json`
- `tools/<tool_id>/tool.py`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When a package tool capability is ready, pass the complete ToolSpec, tool source, dependency list, and exposure targets to create_agent_authoring(action="upsert_package_tool"), then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only validator-indicated target files and paths; do not start a broad schema audit.

## Capability Write Guidance
- Add the complete package tool through create_agent_authoring(action="upsert_package_tool"); do not manually scatter writes across tool.py, manifest ToolSpec, agent_package.json tools index, contracts/tools.json, dependencies, and assembly tool access.
- Remove stale package tools through create_agent_authoring(action="remove_package_tool", tool_id=...); do not manually delete tool directories or manifest index entries.
- ToolSpec objects must be objects, not string references.
- ToolSpec fields are top-level fields: `id`, `description`, `entrypoint`, `input_schema`, `output_schema`, `resources`, `risk_level`, `risk_evaluator`, `concurrent`, and optional `output_compression`.
- `input_schema` only describes the runtime call arguments. Never put `output_schema`, `resources`, `risk_level`, `risk_evaluator`, `entrypoint`, `concurrent`, or `output_compression` inside `input_schema`.
- Add `tool_spec.output_compression.actions` when the tool output contains long lists, search candidates, external ids/slugs/paths, logs, reports, or other machine fields that must remain usable after compression. A single-link tool uses one action config; a multi-action tool sets `action_argument` and one config per action. Tools without an action config use the system default compression.
- Package tool entrypoints return the standard tool envelope; output_schema validates only envelope.output.
- Package tool code must use the `resources` argument for declared runtime selectors such as `runtime_root`; do not rely on `os.getcwd()` as the main resource contract.
- When tool.py imports non-stdlib Python modules that are not package-local and not `agent_factory`, pass installable distributions as `python_requirements` to create_agent_authoring.
- create_agent_authoring rejects package tool writes before any files are changed when third-party imports exist but `python_requirements` is empty.
- Use installable Python distribution names in `python_requirements`; if an import name differs from the distribution name, determine the correct distribution from package documentation or validator evidence instead of guessing.
- Do not implement a tool that only tells the model to call another tool unless that other tool is visible in tool_access.
- Create package tools only after model_pool_select/model bindings are complete and reusable SkillHub skills have been evaluated.
- If a reusable SkillHub skill already provides the capability, call `skillhub(action="search", query=...)`, install with the exact returned `install_name`, and expose the runtime `skill` tool through assembly tool access instead of rebuilding it as a package tool. The search query must be 1 to 3 short keywords or an exact skill name; split broad discovery into multiple focused searches instead of passing a long mixed query.
- After writing or changing a package tool, use create_agent_probe_tool inspect/call with realistic package tool arguments. Probe runs inside the Docker runtime image, performs dependency sandbox_init, and returns the real ToolExecutionGateway observation. Include prompt and tool_goal as human-readable probe context.
- Do not create tools that require unconfirmed secrets, accounts, URLs, files, or external services.

## Boundaries
- Do not hardcode secrets, API keys, account ids, external paths, URLs, schedules, delivery channels, or user data.
- Do not expose create-agent manufacturing tools, .factory files, traces, caches, or validation state as produced-agent runtime capability.
- Do not infer package schemas from project source code during manufacturing; use validator evidence and this skill's examples/resources.
- If required information is missing and cannot be discovered from confirmed resources, ask the user in natural language through create_agent_control.

## Validation And Focus
- Validator evidence should guide repairs but must not automatically change focus.
- Only explicit create_agent_stage(action="set_focus", focus_id=..., reason=...) changes focus.
- Run final validation only from validation_publish after the package behavior is actually implemented.

## Resource Loading
- Use a listed capability example when this skill provides one; otherwise rely on current package files and validator evidence.
- Read repair hints or validator scope only when validation evidence points here.
- Read schema only for a concrete validator failure path or when examples do not define the needed object shape.

Examples:
- `examples/package_tool_system.capability.json`

Repair references:
- `references/package_tool_system.repair_hints.md`
- `references/package_tool_system.common_errors.md`
- `references/package_tool_system.validator_scope.md`

Schema reference, last resort:
- `references/package_tool_system.schema.json`
