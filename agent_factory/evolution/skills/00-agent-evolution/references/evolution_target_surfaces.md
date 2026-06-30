# Evolution Target Surfaces

Use this reference only when deciding where a requested evolution belongs.

| User request type | Primary target surface | Preferred write action |
| --- | --- | --- |
| Add or change executable behavior | `tools/<tool_id>/tool.py`, ToolSpec, dependencies, assembly exposure | `create_agent_authoring(action="upsert_package_tool")` |
| Change only dependency metadata | `contracts/dependencies.json` | `create_agent_authoring(action="configure_dependencies")` |
| Change plan/executor/final answer behavior | `assembly_spec.json`, `render_manifest.json` | `create_agent_authoring(action="configure_pattern_assembly")` |
| Change package identity text | `agent_package.json`, `assembly_spec.json` | `create_agent_authoring(action="set_identity")` |
| Add package knowledge file | `knowledge/*`, `contracts/knowledge.json` if needed | `create_agent_authoring(action="upsert_knowledge_file")` |
| Add runtime resources | `resources.json`, `contracts/resources.json` | `create_agent_authoring(action="upsert_resources")` |
| Add scheduler seed | `contracts/scheduler_seed.json` | `create_agent_authoring(action="upsert_scheduler_seed")` |
| Repair malformed scaffold contract | `contracts/<key>.json` | `create_agent_authoring(action="reset_contract", contract_key=...)` |

If no authoring action can represent the needed managed-surface change, stop and report the missing authoring capability. Do not bypass managed file protection with generic filesystem tools.
