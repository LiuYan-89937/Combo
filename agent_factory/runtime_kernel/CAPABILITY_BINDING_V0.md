# Capability Binding v0

本文档定义 `RuntimeKernel` 的能力挂载规范：

`Capability Binding v0`

目标：

- 定义 Agent 的能力模块如何挂接到 `RuntimeKernel`
- 明确哪些能力属于全局运行时服务，哪些能力属于节点插槽配置
- 明确这些挂载如何落到 LangGraph 基座上

---

## 1. 设计原则

### 1.1 对象与数据分离

必须严格区分：

- **运行时对象**
  例如：
  - model adapter
  - tool registry
  - memory engine
  - knowledge engine
  - context engine
  - policy engine
  - observability manager
  - checkpoint manager

- **运行时数据**
  例如：
  - messages
  - model_context
  - tool_results
  - recall_items
  - citations
  - approval_required
  - route_decision
  - final_answer

规则：

- 运行时对象不进入 `RuntimeState`
- 运行时数据进入 `RuntimeState`

### 1.2 挂载不直接落在 graph 描述上

Graph Pattern 只描述图结构，不负责携带 live service object。

真正承载挂载的是：

`RuntimeKernelInstance`

### 1.3 节点不直接持有平台实现细节

节点只声明自己需要哪些 binding slot。

节点在运行时通过 wrapper 获取：

- 当前节点可见 binding
- 全局服务对象
- hook

### 1.4 子图默认继承父图绑定

子图默认继承父图的能力挂载。

允许：

- 继承
- 收窄
- 局部覆盖

不允许：

- 替换 Kernel 底层语义
- 改变 RuntimeState 根结构

---

## 2. 挂载层次

`Capability Binding v0` 统一分为三种挂载层次：

### 2.1 Global Mount

挂到整个 `RuntimeKernelInstance` 上，作为全局服务。

适合：

- model adapter
- tool registry
- memory engine
- knowledge engine
- context engine
- policy engine
- observability manager
- checkpoint manager
- harness bridge

### 2.2 Node Slot Mount

挂到某个节点实现的 slot 上，作为节点专属配置。

适合：

- prompt binding
- tool subset binding
- retrieval profile binding
- output formatter binding
- local policy profile

### 2.3 Hook Mount

挂到运行时生命周期钩子上。

适合：

- pre-cognitive policy
- pre-operational policy
- pre-finalize policy
- context rebuild hook
- trace emit hook
- interrupt hook

---

## 3. Global Mount 规范

## 3.1 定义

Global Mount 表示：

某个能力模块在整个运行时实例中只注册一次，并作为共享服务存在。

## 3.2 挂载对象

建议 v0 的全局服务对象如下：

- `model_service`
- `tool_registry`
- `memory_engine`
- `knowledge_engine`
- `context_engine`
- `policy_engine`
- `observability_manager`
- `checkpoint_manager`
- `harness_bridge`

## 3.3 落到 LangGraph 的方式

它们不进入 `StateGraph` 的 state。

而是挂在：

`RuntimeKernelInstance.services`

示意：

```text
RuntimeKernelInstance
  services:
    model_service
    tool_registry
    memory_engine
    knowledge_engine
    context_engine
    policy_engine
    observability_manager
    checkpoint_manager
    harness_bridge
```

## 3.4 使用方式

LangGraph 中注册的节点，不直接持有这些对象，而是通过统一 wrapper 注入：

```text
wrapped_node
  -> node_bindings
  -> runtime_services
  -> hooks
  -> node_impl(state)
```

---

## 4. Node Slot Mount 规范

## 4.1 定义

Node Slot Mount 表示：

某个能力配置只对某个节点实现生效。

例如：

- `cognitive.answer` 用一套 prompt
- `cognitive.clarify` 用另一套 prompt
- `operational.tool_call` 只允许某些工具

## 4.2 节点插槽对象

