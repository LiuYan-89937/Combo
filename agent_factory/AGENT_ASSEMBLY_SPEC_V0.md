# Agent Assembly Spec v0

本文档定义 `Agent Assembly Spec v0`：

`Agent Assembly Spec = concrete Agent contract compiled onto RuntimeKernel`

目标：

- 定义一个具体 Agent 如何声明身份、运行图、能力、策略、上下文、测试场景
- 定义这些声明如何转换成 `RuntimeKernel.compile(pattern_id, bindings, services)`
- 明确 Agent 装配层与 RuntimeKernel、工厂 RuntimeKernel 阶段、真实外部服务之间的边界

---

## 1. 定位

`RuntimeKernel` 已经定义了统一运行平台：

- RuntimeState
- Standard Node
- Graph Pattern DSL
- Capability Binding
- Execution Controller
- Checkpoint
- Observability
- Harness Bridge

`Agent Assembly Spec` 位于 RuntimeKernel 之上。

它不定义新的运行时语义，而是把一个具体 Agent 的配置装配到 RuntimeKernel 已有语义上。

一句话：

`AgentAssemblySpec = Agent-level declarative configuration for a RuntimeKernel instance`

典型链路：

```text
Factory 14 stages
  -> Agent Assembly Spec
  -> BindingSet + RuntimeServices requirements
  -> RuntimeKernel.compile(...)
  -> CompiledKernelApp
  -> RuntimeKernel.run/resume(...)
```

---

## 2. 设计原则

### 2.1 声明式优先

Agent Assembly Spec 只描述“要装配什么”，不直接执行装配。

允许：

- 声明 Agent 身份
- 声明使用哪个 graph pattern
- 声明 prompt / tool / memory / knowledge / context / policy 绑定
- 声明 harness 场景

不允许：

- 直接携带 live Python object
- 内嵌任意 LangGraph 代码
- 修改 RuntimeKernel 的节点语义

### 2.2 对象与数据分离

必须严格区分：

- **Spec 数据**
  可以序列化、可以审查、可以版本化

- **Runtime object**
  例如 model client、tool callable、memory store、knowledge retriever

规则：

- Runtime object 不进入 Agent Assembly Spec
- Spec 只声明 service requirement / binding / profile
- Runtime object 由部署环境或测试 fixture 注入

### 2.3 不替代 RuntimeKernel

Agent Assembly Spec 不重复定义：

- RuntimeState 根结构
- Standard Node Catalog
- Graph Pattern DSL 的边语义
- Checkpoint 结构
- Observability event schema
- Harness Bridge 执行方式

这些仍由 RuntimeKernel 负责。

### 2.4 装配结果必须可验证

每个 Agent Assembly Spec 应当能被：

- schema validator 校验
- assembly compiler 编译
- harness scenario 验证
- observability trace 审计

### 2.5 工厂输出与运行时解耦

工厂 RuntimeKernel 阶段可以生成或修改 Agent Assembly Spec。

但 RuntimeKernel 只消费编译后的：

- `pattern_id`
- `BindingSet`
- `RuntimeServices`
- optional harness scenarios

RuntimeKernel 不依赖工厂内部阶段字段。

### 2.6 工厂与模型友好

Agent Assembly Spec 必须方便工厂模型写入、修改和理解。

这意味着：

- 字段命名要直接表达意图，避免过度抽象
- section 要按工厂阶段和运行时职责分块
- 每个 section 尽量可独立生成、独立校验、独立修复
- 支持 draft 状态，允许工厂分阶段逐步补全
- 支持局部 patch，不要求每次重写整份 spec
- 支持 open questions / validation notes，方便模型继续推理
- 运行时 compiler 必须忽略纯 authoring metadata，避免污染 RuntimeKernel

一句话：

`Spec must be model-writable, patch-friendly, and reviewable before it is runnable.`

---

## 3. 非目标

`Agent Assembly Spec v0` 当前不负责：

- 定义工厂 RuntimeKernel 阶段内部提示词
- 生成真实工具实现代码
- 生成真实模型客户端配置
- 管理 secret 明文
- 支持用户自定义任意 graph code
- 支持多 Agent 协作编排
- 支持分布式部署拓扑
- 支持 provider-specific tracing 扩展

