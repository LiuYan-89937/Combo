# Checkpoint Model v0

本文档定义 `RuntimeKernel` 的检查点模型规范：

`Checkpoint Model v0`

目标：

- 定义 RuntimeKernel 在运行中需要保存什么
- 定义 interrupt / resume 依赖的最小持久化模型
- 为恢复、回放、harness 断言提供统一对象

---

## 1. 定位

`Checkpoint Model` 负责定义：

- 运行到中途时需要保存哪些状态
- 如何恢复到中断前的位置
- 恢复后如何继续执行而不是重头开始

它不是：

- RuntimeState 本身
- Checkpoint Manager 的具体实现
- 持久化后端

它是：

`Checkpoint 的统一结构规范`

---

## 2. 设计原则

### 2.1 Checkpoint 不是只存 messages

Checkpoint 必须保存完整运行所需的最小闭包，而不只是消息历史。

### 2.2 对象不落盘

Checkpoint 中不允许保存 live object，例如：

- model adapter
- tool registry
- memory engine
- knowledge engine
- context engine
- policy engine

这些都必须在恢复时由 `RuntimeKernelInstance` 重建。

### 2.3 恢复必须从中断点继续

恢复时不能重新从 `ingress` 开始跑，而必须：

- 恢复当前执行位置
- 恢复当前 state
- 恢复 pending interrupt
- 恢复 route / tool / policy 状态

### 2.4 可审计

Checkpoint 结构必须可被：

- trace 引用
- harness 检查
- debug 回放

---

## 3. 顶层结构

`Checkpoint Model v0` 建议根结构：

```yaml
checkpoint_id: string
schema_version: "0.1"
runtime_kernel_version: string

run_ref: {}
execution_ref: {}
state_snapshot: {}
interrupt_snapshot: {}
observability_ref: {}
metadata: {}
```

---

## 4. 顶层字段说明

## 4.1 `checkpoint_id`

作用：

- 当前 checkpoint 的唯一标识

## 4.2 `schema_version`

作用：

- 标识 checkpoint 结构版本

## 4.3 `runtime_kernel_version`

作用：

- 标识生成该 checkpoint 时的 RuntimeKernel 版本

## 4.4 `run_ref`

作用：

- 标识 checkpoint 属于哪次运行

建议字段：

```yaml
run_ref:
  run_id: string
  agent_id: string
  session_id: string
  pattern_id: string
  pattern_version: integer
```

## 4.5 `execution_ref`

作用：

- 记录恢复所需的执行位置信息

建议字段：

```yaml
execution_ref:
  current_node: string | null
  current_subgraph: string | null
  route_decision: string | null
  turn_count: integer
  max_turns: integer
  finished: boolean
  finish_status: string | null
```

## 4.6 `state_snapshot`

作用：

- 存储恢复运行所需的 `RuntimeState` 快照

说明：

- 这里不是随意复制全部运行对象
- 只保存可序列化后的 `RuntimeState`

## 4.7 `interrupt_snapshot`

作用：

- 保存当前中断相关状态

建议字段：

```yaml
interrupt_snapshot:
  interrupted: boolean
  interrupt_type: string | null
  interrupt_payload: {}
  approval_required: boolean
  resume_token: string | null
```

## 4.8 `observability_ref`

作用：

- 保存与 trace / event / debug snapshot 关联的引用信息

建议字段：

```yaml
observability_ref:
  trace_id: string
  span_id: string | null
  event_offset: integer | null
  debug_refs: []
```

## 4.9 `metadata`

作用：

- 保存额外辅助元信息

建议字段：

```yaml
metadata:
  created_at: string
  reason: string
  created_by: string
```

---

## 5. Checkpoint 的保存时机

`Checkpoint Model v0` 建议至少在以下时机保存：

### 5.1 interrupt 前

当发生：

- approval required
- clarification required
- manual review required

必须先保存 checkpoint，再退出本轮执行。

### 5.2 长循环安全点

若某些 Pattern / subGraph 可能长时间循环运行，建议在安全节点保存阶段性 checkpoint。

### 5.3 恢复后可选保存

恢复成功后可选记录新的 checkpoint，用于审计恢复链路。

---

## 6. 恢复时必须恢复的内容

恢复至少要恢复：

- `RuntimeState`
- `current_node`
- `current_subgraph`
- `route_decision`
- `interrupt_snapshot`
- `trace_id`

恢复时不应直接恢复：

- live engine objects
- provider client instances
- tool callable objects

这些应由 `RuntimeKernelInstance` 基于当前配置重新装配。

---

## 7. 与其他模块的关系

## 7.1 与 RuntimeState

- `RuntimeState` 是运行态
- `Checkpoint Model` 是运行态的持久化快照结构

## 7.2 与 Execution Controller

Execution Controller 决定：

- 什么时候创建 checkpoint
- 从哪里恢复
- 恢复后如何继续执行

## 7.3 与 Interrupt / Approval

Interrupt / Approval Manager 负责产生中断原因与 resume 语义，
Checkpoint Model 负责把这些语义持久化。

## 7.4 与 Observability

Checkpoint 必须保留与 trace 的引用关系，便于：

- 恢复后继续 trace
- harness 对恢复链路做断言

---

## 8. LangGraph 落地方式

Checkpoint 在 LangGraph 基座上的真实落点应是：

- graph checkpointer
- RuntimeKernel 的 checkpoint serializer
- RuntimeKernel 的 resume API

也就是说：

`LangGraph 负责持久化通道`
`RuntimeKernel 负责 checkpoint 结构语义`

---

## 9. v0 明确不做

当前阶段不做：

- 分布式 checkpoint 同步
- 多 worker 恢复协调
- 自定义 checkpoint 协议扩展
- 用户自定义恢复语义

---

## 10. v0 下一步

基于当前文档，下一步需要：

1. 定义 checkpoint serializer
2. 定义 checkpoint storage interface
3. 定义 resume payload 结构
4. 继续落 `Observability v0`
