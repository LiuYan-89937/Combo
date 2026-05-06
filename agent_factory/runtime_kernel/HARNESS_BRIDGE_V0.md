# Harness Bridge v0

本文档定义 `RuntimeKernel` 的测试桥接规范：

`Harness Bridge v0`

目标：

- 定义测试如何驱动 RuntimeKernel
- 定义 harness 如何注入 fixture、消费运行结果、执行断言
- 保证不同 Pattern、不同 Agent、不同子图都能用统一方式测试

---

## 1. 定位

`Harness Bridge` 不是图内部节点，也不是 graph pattern 的一部分。

它是：

`RuntimeKernel 的外部测试接入口`

作用是：

- 启动运行
- 注入 fixture
- 观察 trace / state / events
- 对运行行为做断言

---

## 2. 设计原则

### 2.1 通过 Kernel 驱动，不绕过 Kernel

harness 不能直接调用节点私实现。

必须通过 RuntimeKernel 的：

- compile
- run
- resume

正式入口驱动。

### 2.2 断言运行行为，不只断言最终文本

至少要能断言：

- graph path
- tool lifecycle
- context 传递
- policy 行为
- interrupt / resume
- final answer

### 2.3 fixture 与运行对象分离

fixture 只注入测试数据和测试替身，不改变 Kernel 根语义。

---

## 3. Harness Bridge 的职责

`Harness Bridge v0` 至少负责：

1. fixture 注入
2. graph 运行驱动
3. resume 驱动
4. trace / event 拉取
5. state 快照拉取
6. 统一断言入口

---

## 4. Harness 输入

建议 v0 至少支持以下输入对象：

### 4.1 harness spec

描述要测什么。

### 4.2 compiled kernel app

测试对象。

### 4.3 fixture bundle

包含：

- fake model outputs
- fake tool outputs
- fake memory data
- fake knowledge results
- fake approval responses

### 4.4 test input

用户输入或 resume 输入。

---

## 5. Harness 输出

建议 v0 至少产出：

- `status`
- `scenario_id`
- `assertion_results`
- `event_log`
- `trace_summary`
- `final_state_snapshot`
- `final_answer`

---

## 6. Harness 断言分类

## 6.1 Path Assertions

断言运行路径是否符合预期。

例如：

- 是否进入某个节点
- 是否进入某个子图
- 是否按顺序经过一组节点

## 6.2 Tool Assertions

断言工具行为。

例如：

- 是否提出某个工具调用
- 是否真的执行某个工具
- 工具是否在允许位置调用
- 工具是否触发审批

## 6.3 Context Assertions

断言上下文行为。

例如：

- 是否装配了某类上下文
- 是否压缩
- 是否隐藏某字段

## 6.4 Policy Assertions

断言策略行为。

例如：

- 是否被 block
- 是否要求 approval
- 是否触发 refusal

## 6.5 Interrupt / Resume Assertions

断言中断恢复行为。

例如：

- 是否进入 interrupt
- checkpoint 是否存在
- resume 后是否从中断点继续

## 6.6 Output Assertions

断言输出行为。

例如：

- 最终 answer 是否存在
- 是否满足格式要求
- 是否包含 citation

---

## 7. Fixture 注入方式

fixture 不直接改 RuntimeState 根结构。

它通过 binding / adapter 替身注入。

建议：

- fake model -> 替换 `model_service`
- fake tools -> 替换 `tool_registry` 中某些实现
- fake memory -> 替换 `memory_engine`
- fake knowledge -> 替换 `knowledge_engine`
- fake approval -> 替换 interrupt / approval 响应源

也就是说：

fixture 通过 RuntimeKernel 的 service 层注入，而不是通过 graph 内部 hack。

---

## 8. 与其他模块的关系

## 8.1 与 Capability Binding

Harness Bridge 要能够读取当前 binding 配置，以确认：

- 哪些 prompt 被挂了
- 哪些工具对子图可见
- 哪些 policy hook 生效

## 8.2 与 Observability

Harness 主要消费：

- event stream
- trace summary
- metrics
- debug refs

## 8.3 与 Checkpoint Model

Harness Bridge 必须支持测试：

- interrupt 前是否正确存 checkpoint
- resume 时是否正确恢复
- 恢复后的 path 是否连续

---

## 9. LangGraph 落地方式

在 LangGraph 基座上，Harness Bridge 的落点是：

- 通过 RuntimeKernel compile/run/resume API 驱动 graph
- 不直接接触私有 node callable

换句话说：

Harness Bridge 是 RuntimeKernel 的测试消费者，不是图内组件。

---

## 10. v0 明确不做

当前阶段不做：

- UI 层自动回放工具
- 用户自定义断言 DSL
- 分布式回放测试
- 多 Agent 协同测试编排

---

## 11. v0 下一步

基于当前文档，下一步需要：

1. 定义 harness scenario schema
2. 定义 assertion schema
3. 定义 fixture bundle schema
4. 开始写 RuntimeKernel 代码骨架
