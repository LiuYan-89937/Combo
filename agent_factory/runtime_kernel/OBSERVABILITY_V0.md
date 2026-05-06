# Observability v0

本文档定义 `RuntimeKernel` 的观测规范：

`Observability v0`

目标：

- 定义 RuntimeKernel 的 trace / event / metrics / debug 结构
- 保证不同 Agent、不同 Pattern、不同子图运行结果可比较
- 为 harness、排障、审计提供统一观测接口

---

## 1. 定位

`Observability` 负责回答这些问题：

- 当前运行走了哪些节点
- 为什么从这条边跳到下一条边
- 哪个节点触发了工具调用
- 哪个节点触发了审批 / interrupt
- 子图是怎么进入和退出的
- 最终如何结束

它不是：

- 业务日志堆积点
- provider-specific debug dump

它是：

`RuntimeKernel 的统一运行观测层`

---

## 2. 设计原则

### 2.1 结构化优先

观测结果必须优先采用结构化事件，而不是松散文本日志。

### 2.2 脱敏安全

trace 与 event 必须默认支持 secret redaction。

### 2.3 跨 Pattern 一致

不同 Graph Pattern 运行时，观测对象必须仍然共享统一字段。

### 2.4 支持 Harness 断言

harness 不能只断言最终 answer，还要能断言：

- graph path
- node enter / exit
- tool lifecycle
- interrupt / resume

---

## 3. 观测层组成

`Observability v0` 由 4 部分组成：

1. `Trace`
2. `Structured Events`
3. `Metrics`
4. `Debug Snapshot Refs`

---

## 4. Trace Model

## 4.1 顶层结构

```yaml
trace_id: string
run_id: string
agent_id: string
pattern_id: string
started_at: string
finished_at: string | null
status: string
root_span_id: string
```

## 4.2 Span

建议 v0 至少支持这些 span 类型：

- `node_execution`
- `subgraph_execution`
- `tool_execution`
- `policy_check`
- `context_assembly`
- `memory_operation`
- `knowledge_operation`
- `checkpoint_operation`
- `interrupt_operation`

span 最少字段：

```yaml
span_id: string
parent_span_id: string | null
span_type: string
name: string
started_at: string
finished_at: string | null
status: string
metadata: {}
```

---

## 5. Structured Event Model

事件是 harness 与调试最直接使用的对象。

建议 v0 至少支持这些事件类型：

- `run_started`
- `node_entered`
- `node_completed`
- `node_failed`
- `route_selected`
- `subgraph_entered`
- `subgraph_exited`
- `tool_proposed`
- `tool_started`
- `tool_completed`
- `tool_failed`
- `policy_blocked`
- `interrupt_triggered`
- `resume_started`
- `resume_completed`
- `run_completed`

事件最少字段：

```yaml
event_id: string
trace_id: string
run_id: string
event_type: string
node_id: string | null
subgraph_id: string | null
message: string | null
payload: {}
created_at: string
```

---

## 6. Metrics Model

建议 v0 收集以下基础指标：

- `node_count`
- `subgraph_count`
- `tool_call_count`
- `interrupt_count`
- `resume_count`
- `turn_count`
- `total_latency_ms`
- `max_node_latency_ms`

若模型层后续接入 token 统计，可再加：

- `prompt_tokens`
- `completion_tokens`
- `total_tokens`

---

## 7. Debug Snapshot Refs

大对象不要直接塞到 event / trace 主体中。

建议用引用：

```yaml
debug_refs:
  - ref_id: string
    kind: context_snapshot | tool_output | model_prompt | state_snapshot
    path: string | null
    summary: string
```

作用：

- 保持主 trace 轻量
- 大对象按需读取

---

## 8. 与其他模块的关系

## 8.1 与 Execution Controller

Execution Controller 负责在：

- node 执行前后
- route 决策后
- interrupt / resume 时

触发标准事件。

## 8.2 与 Capability Binding

不同绑定的能力模块在运行时都应通过统一 observability 接口上报行为。

例如：

- context engine -> `context_assembly`
- tool orchestrator -> `tool_*`
- policy engine -> `policy_blocked`

## 8.3 与 Checkpoint Model

Checkpoint 中必须保存对 trace 的引用关系。

## 8.4 与 Harness Bridge

Harness 可以直接消费：

- event stream
- final trace summary
- metrics snapshot

---

## 9. LangGraph 落地方式

在 LangGraph 基座上，Observability 的落点主要是：

- node wrapper 发事件
- subgraph wrapper 发事件
- controller 发 route / interrupt / resume 事件
- manager 维护 trace / metrics 聚合

也就是说：

`LangGraph 负责执行`
`RuntimeKernel 负责把执行过程结构化记录出来`

---

## 10. v0 明确不做

当前阶段不做：

- 分布式 trace 聚合
- 实时 dashboard
- 用户自定义 event schema
- provider-specific tracing 扩展

---

## 11. v0 下一步

基于当前文档，下一步需要：

1. 定义标准 event schema
2. 定义标准 span schema
3. 定义 metrics collector 接口
4. 继续落 `Harness Bridge v0`
