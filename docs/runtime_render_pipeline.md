# Runtime Render Pipeline

本文档定义 Factory 和生产出来的 Agent 共用的运行渲染管线。

目标：

- Factory 与生成 Agent 使用同一套事件协议。
- CLI 与 WebUI 只消费标准事件，不解析业务 state、patch 或阶段私有字段。
- 每个 LangGraph 节点通过统一 wrapper 说明“我是谁、我在做什么、我完成了什么”。
- 模型、工具、interrupt、checkpoint 等运行行为通过同一条事件流展示。

---

# 1. 总原则

所有由 FastAgentFactory 管理的 LangGraph 运行单元，都必须输出统一的 `RuntimeRenderEvent`。

适用对象：

- Factory 自身的制造图。
- RuntimeKernel 编译运行的生成 Agent。
- 后续多 Agent 协作图。
- 后续插件化 Agent 图。

渲染层不直接理解：

- Factory 的阶段 state。
- 生成 Agent 的业务 state。
- LangGraph 原始 patch 结构。
- 某个节点的私有字段。

渲染层只理解：

- run 事件。
- node 事件。
- model 事件。
- tool 事件。
- interrupt 事件。
- artifact / checkpoint / debug 事件。

---

# 2. RuntimeRenderEvent

统一事件 envelope：

