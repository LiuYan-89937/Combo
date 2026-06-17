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
4. When adding a capability, update all required package surfaces in one coherent step, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- Add the complete package tool as a coherent unit: tool.py, manifest ToolSpec, agent_package.json tools index, contracts/tools.json enablement, and assembly tool access.
- ToolSpec objects must be objects, not string references.
- Package tool entrypoints return the standard tool envelope; output_schema validates only envelope.output.
- Package tool code must use the `resources` argument for declared runtime selectors such as `runtime_root`; do not rely on `os.getcwd()` as the main resource contract.
- When tool.py imports non-stdlib Python modules that are not package-local and not `agent_factory`, update `contracts/dependencies.json` `config.python_requirements` in the same capability increment.
- Do not implement a tool that only tells the model to call another tool unless that other tool is visible in tool_access.
- After writing or changing a package tool, use create_agent_probe_tool inspect/call with realistic package tool arguments. Include prompt and tool_goal as human-readable probe context.
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
