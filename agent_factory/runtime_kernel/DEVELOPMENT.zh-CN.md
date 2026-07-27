[English](DEVELOPMENT.md) | [简体中文](DEVELOPMENT.zh-CN.md)

# Runtime Kernel Development

本文档只讨论 `RuntimeKernel` 本身的开发，不讨论工厂 RuntimeKernel 阶段的实现细节，也不讨论具体 Agent 的业务配置内容。

---

## 1. 定位

`RuntimeKernel` 是整个系统的统一运行平台层。

它的职责不是定义某个具体 Agent 做什么，而是定义：

- Agent 在 LangGraph 上如何运行
- 运行时有哪些标准能力模块
- 这些模块如何被挂接
- 图结构如何被编译
- 运行状态如何被保存、恢复、观测、测试

一句话：

`RuntimeKernel = LangGraph-based execution platform for contract-assembled agents`

---

## 2. 开发目标

`RuntimeKernel` 开发的目标有 8 个：

1. 提供统一的运行时状态模型
2. 提供统一的标准节点目录
3. 提供统一的 Graph Pattern DSL 编译机制
4. 提供统一的能力挂载接口
5. 提供统一的执行控制、中断、恢复机制
6. 提供统一的 trace、metrics、debug 观测接口
7. 提供统一的 checkpoint / persistence 机制
8. 提供统一的 harness 接入口

---

## 3. 非目标

`RuntimeKernel` 当前阶段不负责：

- 生成具体 Agent 的业务逻辑
- 生成业务工具代码
- 编写知识库内容
- 定义工厂 RuntimeKernel 阶段的内部提示词
- 让用户自由提交任意 LangGraph 代码直接运行

---

## 4. 总体分层

建议把 `RuntimeKernel` 按以下 4 层来开发：

### Layer 0: LangGraph / LangChain Infrastructure

基础设施层，包括：

- LangGraph `StateGraph`
- LangGraph checkpoint
- LangChain messages
- LangChain tool protocol
- LangChain model abstraction

这一层不做业务封装，只作为底层依赖。

### Layer 1: Runtime Kernel Core

核心平台层，包括：

- Runtime State System
- Standard Node Catalog
- Graph Pattern Compiler
- Execution Controller
- Context Engine
- Tool Orchestrator
- Memory Engine
- Knowledge Engine
- Interrupt / Approval Manager
- Checkpoint Manager
- Observability Manager
- Harness Bridge

### Layer 2: Capability Adapters

接入层，包括：

- model adapter
- tool adapter
- memory adapter
- knowledge adapter
- context adapter
- harness adapter

作用是把不同实现统一接入 Kernel。

### Layer 3: Agent Assembly Instance

实例层，由后续的 Agent Assembly Spec 驱动。

这层不属于 Kernel 本身的开发范围，但 Kernel 需要为它预留清晰接口。

---

## 5. Runtime Kernel 的核心对象

### 5.1 RuntimeState

`RuntimeState` 是统一运行状态模型，不能按具体 Agent 各自定义。

建议至少划分为以下区块：

- Conversation State
- Context State
- Tool State
- Memory State
- Execution State
- Observability State

要求：

- 必须可序列化
- 必须支持 checkpoint 持久化
- 必须支持 schema version 演进
- 必须支持 harness 稳定断言

### 5.2 Standard Node

Kernel 提供受控标准节点目录，Graph Pattern DSL 只能引用标准节点或受控扩展节点。

建议的第一批标准节点：

- `ingress`
- `answer`
- `tool_exec`
- `commit`
- `finalize`

记忆不再通过专用业务节点实现。会话内记忆统一使用 LangGraph `messages` channel + checkpointer，跨会话记忆统一使用 LangGraph `BaseStore`。

### 5.3 Graph Pattern DSL

Kernel 不直接接受任意图代码，而是接受受控 DSL。

这个 DSL 用于描述：

- 主图结构
- 节点集合
- 边关系
- subGraph 挂载
- interrupt 点
- 终止规则

要求：

- 可校验
- 可编译
- 可版本化
- 可被 harness 测试

### 5.4 Capability Binding

Kernel 需要统一的能力挂接对象，至少包括：

- prompt binding
- tool binding
- memory binding
- knowledge binding
- context binding
- harness binding

每种 binding 都应该有统一生命周期和统一编译接口。

---

## 6. Runtime Kernel 的核心子系统

### 6.1 State Schema System

职责：

- 定义 `RuntimeState`
- 管理 schema version
- 支持 migration
- 支持序列化与恢复

### 6.2 Graph Pattern Compiler

职责：

- 读取 Graph Pattern DSL
- 校验 DSL 合法性
- 选择标准节点实现
- 注入 subGraph
- 生成 LangGraph app

### 6.3 Execution Controller

职责：

