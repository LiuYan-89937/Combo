---
name: 12-assembly-pattern-system
description: Guides assembly bindings, runtime behavior, and optional custom patterns.
metadata:
  system_id: assembly_pattern_system
  stage_order: 12
  load_when: assembly_pattern_system
---
# Assembly Pattern System

## Role
Guides assembly bindings, runtime behavior, and optional custom patterns.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The produced agent needs its runtime prompt, model operation, tool access, bindings, output behavior, or optional custom pattern updated.
- Package tools/nodes must be connected to the react_agent runtime.
- Validator reports assembly compile or binding schema issues.

## Focus Files
- `assembly_spec.json`
- `patterns/`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When adding a capability, update all required package surfaces in one coherent step, then stop tool calls so graph validation can run.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- The runtime system prompt belongs in assembly_spec.json prompt bindings unless the package explicitly adds prompt files and manifest indexing.
- Do not rewrite the whole assembly just to compare it with examples; edit the binding or tool section required by the capability.
- Keep prompt, tool_access, and model_operation bindings coherent for the same target node.
- Use complete examples for object shape only when adding or repairing bindings.

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
- `examples/assembly_pattern_system.capability.json`
- `examples/assembly_spec.with_tools_and_bindings.json`

Repair references:
- `references/assembly_pattern_system.repair_hints.md`
- `references/assembly_pattern_system.common_errors.md`
- `references/assembly_pattern_system.validator_scope.md`

Schema reference, last resort:
- `references/assembly_pattern_system.schema.json`
