# RuntimeState v0

本文档定义 `RuntimeKernel` 的统一运行状态模型 `RuntimeState v0`。

目标：

- 为所有 Agent 提供统一运行状态根结构
- 为 Graph Pattern 编译与标准节点执行提供稳定输入输出边界
- 为 checkpoint / resume / trace / harness 提供统一断言对象

---

## 1. 设计原则

### 1.1 单一根状态

所有 Agent 都运行在同一个根状态对象上：

`RuntimeState`

不允许不同 Agent 各自定义独立的根状态结构。

### 1.2 分区管理

`RuntimeState` 必须按职责拆分为若干 section，避免所有字段堆在一个平面 dict 中。

### 1.3 可序列化

`RuntimeState` 必须能被：

- 持久化
- checkpoint 保存
- checkpoint 恢复
- harness 断言
- trace 快照引用

### 1.4 稳定演进

`RuntimeState` 必须具备：

- `schema_version`
- 明确 section 边界
- 向后兼容迁移策略

### 1.5 受控变更

每个标准节点只能修改自己被允许修改的 section / field，不允许任意全局改写。

---

## 2. 根结构

`RuntimeState v0` 建议的根结构如下：

```yaml
schema_version: "0.1"
run: {}
conversation: {}
context: {}
tools: {}
memory: {}
knowledge: {}
policy: {}
execution: {}
observability: {}
```

---

## 3. Section 定义

## 3.1 Run State

作用：

- 记录本次运行的全局身份信息
- 提供与 session / agent / pattern 相关的稳定元信息

建议字段：

```yaml
run:
  run_id: string
  agent_id: string
  session_id: string
  pattern_id: string
  pattern_version: integer
  runtime_kernel_version: string
  started_at: string
```

字段说明：

- `run_id`
  本次运行唯一标识
- `agent_id`
  Agent 规范实例标识
- `session_id`
  会话标识
- `pattern_id`
  当前采用的 Graph Pattern
- `pattern_version`
  当前 Pattern 版本
- `runtime_kernel_version`
  当前 RuntimeKernel 版本
- `started_at`
  运行开始时间

---

## 3.2 Conversation State

作用：

- 保存对话输入输出
- 保存当前轮的主要语言交互内容

建议字段：

```yaml
conversation:
  messages: []
  current_user_input: string | null
  current_user_input_id: string | null
  assistant_draft: string | null
  final_answer: string | null
  clarification_question: string | null
  turn_index: integer
```

字段说明：

- `messages`
  标准化消息序列
- `current_user_input`
  当前轮原始用户输入
- `current_user_input_id`
  当前轮输入唯一标识
- `assistant_draft`
  尚未 finalize 的模型草稿
- `final_answer`
  已完成输出
- `clarification_question`
  当前需要向用户追问的问题
- `turn_index`
  当前第几轮交互

---

## 3.3 Context State

作用：

- 保存上下文引擎编译后的结果
- 显式区分模型可见、工具可见、隐藏内容

建议字段：

```yaml
context:
  source_refs: []
  model_context: {}
  tool_context: {}
  hidden_context: {}
  compression_applied: boolean
  token_budget: {}
  assembly_log: []
```

字段说明：

- `source_refs`
  当前上下文使用了哪些来源
- `model_context`
  模型可见上下文
- `tool_context`
  工具可见上下文
- `hidden_context`
  运行中保留但不暴露给模型 / 工具的上下文
- `compression_applied`
  是否做过压缩
- `token_budget`
  当前上下文预算记录
- `assembly_log`
  本轮上下文装配过程摘要

---

## 3.4 Tool State

作用：

- 统一记录工具生命周期
- 管理待执行工具、已执行工具、审批状态

建议字段：

```yaml
tools:
  available_tools: []
  pending_tool_call: null
  pending_tool_calls: []
  tool_results: []
  tool_failures: []
  approval_queue: []
  last_tool_result: null
```

字段说明：

- `available_tools`
  当前 Agent 已注册工具
- `pending_tool_call`
  当前待执行工具调用
- `pending_tool_calls`
  多工具并行场景的待执行列表
- `tool_results`
  已完成工具结果
- `tool_failures`
  工具失败记录
- `approval_queue`
  等待人工审批的工具动作
- `last_tool_result`
  最近一次工具结果

---

## 3.5 Memory State

作用：

- 记录短期记忆、摘要记忆、待写入记忆

建议字段：

```yaml
memory:
  short_term_snapshot: {}
  summary_memory: string | null
  recall_items: []
  pending_write: []
  write_applied: boolean
```

字段说明：

- `short_term_snapshot`
  当前会话短期记忆快照
- `summary_memory`
  摘要记忆
- `recall_items`
  本轮召回结果
- `pending_write`
  尚未写入持久层的记忆项
- `write_applied`
  本轮是否已完成记忆写回

---

## 3.6 Knowledge State

作用：

- 记录知识检索、检索结果、引用信息

建议字段：

```yaml
knowledge:
  retrieval_query: string | null
  retrieved_items: []
  ranked_items: []
  citations: []
  source_metadata: {}
```

