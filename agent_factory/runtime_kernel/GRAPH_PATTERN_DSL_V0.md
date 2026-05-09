# Graph Pattern DSL v0

本文档定义 `RuntimeKernel` 的图结构描述语言：

`Graph Pattern DSL v0`

目标：

- 用受控 DSL 描述 Agent 的主图结构
- 不允许直接提交任意 LangGraph 代码
- 主图和子图使用同一套 Pattern 规范
- 子图可以像 LangGraph 一样被父图当作一个节点引用

---

## 1. 设计原则

### 1.1 受控 DSL

Graph Pattern 不是运行时代码，而是受控 DSL。

它只能描述：

- 图的元信息
- 节点集合
- 边关系
- interrupt 点
- 终止规则
- 子图边界契约

### 1.1.1 Pattern Catalog 与完整 Pattern 分离

Pattern 有两种读取视图：

- `PatternCatalogItemSpec`：只包含 `pattern_id / kind / embeddable / version / name / description / metadata`
- `GraphPatternSpec`：包含完整 `nodes / edges / wrappers / contracts`，只给 RuntimeKernel 编译和验证使用

Factory 模型做 pattern 选择时只能读取 catalog item，不应一次性接收完整 YAML 内容。
完整 Pattern YAML 只在 `RuntimeKernel.compile(...)`、validator、harness 或明确的工程审查场景中读取。

### 1.2 主图与子图同构

主图和子图都使用同一套 `GraphPatternSpec`。

区别只通过字段表达：

- `kind: main`
- `kind: subgraph`

### 1.3 子图可以作为节点引用

父图中的某个节点可以不直接指向标准实现，而是指向另一个 Pattern：

- `impl: pattern_ref`
- `pattern_ref: some_subgraph_v1`

也就是说：

`subGraph = 可嵌入的 Pattern`

### 1.4 Kernel 固定语义

DSL 可以定义图结构，但不能改变 Runtime Kernel 的底层语义，例如：

- RuntimeState 根结构
- tool lifecycle
- checkpoint 协议
- trace 协议

### 1.5 节点引用必须走 `type + impl`

每个节点必须明确：

- `type`
- `impl`

从而区分：

- 平台保留节点
- 标准节点类别
- 具体标准实现
- 子图引用节点

---

## 2. 顶层结构

Graph Pattern DSL v0 的顶层结构建议如下：

```yaml
pattern_id: string
kind: main | subgraph
embeddable: boolean
version: integer
name: string
description: string
metadata:
  summary: string
  use_when: []
  avoid_when: []
  selection_notes: []
  tags: []

entry_node: string
nodes: []
edges: []
interrupt_points: []
termination: {}
constraints: {}

input_contract: {}
output_contract: {}
exit_routes: []
state_mode: shared | isolated
```

---

## 3. 顶层字段说明

## 3.1 `pattern_id`

作用：

- Pattern 的唯一标识

要求：

- 全局唯一
- 建议使用 snake_case

示例：

```yaml
pattern_id: react_agent
```

## 3.2 `kind`

作用：

- 指明这是主图还是子图

允许值：

- `main`
- `subgraph`

示例：

```yaml
kind: main
```

## 3.3 `embeddable`

作用：

- 是否允许被其他 Pattern 作为子图引用

规则：

- `kind: main` 通常为 `false`
- `kind: subgraph` 通常为 `true`

示例：

```yaml
embeddable: true
```

## 3.4 `version`

作用：

- Pattern 版本号

要求：

- 正整数

## 3.5 `name`

作用：

- Pattern 展示名

## 3.6 `description`

作用：

- 描述 Pattern 的用途与场景

## 3.7 `entry_node`

作用：

- 图入口节点

约束：

- 必须存在于 `nodes[].id`

## 3.8 `nodes`

作用：

- 定义当前 Pattern 的节点集合

每个节点最少字段：

- `id`
- `type`
- `impl`

可选字段：

- `pattern_ref`
- `config`

示例：

```yaml
nodes:
  - id: ingress
    type: reserved
    impl: ingress

  - id: answer
    type: cognitive
    impl: cognitive.answer

  - id: tool_exec
    type: operational
    impl: operational.tool_call

  - id: finalize
    type: reserved
    impl: finalize
```

### 允许的 `type`

- `reserved`
- `cognitive`
- `operational`
- `governance`
- `terminal`
- `sub_graph`

说明：