---

## 4. 顶层结构

建议根结构：

```yaml
schema_version: "0.1"
assembly_id: string

authoring: {}
agent: {}
runtime: {}
services: {}
capabilities: {}
bindings: {}
io_contract: {}
policy: {}
interrupts: {}
harness: {}
metadata: {}
```

字段说明：

- `schema_version`
  Agent Assembly Spec schema 版本

- `assembly_id`
  当前装配规格唯一标识

- `authoring`
  工厂写入、修改、审查过程中的辅助信息

- `agent`
  Agent 身份与展示信息

- `runtime`
  RuntimeKernel 运行图与执行限制

- `services`
  运行所需 service requirement，不包含 live object

- `capabilities`
  Agent 可用能力声明

- `bindings`
  转换到 RuntimeKernel `BindingSet` 的绑定声明

- `io_contract`
  Agent 输入输出与可见状态约束

- `policy`
  Agent 级策略与风险控制声明

- `interrupts`
  interrupt / approval / resume 行为声明

- `harness`
  Agent 级测试场景

- `metadata`
  审计、来源、生成阶段等附加信息

---

## 5. Authoring State

## 5.1 作用

`authoring` 是工厂写入和模型修改 spec 时使用的辅助区。

它不进入 RuntimeKernel `RuntimeState`，也不直接转换成 `BindingSet`。

建议结构：

```yaml
authoring:
  status: draft | ready_for_validation | validated | rejected
  current_stage: string | null
  last_updated_by_stage: string | null
  open_questions: []
  assumptions: []
  validation_notes: []
  revision_log: []
```

字段说明：

- `status`
  当前 spec 写作状态

- `current_stage`
  当前正在写入或修改 spec 的工厂阶段

- `last_updated_by_stage`
  最近一次修改来自哪个工厂阶段

- `open_questions`
  工厂模型尚未解决的问题

- `assumptions`
  工厂模型当前采用的假设

- `validation_notes`
  validator 或审查过程留下的问题

- `revision_log`
  重要修改记录

## 5.2 v0 规则

- draft spec 可以不完整
- runnable spec 必须通过 final validation
- Assembly Compiler 只允许编译 `ready_for_validation` 或 `validated` 且通过校验的 spec
- RuntimeKernel 不消费 `authoring`
- 工厂模型可以优先修改 `authoring.open_questions` 和 `authoring.validation_notes`，再修改运行 section

---

## 6. Agent Identity

## 6.1 作用

`agent` 描述一个具体 Agent 的稳定身份。

建议结构：

```yaml
agent:
  agent_id: string
  name: string
  version: string
  description: string
  owner: string | null
  tags: []
```

字段说明：

- `agent_id`
  Agent 稳定唯一标识，应写入 `RuntimeState.run.agent_id`

- `name`
  面向人类的名称

- `version`
  Agent 自身版本，不等同于 RuntimeKernel 版本

- `description`
  Agent 能力摘要

- `owner`
  责任方或生成方，可为空

- `tags`
  便于检索和分类

## 6.2 v0 规则

- `agent_id` 必须非空
- `version` 必须非空
- `agent_id + version` 应能唯一定位一个装配版本

---

## 7. Runtime Selection

## 7.1 作用

`runtime` 指定该 Agent 使用哪个 RuntimeKernel graph pattern，以及执行限制。

建议结构：

```yaml
runtime:
  runtime_kernel_version: string
  pattern_id: string
  pattern_version: integer
  execution_limits:
    max_turns: integer
    max_retries: integer
    max_subgraph_depth: integer
    timeout_seconds: integer
```

字段说明：

- `runtime_kernel_version`
  期望兼容的 RuntimeKernel 版本

- `pattern_id`
  使用的 Graph Pattern，例如 `react_agent`

- `pattern_version`
  Pattern 版本

- `execution_limits`
  写入 RuntimeState execution section 的默认限制

## 7.2 v0 规则

- `pattern_id` 必须能被 RuntimeKernel `PatternRegistry` 找到
- `pattern_version` 必须与实际 pattern 兼容
- execution limits 必须为正整数
- Agent Assembly Spec 不能直接定义新的 Pattern DSL

---