建议 v0 抽象统一结构：

```yaml
binding_id: string
binding_type: string
target:
  node_id: string
  impl: string
payload: {}
```

### 字段说明

- `binding_id`
  当前 binding 唯一标识
- `binding_type`
  当前 binding 类型
- `target.node_id`
  绑定到哪个图节点
- `target.impl`
  绑定到哪个节点实现
- `payload`
  具体绑定内容

---

## 5. Hook Mount 规范

## 5.1 定义

Hook Mount 表示：

某项能力不直接属于某个节点实现，而是在节点执行前后作为运行时钩子触发。

## 5.2 建议的 v0 hook 位点

- `pre_cognitive`
- `post_cognitive`
- `pre_operational`
- `post_operational`
- `pre_governance`
- `post_governance`
- `pre_terminal`
- `post_terminal`
- `on_interrupt`
- `on_resume`

## 5.3 典型用途

- 策略前置检查
- 上下文重建
- trace 记录
- interrupt payload 生成
- 输出后检查

## 5.4 落到 LangGraph 的方式

LangGraph 本身不直接提供完整 hook 系统，因此由节点 wrapper 负责执行：

```text
wrapped_node(state):
  run_pre_hooks(...)
  patch = node_impl(...)
  patch = run_post_hooks(...)
  return patch
```

---

## 6. 各能力模块的挂载方式

## 6.1 Prompt Binding

### 类型

`node slot mount`

### 原则

Prompt 不作为 graph 级单一字符串挂载，而是按节点插槽挂载。

### 推荐挂载目标

- `cognitive.clarify`
- `cognitive.plan`
- `cognitive.route`
- `cognitive.answer`
- `cognitive.review`

### 典型结构

```yaml
binding_id: prompt_answer_v1
binding_type: prompt
target:
  node_id: answer
  impl: cognitive.answer
payload:
  prompt_id: prompt.answer.default
  template_ref: prompt://answer/default
  variables:
    - conversation
    - context
    - memory
    - knowledge
```

### 落地方式

- 编译时记录到 `node_bindings`
- 运行时 wrapper 把它传给对应 cognitive 节点

---

## 6.2 Tool Binding

### 类型

- global mount
- node slot mount

### 原则

工具分两层挂载：

1. 全局：
   `tool_registry`
2. 节点局部：
   当前节点可见工具子集

### 全局层

```yaml
service: tool_registry
content:
  all_tools:
    - get_order
    - search_orders
    - list_orders
```

### 节点层

```yaml
binding_id: tool_access_main
binding_type: tool_access
target:
  node_id: tool_exec
  impl: operational.tool_call
payload:
  allowed_tool_ids:
    - get_order
    - search_orders
  approval_policy: standard
```

### 落地方式

- 节点从 binding 中拿 `allowed_tool_ids`
- 再去全局 `tool_registry` 解析具体工具

---

## 6.3 Memory Binding

### 类型

- global mount
- node slot mount（可选）

### 原则

Memory Engine 全局挂载，但不允许所有节点直接访问。

Memory 访问必须通过特定标准实现节点发生。

### 全局层

```yaml
service: memory_engine
content:
  backend: session_store
  mode: short_term_plus_summary
```

### 节点层

推荐挂载到：

- `operational.memory_retrieve`
- `terminal.commit`

### 落地方式

- 节点调用全局 `memory_engine`
- 结果写回 `state.memory`

---

## 6.4 Knowledge Binding

### 类型

- global mount
- node slot mount（可选）

### 原则

Knowledge Engine 全局挂载，检索动作通过 `operational.*` 节点实现。

### 全局层

```yaml
service: knowledge_engine
content:
  sources:
    - kb://orders
    - kb://faq
```

### 节点层

推荐挂载到：

- `operational.knowledge_retrieve`
- `operational.resource_probe`

### 落地方式

- 节点调用全局 `knowledge_engine`
- 结果写回 `state.knowledge`

