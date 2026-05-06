# Execution Controller v0

本文档定义 `RuntimeKernel` 的执行控制器规范：

`Execution Controller v0`

目标：

- 定义一次 Agent 运行在 Kernel 中如何被调度
- 定义图执行时的运行纪律，而不是图结构本身
- 统一控制路由、循环、中断、恢复、终止

---

## 1. 定位

`Execution Controller` 是 RuntimeKernel 的运行调度器。

它不负责：

- 定义 Graph Pattern 结构
- 实现具体节点逻辑
- 实现具体工具能力

它负责：

- 驱动执行循环
- 决定当前怎么走图
- 控制什么时候暂停、恢复、终止
- 防止运行失控

一句话：

`Graph Pattern 定义结构`
`Execution Controller 定义运行规则`

---

## 2. 核心职责

`Execution Controller v0` 负责以下 6 类事情：

1. `run loop`
2. `route resolution`
3. `interrupt handling`
4. `resume handling`
5. `termination handling`
6. `execution limits`

---

## 3. Run Loop

### 3.1 作用

负责驱动一次完整的运行循环。

标准过程：

1. 读取当前 `RuntimeState`
2. 找到当前节点
3. 执行节点
4. 收到节点返回的 state patch
5. 合并到 `RuntimeState`
6. 解析下一跳
7. 继续执行或结束

### 3.2 v0 原则

- 每一轮执行都必须是显式的
- 每一步都必须能被 trace 记录
- 每一次节点执行后都必须经过统一的 route resolution

---

## 4. Route Resolution

### 4.1 作用

负责决定当前执行完某个节点后，下一步该进入哪个节点或哪个子图出口分支。

### 4.2 依据

路由决策可以依赖：

- 当前 `RuntimeState`
- 当前节点返回的 patch
- `policy` section
- `tools` section
- `execution.route_decision`
- 子图的 `exit_route`

### 4.3 v0 原则

- route 不能绕过 Pattern DSL
- route 只能在已定义边中选择
- route 的最终结果必须写入 `execution.route_decision`

---

## 5. Interrupt Handling

### 5.1 作用

负责在运行中接住中断请求，并把当前运行切换到暂停状态。

### 5.2 中断来源

常见来源：

- approval required
- clarification required
- manual review required
- policy interrupt
- tool interrupt

### 5.3 v0 行为

当发生 interrupt 时，Execution Controller 必须：

1. 停止继续调度下一节点
2. 写入 `execution.interrupted = true`
3. 保存 interrupt payload
4. 触发 checkpoint
5. 返回暂停结果

### 5.4 interrupt 不是失败

v0 明确：

- interrupt 是一种正常运行状态
- 不能直接视为 failed

---

## 6. Resume Handling

### 6.1 作用

负责从 checkpoint 恢复运行，并把新的 resume 输入接回图执行流程。

### 6.2 恢复步骤

1. 读取 checkpoint
2. 恢复 `RuntimeState`
3. 恢复当前 node / subgraph 位置
4. 注入 resume payload
5. 继续 run loop

### 6.3 v0 原则

- resume 不能跳过 checkpoint 恢复
- resume 后必须保留 trace 连续性
- resume 后必须从中断点继续，而不是从入口重新跑

---

## 7. Termination Handling

### 7.1 作用

负责统一判断一次运行什么时候算结束。

### 7.2 终止类型

建议 v0 统一支持：

- `completed`
- `interrupted`
- `failed`
- `blocked`

### 7.3 终止依据

终止可以由以下情况触发：

- 到达 success node
- 到达 failure node
- 触发 interrupt
- policy block
- 超过最大轮数
- 执行超时

### 7.4 v0 原则

- 终止状态统一写入 `execution.finish_status`
- 终止后必须禁止继续调度

---

## 8. Execution Limits

### 8.1 作用

防止图执行进入无限循环或过度消耗。

### 8.2 建议限制项

- `turn_count`
- `max_turns`
- `retry_count`
- `max_retries`
- `max_subgraph_depth`
- `timeout_seconds`

### 8.3 v0 原则

- 每次节点执行后都要更新计数
- 达到限制后必须统一走终止逻辑

---

## 9. 与其他模块的关系

## 9.1 与 Graph Pattern DSL

Graph Pattern DSL 负责描述：

- 节点
- 边
- interrupt 点
- termination 规则

Execution Controller 负责：

- 按这些规则实际调度运行

## 9.2 与 Standard Node

Standard Node 负责：

- 做具体工作

Execution Controller 负责：

- 何时执行哪个节点
- 节点执行后怎么路由

## 9.3 与 Policy Engine

Policy Engine 负责：

- 给出是否阻断、是否审批、是否拒答的判断

Execution Controller 负责：

- 收到这些判断后，决定暂停、终止还是继续

## 9.4 与 Checkpoint Manager

Checkpoint Manager 负责：

- 存储与恢复 checkpoint 数据

Execution Controller 负责：

- 什么时候存
- 什么时候恢复
- 从哪里继续

## 9.5 与 Harness Bridge

Harness Bridge 负责：

- 驱动运行并做断言

Execution Controller 负责：

- 提供稳定的执行轨迹、终止状态和恢复语义

---

## 10. 运行时输入输出

## 10.1 输入

Execution Controller v0 至少依赖：

- compiled graph
- current `RuntimeState`
- node registry
- node bindings
- hook bindings
- policy outputs
- subgraph exit route
- resume payload

## 10.2 输出

Execution Controller v0 至少产出：

- updated `RuntimeState`
- next node id
- execution status
- interrupt payload
- final result

---

## 11. 子图执行控制

### 11.1 子图在控制器中的地位

子图在父图中虽然表现为节点，但运行时仍然要进入自己的执行流。

### 11.2 v0 建议

子图执行时：

1. 父图把当前 state 传入子图
2. 子图自己跑内部 loop
3. 子图结束时返回：
   - updated state
   - `exit_route`
4. 父图根据 `exit_route` 继续 route resolution

### 11.3 v0 原则

- 子图结束不等于整个运行结束
- 子图返回的 `exit_route` 必须进入父图边选择

---

## 12. LangGraph 落地方式

### 12.1 核心落点

Execution Controller 最终落到 LangGraph 基座上，不是直接替换 LangGraph，而是包住它的运行流程。

### 12.2 落地职责

- 驱动 `StateGraph` 的节点执行顺序
- 处理节点后的 route decision
- 处理中断与恢复
- 处理执行限制

### 12.3 节点执行包装

每个节点在进入 LangGraph 前应被包装为统一执行单元：

```text
wrapped_node
  -> run_pre_hooks
  -> execute_node_impl
  -> run_post_hooks
  -> return_state_patch
```

Execution Controller 负责解释这些 patch 如何进入下一跳。

---

## 13. v0 明确不做

当前阶段不做：

- 分布式多 worker 调度
- 多 Agent 协同调度
- 自由表达式级 route engine
- 用户自定义执行语义

---

## 14. v0 下一步

基于当前文档，下一步需要：

1. 定义 `execution` section 的正式字段
2. 定义 route resolution 输入输出格式
3. 定义 interrupt payload 结构
4. 定义 resume payload 结构
5. 再继续落 `Checkpoint Model v0`
