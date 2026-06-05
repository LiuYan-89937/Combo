---
name: 02-runtime-contract-index
description: RuntimeKernel compilation reference. Lists all 14 required contracts, their roles, dependencies, and which skill provides detailed guidance for each.
metadata:
  system_boundary: runtime-contract-index
  load_when: contract-selection, runtime-build-failed, missing-required-contracts
---

# Runtime Contract Index

## When to load

Load this skill when planning which contracts to configure, or when `runtime_contracts.build` fails.

## Hard Constraint

`agent_package.json.contracts` MUST declare all 14 required contract keys. The scaffold already generates defaults for all of them. You configure the ones relevant to user requirements; leave others at defaults.

## Required Contracts (all 14)

| Key | File | Role | Detail Skill |
|-----|------|------|--------------|
| `artifact` | `contracts/artifact.json` | Output artifact storage | 14-render-and-events |
| `context` | `contracts/context.json` | Prompt context window management | 03-context-contract |
| `dependencies` | `contracts/dependencies.json` | Package dependency declarations | (use default) |
| `knowledge` | `contracts/knowledge.json` | RAG knowledge sources | 05-knowledge-contract |
| `memory` | `contracts/memory.json` | Cross-session long-term memory | 04-memory-contract |
| `model` | `contracts/model.json` | Model service configuration | (use default) |
| `node_provider` | `contracts/node_provider.json` | Package node registration | 10-package-nodes |
| `render` | `contracts/render.json` | UI rendering config | 14-render-and-events |
| `resources` | `contracts/resources.json` | Runtime resource declarations | 07-state-resources-contract |
| `sandbox` | `contracts/sandbox.json` | Sandbox/isolation config | (use default) |
| `scheduler` | `contracts/scheduler.json` | Scheduler runtime config | 11-scheduler-contract |
| `session` | `contracts/session.json` | Session persistence config | 16-session-contract |
| `state` | `contracts/state.json` | State namespace declarations | 07-state-resources-contract |
| `tools` | `contracts/tools.json` | Tool provider configuration | 08-tools-contract |
| `trace` | `contracts/trace.json` | Execution trace/observability | 06-trace-contract |

## Decision Rules

```
For EVERY agent:
  → tools, session, context, state, resources, trace: keep defaults or configure

IF agent needs scheduled tasks (cron, daily push):
  → Configure scheduler contract (skill 11)
  → Add scheduler_seed contract (skill 12) — requires adding to agent_package.json.contracts

IF agent needs knowledge/RAG:
  → Configure knowledge contract (skill 05)

IF agent needs persistent memory:
  → Configure memory contract (skill 04)

IF agent needs custom package nodes:
  → Configure node_provider contract (skill 10) — rare

Everything else: leave at scaffold defaults.
```

## Contract Dependencies

- `scheduler` tool auto-injection requires `scheduler` contract with `store_path` configured
- `knowledge` tool auto-injection requires `knowledge` contract with sources configured
- `node_provider` manifests must reference files that exist in the package
- `tools.config.builtin_tools_enabled` controls which builtin tools are available

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `missing required contracts: X, Y` | agent_package.json.contracts doesn't list all 14 | Run `create_agent_scaffold(action=ensure_base_package)` |
| `runtime_contracts.build failed` | A contract file has invalid schema | Check the specific contract file against its schema |
| `RuntimeKernelError: unknown node provider id` | node_provider.json has wrong provider_id | Must be `builtin.package_nodes` (see skill 10) |

## Resources

- `references/contract_index.schema.json` — RuntimeContractEnvelope schema
- `examples/runtime_contract_index.minimal.json` — Minimal contract envelope
