---
name: 00-agent-evolution
description: Guides evolution of an already published AgentPackage with target-first repair, scoped edits, validation, and auto-publish readiness.
metadata:
  system_id: agent_evolution
  stage_order: 0
  load_when: agent_evolution
---
# Agent Evolution

## Role
Guide changes to an already published AgentPackage. Evolution is not manufacturing a new package. It changes the selected published package in place, validates it like a new package, and lets the runtime publish the new package state after successful validation.

## Required Flow
1. Restate the user evolution goal in one concrete sentence.
2. Identify the target surface before editing: package tool, pattern assembly, prompt, dependency contract, runtime resource, knowledge, scheduler, state, or validation repair.
3. Read only the files needed for that target surface.
4. Choose one write strategy before editing:
   - `create_agent_authoring` for managed package surfaces.
   - generic `edit` or `write` only for unmanaged capability content.
5. Apply the complete coherent change for that target surface once.
6. If package tool behavior changed, run fresh `create_agent_probe_tool(action="inspect")` and `create_agent_probe_tool(action="call", probe_kind="success_path", ...)`.
7. Run `create_agent_validate(scope="full_static")`.
8. If validation fails, repair only the validator-indicated target files and repeat validation.
9. Finish by calling `create_agent_control(action="finalize")` only after validation passes.

## Target Surface Rules
- Package tool source, ToolSpec, manifest index, tool contract, dependencies, and assembly exposure are one coherent surface. Use `create_agent_authoring(action="upsert_package_tool")` with the complete tool source, complete ToolSpec, Python requirements, optional system packages/binaries, and exposure nodes.
- If the only needed change is dependency metadata, use `create_agent_authoring(action="configure_dependencies")` with `python_requirements`, `system_packages`, `system_binaries`, or `install_mode`.
- Do not manually edit managed files such as `agent_package.json`, `assembly_spec.json`, `contracts/*.json`, `tools/*/manifest.json`, package `resources.json`, `knowledge/`, or `state/`.
- If a required managed-surface field is not supported by the current authoring actions, stop and report the authoring gap. Do not try `edit` or `write` against managed contracts.
- For `plan_and_execute`, expose package tools only to `executor`. The planner only maintains `runtime_plan`; final_answer does not call tools.
- If the user goal is unrelated to a failed trace, do not repair the trace unless it blocks validation or runtime readiness.
- Docker, model-contract, checkpointer, ToolGateway, and RuntimeKernel infrastructure errors are not package evolution targets. Report them as environment/runtime blockers instead of modifying the package to compensate.

## Anti-Patterns
- Do not alternate between `reset_contract`, `upsert_package_tool`, and generic edits hoping validation will improve.
- Do not reset a contract unless validator evidence identifies that contract as malformed and no more specific authoring action applies.
- Do not call `create_agent_stage`; it is a manufacturing-only focus tool and published packages do not have manufacturing task analysis.
- Do not read broad schema resources or project source code to discover package structure when current package files and validator evidence are enough.
- Do not add hardcoded local paths, user-specific files, API keys, Docker socket paths, or one-off test fixtures.
- Do not treat stale probe records as proof after changing package code.

## Completion Criteria
- The user goal is implemented in the package surface that actually owns the behavior.
- Changed package tools have fresh successful-path probe evidence, unless an infrastructure blocker such as Docker daemon unavailable prevents probing.
- `create_agent_validate(scope="full_static")` passes.
- `create_agent_control(action="finalize")` is called exactly once after validation passes.

References:
- `references/evolution_target_surfaces.md`
