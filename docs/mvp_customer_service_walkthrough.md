# FastAgentFactory MVP Customer-Service Walkthrough

This walkthrough demonstrates the CLI-first MVP using the customer-service Agent.

The MVP path is:

```text
create-agent
-> validate-agent
-> test-agent
-> register-agent
-> release
-> run-agent
-> unknown intent UpgradeRequest
-> plan/apply patch
-> validate/test v1.1.0
```

## 1. Initialize Factory Workspace

```bash
agentfactory init
```

Expected result: `.agentfactory/` exists with local Factory config, memory, trace, draft package, and registry folders.

## 2. Create Customer-Service Agent Draft

```bash
agentfactory create-agent \
  --prompt "创建一个客服 Agent，支持售前、售后、退款、投诉、转人工、订单查询和客服知识库查询" \
  --draft \
  --no-stream
```

Expected result:

- a draft package under `.agentfactory/packages/drafts/...`
- primitives YAML
- full package YAML
- generated draft tools
- generated tool tests
- `mcp.yaml`
- `harness.yaml`
- local verification reports

Generated low-risk tools are now executable local mock/read-only implementations. The Factory asks the model for structured tool code, scans it for unsafe imports/calls, writes generated unit tests, and only lets Runtime execute low-risk draft tools after the tests pass.

You can inspect and select generated drafts without copying paths:

```bash
agentfactory drafts list
agentfactory drafts show latest
agentfactory drafts run latest --input "帮我查一下订单 123"
```

In `agentfactory shell`:

```text
/drafts
/drafts show latest
/drafts use latest
/run --input "帮我查一下订单 123"
```

When the generated AgentPackage has no independent model provider config, `run-agent` uses the Factory workspace `.env` by default.

## 3. Validate and Test

```bash
agentfactory validate-agent .agentfactory/packages/drafts/customer-service-agent
agentfactory test-agent .agentfactory/packages/drafts/customer-service-agent
```

`validate-agent` runs full package validation by default.

`test-agent` runs the AgentHarness runner, which now drives the runtime-backed path with fake model output in tests.

## 4. Register and Release

```bash
agentfactory register-agent .agentfactory/packages/drafts/customer-service-agent
agentfactory release customer-service-agent --version 1.0.0 --channel available
agentfactory registry list
```

The filesystem registry lives under `.agentfactory/registry`.

## 5. Run Agent

```bash
agentfactory run-agent customer-service-agent \
  --version 1.0.0 \
  --input "帮我查一下订单 123" \
  --session-id demo
```

Expected result:

- runtime type: workflow
- intent: `order_query`
- safe generated tool routed through `ToolRouter -> ToolExecutor`
- final answer summarizes the controlled tool result
- agent trace and memory written inside the AgentPackage, separate from Factory memory

Conversation history is file-backed. Reusing the same `--session-id` lets the Agent read recent turns from `memory/session_memory.jsonl`:

```bash
agentfactory run-agent customer-service-agent --version 1.0.0 --session-id demo --input "我叫刘岩"
agentfactory run-agent customer-service-agent --version 1.0.0 --session-id demo --input "我叫什么？"
```

## 6. Unknown Intent Upgrade Request

```bash
agentfactory run-agent customer-service-agent \
  --version 1.0.0 \
  --input "我要返厂维修"
```

Expected result:

- runtime status: `needs_upgrade`
- upgrade request file under the package `upgrades/` directory

## 7. Patch to v1.1.0

```bash
agentfactory plan-upgrade .agentfactory/packages/drafts/customer-service-agent \
  --prompt "增加返厂维修意图" \
  --target-version 1.1.0 \
  --output .agentfactory/patch_plan.yaml

agentfactory approve-patch generated-tool-repair-ticket-create \
  --actor user \
  --patch-plan .agentfactory/patch_plan.yaml

agentfactory apply-patch-plan .agentfactory/packages/drafts/customer-service-agent \
  --output .agentfactory/packages/drafts/customer-service-agent-v1.1.0 \
  --target-version 1.1.0

agentfactory validate-agent .agentfactory/packages/drafts/customer-service-agent-v1.1.0
agentfactory test-agent .agentfactory/packages/drafts/customer-service-agent-v1.1.0
```

Expected v1.1.0 changes:

- `repair_return` scenario in `harness.yaml`
- `repair_ticket_create` generated draft tool
- confirmation required before high-risk execution

## Notes

- Default unit and integration tests use `FakeModelAdapter`; real OpenAI-compatible provider tests stay opt-in.
- Tool execution is controlled by Runtime, never by the LLM adapter.
- Factory memory and AgentInstance memory are physically separated.
- Secrets are redacted from trace and memory records.