## 8. Service Requirements

## 8.1 作用

`services` 声明运行时需要哪些全局服务。

它不保存服务对象，只保存 requirement。

建议结构：

```yaml
services:
  required:
    - model_service
    - tool_registry
    - memory_engine
    - knowledge_engine
    - context_engine
    - policy_engine
    - observability_manager
    - checkpoint_manager
  optional:
    - harness_bridge
  profiles:
    model_service:
      profile_id: string
      provider_hint: string | null
    tool_registry:
      profile_id: string
    memory_engine:
      profile_id: string
    knowledge_engine:
      profile_id: string
```

字段说明：

- `required`
  编译或运行前必须注入的 service kind

- `optional`
  可选 service kind

- `profiles`
  给部署环境或测试 fixture 使用的 profile id

## 8.2 v0 规则

- service kind 必须属于 RuntimeKernel `RuntimeServices` 支持集合
- profile 只用于解析运行时对象，不进入 RuntimeState
- 缺失 required service 时 assembly compiler 必须报错

---

## 9. Capabilities

## 9.1 作用

`capabilities` 声明 Agent 可用能力。

它面向 Agent 级审查，不直接等同于 RuntimeKernel binding。

建议结构：

```yaml
capabilities:
  prompts: []
  tools: []
  memory: {}
  knowledge: {}
  context: {}
  policies: []
```

---

## 9.2 Prompt Capability

建议结构：

```yaml
prompts:
  - prompt_id: string
    purpose: answer | clarify | plan | review | route | custom
    template: string
    variables: []
    target_nodes: []
```

规则：

- `prompt_id` 必须唯一
- `target_nodes` 必须引用 runtime pattern 中存在的 node id
- template 是可审查数据，不是 live object

---

## 9.3 Tool Capability

建议结构：

```yaml
tools:
  - tool_id: string
    name: string
    description: string
    risk_level: low | normal | high
    requires_approval: boolean
    allowed_nodes: []
```

规则：

- `tool_id` 必须唯一
- `allowed_nodes` 必须引用 operational tool 节点
- tool implementation 不进入 spec
- `requires_approval = true` 时必须能映射到 policy / interrupt 声明

---

## 9.4 Memory Capability

建议结构：

```yaml
memory:
  enabled: boolean
  recall_profile_id: string | null
  write_profile_id: string | null
```

规则：

- memory 访问必须通过标准节点发生
- spec 不直接读写 memory store

---

## 9.5 Knowledge Capability

建议结构：

```yaml
knowledge:
  enabled: boolean
  retrieval_profile_id: string | null
  source_refs: []
  citation_required: boolean
```

规则：

- `source_refs` 是知识源引用，不是大块正文
- 若 `citation_required = true`，harness 应包含 citation 断言

---

## 9.6 Context Capability

建议结构：

```yaml
context:
  assembly_profile_id: string
  model_visible_sections: []
  tool_visible_sections: []
  hidden_sections: []
  compression:
    enabled: boolean
    strategy: string | null
```

规则：

- model/tool/hidden 可见性必须显式区分
- 不允许把 secret 放入 model visible context

---

## 9.7 Policy Capability

建议结构：

```yaml
policies:
  - policy_id: string
    phase: precheck | postcheck | tool | approval | refusal
    profile_id: string
    rules: {}
```

规则：

- policy phase 必须能映射到 RuntimeKernel governance 节点或 hook
- policy 结果进入 RuntimeState policy section

---

## 10. Runtime Bindings

## 10.1 作用

`bindings` 是 Agent Assembly Spec 到 RuntimeKernel `BindingSet` 的直接映射层。

建议结构：

```yaml
bindings:
  services: []
  node_bindings: []
  hooks: []
```

这三类结构应与 `Capability Binding v0` 保持一致。

---

## 10.2 Service Binding

建议结构：

```yaml
services:
  - service_id: string
    kind: model_service | tool_registry | memory_engine | knowledge_engine | context_engine | policy_engine | observability_manager | checkpoint_manager | harness_bridge
    required: boolean
    config: {}
```

规则：

- service binding 只声明 requirement
- `config` 不能包含 secret 明文

---

## 10.3 Node Binding

建议结构：

