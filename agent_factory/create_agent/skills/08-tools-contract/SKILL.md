---
name: 08-tools-contract
description: Use when configuring tool availability for the agent. Covers builtin tool inheritance, package tools, MCP extensions, and tool_access bindings.
metadata:
  system_boundary: tools-contract
  load_when: tools-contract, tool-binding, tool-provider, package-tools-config
---

# Tools Contract

## When to load

Load this skill when working on `contracts/tools.json` or when validation mentions tools_contract.

## Hard Constraints

1. `contracts/tools.json` must have `"type": "tools"` and `"version": "tools_contract.v0"`.
2. The tools_contract does NOT manually list individual tools. It configures **providers** that auto-discover tools at runtime.

## Core Concept: Tool Providers

The RuntimeKernel resolves tools through three providers (all enabled by default):

| Provider | Config flag | What it does |
|----------|-------------|--------------|
| **Builtin** | `config.builtin_tools_enabled: true` | Auto-registers read, write, edit, glob, grep, ls, bash, scheduler, knowledge, tool_output, resource_set |
| **Package** | `config.package_tools_enabled: true` | Scans `tools/` directory for Python entrypoints with manifest |
| **Extensions** | `config.instance_extensions_enabled: true` | Loads MCP servers and extensions from instance extension root |

**Most agents need no changes to the default tools_contract.** The scaffold default already enables all three providers.

## Decision Rules

```
IF agent needs standard file/shell tools only:
  → Keep default tools_contract (all providers enabled)
  → No changes needed

IF agent needs custom HTTP/API tools:
  → Keep providers enabled
  → Create package tools in tools/ directory (see skill 09-package-tools)

IF agent needs MCP server tools:
  → Keep instance_extensions_enabled: true
  → Configure MCP servers in the instance extension root

IF agent should NOT have shell access:
  → Set config.builtin_tool_ids to exclude "bash"
  → Or use tool_access binding in assembly to restrict per-node
```

## Minimal Working Example

```json
{
  "type": "tools",
  "version": "tools_contract.v0",
  "config": {
    "builtin_tools_enabled": true,
    "builtin_tool_ids": [],
    "builtin_workspace_root": "/workdir",
    "builtin_allow_external_paths": false,
    "package_tools_enabled": true,
    "instance_extensions_enabled": true,
    "instance_extension_root": ".agent_runtime/extensions"
  }
}
```

When `builtin_tool_ids` is empty `[]`, ALL implemented builtin tools are available. To restrict, list specific ids (see `references/builtin_tool_ids.md`).

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| No tools available at runtime | All providers disabled | Ensure at least `builtin_tools_enabled: true` |
| Tool not found | Package tool entrypoint missing or MCP server not configured | Check tools/ directory structure (skill 09) |
| `Extra inputs are not permitted` | Wrong field names in config | Use exact field names from schema |

## Resources

- `references/tools_contract.schema.json` — ToolsContract JSON schema
- `references/builtin_tool_ids.md` — Complete list of builtin tool IDs
- `examples/tools_contract.minimal.json` — Minimal valid tools_contract
