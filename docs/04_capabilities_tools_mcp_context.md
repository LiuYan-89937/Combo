# 04. Capability / Tool / MCP / Context

## 目标

实现能力层的最小闭环：所有工具、MCP、上下文都通过 Capability 抽象进入 Registry 和 Runtime，Agent 不直接绑定实现对象。

这一阶段要解决的问题：

```text
1. Runtime 节点如何调用工具，但不直接依赖工具实现？
2. MCP Server 暴露的外部能力如何进入内部 Capability 体系？
3. Context 如何被加载、选择、编译，并控制对模型和工具的可见性？
4. Factory 生成的工具代码如何进入草稿区、测试区、审批区？
5. 高风险能力如何在调用前触发 human_confirm？
```

## 设计原则

```text
1. Agent 绑定 CapabilityRef，不绑定实现对象。
2. Runtime 只能通过 RuntimeContext 调能力。
3. Tool / MCP / Context 都是 Capability 的派生类型。
4. Capability 顶层字段统一，领域字段由子类型扩展。
5. 工具调用必须经过 ToolRouter 和 PolicyEngine。
6. MCP 不能裸露给 Agent，必须先映射成内部 Capability。
7. Context 不是拼 prompt，而是可选择、可编译、可见性受控的对象。
8. Factory 生成代码默认不可信，必须走静态检查、沙箱测试、Harness、审批。
```

## 核心模块

```text
agent_factory/capability/
├── base.py
├── refs.py
├── status.py
├── tool_capability.py
├── mcp_capability.py
├── context_capability.py
├── guardrail_capability.py
└── catalog.py

agent_factory/tools/
├── base_tool.py
├── tool_router.py
├── tool_executor.py
├── tool_schema.py
├── tool_result.py
├── tool_invocation.py
├── generated_tool.py
└── generated_tool_gate.py

agent_factory/mcp/
├── mcp_client.py
├── mcp_manager.py
├── mcp_binding.py
├── mcp_adapter.py
├── mcp_health.py
├── mcp_capability_importer.py
└── mcp_result.py

agent_factory/context/
├── context_manager.py
├── context_source.py
├── context_bundle.py
├── context_loader.py
├── context_selector.py
├── context_compiler.py
├── context_visibility.py
└── context_result.py
```

## Capability

### BaseCapability

所有 Capability 至少包含：

```python
class BaseCapability(BaseModel):
    id: CapabilityRef
    name: str
    type: CapabilityType
    version: str
    status: CapabilityStatus
    risk_level: RiskLevel
    owner: str | None = None
    schema_ref: str | None = None
    harness_status: HarnessStatus | None = None
    hot_update_allowed: bool = False
```

第一版 Capability 类型：

```text
ToolCapability
MCPCapability
ContextCapability
GuardrailCapability
```

后续可扩展：

```text
MemoryCapability
RetrieverCapability
ModelCapability
EvalCapability
WorkflowCapability
```

说明：第一版模型调用边界由 `04_model_llm_interaction.md` 定义，`ModelCapability` 暂时作为后续 Registry 化模型资产的扩展方向，不在本阶段接管模型调用。

### CapabilityRef

CapabilityRef 是 AgentPackage 和 Runtime 之间的稳定引用。

```text
tool.order_query@1.0.0
mcp.customer_kb.search_policy@1.0.0
context.customer_service_policy@1.0.0
guardrail.high_risk_tool_confirm@1.0.0
```

规则：

```text
1. AgentPackage 绑定 CapabilityRef。
2. Runtime 根据 CapabilityRef 从 Registry / CapabilityCatalog 获取可用能力。
3. CapabilityRef 不能直接指向 Python 对象。
4. 不同版本 Capability 必须可共存。
5. Disabled / Failed 的 Capability 不能被 Runtime 调用。
```

## Tool

### ToolCapability