```yaml
node_bindings:
  - binding_id: string
    binding_type: prompt | tool_access | policy_profile | retrieval_profile | strategy_profile | output_formatter | custom
    target:
      node_id: string
      impl: string
    payload: <typed payload for binding_type>
```

规则：

- `target.node_id` 必须属于 runtime pattern
- `target.impl` 必须与该 node 的 impl 一致
- 标准 `binding_type` 必须使用对应的强类型 payload schema，不允许额外字段
- `custom` 是唯一开放扩展入口，允许 `config` 为 dict，但必须提供最小元信息

标准 payload：

```yaml
prompt:
  prompt_id: string
  template: string
  variables: []

tool_access:
  allowed_tool_ids: []
  approval_policy: string

policy_profile:
  profile_id: string
  rules: {}

retrieval_profile:
  query_source: string
  top_k: integer

strategy_profile:
  strategy_ids: []
  parameters: {}

output_formatter:
  formatter_id: string
  mode: string
  config: {}

custom:
  extension_id: string
  schema_version: string
  purpose: string
  config: {}
```

扩展规则：

- `custom.config` 可由扩展实现自行解释
- validator 只轻校验 `custom` 的最小元信息，不深度理解扩展配置
- `custom` 不能冒充或覆盖 RuntimeKernel 标准 binding 语义

---

## 10.4 Hook Binding

建议结构：

```yaml
hooks:
  - binding_id: string
    hook_point: pre_cognitive | post_cognitive | pre_operational | post_operational | pre_governance | post_governance | pre_terminal | post_terminal | on_interrupt | on_resume
    enabled: boolean
    order: integer
    payload: {}
```

规则：

- hook point 必须属于 RuntimeKernel 支持集合
- 同一 hook point 内按 `order` 升序执行
- hook 不能改变 RuntimeKernel 节点类别语义

---

## 11. IO Contract

## 11.1 作用

`io_contract` 描述 Agent 对外输入、输出和 RuntimeState section 可见性。

建议结构：

```yaml
io_contract:
  input:
    type: user_message
    required_fields: []
  output:
    final_answer_required: boolean
    citations_required: boolean
    format: text | json | markdown
  readable_sections: []
  writable_sections: []
```

字段说明：

- `input`
  外部调用 Agent 时的输入约束

- `output`
  Agent 完成时的输出约束

- `readable_sections`
  Agent 运行期间允许读取的 RuntimeState sections

- `writable_sections`
  Agent 运行期间允许写入的 RuntimeState sections

## 11.2 v0 规则

- section 名称必须属于 RuntimeState 根 section
- `writable_sections` 不能突破 RuntimeKernel standard node 的写边界
- output contract 应被 harness scenario 验证

---

## 12. Policy / Approval / Interrupt

## 12.1 Policy

Agent 级 `policy` 描述默认风险控制。

建议结构：

```yaml
policy:
  default_risk_level: low | normal | high
  blocked_phrases: []
  approval_phrases: []
  refusal_phrases: []
```

规则：

- policy spec 应转换为 `policy_profile` node binding 或 governance hook
- policy 结果由 RuntimeKernel 写入 RuntimeState policy section

---

## 12.2 Interrupts

建议结构：

```yaml
interrupts:
  approval_required:
    enabled: boolean
    resume_payload_schema: {}
  tool_interrupt:
    enabled: boolean
    resume_payload_schema: {}
  clarification_required:
    enabled: boolean
```

规则：

- interrupt 是正常运行状态，不是 failed
- interrupt 前必须由 RuntimeKernel checkpoint
- resume payload 是可序列化数据
- spec 不定义用户自定义恢复语义

---

## 13. Harness

## 13.1 作用

`harness` 定义 Agent 级验收场景。

建议结构：

```yaml
harness:
  scenarios:
    - scenario_id: string
      input_text: string
      resume_after_interrupt: boolean
      resume_payload: {}
      fixtures:
        model_profile_id: string | null
        tool_profile_id: string | null
        memory_profile_id: string | null
        knowledge_profile_id: string | null
      assertions: []
```

断言类型应复用 Harness Bridge v0 支持集合，例如：

- graph path
- tool proposed / called / approval
- context built / hidden / compressed
- policy blocked / approval / refusal
- checkpoint created
- resume event / resume continuity
- final answer
- output contains
- citation present

