---
name: 10-package-nodes
description: Use ONLY when deterministic graph logic requires a package-local node that cannot be expressed by builtin cognitive/operational nodes. Most agents do NOT need this.
metadata:
  system_boundary: package-nodes
  load_when: package-node, node-provider, custom-node, Unknown node impl error
---

# Package Nodes

## When to load

Load this skill ONLY when you have confirmed that no builtin node impl satisfies the requirement. This is rare.

## Decision Tree (MUST follow before creating a package node)

```
Does the node need LLM reasoning/answering?
  YES → Use cognitive.answer (builtin). Do NOT create a package node.

Does the node need to execute tools?
  YES → Use operational.tool_call (builtin). Do NOT create a package node.

Does the node need deterministic code logic (state machine, data transform, validation)?
  YES → Create a package node. Continue reading.

Everything else → Use builtin nodes. See skill 13-assembly-and-patterns.
```

**99% of agents do not need package nodes.** The builtin `react_agent` pattern with `cognitive.answer` + `operational.tool_call` handles most use cases through LLM reasoning and tool calls.

## Hard Constraints (violation = compile failure)

1. Package node `impl_id` MUST start with `package.` prefix.
   - Valid: `package.data_transform`, `package.state_validator`
   - Invalid: `stock_analyst`, `my_node`, `custom.thing`

2. `node_provider.json` providers MUST use `provider_id: "builtin.package_nodes"`.
   - This is a fixed constant, not a user-chosen name.

3. Provider config has only one valid field: `manifest_paths` (array of strings pointing to manifest files).

4. Manifest path format: `nodes/<impl_name>/manifest.json`

5. Entrypoint format: `nodes/<impl_name>/node.py:run`

6. Node Python entrypoint signature: `def run(context: Any) -> dict[str, Any]`

## Correct node_provider.json

```json
{
  "type": "node_provider",
  "version": "node_provider_contract.v0",
  "enabled": true,
  "config": {
    "providers": [
      {
        "provider_id": "builtin.package_nodes",
        "config": {
          "manifest_paths": ["nodes/my_transform/manifest.json"]
        }
      }
    ]
  }
}
```

## Correct manifest (nodes/my_transform/manifest.json)

```json
{
  "version": "package_node.v0",
  "impl_id": "package.my_transform",
  "node_type": "operational",
  "entrypoint": "nodes/my_transform/node.py:run",
  "description": "Deterministic data transformation logic.",
  "input_schema": {"type": "object", "additionalProperties": true},
  "output_schema": {"type": "object", "additionalProperties": true},
  "readable_sections": [],
  "writable_sections": [],
  "required_services": [],
  "tool_access": []
}
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Unknown node impl: X` | impl_id doesn't start with `package.` or provider not configured | Add `package.` prefix AND configure node_provider.json |
| `unknown node provider id: X` | Wrong provider_id in node_provider.json | Must be exactly `builtin.package_nodes` |
| `Extra inputs are not permitted` | Wrong fields in provider config | Only `provider_id` and `config.manifest_paths` are valid |
| `impl_id must start with package.` | Missing package. prefix | Rename to `package.your_name` |

## Resources

- `references/package_node.schema.json` — PackageNodeManifest schema
- `examples/package_node.minimal.json` — Minimal valid manifest