```python
class ToolCapability(BaseCapability):
    input_schema: JsonSchema
    output_schema: JsonSchema
    permissions: ToolPermissions
    execution: ToolExecutionPolicy
    risk: ToolRiskPolicy
    implementation: ToolImplementation
```

### Tool 调用链

```text
Runtime Node
  ↓
ToolRouter.select / ToolRouter.call
  ↓
PolicyEngine.check_tool_permission
  ↓
ToolInput validation
  ↓
human_confirm interrupt if needed
  ↓
ToolExecutor
  ↓
BaseTool.run
  ↓
ToolResult validation
  ↓
TraceSpan
```

### 核心对象

```python
class ToolInvocation(BaseModel):
    invocation_id: str
    tool_ref: CapabilityRef
    input: dict[str, Any]
    caller_node_id: str
    trace_id: str
    risk_level: RiskLevel

class ToolResult(BaseModel):
    invocation_id: str
    status: Literal["success", "failed", "interrupted"]
    output: dict[str, Any] | None = None
    error: ToolError | None = None
    requires_confirmation: bool = False
```

`input` 和 `output` 可以是动态 mapping，但必须被 `ToolInvocation` / `ToolResult` 对象包住，不允许裸 dict 在 Runtime 中流动。

### ToolRouter 职责

```text
1. 根据 CapabilityRef 找到 ToolCapability。
2. 检查工具状态是否可用。
3. 检查 policy 是否允许调用。
4. 检查 risk_level 是否需要 human_confirm。
5. 校验 input_schema。
6. 调用 ToolExecutor。
7. 校验 output_schema。
8. 写入 trace。
```

### Factory 生成工具

Factory 生成工具必须先进入草稿区：

```text
generated/draft_tools/
├── repair_ticket_create.py
└── repair_ticket_create.tool.yaml
```

准入流程：

```text
generated draft
  ↓
static check
  ↓
sandbox test
  ↓
tool harness
  ↓
ApprovalRecord
  ↓
CapabilityRegistry Candidate
  ↓
Available
```

规则：

```text
1. Factory 生成工具必须声明 implementation.source=factory_generated。
2. 未通过静态检查不能进入 Harness。
3. 未通过沙箱测试不能进入 Harness。
4. high / critical 工具必须有 ApprovalRecord。
5. 未审批生成工具不能进入 Available。
6. 写操作工具不能立即热更新，必须走新版本发布。
```

## MCP

MCP 是第一版必须实现的外部能力接入方式。MCP Server 暴露的 tools、resources、prompts 不直接给 Agent 使用，必须经过映射、过滤、风险归类，再进入内部 Capability 体系。

### MCP 接入链

```text
mcp.yaml
  ↓
MCPClientManager
  ↓
MCP health_check
  ↓
tools/list
  ↓
MCPBinding
  ↓
MCPCapability
  ↓
CapabilityRegistry
  ↓
Runtime call_mcp
```

### MCPCapability

```python
class MCPCapability(BaseCapability):
    server_id: str
    mcp_tool_name: str | None = None
    mcp_resource_uri: str | None = None
    input_mapping: MappingExpression
    output_mapping: MappingExpression
    trust: MCPTrustPolicy
```

### MCPClientManager 职责

```text
1. 管理 MCP Server 生命周期。
2. 执行 health_check。
3. 调用 tools/list 发现工具。
4. 调用 tools/call 执行工具。
5. 管理 MCPBinding。
6. 将 MCP tool 映射为 MCPCapability。
7. 对 MCP 输出进行 sanitization。
8. 将 MCP 输入输出写入 trace。
```

### 第一版 MCP 范围

必做：

```text
1. stdio transport。
2. tools/list。
3. tools/call。
4. health_check。
5. MCPBinding。
6. MCP tool 转 MCPCapability。
7. MCP tool risk_level 进入 PolicyEngine。
8. 敏感 MCP tool 调用触发 human_confirm。
```

暂不做：

```text
1. 复杂 OAuth。
2. 多租户 MCP 权限。
3. MCP Server Marketplace。
4. 复杂 prompts/resources 策略。
5. 远程 MCP 高可用连接池。
```