---

## 6.5 Context Binding

### 类型

- global mount
- hook mount
- node slot mount（少量）

### 原则

Context Engine 是全局服务，不是 prompt helper。

### 全局层

```yaml
service: context_engine
content:
  default_policy: standard_context_v1
```

### Hook 层

推荐：

- `pre_cognitive`
- `pre_operational`

### 落地方式

- 在进入 cognitive / operational 节点前重建 `model_context` 或 `tool_context`
- 写回 `state.context`

---

## 6.6 Policy Binding

### 类型

- global mount
- node slot mount
- hook mount

### 原则

Policy 是双落点：

1. 全局 `policy_engine`
2. `governance.*` 节点显式消费
3. 某些 pre-hook / post-hook 消费

### 全局层

```yaml
service: policy_engine
content:
  profile: moderate_risk
```

### 节点层

推荐挂载到：

- `governance.precheck`
- `governance.postcheck`
- `governance.approval_gate`

### Hook 层

推荐：

- `pre_cognitive`
- `pre_operational`
- `pre_terminal`

---

## 6.7 Harness Binding

### 类型

`global mount`

### 原则

Harness 不挂到图内部节点上，而作为 RuntimeKernel 外部桥接能力。

### 全局层

```yaml
service: harness_bridge
content:
  mode: standard
```

### 落地方式

- Harness 通过 Kernel 外部 API 驱动 graph
- 读取 state / trace / events 做断言

---

## 7. 子图绑定继承规则

## 7.1 默认规则

子图默认继承父图全部 binding。

## 7.2 允许收窄

子图可以声明收窄：

- `allowed_prompts`
- `allowed_tools`
- `allowed_context_sections`
- `allowed_policy_scopes`

## 7.3 允许局部覆盖

子图可以覆盖：

- prompt slot
- tool subset
- local policy profile

## 7.4 不允许覆盖

子图不能替换：

- RuntimeState 根结构
- 全局 engine 类型
- checkpoint 协议
- trace 协议

---

## 8. 编译时挂载流程

`Capability Binding v0` 建议的编译流程如下：

1. 读取 Graph Pattern
2. 创建 `RuntimeKernelInstance`
3. 注册 global services
4. 解析每个节点需要的 node slot bindings
5. 解析 hook bindings
6. 生成 node wrapper
7. 编译为 LangGraph app

---

## 9. LangGraph 落地方式

## 9.1 Pattern 落地

Graph Pattern DSL 编译成：

- `StateGraph(RuntimeState)`
- `add_node(...)`
- `add_edge(...)`
- `add_conditional_edges(...)`

## 9.2 节点落地

LangGraph 中真正注册的是 wrapper 后的 callable：

```text
wrapped_node
  -> runtime_services
  -> node_bindings
  -> hooks
  -> node_impl
```

## 9.3 子图落地

若节点定义为：

```yaml
type: sub_graph
impl: pattern_ref
pattern_ref: clarification_loop_v1
```

则：

- 编译器先编译子图
- 再用子图包装器把它作为父图节点注册

---

## 10. v0 统一根结构建议

建议定义一个统一的绑定集合根对象：

```yaml
bindings:
  services: {}
  node_bindings: []
  hooks: []
```

说明：

- `services`
  全局服务挂载
- `node_bindings`
  节点插槽挂载
- `hooks`
  生命周期钩子挂载

---

## 11. v0 明确不做

当前阶段不做：

- 用户扩展 binding 类型管理系统
- 热更新 binding
- 动态替换全局 engine 类型
- graph 运行中新增 binding

---

## 12. v0 下一步

基于当前讨论，下一步需要：

1. 给 `bindings.services` 定正式 schema
2. 给 `bindings.node_bindings` 定正式 schema
3. 给 `bindings.hooks` 定正式 schema
4. 继续细化 `Execution Controller v0`
