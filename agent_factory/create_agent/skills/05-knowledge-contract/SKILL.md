---
name: 05-knowledge-contract
description: Use when the agent needs runtime knowledge sources (RAG, document catalog, or FTS). Configures knowledge retrieval and the auto-injected knowledge tool.
metadata:
  system_boundary: knowledge-contract
  load_when: knowledge, rag, documents, source-catalog
---

# Knowledge Contract

## When to load

Load when the agent needs access to documents, knowledge bases, or search-based retrieval at runtime.

## Hard Constraints

1. `contracts/knowledge.json`: `"type": "knowledge"`, `"version": "knowledge_contract.v0"`
2. Knowledge tool is auto-injected only when knowledge contract has configured sources.
3. Do not write user-private knowledge into package source files.

## Decision Rules

```
IF agent needs semantic search over documents:
  → Configure knowledge contract with sources
  → knowledge tool will be auto-available

IF agent only needs public web search:
  → Use a package tool or builtin bash+curl. Do NOT configure knowledge contract.

IF no retrieval needed:
  → Keep default empty knowledge contract
```

## Minimal Working Example

```json
{
  "type": "knowledge",
  "version": "knowledge_contract.v0",
  "config": {
    "enabled": false,
    "sources": []
  }
}
```

## Resources

- `references/knowledge_contract.schema.json`
- `examples/knowledge_contract.minimal.json`