- `reserved`
  只用于平台保留节点：
  - `ingress`
  - `finalize`
- `sub_graph`
  只用于引用另一个 Pattern 作为节点嵌入

### `impl` 规则

`impl` 在 v0 有两种形式：

1. 标准实现
   例如：
   - `cognitive.answer`
   - `operational.tool_call`
   - `governance.precheck`

2. 子图引用
   固定写法：

```yaml
type: sub_graph
impl: pattern_ref
pattern_ref: clarification_loop_v1
```

## 3.9 `edges`

作用：

- 定义节点之间的流转关系

每条边最少字段：

- `from`
- `to`
- `when`

示例：

```yaml
edges:
  - from: ingress
    to: precheck
    when: always

  - from: answer
    to: tool_exec
    when: model.requests_tool
```

## 3.10 `interrupt_points`

作用：

- 定义哪些节点允许进入 interrupt / approval / pause

约束：

- 只能引用支持 interrupt 的节点 id

## 3.11 `termination`

作用：

- 定义成功结束与失败结束节点

示例：

```yaml
termination:
  success_nodes:
    - finalize
  failure_nodes: []
```

## 3.12 `constraints`

作用：

- 定义 Pattern 的运行约束

v0 先保留：

```yaml
constraints:
  allowed_node_types:
    - reserved
    - cognitive
    - operational
    - governance
    - terminal
    - sub_graph
  required_capabilities: []
```

## 3.13 `input_contract`

作用：

- 只对子图有意义
- 定义子图允许读取哪些 RuntimeState section

示例：

```yaml
input_contract:
  readable_sections:
    - conversation
    - context
    - policy
```

## 3.14 `output_contract`

作用：

- 只对子图有意义
- 定义子图允许写哪些 RuntimeState section

示例：

```yaml
output_contract:
  writable_sections:
    - conversation
    - execution
    - policy
```

## 3.15 `exit_routes`

作用：

- 只对子图有意义
- 定义子图结束后允许返回给父图的退出结果

示例：

```yaml
exit_routes:
  - done
  - need_more_input
  - blocked
```

## 3.16 `state_mode`

作用：

- 定义子图和父图的状态关系

允许值：

- `shared`
- `isolated`

v0 建议：

- 先只正式支持 `shared`

---

## 4. Edge Condition v0

v0 不引入自由表达式语言。

`edges.when` 只允许使用受控枚举条件。

建议的 v0 条件集合：

- `always`
- `model.requests_tool`
- `model.ready_to_answer`
- `policy.blocked`
- `policy.approval_required`
- `tool.completed`
- `tool.failed`
- `tool.interrupted`
- `subgraph.done`
- `subgraph.need_more_input`
- `subgraph.blocked`
- `execution.finished`

---

## 5. 示例 1：主图 Pattern

下面是一个支持“澄清后执行”的主图示例。

```yaml
pattern_id: clarify_then_act
kind: main
embeddable: false
version: 1
name: Clarify Then Act
description: Ask for missing information before entering the main action flow.

entry_node: ingress

nodes:
  - id: ingress
    type: reserved
    impl: ingress

  - id: clarify_loop
    type: sub_graph
    impl: pattern_ref
    pattern_ref: clarification_loop_v1

  - id: precheck
    type: governance
    impl: governance.precheck

  - id: answer
    type: cognitive
    impl: cognitive.answer

  - id: tool_exec
    type: operational
    impl: operational.tool_call

  - id: finalize
    type: reserved
    impl: finalize

edges:
  - from: ingress
    to: clarify_loop
    when: always

  - from: clarify_loop
    to: precheck
    when: subgraph.done

  - from: clarify_loop
    to: finalize
    when: subgraph.need_more_input

  - from: clarify_loop
    to: finalize
    when: subgraph.blocked

  - from: precheck
    to: finalize
    when: policy.blocked

  - from: precheck
    to: answer
    when: always

  - from: answer
    to: tool_exec
    when: model.requests_tool

  - from: answer
    to: finalize
    when: model.ready_to_answer

  - from: tool_exec
    to: answer
    when: tool.completed

interrupt_points:
  - precheck
  - tool_exec

termination:
  success_nodes:
    - finalize
  failure_nodes: []

constraints:
  allowed_node_types:
    - reserved
    - cognitive
    - operational
    - governance
    - terminal
    - sub_graph
  required_capabilities: []

input_contract: {}
output_contract: {}
exit_routes: []
state_mode: shared
```

