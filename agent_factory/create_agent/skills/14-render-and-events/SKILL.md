---
name: 14-render-and-events
description: Use when configuring render_manifest.json for CLI/WebUI display of agent execution progress. Maps graph nodes to user-facing labels.
metadata:
  system_boundary: render-events
  load_when: render, events, cli-ui, webui
---

# Render And Events

## When to load

Load when configuring how the agent's execution appears to the user (node labels, progress indicators).

## Hard Constraints

1. `render_manifest.json` must reference actual graph node IDs from the pattern.
2. Every node in the pattern should have a corresponding render entry.
3. Node labels should be clear and domain-neutral.

## Minimal Example

For a builtin `react_agent` pattern:

```json
{
  "graph_id": "my_agent",
  "nodes": {
    "ingress": {"node_id": "ingress", "label": "Receiving", "kind": "reserved", "purpose": "Accept input.", "doing": "Processing request.", "expected_output": "Ready."},
    "answer": {"node_id": "answer", "label": "Thinking", "kind": "cognitive", "purpose": "Reason and answer.", "doing": "Analyzing request.", "expected_output": "Response ready."},
    "tool_exec": {"node_id": "tool_exec", "label": "Working", "kind": "operational", "purpose": "Execute tools.", "doing": "Running tools.", "expected_output": "Results available."},
    "finalize": {"node_id": "finalize", "label": "Done", "kind": "terminal", "purpose": "Complete.", "doing": "Finalizing.", "expected_output": "Complete."}
  }
}
```

## Decision Rules

```
IF using builtin pattern:
  → Update render_manifest to match builtin pattern node IDs (ingress, precheck, answer, tool_exec, postcheck, commit, finalize)

IF using custom pattern:
  → Map each node_id from your pattern to a render entry
```

## Resources

- `references/render_manifest.schema.json` — RenderManifest schema
- `examples/render_manifest.minimal.json`
