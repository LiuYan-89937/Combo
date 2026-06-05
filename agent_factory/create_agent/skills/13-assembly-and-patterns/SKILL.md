---
name: 13-assembly-and-patterns
description: Use when creating or repairing assembly_spec.json, pattern selection, node configuration, bindings, and graph structure. This is the primary skill for defining how the agent executes.
metadata:
  system_boundary: assembly-patterns
  load_when: assembly, pattern, binding, graph-compile-error, semantic.pattern_logic, semantic.bindings_empty
---

# Assembly And Patterns

## When to load

Load this skill when working on `assembly_spec.json`, `patterns/main.yaml`, or any validation error mentioning assembly/pattern/binding.

## Hard Constraints (violation = compile failure)

1. `assembly_spec.runtime.pattern_id` must be one of:
   - A builtin pattern id: `react_agent`, `clarify_then_act`
   - A package-local pattern id that matches a `pattern_id` field in a file listed in `agent_package.json.patterns[]`

2. Every `node.impl` in a pattern must be one of:
   - A builtin impl (see `references/builtin_impls.md` for the complete list)
   - A package node impl starting with `package.*` (requires node_provider setup — see skill 10)

3. Every `edge.when` must be a valid routing condition (see `references/builtin_impls.md` for complete list).

4. Pattern must have `entry_node` that matches a node id, and `termination.success_nodes` with at least one terminal/reserved node.

5. `BindingSet` schema is strict (`extra="forbid"`). Every field must match the schema exactly.

## Decision Rules

### Choosing a pattern

```
IF the agent needs dynamic reasoning + tool use (most agents):
  → Use builtin pattern: assembly_spec.runtime.pattern_id = "react_agent"
  → Set agent_package.json.patterns = []
  → Do NOT write patterns/main.yaml (scaffold default is fine)

IF the agent must collect required info before any action:
  → Use builtin pattern: assembly_spec.runtime.pattern_id = "clarify_then_act"
  → Set agent_package.json.patterns = []

IF neither builtin fits (rare — fixed deterministic pipeline):
  → Write a custom patterns/main.yaml
  → Set agent_package.json.patterns = ["patterns/main.yaml"]
  → assembly_spec.runtime.pattern_id must match the pattern_id in the YAML
```

### Choosing node impls (for custom patterns only)

```
Need LLM to reason and answer?      → cognitive.answer
Need LLM to choose between routes?  → cognitive.route
Need LLM to ask clarification?      → cognitive.clarify
Need tool execution?                 → operational.tool_call
Need policy/safety check?            → governance.precheck / governance.postcheck
Need to end successfully?            → terminal.commit + finalize
Need deterministic code logic?       → package node (see skill 10 — rare)
```

### Bindings

Bindings configure how nodes behave. Most agents using builtin patterns need NO bindings — the defaults work.

Add bindings only when you need to:
- Inject a custom prompt into a cognitive node (`binding_type: "prompt"`)
- Restrict which tools a node can see (`binding_type: "tool_access"`)
- Configure structured output (`binding_type: "model_operation"`)

See `references/binding_reference.md` for the complete binding_type and payload schemas.

## Minimal Working Example (builtin react_agent)

```json
{
  "schema_version": "0.1",
  "agent": {"id": "my_agent", "name": "My Agent"},
  "runtime": {"pattern_id": "react_agent"},
  "bindings": {"services": [], "node_bindings": [], "hooks": []},
  "tools": [],
  "output": {"format": "text"},
  "graph_overrides": {"node_wrappers": []},
  "harness": [],
  "metadata": {}
}
```

With this assembly_spec + `agent_package.json.patterns = []`, the agent uses the builtin react_agent pattern which includes: ingress → precheck → answer ↔ tool_exec → postcheck → commit → finalize.

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown node impl: X` | Using a non-existent impl id | Use only impls from `references/builtin_impls.md` or `package.*` |
| `pattern_id not found` | assembly_spec references a pattern that isn't registered | Use a builtin id or ensure the YAML is in `agent_package.json.patterns[]` |
| `Extra inputs are not permitted` in bindings | Wrong payload fields for the binding_type | Match payload to `references/binding_reference.md` |
| `validation_scope: assembly_compile failed` | Pattern YAML has invalid structure | Check node types, edge conditions, termination spec |

## Resources

- `references/builtin_impls.md` — Complete list of builtin node impls, edge conditions, and patterns
- `references/binding_reference.md` — All binding types, service kinds, hook points
- `references/assembly_spec.schema.json` — AgentAssemblySpec JSON schema
- `references/pattern.schema.json` — GraphPatternSpec JSON schema
- `references/assembly_spec.common_errors.md` — Extended error catalog
- `references/assembly_spec.repair_hints.md` — Repair strategies
