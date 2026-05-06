# Standard Node Catalog v0

本文档定义 `RuntimeKernel` 的标准节点目录 `Standard Node Catalog v0`。

目标：

- 为 `Graph Pattern DSL v0` 提供受控节点集合
- 为 `RuntimeKernel` 的图编译提供统一节点语义
- 避免节点分类重叠，保证后续 Pattern 差异清晰

---

## 1. 设计原则

### 1.1 节点按运行责任分类

标准节点的分类不按“表面功能名词”拆，而按：

`节点在 RuntimeKernel 中对状态和执行流承担的核心责任`

来分类。

### 1.2 只保留四类通用节点

v0 只保留 4 类通用节点：

- `cognitive`
- `operational`
- `governance`
- `terminal`

### 1.3 平台保留节点单独处理

平台保留节点不并入四类竞争抽象中：

- `ingress`
- `finalize`

它们是 Kernel 固定入口 / 固定收束点。

### 1.4 分类必须避免职能重叠

以下内容在 v0 中统一收口：

- 推理、判断、规划、澄清、路由判断 -> `cognitive`
- 工具调用、知识检索、记忆检索、资源探测 -> `operational`
- 策略检查、审批、中断、阻断、拒答 -> `governance`
- 结束、提交、收束 -> `terminal`

### 1.5 节点实现与节点类别分离

节点目录分两层：

1. **Node Category**
   节点责任类别
2. **Standard Implementation**
   平台内置实现

也就是说：

`Graph Pattern` 不应该只连“大类节点”，而是引用具体实现。

---

## 2. 节点目录总结构

`Standard Node Catalog v0` 由三部分组成：

### A. Kernel Reserved Nodes

平台保留节点：

- `ingress`
- `finalize`

### B. Runtime Node Categories

通用节点责任类别：

- `cognitive`
- `operational`
- `governance`
- `terminal`

### C. Standard Implementations

平台内置标准实现，例如：

- `cognitive.clarify`
- `cognitive.plan`
- `operational.tool_call`
- `governance.precheck`
- `terminal.commit`

---

## 3. Kernel Reserved Nodes

## 3.1 ingress

中文：入口节点
English: Ingress

作用：

- 接收外部输入
- 初始化本轮运行
- 写入本轮执行入口信息

职责边界：

- 不做业务推理
- 不做工具调用
- 不做策略判断
- 只负责把运行带入第一个可执行节点

建议输入：

- `run`
- 外部输入 payload

建议输出：

- `conversation.current_user_input`
- `execution.current_node`
- `execution.turn_count`

是否支持 interrupt：否
是否支持 subGraph：否

---

## 3.2 finalize

中文：收束节点
English: Finalize

作用：

- 结束本轮执行
- 输出最终结果
- 标记运行状态结束

职责边界：

- 不再进入新的业务推理循环
- 不发起新的工具调用
- 不做新的知识检索

建议输入：

- `conversation.final_answer`
- `policy`
- `execution`

建议输出：

- `execution.finished`
- `execution.finish_status`

是否支持 interrupt：否
是否支持 subGraph：否

---

## 4. Runtime Node Categories

## 4.1 cognitive

中文：认知节点
English: Cognitive Node

定义：

凡是“需要模型进行理解、判断、规划、澄清、总结、路由决策、答案生成”的节点，都归入 `cognitive`。

典型职责：

- 理解用户意图
- 澄清缺失信息
- 规划任务步骤
- 做 route decision
- 生成回答草稿
- 做结果 review

注意：

- route 判断也归入 `cognitive`
- ready / continue / revise 这类决策也归入 `cognitive`
- 不单独再拆一个 `control` 类

典型输入：

- `conversation`
- `context`
- `memory`
- `knowledge`
- `policy`

典型输出：

- `conversation.assistant_draft`
- `execution.route_decision`
- `tools.pending_tool_call`
- `conversation.clarification_question`

是否支持 interrupt：通常否
是否支持 subGraph：通常是

---

## 4.2 operational

中文：操作节点
English: Operational Node

定义：

凡是“执行外部能力、系统能力、工具能力、检索能力”的节点，都归入 `operational`。

典型职责：

- 调用工具
- 检索知识
- 检索记忆
- 读取资源
- 探测外部状态

注意：

- `knowledge retrieval` 归入 `operational`
- `memory retrieval` 归入 `operational`
- 不再单独拆一个 `retrieval` 类

原因：

从 RuntimeKernel 的角度看，这些都是：

`执行一次外部 / 系统操作，然后把结果写回状态`