## 13.2 v0 规则

- harness scenario 通过 RuntimeKernel compile/run/resume API 驱动
- fixture 通过 service layer 注入
- harness 不直接调用 node 私实现

---

## 14. Factory Authoring Model

## 14.1 作用

Factory Authoring Model 定义工厂如何逐步写入、修改和修复 Agent Assembly Spec。

它面向模型生成过程，而不是 RuntimeKernel 执行过程。

---

## 14.2 写入模式

工厂 v0 至少支持三种写入模式：

```yaml
write_mode: create | patch | repair
```

- `create`
  从空 spec 创建初稿

- `patch`
  对已有 spec 做局部修改

- `repair`
  根据 validation notes 修复非法或不完整字段

规则：

- patch 应尽量只修改相关 section
- repair 必须保留原有有效字段
- 工厂模型不应为了小改动重写整份 spec

---

## 14.3 阶段写入边界

建议工厂 RuntimeKernel 阶段按 section 分工写入：

```text
requirement_capture
  -> agent.description / io_contract.input / authoring.open_questions

runtime_pattern_selection
  -> runtime.pattern_id / runtime.session_config

graph_behavior_planning
  -> graph_overrides / node intent notes

node_strategy_planning
  -> graph_overrides.node_wrappers / policy / tool visibility notes

tool_capability_planning
  -> tools draft / approval notes

resource_and_condition_planning
  -> services.profiles / resource contracts / environment assumptions

assembly_spec_generation
  -> AgentAssemblySpec draft

package_generation
  -> metadata.package_refs / generated package artifacts

harness_generation_and_test
  -> harness.scenarios / validation_notes / repair evidence

repair_or_finalize
  -> metadata.summary / authoring.status / final AssemblySpec
```

规则：

- 每个阶段可以读取整份 spec
- 每个阶段应优先写入自己负责的 section
- 跨 section 修改必须在 `revision_log` 中说明原因

---

## 14.4 模型可理解性规则

为了让工厂模型稳定理解和修改 spec，v0 要求：

- 同一实体必须有稳定 id，例如 `prompt_id`、`tool_id`、`policy_id`
- 引用必须通过 id，不通过自然语言描述匹配
- 每个 list item 应尽量包含 `description` 或 `purpose`
- 不把多个语义混进一个自由文本字段
- 不使用缩写字段名
- 不要求模型根据隐含默认值推断关键行为

示例：

```yaml
tools:
  - tool_id: order_lookup
    name: Order Lookup
    description: Look up order status by order id.
    risk_level: normal
    requires_approval: false
    allowed_nodes:
      - tool_exec
```

---

## 14.5 Draft Validation 与 Final Validation

Agent Assembly Spec v0 区分两类校验：

- `draft validation`
  用于工厂写作过程中，允许缺字段，但要发现结构问题

- `final validation`
  用于编译前，必须满足 RuntimeKernel 装配要求

draft validation 至少检查：

- YAML / JSON 可解析
- section 类型正确
- id 字段格式基本正确
- 已出现的引用不明显冲突

final validation 至少检查：

- 必填字段完整
- runtime pattern 存在
- binding target 全部有效
- service requirements 可满足
- harness scenario 可运行

---

## 15. Assembly Compiler Semantics

## 15.1 作用

Assembly Compiler 负责把 Agent Assembly Spec 转换为 RuntimeKernel 可运行对象。

建议流程：

1. 读取 Agent Assembly Spec
2. 校验 schema version
3. 校验 agent identity
4. 解析 runtime pattern
5. 校验 service requirements
6. 校验 capability 声明
7. 生成 RuntimeKernel `BindingSet`
8. 校验 node binding target
9. 校验 hook binding
10. 调用 `RuntimeKernelFacade.compile(...)`
11. 生成可选 harness scenario bundle

---

## 15.2 编译产物

建议产物：

```yaml
assembly_result:
  assembly_id: string
  agent_id: string
  agent_version: string
  pattern_id: string
  binding_set_ref: {}
  required_services: []
  harness_scenarios: []
```

在 Python 运行时，对应：