## Context

Context 不是简单 prompt 拼接，而是可管理对象。

### ContextCapability

```python
class ContextCapability(BaseCapability):
    source_type: ContextSourceType
    priority: int
    required: bool
    refresh_policy: ContextRefreshPolicy
    visibility_policy: ContextVisibilityPolicy
```

### Context 调用链

```text
Runtime Node load_context
  ↓
ContextManager.load
  ↓
ContextLoader
  ↓
ContextSelector
  ↓
ContextCompiler
  ↓
ContextVisibilityPolicy
  ↓
ContextBundle
```

### ContextBundle

```python
class ContextBundle(BaseModel):
    bundle_id: str
    sources: list[CompiledContextItem]
    visible_to_model: list[CompiledContextItem]
    visible_to_tools: list[CompiledContextItem]
    hidden: list[CompiledContextItem]
    token_estimate: int
```

### ContextManager 职责

```text
1. 加载 required context。
2. 加载 optional context。
3. 按 priority / recency / relevance 选择上下文。
4. 控制 max_context_tokens。
5. 执行 compression_policy 占位。
6. 执行 visibility_policy。
7. 禁止 tool_auth_token 暴露给模型。
8. 输出 ContextBundle 对象。
```

### 可见性规则

```text
1. hidden_from_model 永远不能进入模型输入。
2. visible_to_tools 只给工具调用使用。
3. visible_to_model 只能包含允许模型看到的内容。
4. 敏感字段默认 hidden。
5. 长期记忆进入 ContextCompiler 前必须先过 visibility_policy。
```

## GuardrailCapability

第一版只保留最小抽象，具体 Guardrail 深化放到后续阶段。

```text
1. tool_input_guardrail
2. tool_output_guardrail
3. context_visibility_guardrail
4. high_risk_action_guardrail
```

Guardrail 在 04 阶段只要求能注册和被 PolicyEngine 引用，不要求实现完整策略引擎。

## 必做任务

```text
1. 实现 BaseCapability、CapabilityRef、CapabilityStatus、CapabilityType。
2. 实现 ToolCapability、MCPCapability、ContextCapability。
3. 实现 CapabilityCatalog 读取 Registry 中的能力记录。
4. 实现 BaseTool、ToolRouter、ToolExecutor、ToolInvocation、ToolResult。
5. 实现 Factory 生成工具的 generated_tool_gate。
6. 实现 MCPClientManager、MCPBinding、MCPCapability importer。
7. 实现 stdio MCP tools/list 和 tools/call 的最小封装。
8. 实现 ContextManager、ContextLoader、ContextSelector、ContextCompiler、ContextBundle。
9. 实现 visibility_policy，确保敏感字段不会暴露给模型。
10. 将 Tool / MCP / Context 调用全部写入 trace。
```

## 验收标准

```text
1. ToolRouter 只能调用 policy 允许的工具。
2. high / critical 工具会返回 human_confirm interrupt。
3. Tool input_schema 校验失败时不会执行工具。
4. Tool output_schema 校验失败时返回 failed ToolResult。
5. Factory 生成工具代码未审批时不能进入 Available。
6. MCP Server 可以完成 tools/list。
7. MCP tool 可以被映射为 MCPCapability。
8. call_mcp 可以通过 MCPClientManager 执行 mock MCP tool。
9. ContextCompiler 不会把 tool_auth_token 暴露给模型。
10. ContextManager 输出 ContextBundle 对象。
11. Runtime 节点不直接调用具体 Tool / MCP / Context 实现。
```

## 不做

```text
1. 不做复杂 MCP OAuth。
2. 不做大型向量检索。
3. 不做多租户权限。
4. 不做生产级工具沙箱。
5. 不做完整 Guardrail 策略引擎。
6. 不做真实不可逆写操作。
7. 不做 MCP Server Marketplace。
```
