# 11. Agent Building Primitives

## 目标

本文件定义 AgentFactory 生产个性化 Agent 时必须使用的底层标准件。

这些标准件不是业务功能清单，而是 AgentPackage 的制造零件。Factory 必须先把自然语言需求转成这些标准件，再继续生成 Runtime、Tool、MCP、Context、Harness 和升级策略。

核心原则：

```text
1. 不直接拼 prompt。
2. 不让每个 Agent 自己发明对话结构。
3. 不让工具、知识、输出、转交、护栏散落在 Runtime 里。
4. Factory 生成的 AgentPackage 必须包含所有标准件文件。
5. 空能力也要有文件和空集合，保证包结构稳定。
6. 标准件进入核心逻辑后必须是 Pydantic 对象，不是裸 dict。
```

## 必需文件

每个 AgentPackage 第一版必须包含：

```text
instructions.yaml
output.yaml
conversation.yaml
run_context.yaml
toolsets.yaml
knowledge.yaml
guardrails.yaml
handoffs.yaml
observability.yaml
```

允许空能力：

```text
toolsets.yaml      toolsets: []
knowledge.yaml     sources: [] / retrievers: []
handoffs.yaml      targets: []
guardrails.yaml    rules: []
```

但文件不能缺失。缺失文件是 fatal validation issue。

## Factory 生成顺序

```text
自然语言需求
  ↓
InstructionSpec
  ↓
OutputSpec
  ↓
ConversationSpec
  ↓
RunContextSpec
  ↓
ToolsetSpec / KnowledgeSpec / GuardrailSpec / HandoffSpec
  ↓
ObservabilitySpec
  ↓
Runtime / Tool / MCP / Context / Harness
  ↓
AgentPackage draft
```

这样 Factory 不是直接拼 prompt，而是先确定 Agent 的身份、输出、对话、依赖、工具组、知识、护栏、转交和观测边界。

## 正式产物与底层验证的边界

正式生产路径只有一条：

```text
用户自然语言需求
  ↓
AgentFactory
  ↓
AgentPackagePrimitives 对象
  ↓
PackageWriter
  ↓
9 个必需 YAML 标准件文件
  ↓
PackageValidator / AgentHarness
  ↓
AgentInstance 读取配置包并运行
```

此前用于客服机器人的手动构造示例，只是底层 smoke test：

```text
手动构造 AgentPackagePrimitives
  ↓
PrimitiveAgent
  ↓
ModelService
```

这个 smoke test 只证明消息、输出 schema、模型调用和 primitives 对象可以串通。它不能代表 AgentFactory 的制造流程，也不能替代 YAML AgentPackage。Factory 的职责是生成可复现、可追踪、可校验的配置包，而不是在内存里临时拼一个 Agent。

## 工具函数与自测如何进入包

配置包不把 Python 代码塞进 YAML。YAML 只声明工具、权限、输入输出 schema、测试场景和加载引用；真正的工具实现与自测用例是 AgentPackage 内的文件 artifact。

推荐第一版结构：

```text
customer-service-agent/
  instructions.yaml
  output.yaml
  conversation.yaml
  run_context.yaml
  toolsets.yaml
  knowledge.yaml
  guardrails.yaml
  handoffs.yaml
  observability.yaml
  tools/
    order_query.py
    refund_policy_query.py
  harness/
    harness.yaml
    cases/
      refund_basic.yaml
      order_query.yaml
```

加载规则：

```text
1. ToolsetSpec 暴露工具 id 和策略。
2. Tool / Capability 规范记录工具实现位置、函数名、输入输出 schema 和风险等级。
3. ToolRouter 根据声明找到工具实现，但不让 LLM 直接执行。
4. PolicyEngine 在执行前做权限、审批和风险检查。
5. HarnessRunner 根据 harness.yaml 和 cases 运行包内自测。
6. Trace 记录 tool proposal、审批、执行结果和模型输出，不记录 secret。
```

因此，Factory 可以生成工具实现代码，但生成后仍然要落到包内 artifact，并经过静态检查、Harness、审批和 trace 约束。

## InstructionSpec

定位：定义 Agent 的身份、目标、风格和边界。

关键字段：

```text
persona       Agent 扮演什么角色
goal          Agent 要完成什么目标
style         回答风格
boundaries    不能做什么
principles    长期遵守的原则
few_shots     示例对话
```

客服示例：

```yaml
schema_version: "0.1"
kind: "InstructionSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
persona: "温和、专业的客服 Agent"
goal: "处理退款、投诉、转人工和订单查询"
style: "简洁、安抚、给出下一步"
boundaries:
  - "不承诺已退款"
  - "不泄露内部工具鉴权信息"
```

校验：

```text
persona 必须非空。
goal 必须非空。
```

## OutputSpec

定位：定义 Agent 最终输出的形态、schema、校验和修复策略。

第一版支持：

```text
text
json_object
json_array
pydantic_model
```

示例：

```yaml
schema_version: "0.1"
kind: "OutputSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
output_mode: "json_object"
schema:
  type: "object"
  properties:
    intent:
      type: "string"
    answer:
      type: "string"
    requires_human:
      type: "boolean"
  required:
    - "intent"
    - "answer"
validation:
  strict: true
  max_repair_attempts: 1
repair:
  enabled: true
  strategy: "validator_feedback"
```

校验：

```text
json_object / pydantic_model 必须是 object schema。
json_array 必须是 array schema。
pydantic_model 必须声明 model_name。
非法 JSON 输出不直接进入业务层，应返回结构化错误或进入修复策略。
```

## ConversationSpec