- 控制执行循环
- 控制 route 决策
- 控制最大迭代次数
- 控制超时
- 处理中断与继续

### 6.4 Context Engine

职责：

- 收集上下文源
- 控制上下文拼装顺序
- 控制可见性
- 控制预算
- 控制压缩

### 6.5 Tool Orchestrator

职责：

- 工具注册
- 工具选择
- 工具审批
- 工具执行
- 工具观察结果标准化
- 工具失败与重试处理

### 6.6 Memory Engine

职责：

- 短期记忆
- 长期记忆
- 摘要记忆
- 写入策略
- 召回策略
- 脱敏与清理

### 6.7 Knowledge Engine

职责：

- 知识源装载
- 索引与检索
- 证据组织
- citation 输出
- freshness 管理

### 6.8 Interrupt / Approval Manager

职责：

- clarification pause
- human approval
- interrupt payload
- resume token / resume command

### 6.9 Checkpoint Manager

职责：

- 存储运行中状态
- 存储中断状态
- 从 checkpoint 恢复
- 支持 harness 对恢复流程做断言

### 6.10 Observability Manager

职责：

- trace
- span
- metrics
- structured events
- debug snapshot

### 6.11 Harness Bridge

职责：

- 让 harness 通过统一入口驱动 Kernel
- 注入 fixture
- 验证 graph path / tool call / context 行为

---

## 7. Graph Pattern DSL 在 Kernel 中的地位

当前已确定：

`Graph Pattern = 受控 DSL`

这意味着：

- Kernel 固定底层运行语义
- Pattern 负责描述主图结构
- Pattern 不直接等于运行时代码
- Pattern 由 Kernel 解释和编译

Kernel 对 Pattern 的支持必须包括：

- Pattern Schema
- Pattern Validator
- Pattern Compiler
- Pattern Registry
- Pattern Harness

当前阶段先定义规范，不做用户扩展管理。

---

## 8. 开发顺序

`RuntimeKernel` 建议按下面顺序开发：

### Phase A: Foundation

1. 定义 `RuntimeState`
2. 定义 Standard Node Catalog
3. 定义 Graph Pattern DSL v0
4. 定义 Graph Pattern Validator

### Phase B: Compilation

5. 实现 Graph Pattern Compiler
6. 实现 Standard Node Runtime Interface
7. 实现 SubGraph Runtime Interface

### Phase C: Core Capability Systems

8. 实现 Context Engine
9. 实现 Tool Orchestrator
10. 实现 Memory Engine
11. 实现 Knowledge Engine

### Phase D: Runtime Control

12. 实现 Execution Controller
13. 实现 Interrupt / Approval Manager
14. 实现 Checkpoint Manager

### Phase E: Quality And Operations

15. 实现 Observability Manager
16. 实现 Harness Bridge
17. 完成 Kernel 级别测试基线

---

## 9. 开发阶段的验收标准

### RuntimeState 验收

- 状态结构稳定
- 可序列化
- 可 checkpoint
- 可恢复

### Graph Pattern DSL 验收

- 可表达主图结构
- 可表达 interrupt 点
- 可表达 subGraph 挂载
- 可被 validator 校验

### Compiler 验收

- 同一份 DSL 编译结果稳定
- 非法 Pattern 会报明确错误
- 可输出 LangGraph app

### Capability System 验收

- tools / memory / context / knowledge 都有统一挂载方式
- 不同 Agent 不需要改 Kernel 内核语义

### Observability 验收

- 能看到 graph path
- 能看到 route 决策
- 能看到 tool lifecycle
- 能看到 interrupt / resume

### Harness 验收

- 可对 graph path 做断言
- 可对 tool 调用做断言
- 可对 context 传递做断言
- 可对 checkpoint / resume 做断言

---

## 10. 当前明确不做的事

当前 `RuntimeKernel` 文档阶段明确不做：

- 用户扩展 Pattern 的管理系统
- 用户自定义节点类型的开放注册
- 任意运行时代码生成
- 与工厂 RuntimeKernel 阶段的字段级映射细节

这些内容在 Kernel 核心结构稳定后再继续设计。

---

## 11. 下一步建议

按照当前讨论结果，Kernel 开发的下一份正式文档建议从这里开始：

1. `RuntimeState v0`
2. `Standard Node Catalog v0`
3. `Graph Pattern DSL v0`

优先级建议：

`Graph Pattern DSL v0` 与 `Standard Node Catalog v0` 可以并行定义，随后再落 `RuntimeState v0` 的最终结构。

---

## 12. 相关文档

- [项目说明](../../project-documentation/ProjectOverview.zh-CN.md)
- [Agent 架构](../../project-documentation/AgentArchitecture.zh-CN.md)
- [核心能力](../../project-documentation/CoreCapabilities.zh-CN.md)
- [部署与验收](../../project-documentation/Deployment.zh-CN.md)
