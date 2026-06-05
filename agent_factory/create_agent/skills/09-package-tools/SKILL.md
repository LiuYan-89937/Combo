---
name: 09-package-tools
description: Use when creating custom tool implementations in the tools/ directory. Covers manifest, entrypoint, schemas, and runtime compilation requirements.
metadata:
  system_boundary: package-tools
  load_when: package-generated-tool, tool-compile-error, custom-tool
---

# Package Tools

## When to load

Load this skill when you need to create a custom tool that doesn't exist as a builtin or MCP extension.

## Hard Constraints

1. Tool directory structure: `tools/<tool_id>/manifest.json` + `tools/<tool_id>/tool.py`
2. `manifest.json` must be a valid ToolSpec (see `references/package_tool.schema.json`)
3. `entrypoint` format: `tools/<tool_id>/tool.py:run`
4. Entrypoint function signature: `def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]`
5. `input_schema` and `output_schema` must be valid JSON Schema objects with `"type": "object"`
6. `id` must be snake_case: `^[a-z][a-z0-9_]*$`
7. Tool is auto-discovered when `tools_contract.config.package_tools_enabled = true`

## Minimal Working Example

### tools/fetch_news/manifest.json
```json
{
  "id": "fetch_news",
  "description": "Fetch latest news headlines from a public RSS feed.",
  "entrypoint": "tools/fetch_news/tool.py:run",
  "input_schema": {
    "type": "object",
    "properties": {
      "source_url": {"type": "string", "description": "RSS feed URL"},
      "max_items": {"type": "integer", "default": 10}
    },
    "required": ["source_url"],
    "additionalProperties": false
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "headlines": {"type": "array", "items": {"type": "object"}},
      "fetched_at": {"type": "string"}
    },
    "required": ["headlines", "fetched_at"],
    "additionalProperties": false
  },
  "risk_level": "low",
  "concurrent": true
}
```

### tools/fetch_news/tool.py
```python
from typing import Any
from datetime import datetime, UTC
import httpx

def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    source_url = arguments["source_url"]
    max_items = arguments.get("max_items", 10)
    # Fetch and parse RSS
    response = httpx.get(source_url, timeout=15)
    response.raise_for_status()
    # ... parse XML/RSS ...
    return {
        "headlines": [],  # parsed items
        "fetched_at": datetime.now(UTC).isoformat(),
    }
```

## Decision Rules

```
IF you need HTTP API calls, data fetching, or format conversion:
  → Create a package tool

IF you need LLM reasoning:
  → Do NOT create a tool. Use cognitive.answer node instead.

IF the capability exists as a builtin (read/write/bash/grep):
  → Do NOT create a tool. Use the builtin.
```

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `tool id must be snake_case` | Using kebab-case or camelCase | Use `fetch_news` not `fetch-news` |
| `entrypoint must use '<path>:<function>'` | Wrong format | `tools/name/tool.py:run` |
| Tool not discovered | package_tools_enabled is false | Check tools_contract config |
| Import error at runtime | Missing dependency | Declare in dependencies contract |

## Resources

- `references/package_tool.schema.json` — ToolSpec schema
- `examples/package_tool.minimal.json` — Minimal valid tool manifest
