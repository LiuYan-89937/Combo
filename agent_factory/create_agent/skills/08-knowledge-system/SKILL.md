---
name: 08-knowledge-system
description: Guides knowledge contract and package knowledge assets for produced agents.
metadata:
  system_id: knowledge_system
  stage_order: 8
  load_when: knowledge_system
---
# Knowledge System

## Role
Guides knowledge contract and package knowledge assets for produced agents.

## Baseline Package Assumption
- The workspace starts with a scaffolded empty AgentPackage: required files, required contracts, and package asset directories already exist.
- Do not compare scaffolded files against schema or capability examples just to prove they are valid. The validator owns schema correctness.
- Treat focus files as suggested edit surfaces, not write locks. Edit cross-file references when one capability requires a coherent package change.
- Use examples to learn the smallest complete shape for a capability you are adding or repairing, not as a checklist for baseline scaffold files.
- Use schema resources only when validator evidence or an example is insufficient for a concrete failed path.

## When To Use This Skill
- The agent needs packaged knowledge files, retrieval config, domain references, or curated source material.
- A package tool/node depends on knowledge assets.
- Validator reports knowledge contract issues.

## Focus Files
- `contracts/knowledge.json`
- `knowledge/`

## Manufacturing Protocol
1. Inspect current focus and latest validation evidence with create_agent_stage(action="inspect") when the next action is unclear.
2. Read the current target package files before editing. Preserve unrelated valid scaffold content.
3. If the requested capability does not affect this focus, leave these files as-is and move to the next useful focus yourself.
4. When adding a capability, update all required package surfaces in one coherent step, then call create_agent_validate with the appropriate scope.
5. When validation fails, repair only the target files and paths indicated by validator evidence; do not start a broad schema audit.

## Capability Write Guidance
- Do not invent knowledge content or claim live external knowledge unless backed by confirmed resources/tools.
- Use knowledge/ for package-owned static assets; use resource facts for external or user-provided sources.
- Update the knowledge contract only when the package includes real knowledge assets or retrieval behavior.

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

Repair references:
- `references/knowledge_system.repair_hints.md`
- `references/knowledge_system.common_errors.md`
- `references/knowledge_system.validator_scope.md`

Schema reference, last resort:
- `references/knowledge_system.schema.json`