定位：定义多轮会话、历史窗口、摘要、压缩和消息保留策略。

示例：

```yaml
schema_version: "0.1"
kind: "ConversationSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
history_window: 12
summarize_after: 20
summary_strategy: "rolling"
retain_system_messages: true
retain_tool_messages: true
redact_before_storage: true
```

校验：

```text
history_window 必须大于 0。
summarize_after 必须大于 0。
```

## RunContextSpec

定位：定义每次运行可访问的依赖、namespace、trace、session 和访问边界。

示例：

```yaml
schema_version: "0.1"
kind: "RunContextSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
namespace_template: "agent:{agent_name}:version:{version}:instance:{instance_id}"
dependency_refs:
  - "model.default"
  - "toolset.customer_service"
access_policy:
  model: true
  tools: true
  mcp: true
  context: true
  memory: true
  registry: false
trace_required: true
session_required: true
```

规则：

```text
AgentInstance 只能访问自己的 RunContext。
Registry 默认不暴露给运行中 Agent。
工具、MCP、Context、Memory 必须通过 RunContext 间接访问。
```

## ToolsetSpec

定位：定义工具组、工具暴露策略、选择策略和 proposal-only 边界。

示例：

```yaml
schema_version: "0.1"
kind: "ToolsetSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
toolsets:
  - id: "customer_service_tools"
    exposed_tools:
      - "order_query"
      - "refund_policy_query"
    hidden_tools:
      - "payment_refund_execute"
    proposal_only: true
    selection_strategy: "auto"
```

校验：

```text
toolset id 必须唯一。
同一个工具不能同时 exposed 和 hidden。
proposal_only=true 时，LLM 只能生成 ToolCallProposal，不能直接执行工具。
```

## KnowledgeSpec

定位：定义知识源、retriever、引用策略和上下文注入方式。

示例：

```yaml
schema_version: "0.1"
kind: "KnowledgeSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
sources:
  - id: "customer_policy_kb"
    type: "mcp"
    ref: "mcp.customer_kb.search_policy"
    citation_required: true
retrievers:
  - id: "policy_retriever"
    source_refs:
      - "customer_policy_kb"
    strategy: "hybrid"
    top_k: 5
default_retriever: "policy_retriever"
inject_as: "context"
```

校验：

```text
knowledge source id 必须唯一。
retriever id 必须唯一。
retriever.source_refs 必须引用已存在 source。
default_retriever 必须引用已存在 retriever。
```

## GuardrailSpec

定位：定义 input、model、tool、output 阶段的通用护栏。

支持阶段：

```text
input
model_request
model_response
tool
output
```

支持动作：

```text
block
warn
human_confirm
redact
handoff
retry
```

示例：

```yaml
schema_version: "0.1"
kind: "GuardrailSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
rules:
  - id: "high_risk_tool_confirm"
    stage: "tool"
    action: "human_confirm"
    risk_level: "high"
    description: "高风险工具必须确认"
```

校验：

```text
guardrail rule id 必须唯一。
stage / action 必须是允许枚举值。
```

## HandoffSpec

定位：定义转人工、转专家 Agent、转工作流和转外部服务。

示例：

```yaml
schema_version: "0.1"
kind: "HandoffSpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
targets:
  - id: "human_support"
    type: "human"
    target_ref: "queue.customer_service"
    condition: "state.intent == 'complaint' and state.risk_level == 'high'"
    context_policy:
      include_summary: true
      include_trace_refs: true
      include_sensitive_context: false
```

校验：

```text
handoff target id 必须唯一。
include_sensitive_context 默认 false。
```

## ObservabilitySpec

定位：定义 trace span taxonomy、usage、hash、内容记录和敏感字段禁止规则。

标准 span 类型：

```text
agent_run
model_generation
prompt_render
tool_proposal
tool_call
mcp_call
context_load
guardrail_check
handoff
checkpoint
```

示例：

```yaml
schema_version: "0.1"
kind: "ObservabilitySpec"
metadata:
  name: "customer-service-agent"
  version: "1.0.0"
trace_enabled: true
spans:
  - type: "agent_run"
    enabled: true
  - type: "model_generation"
    enabled: true
  - type: "tool_call"
    enabled: true
record_usage: true
record_prompt_hash: true
record_response_hash: true
record_content: false
forbidden_fields:
  - "api_key"
  - "secret"
  - "authorization"
  - "auth_header"
  - "tool_auth_token"
allowed_sensitive_fields: []
```

校验：

```text
span type 不能重复。
api_key / secret / authorization / auth_header / tool_auth_token 必须保持 forbidden。
allowed_sensitive_fields 不能显式允许敏感字段。
```

## 与其他阶段的关系

```text
02 Specs / Validator
  负责加载和校验这些标准件。

04 Model / LLM
  使用 InstructionSpec、OutputSpec、ConversationSpec 构建消息和请求。

03 Runtime
  使用 RunContextSpec、ToolsetSpec、GuardrailSpec、HandoffSpec 控制运行。

04 Capability / Tool / MCP / Context
  提供 ToolsetSpec 和 KnowledgeSpec 引用的真实能力。

05 AgentHarness
  使用同一套标准件生成可复现场景和断言。

07 Upgrade / Release
  PatchPlan 修改这些标准件时必须产生 PackageDiff 和 ApprovalRecord。
```

## 第一版不做

```text
1. 不实现完整 RAG 索引。
2. 不实现完整多 Agent 协作。
3. 不实现复杂策略语言。
4. 不实现生产级 trace exporter。
5. 不让标准件绕过 Runtime、ToolRouter、PolicyEngine。
```