---

## 6. 示例 2：子图 Pattern

下面是被主图引用的 `clarification_loop_v1` 子图。

```yaml
pattern_id: clarification_loop_v1
kind: subgraph
embeddable: true
version: 1
name: Clarification Loop
description: Multi-turn clarification loop before the main action phase.

entry_node: clarify

nodes:
  - id: clarify
    type: cognitive
    impl: cognitive.clarify

  - id: route_after_clarify
    type: cognitive
    impl: cognitive.route

  - id: finalize
    type: reserved
    impl: finalize

edges:
  - from: clarify
    to: route_after_clarify
    when: always

  - from: route_after_clarify
    to: finalize
    when: subgraph.done

  - from: route_after_clarify
    to: finalize
    when: subgraph.need_more_input

  - from: route_after_clarify
    to: finalize
    when: subgraph.blocked

interrupt_points: []

termination:
  success_nodes:
    - finalize
  failure_nodes: []

constraints:
  allowed_node_types:
    - reserved
    - cognitive
    - operational
    - governance
    - terminal
  required_capabilities: []

input_contract:
  readable_sections:
    - conversation
    - context
    - policy

output_contract:
  writable_sections:
    - conversation
    - execution
    - policy

exit_routes:
  - done
  - need_more_input
  - blocked

state_mode: shared
```

---

## 7. 子图作为节点引用时的编译语义

当父图出现下面这种节点：

```yaml
- id: clarify_loop
  type: sub_graph
  impl: pattern_ref
  pattern_ref: clarification_loop_v1
```

Kernel 编译时应解释为：

- `clarify_loop` 在父图中是一个节点
- 该节点内部运行 `clarification_loop_v1`
- 子图完成后，返回某个 `exit_route`
- 父图根据 `subgraph.done / subgraph.need_more_input / subgraph.blocked` 继续流转

也就是说：

`子图在结构上是 Pattern`
`在父图编译结果里表现为 Node`

---

## 8. Validator 规则

Graph Pattern Validator v0 至少要检查：

### 8.1 结构合法性

- `pattern_id` 非空
- `kind` 合法
- `embeddable` 合法
- `version` 为正整数
- `entry_node` 非空
- `nodes` 非空

### 8.2 节点合法性

- `nodes[].id` 全局唯一
- `nodes[].type` 合法
- `nodes[].impl` 合法
- 若 `nodes[].type == sub_graph`，则 `nodes[].impl` 必须为 `pattern_ref`
- 若 `nodes[].type != sub_graph`，则 `nodes[].impl` 不能为 `pattern_ref`
- 如果 `impl == pattern_ref`，必须存在 `pattern_ref`
- `entry_node` 必须属于某个 `nodes[].id`

### 8.3 边合法性

- `edges.from` 必须引用已定义的 `nodes[].id`
- `edges.to` 必须引用已定义的 `nodes[].id`
- `when` 必须属于受控条件集合

### 8.4 interrupt 合法性

- `interrupt_points` 只能引用支持 interrupt 的节点 id

### 8.5 termination 合法性

- `termination.success_nodes` 不能为空
- success node 必须存在于 `nodes[].id`

### 8.6 子图边界合法性

若 `kind == subgraph`，则：

- `embeddable` 应为 `true`
- `input_contract` 必须存在
- `output_contract` 必须存在
- `exit_routes` 必须非空
- `state_mode` 必须合法

### 8.7 可达性

- 必须至少存在一条从 `entry_node` 到 success node 的路径

---

## 9. DSL 与 Kernel 的边界

DSL 可以控制：

- 选哪些标准实现
- 节点怎么连
- 哪个节点引用哪个子图
- 哪些节点允许 interrupt
- 子图的输入输出边界

DSL 不允许控制：

- RuntimeState 根结构
- provider-specific 模型实现
- tool lifecycle 协议
- checkpoint 协议
- trace 协议

---

## 10. v0 明确不做

Graph Pattern DSL v0 暂不支持：

- 自由表达式语言
- 用户自定义底层节点类别
- 用户自定义根状态结构
- 用户自定义底层执行语义
- 用户扩展 Pattern 的管理系统

---

## 11. v0 下一步

基于当前 DSL 文档，下一步需要：

1. 实现 `Pattern Schema`
2. 实现 `Pattern Validator`
3. 实现 `Pattern Compiler`
4. 定义 `SubGraph Embedding Rules`
