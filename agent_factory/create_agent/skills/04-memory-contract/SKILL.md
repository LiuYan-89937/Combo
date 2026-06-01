---
name: 04-memory-contract
description: Use when an AgentPackage needs cross-session memory, long-term facts, or BaseStore-backed recall. Clarifies memory versus context compression and secret handling.
metadata:
  system_boundary: memory-contract
  load_when: memory, cross-session, long-term-facts
---

# Memory Contract

Memory stores durable cross-session facts. It is separate from current-session context compression.

Build rules:

- Use memory only when the produced agent should remember user, task, or domain facts across sessions.
- Keep namespaces isolated by owner/package/session where required.
- Do not store secrets or private credentials as memory facts.
- Use BaseStore-backed retrieval through the memory system instead of custom vector store code.
- Context may inject memory results, but memory owns persistence and retrieval semantics.

When not to include:

- The package only needs current run state.
- The package only needs a knowledge base supplied as explicit sources.

Acceptance:

- Memory contract contributes memory services without leaking secrets into state, events, or package source files.