```json
{
  "protocol_version": "runtime_render.v1",
  "event_id": "string",
  "event_type": "node_started",
  "producer_type": "factory | agent",
  "session_id": "string | null",
  "thread_id": "string | null",
  "run_id": "string",
  "graph_id": "string",
  "stage_id": "string | null",
  "node_id": "string | null",
  "node_label": "string | null",
  "node_kind": "string | null",
  "span_id": "string | null",
  "parent_span_id": "string | null",
  "sequence": 1,
  "timestamp": "string",
  "severity": "info | warning | error",
  "message": "string | null",
  "payload": {}
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `protocol_version` | 渲染协议版本。 |
| `event_id` | 单条事件唯一 ID。 |
| `event_type` | 标准事件类型。 |
| `producer_type` | 事件来源：Factory 或生成 Agent。 |
| `session_id` | 会话 ID。 |
| `thread_id` | LangGraph checkpoint thread ID。 |
| `run_id` | 单次运行 ID。 |
| `graph_id` | 当前图 ID。 |
| `stage_id` | Factory 阶段 ID；生成 Agent 可为空。 |
| `node_id` | LangGraph 节点 ID。 |
| `node_label` | 面向用户展示的节点名。 |
| `node_kind` | 节点类型，例如 `llm`、`tool`、`router`、`validator`、`subgraph`。 |
| `span_id` | 当前事件 span。 |
| `parent_span_id` | 父 span。 |
| `sequence` | 同一 run 内递增序号。 |
| `timestamp` | 事件时间。 |
| `severity` | 展示级别。 |
| `message` | 面向人的简短摘要。 |
| `payload` | 事件类型对应的结构化数据。 |

`stage_id` 是可选字段。Factory 可以使用它展示制造流程进度；生成 Agent 不强制拥有阶段。

---

# 3. 标准事件类型

## 3.1 Runtime / Session

```text
runtime_ready
session_started
session_switched
session_listed
```

## 3.2 Run

```text
run_started
run_completed
run_failed
```

## 3.3 Graph / Node

```text
graph_started
graph_completed
graph_failed
node_started
node_progress
node_completed
node_failed
```

`node_progress` 用于展示节点内部阶段性说明，例如“正在整理需求”、“正在校验 AssemblySpec”、“正在等待工具 observation”。

## 3.4 Model

```text
model_call_started
model_stream_delta
model_message_completed
model_call_completed
model_call_failed
```

## 3.5 Tool

```text
tool_call_proposed
tool_approval_requested
tool_approval_resolved
tool_call_started
tool_call_completed
tool_call_failed
tool_observation_available
```

工具事件必须来自统一工具系统和 `ToolExecutionGateway`，不能由前端从 patch 中临时猜测。

## 3.6 Interrupt

```text
interrupt_requested
runtime_paused
runtime_resumed
```

## 3.7 Checkpoint / Artifact / Debug

```text
checkpoint_created
checkpoint_selected
checkpoint_restored
artifact_created
debug_patch
```

`debug_patch` 只用于调试面板，不能作为 CLI/WebUI 主渲染数据源。
全链路 trace 不再通过前端事件快照承载，持久事实源统一写入 `trace_system` 的 JSONL trace store。

---

# 4. NodeRenderSpec

每个可展示节点都必须拥有 `NodeRenderSpec`。

```json
{
  "node_id": "manufacturing_cleared",
  "label": "制造流程已清空",
  "kind": "factory_manufacturing_shell",
  "purpose": "明确旧制造流程已从 create-agent 执行路径移除",
  "doing": "返回清空状态，等待新的制造域设计",
  "expected_output": "说明当前制造流程尚未重建",
  "visible_to_user": true
}
```

字段说明：

| 字段 | 含义 |
| --- | --- |
| `node_id` | LangGraph 节点 ID。 |
| `label` | 面向用户的短名称。 |
| `kind` | 节点类型。 |
| `purpose` | 节点为什么存在。 |
| `doing` | 节点运行时正在做什么。 |
| `expected_output` | 节点完成后应该产出什么。 |
| `visible_to_user` | 是否默认展示在 CLI/WebUI 主流程中。 |

`NodeRenderSpec` 不描述工具权限、资源值、模型参数或业务实现代码。

---

# 5. Render Wrapper

统一系统 wrapper：

```text
observability.render_node
```

它是 Runtime 基础设施，不是业务 wrapper。

支持 phase：

```text
before
after
on_error
```

职责：

```text
before   -> 发 node_started
after    -> 发 node_completed
on_error -> 发 node_failed
```

`before` 事件示例：

```json
{
  "event_type": "node_started",
  "node_id": "manufacturing_cleared",
  "node_label": "制造流程已清空",
  "node_kind": "factory_manufacturing_shell",
  "payload": {
    "purpose": "明确旧制造流程已从 create-agent 执行路径移除",
    "doing": "返回清空状态，等待新的制造域设计",
    "expected_output": "说明当前制造流程尚未重建"
  }
}
```

`after` 事件示例：

```json
{
  "event_type": "node_completed",
  "node_id": "manufacturing_cleared",
  "node_label": "制造流程已清空",
  "payload": {
    "output_summary": "旧制造流程已清空"
  }
}
```

`on_error` 事件示例：

```json
{
  "event_type": "node_failed",
  "node_id": "manufacturing_cleared",
  "node_label": "制造流程已清空",
  "severity": "error",
  "payload": {
    "error_summary": "制造入口执行失败"
  }
}
```

---

# 6. 系统 Wrapper 与业务 Wrapper

wrapper 分为两类：

| 类型 | 来源 | 是否由模型规划 | 例子 |
| --- | --- | --- | --- |
| 系统 wrapper | RuntimeKernel 自动注入 | 否 | `observability.render_node`、metrics、checkpoint trace |
| 业务 wrapper | 第四阶段规划，第七阶段冻结 | 是 | context、memory、policy、tool visibility |

系统 wrapper 不写入业务语义的 `graph_overrides.node_wrappers`。

编译时有效 wrapper 顺序：

```text
system_before_wrappers
  -> pattern_wrappers
  -> assembly_business_wrappers
  -> system_after_wrappers
```

`observability.render_node` 必须由 RuntimeKernel 编译阶段自动注入。

---

# 7. Factory 如何接入

Factory 自身也必须走同一套渲染管线。

Factory 的节点是固定流程，因此 `NodeRenderSpec` 来自固定 registry。

建议文件：

```text
agent_factory/factory_graph/render_manifest.py
```

示例：

```python
FACTORY_NODE_RENDER_SPECS = {
    "manufacturing_cleared": {
        "node_id": "manufacturing_cleared",
        "label": "制造流程已清空",
        "kind": "factory_manufacturing_shell",
        "purpose": "明确旧制造流程已从 create-agent 执行路径移除",
        "doing": "返回清空状态，等待新的制造域设计",
        "expected_output": "说明当前制造流程尚未重建",
        "visible_to_user": True,
    }
}
```

Factory 当前已经有 bridge normalizer，但后续主渲染数据应改为：

```text
Factory node
  -> render wrapper / render adapter
  -> RuntimeRenderEvent
  -> CLI / WebUI
```

Factory 的 `event_normalizer` 只负责：

- 转发标准事件。
- 保留 `debug_patch`。

它不应该长期承担“猜节点在干嘛”的职责。

---

# 8. 生成 Agent 如何接入

生成 Agent 的节点说明不是运行时猜出来的。

来源链路：

```text
Runtime Design
  -> 生成节点业务说明初稿并补充节点运行方式说明