```text
AgentAssemblySpec
  -> BindingSet
  -> RuntimeServices requirements
  -> CompiledKernelApp
```

---

## 16. Validation Rules

Validator v0 至少检查：

### 16.1 结构合法性

- `schema_version` 支持
- `assembly_id` 非空
- `authoring.status` 合法
- `agent.agent_id` 非空
- `agent.version` 非空
- `runtime.pattern_id` 非空

### 16.2 Runtime 合法性

- pattern 存在
- pattern version 兼容
- execution limits 为正整数

### 16.3 Service 合法性

- required service kind 合法
- 不包含 live object
- 不包含 secret 明文

### 16.4 Capability 合法性

- prompt id 唯一
- tool id 唯一
- target node 存在
- policy phase 合法

### 16.5 Binding 合法性

- node binding target 存在
- node binding impl 匹配
- binding type 合法
- hook point 合法

### 16.6 IO 合法性

- section 名称合法
- output contract 可被 harness 表达

### 16.7 Harness 合法性

- scenario id 唯一
- assertion type 合法
- resume scenario 必须存在 interrupt 预期

- draft validation 与 final validation 必须分开
- final validation 失败时应写入 `authoring.validation_notes`

---

## 17. 与 RuntimeKernel 的关系

## 17.1 RuntimeKernel 负责

- 图结构语义
- 节点执行
- state patch 合并
- route resolution
- interrupt / resume
- checkpoint
- observability
- harness bridge

## 17.2 Agent Assembly Spec 负责

- 选择哪个 Pattern
- 声明 Agent 能力
- 声明绑定
- 声明 service requirements
- 声明 Agent 级测试场景

## 17.3 Assembly Compiler 负责

- 把 spec 转成 RuntimeKernel 输入
- 在编译期尽量发现装配错误
- 不改变 RuntimeKernel 内核语义

---

## 18. 与工厂 RuntimeKernel 阶段的关系

工厂 RuntimeKernel 阶段可以作为 Agent Assembly Spec 的生成过程。

建议对应关系：

```text
requirement_capture
  -> agent.description / io_contract.input

runtime_pattern_selection
  -> runtime.pattern_id

graph_behavior_planning
  -> node responsibilities / routing / interrupts

node_strategy_planning
  -> wrappers / context / memory / policy / tool visibility

tool_capability_planning
  -> tool capability needs

resource_and_condition_planning
  -> resource and condition contracts

assembly_spec_generation
  -> AgentAssemblySpec draft

package_generation
  -> generated package artifacts

harness_generation_and_test
  -> harness report

repair_or_finalize
  -> final AgentAssemblySpec and repair notes
```

注意：

- 这是生成关系，不是 RuntimeKernel 运行依赖
- RuntimeKernel 不读取工厂阶段内部字段

---

## 19. 序列化与版本演进

Agent Assembly Spec 必须：

- 可 JSON / YAML 序列化
- 不含 live object
- 不含 secret 明文
- 可被 schema version 迁移
- 可被 code review 审查

版本字段：

- `schema_version`
  装配规格 schema 版本

- `agent.version`
  Agent 配置版本

- `runtime.runtime_kernel_version`
  目标 RuntimeKernel 版本

- `runtime.pattern_version`
  目标 Pattern 版本

---

## 20. v0 明确不做

当前阶段不做：

- 多 Agent 协作编排
- 分布式部署拓扑
- 用户自定义任意 LangGraph code
- 用户自定义 RuntimeState 根结构
- 用户自定义 event schema
- secret 管理系统
- provider-specific model/tool 配置细节
- 自动生成真实工具代码
- 自动生成真实知识库内容
- 复杂 JSON Patch 标准兼容层
- 多模型协同编辑协议

---

## 21. v0 下一步

基于本文档，下一步需要：

1. 定义 `AgentAssemblySpec` schema
2. 定义 Agent Assembly loader
3. 定义 Agent Assembly validator
4. 定义 Assembly Compiler
5. 定义 spec -> `BindingSet` 转换
6. 定义 spec -> Harness Scenario 转换
7. 定义 draft validation / final validation
8. 定义简单 patch / repair 输入格式
9. 写一个最小 example spec
10. 用 RuntimeKernel 现有测试替身跑通装配验收
