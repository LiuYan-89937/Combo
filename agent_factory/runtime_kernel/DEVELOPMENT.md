[English](DEVELOPMENT.md) | [简体中文](DEVELOPMENT.zh-CN.md)

# Runtime Kernel Development

This document describes development boundaries for `RuntimeKernel`. It does not define Factory authoring-stage behavior or package-specific business configuration.

## 1. Positioning

`RuntimeKernel` is the unified execution platform for contract-assembled agents. It defines how agents run on LangGraph, how standard capabilities are attached, how graph patterns are compiled, and how execution state is persisted, resumed, observed, and tested.

```text
RuntimeKernel = LangGraph-based execution platform for contract-assembled agents
```

## 2. Development Goals

RuntimeKernel provides:

1. one runtime state model;
2. one standard node catalog;
3. one Graph Pattern DSL compiler;
4. one capability-binding interface;
5. execution control, interruption, and recovery;
6. trace, metrics, and debugging interfaces;
7. checkpoint and persistence integration;
8. a stable harness boundary.

## 3. Non-goals

RuntimeKernel does not:

- generate package-specific business behavior;
- generate business tool code;
- author knowledge content;
- define internal Factory authoring prompts;
- execute arbitrary user-provided LangGraph source directly.

## 4. Layering

### Layer 0: LangGraph and LangChain Infrastructure

This layer contains `StateGraph`, checkpoints, messages, tool protocols, and model abstractions. RuntimeKernel treats them as dependencies and does not duplicate them.

### Layer 1: Runtime Kernel Core

- Runtime State System
- Standard Node Catalog
- Graph Pattern Compiler
- Execution Controller
- Context, Tool, Memory, and Knowledge systems
- Interrupt and Approval Manager
- Checkpoint Manager
- Observability Manager
- Harness Bridge

### Layer 2: Capability Adapters

Adapters connect model, tool, memory, knowledge, context, and harness implementations to stable kernel contracts.

### Layer 3: Agent Assembly Instance

An Agent Assembly Spec selects and configures capabilities for one package. This layer consumes RuntimeKernel interfaces but does not belong to the kernel core.

## 5. Core Objects

### 5.1 RuntimeState

`RuntimeState` is shared by all agent types and includes conversation, context, tool, memory, execution, and observability state. It must be serializable, checkpoint-compatible, versioned, migratable, and stable enough for harness assertions.

### 5.2 Standard Nodes

Graph patterns reference a controlled catalog of standard or registered extension nodes. Core nodes include:

- `ingress`
- `answer`
- `tool_exec`
- `commit`
- `finalize`

Conversation memory uses the LangGraph `messages` channel and checkpointer. Cross-session memory uses the configured store rather than package-specific graph nodes.

### 5.3 Graph Pattern DSL

RuntimeKernel accepts a controlled DSL instead of arbitrary graph code. The DSL declares nodes, edges, subgraphs, interrupt points, routing, and termination rules. It must be validatable, compilable, versioned, and testable.

### 5.4 Capability Bindings

Prompt, tool, memory, knowledge, context, and harness bindings follow a common lifecycle and compilation boundary. Bindings describe attachment; they do not bypass runtime ownership.

## 6. Core Subsystems

### 6.1 State Schema System

Defines RuntimeState, schema versions, migrations, serialization, and recovery.

### 6.2 Graph Pattern Compiler

Validates the DSL, resolves registered nodes, attaches subgraphs, and compiles the LangGraph application.

### 6.3 Execution Controller

Controls execution loops, routing, iteration limits, timeouts, interruption, continuation, and finalization.

### 6.4 Context Engine

Collects context sources, applies visibility and ordering, enforces token budgets, and triggers compression using the effective runtime context limit.

### 6.5 Tool Orchestrator

Registers and exposes tools, applies approval policy, delegates execution to the unified gateway, normalizes observations, and handles retryable failures.

### 6.6 Memory Engine

Coordinates conversation persistence, cross-session extraction, write policy, scoped retrieval, redaction, and deletion.

### 6.7 Knowledge Engine

Coordinates ingestion, indexing, retrieval, opening, citation, and package/session ownership.

### 6.8 Interrupt and Approval Manager

Represents approval requests as resumable runtime state and prevents tools from executing outside their declared policy.

### 6.9 Checkpoint Manager

Owns checkpoint configuration, thread identity, persistence backend integration, deletion, and recovery.

### 6.10 Observability Manager

Emits structured trace events, model usage, tool activity, state transitions, errors, and performance metrics without injecting observability payloads into model context unnecessarily.

### 6.11 Harness Bridge

Exposes deterministic setup, input, state inspection, trace inspection, and cleanup boundaries for runtime validation.

## 7. Role of the Graph Pattern DSL

The DSL is an assembly contract, not a second programming language. It selects registered runtime behavior and topology while keeping implementation in typed kernel modules. Validation rejects unknown nodes, invalid routes, unsupported interrupts, and incompatible capability requirements before execution.

## 8. Engineering Sequence

The mature construction path is dependency-ordered:

1. state schemas and persistence boundaries;
2. standard nodes and registry;
3. DSL schema, validation, and compiler;
4. context, tool, memory, knowledge, and approval systems;
5. execution control, interruption, and recovery;
6. observability and harness integration.

This order describes dependencies, not separate product editions. Every stage targets the same final runtime architecture.

## 9. Acceptance Criteria

### RuntimeState

- serializes and restores without package-specific schema forks;
- supports explicit version migration;
- preserves ownership boundaries.

### Graph Pattern DSL

- rejects invalid nodes, edges, and routes;
- compiles supported patterns deterministically;
- remains versioned and inspectable.

### Compiler

- resolves only registered implementations;
- produces a runnable graph with the declared interrupts and termination rules;
- does not inject undeclared package behavior.

### Capability Systems

- attach through stable bindings;
- share one lifecycle and error model;
- preserve context and persistence boundaries.

### Observability

- records model, tool, state, and error events;
- distinguishes runtime evidence from model-visible context;
- supports session and task inspection.

### Harness

- can create isolated runtime inputs;
- can inspect final state and trace;
- can clean up without leaking sessions, files, or database handles.

## 10. Explicit Exclusions

RuntimeKernel does not maintain per-package runtime branches, silently widen filesystem access, treat package assets as automatically injected knowledge, or allow extensions to replace gateway policy.

## 11. Extension Guidance

New capabilities should begin with a typed contract and lifecycle owner, reuse existing gateway and persistence abstractions, and register through an explicit catalog. Avoid rule-based fixes in prompts or routers when the missing concept belongs in the runtime model.

## 12. Related Documentation

- [Project specification](../../project-documentation/ProjectOverview.md)
- [Agent architecture](../../project-documentation/AgentArchitecture.md)
- [Core capabilities](../../project-documentation/CoreCapabilities.md)
- [Deployment and acceptance](../../project-documentation/Deployment.md)