字段说明：

- `retrieval_query`
  当前检索查询
- `retrieved_items`
  原始召回结果
- `ranked_items`
  排序后结果
- `citations`
  当前准备输出的引用
- `source_metadata`
  来源元信息摘要

---

## 3.7 Policy State

作用：

- 统一记录风险控制、阻断、审批、拒答

建议字段：

```yaml
policy:
  risk_level: string
  blocked: boolean
  block_reason: string | null
  approval_required: boolean
  interrupt_required: boolean
  refusal_reason: string | null
  checks: []
```

字段说明：

- `risk_level`
  当前风险等级
- `blocked`
  是否被策略拦截
- `block_reason`
  拦截原因
- `approval_required`
  是否需要人工确认
- `interrupt_required`
  是否需要进入 interrupt
- `refusal_reason`
  若拒答，对外输出原因
- `checks`
  本轮执行的策略检查记录

---

## 3.8 Execution State

作用：

- 描述图执行的当前进度与路由决策

建议字段：

```yaml
execution:
  current_node: string | null
  current_subgraph: string | null
  route_decision: string | null
  turn_count: integer
  max_turns: integer
  interrupted: boolean
  finished: boolean
  finish_status: string | null
```

字段说明：

- `current_node`
  当前所在节点
- `current_subgraph`
  当前所在子图
- `route_decision`
  最近一次路由决策
- `turn_count`
  当前运行轮数
- `max_turns`
  最大运行轮数
- `interrupted`
  是否已进入 interrupt
- `finished`
  是否已结束
- `finish_status`
  最终结束状态

---

## 3.9 Observability State

作用：

- 保存 trace、event、metrics、debug 相关信息

建议字段：

```yaml
observability:
  trace_id: string
  span_stack: []
  events: []
  metrics: {}
  debug_refs: []
```

字段说明：

- `trace_id`
  当前 trace 唯一标识
- `span_stack`
  当前 span 栈
- `events`
  结构化运行事件
- `metrics`
  本轮计量信息
- `debug_refs`
  调试快照引用

---

## 4. Section 与标准节点的关系

建议的 section 修改边界如下：

| Node | 可读取 | 可写入 |
|---|---|---|
| `ingress` | `run`, `conversation` | `conversation`, `execution`, `observability` |
| `context` | `conversation`, `memory`, `knowledge`, `run` | `context`, `observability` |
| `memory_recall` | `conversation`, `memory`, `run` | `memory`, `observability` |
| `knowledge_retrieve` | `conversation`, `context`, `run` | `knowledge`, `observability` |
| `policy_precheck` | `conversation`, `context`, `tools`, `knowledge` | `policy`, `execution`, `observability` |
| `model` | `conversation`, `context`, `memory`, `knowledge`, `policy` | `conversation`, `tools`, `execution`, `observability` |
| `tool` | `tools`, `context`, `policy` | `tools`, `policy`, `execution`, `observability` |
| `observation` | `tools`, `conversation` | `conversation`, `tools`, `observability` |
| `policy_postcheck` | `conversation`, `tools`, `policy` | `policy`, `conversation`, `observability` |
| `memory_write` | `conversation`, `memory`, `policy` | `memory`, `observability` |
| `finalize` | `conversation`, `policy`, `execution` | `conversation`, `execution`, `observability` |

---

## 5. 序列化要求

`RuntimeState v0` 必须满足以下要求：

### 5.1 可 JSON 序列化

- 不允许直接把不可序列化对象放入状态根字段
- 复杂对象必须转为：
  - primitive
  - dict
  - list
  - reference id

### 5.2 Message 序列化策略

- `messages` 应使用统一的 message serializer
- 不直接裸存 provider-specific message 对象

### 5.3 大对象引用策略

以下内容应优先存引用而非正文：

- 大体积知识块
- 工具原始输出
- debug snapshot
- 长文档上下文

---

## 6. Checkpoint 要求

Checkpoint 至少应保存：

- `RuntimeState`
- 当前 node
- 当前 subgraph
- pending tool / approval 状态
- interrupt payload
- trace id

恢复时至少应恢复：

- 当前执行位置
- conversation state
- context state
- tool state
- policy state
- observability continuity

---

## 7. Harness 断言要求

`RuntimeState v0` 必须支持 harness 对以下内容做断言：

- graph path 是否符合预期
- policy 是否在正确阶段触发
- tool 是否在正确节点调用
- context 是否在预期位置被装配
- interrupt / resume 是否恢复成功
- final_answer 是否在 `finalize` 后产生

---

## 8. v0 明确不做

当前 `RuntimeState v0` 暂不引入：

- 多 Agent 协同状态
- 分布式执行状态
- 动态 schema 热切换
- 用户自定义根状态字段

---

## 9. v0 下一步

基于当前文档，下一步要做的是：

1. 定义 `RuntimeState` 的正式 schema 文件
2. 定义 section 级别 serializer
3. 为 Standard Node Catalog 逐个确认 section 读写边界