典型输入：

- `tools`
- `context.tool_context`
- `knowledge`
- `memory`
- `policy`

典型输出：

- `tools.tool_results`
- `knowledge.retrieved_items`
- `memory.recall_items`
- `tools.tool_failures`

是否支持 interrupt：通常是
是否支持 subGraph：通常是

---

## 4.3 governance

中文：治理节点
English: Governance Node

定义：

凡是“执行策略约束、审批判断、中断、阻断、拒答、输出前合规检查”的节点，都归入 `governance`。

典型职责：

- precheck
- postcheck
- approval gate
- refusal gate
- risk gate

注意：

- approval / interrupt 属于治理，不单独再拆一个类别
- policy 与 interrupt 在这一层统一收口

典型输入：

- `conversation`
- `context`
- `tools`
- `knowledge`
- `policy`

典型输出：

- `policy.blocked`
- `policy.approval_required`
- `policy.interrupt_required`
- `policy.refusal_reason`

是否支持 interrupt：是
是否支持 subGraph：是

---

## 4.4 terminal

中文：终结节点
English: Terminal Node

定义：

凡是“结束当前阶段或结束当前运行，并提交最终结果”的节点，都归入 `terminal`。

典型职责：

- finalize answer
- commit result
- mark finished

注意：

- `finalize` 是平台保留实现
- `terminal` 这个类别用于描述其他终结型实现

典型输入：

- `conversation.final_answer`
- `execution`
- `policy`

典型输出：

- `execution.finished`
- `execution.finish_status`
- 最终返回对象

是否支持 interrupt：通常否
是否支持 subGraph：通常否

---

## 5. Standard Implementations v0

下面给出 v0 建议的第一批平台内置标准实现。

## 5.1 cognitive implementations

- `cognitive.clarify`
  用于多轮补问和需求澄清

- `cognitive.plan`
  用于规划任务步骤或行动方案

- `cognitive.route`
  用于判断下一跳路由

- `cognitive.answer`
  用于生成回答草稿

- `cognitive.review`
  用于检查已有草稿并决定是否修正

## 5.2 operational implementations

- `operational.tool_call`
  调用工具

- `operational.knowledge_retrieve`
  检索知识源

- `operational.memory_retrieve`
  检索记忆

- `operational.resource_probe`
  探测资源 / 外部状态

## 5.3 governance implementations

- `governance.precheck`
  模型前策略检查

- `governance.postcheck`
  输出前策略检查

- `governance.approval_gate`
  审批门

- `governance.refusal_gate`
  拒答门

## 5.4 terminal implementations

- `terminal.commit`
  提交本轮结果

- `terminal.close`
  关闭运行并返回结束状态

---

## 6. 节点与 Pattern 的关系

Pattern 不是直接使用四个大类节点，而是：

- 引用平台保留节点
- 引用具体标准实现

例如：

```yaml
nodes:
  - id: ingress
    type: reserved
    impl: ingress

  - id: clarify
    type: cognitive
    impl: cognitive.clarify

  - id: approval_gate
    type: governance
    impl: governance.approval_gate

  - id: tool_exec
    type: operational
    impl: operational.tool_call

  - id: finalize
    type: reserved
    impl: finalize
```

这样不同 Pattern 才会真正拉开差异。

---

## 7. 节点类别与 Pattern 差异示例

### 7.1 react_agent

更偏向：

- `cognitive.answer`
- `operational.tool_call`
- `governance.precheck`
- `finalize`

### 7.2 clarify_then_act

更偏向：

- `cognitive.clarify`
- `governance.approval_gate`
- `operational.tool_call`
- `finalize`

### 7.3 planner_executor

更偏向：

- `cognitive.plan`
- `operational.*`
- `cognitive.review`
- `terminal.commit`

这也是为什么节点分类必须按运行责任，而不是按表面功能。

---

## 8. v0 约束

### 8.1 允许的节点来源

Graph Pattern DSL v0 只能引用：

- `ingress`
- `finalize`
- 平台内置 standard implementation

### 8.2 不允许的事

当前阶段不允许：

- 用户自定义新的节点类别
- 用户自定义新的底层节点语义
- 把 route / ready / revise 判断拆成新的通用类别

---

## 9. v0 下一步

基于当前文档，下一步需要：

1. 把 `Graph Pattern DSL v0` 中的 `nodes` 结构改成 `type + impl` 形式
2. 为第一批 standard implementation 定义正式接口
3. 再讨论 `SubGraph Catalog v0`