Capability Contract / Package Build
  -> 冻结 NodeRenderSpec

Package Build
  -> 物化 render_manifest.json

RuntimeKernel compile
  -> 读取 render_manifest.json
  -> 自动注入 observability.render_node
```

AgentPackage 中应包含：

```text
render_manifest.json
```

示例：

```json
{
  "version": "render_manifest.v0",
  "graph_id": "mysql_agent",
  "nodes": {
    "clarify_request": {
      "node_id": "clarify_request",
      "label": "需求澄清",
      "kind": "llm",
      "purpose": "澄清用户提出的数据库管理需求",
      "doing": "分析用户输入，判断是否需要追问，并整理成可执行任务",
      "expected_output": "明确的数据库管理任务描述",
      "visible_to_user": true
    }
  }
}
```

RuntimeKernel 编译 AgentPackage 时读取 `render_manifest.json`，并把对应节点说明放入 node execution context，供 `observability.render_node` 读取。

生成 Agent 不需要手写前端事件，也不需要知道 CLI 或 WebUI 的存在。

---

# 9. 模型事件与工具事件

`observability.render_node` 只负责节点生命周期。

模型事件由统一 model wrapper 或模型调用入口负责：

```text
model_call_started
model_stream_delta
model_message_completed
model_call_completed
model_call_failed
```

工具事件由统一工具系统负责：

```text
ToolSpec
  -> ToolExecutionGateway
  -> ToolNode
  -> ToolMessage / Observation
  -> RuntimeRenderEvent
```

工具事件不能由节点 render wrapper 代发。

这样可以避免三种事件混在一起：

- 节点在干嘛。
- 模型说了什么。
- 工具执行了什么。

---

# 10. CLI / WebUI 消费规则

CLI 和 WebUI 只消费 `RuntimeRenderEvent`。

推荐视图分层：

| 视图 | 数据来源 |
| --- | --- |
| Timeline | `run_*`、`node_*` |
| Live Activity | `node_progress`、`model_*`、`tool_*`、`interrupt_*` |
| Tool Panel | `tool_*` |
| Interrupt Panel | `interrupt_requested`、`tool_approval_requested` |
| Trace / Debug Panel | `trace_system` JSONL facts、`debug_patch` |
| Artifact Panel | `artifact_created` |

前端禁止依赖：

- Factory 阶段私有 state。
- 生成 Agent 节点私有 state。
- LangGraph patch 内部结构。
- 模型输出里的临时文案格式。

---

# 11. 与现有文档的边界

本文档负责：

- Factory 与生成 Agent 共用的渲染事件协议。
- NodeRenderSpec 来源。
- 系统 render wrapper 挂载位置。
- CLI/WebUI 消费边界。

`agent_factory/runtime_kernel/OBSERVABILITY_V0.md` 负责：

- RuntimeKernel 内部 trace / event / metrics / debug_refs。
- harness 和调试使用的观测数据。

`docs/basic_capability_construction.md` 负责：

- ToolSpec。
- 工具注册。
- ToolExecutionGateway。
- ToolNode / Observation 闭环。
- 工具、记忆、知识、定时任务四类基础系统的现状与边界。

三者关系：

```text
RuntimeKernel Observability
  -> 产生结构化运行事实

Runtime Render Pipeline
  -> 把运行事实标准化给 CLI/WebUI

Basic Capability Construction
  -> 记录工具、记忆、知识、定时任务的系统边界
```

---

# 12. 实现顺序

实现必须按这个顺序推进：

1. 定义 `RuntimeRenderEvent` 与 `NodeRenderSpec` schema。
2. 为 Factory 增加固定 `FACTORY_NODE_RENDER_SPECS`。
3. 新增 `observability.render_node` 系统 wrapper。
4. RuntimeKernel 编译时自动注入系统 wrapper。
5. 第七阶段冻结生成 Agent 的 `NodeRenderSpec`。
6. 第八阶段物化 `render_manifest.json`。
7. bridge 输出 `RuntimeRenderEvent`。
8. TS CLI 改为只按 `RuntimeRenderEvent` 渲染主流程。

不允许在 CLI/WebUI 中为某个阶段或某个 Agent 节点写特殊渲染规则。
