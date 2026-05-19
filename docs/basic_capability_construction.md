# Basic System Construction

本文档记录 FastAgentFactory 的基础能力系统与运行基础设施建设状态。

这里不再引入统一的 `Capability` 总外壳，也不强行要求所有系统共享同一种 registry、compiler 或 schema 形态。系统数量不多，可以各自拥有适合自身语义的架构。

当前确认六类基础系统，其中工具、记忆、知识、定时任务偏能力接入，Trace 与上下文管理偏运行基础设施：

| 系统 | 当前状态 |
| --- | --- |
| 工具系统 | 已系统化搭建，是当前最成熟的一类。 |
| 记忆系统 | 已形成 LangGraph 原生规范：会话内 messages/checkpointer，跨会话 BaseStore。 |
| 知识系统 | 有 RuntimeKernel 实现迹象，但未形成统一规范。 |
| 定时任务系统 | 暂未看到项目内正式实现。 |
| Trace 系统 | 目前只有事件流、debug patch、render 事件等分散能力，尚未形成独立 trace 模块。 |
| 上下文管理系统 | RuntimeKernel 有 ContextEngine 迹象，Factory prompt context 也已存在，但尚未形成统一上下文工程。 |

本文档的作用：

- 总结当前工具系统现状。
- 列出记忆、知识、定时任务、Trace、上下文管理在当前项目里的实现线索。
- 为后续清理 Factory 与 RuntimeKernel 的规范边界提供索引。
- 避免为了设计而设计，先按真实系统需要逐步成型。

---

## 1. 总原则

各系统可以有不同架构，但必须遵守几条工程边界。

### 1.1 Factory 与生成 Agent 共用规范，不共用运行数据

Factory 自己使用的工具、记忆、知识、定时任务，和生产出来的 Agent 使用的对应系统，应该遵循同一套规范思想，但运行数据必须隔离。

例如：

- Factory 的 MCP / Skill 不自动继承给生成 Agent。
- Factory 的 session、checkpoint、记忆不写入生成 Agent 的 memory。
- Factory 的 mainModel、taskModel、API key、base URL、thinking 参数不进入生成 Agent 的业务资源。
- AgentInstance 后续自己配置的 MCP、Skill、知识源、记忆后端，不反向污染 AgentPackage。

### 1.2 AgentPackage 只写规范产物，不写宿主机私有运行态

AgentPackage 应该写入可迁移、可校验的规范文件。

不应写入：

- Factory 自身配置。
- 用户本机 secret。
- 用户本机 MCP server 实例。
- 用户本机 Skill 目录内容。
- 未经过 sandbox contract 转换的宿主机绝对路径。

### 1.3 RuntimeKernel 负责把规范编译成运行能力

Factory 不直接生成运行时代码来绕过 RuntimeKernel。

生产流程应该是：

```text
Factory 阶段产物
  -> AgentPackage 规范文件
  -> RuntimeKernel 编译
  -> AgentInstance 运行时加载
```

各系统怎么编译可以不同，但都必须有明确入口，而不是散落在节点代码、prompt、工具函数里。

### 1.4 当前文档只记录系统层级，不预设总抽象

当前不定义统一的 `CapabilitySpec`。

后续如果某一类系统自然长出稳定 schema，就在该系统内部定义；如果多个系统后来真的出现公共字段，再抽取公共基础类型。现在不提前抽象。

### 1.5 编译层 Contract / Builder 规范

组成 Agent 的 JSON 装配流程统一采用 Contract / Builder 标准，不兼容旧的 metadata 注入方式。

```text
AgentPackageManifest
  -> AssemblySpec
  -> RuntimeContracts
  -> ContractRegistry
  -> RuntimeContribution
  -> RuntimeServices / System Wrappers / Tool Providers / Workers
  -> RuntimeKernel compile
```

边界：

- `AgentPackageManifest` 是 AgentPackage 唯一入口，只索引文件。
- `AssemblySpec` 只描述 Agent 逻辑装配，不承载 session、memory、render、tool provider 等运行基础设施。
- `RuntimeContract` 负责声明工具、记忆、知识、定时任务、Trace、上下文等基础能力如何接入。
- `ContractRegistry` 只接受系统注册的 contract schema 和内置 builder。
- `RuntimeContribution` 是 builder 唯一输出，允许贡献 `services / system_wrappers / tool_providers / context_sources / background_workers / event_publishers / session_hooks / diagnostics`。
- `RuntimeContributionMerger` 负责确定性合并；重复 service、重复 system wrapper、重复 tool id 必须失败。

强制规则：

- 禁止通过 `AssemblySpec.metadata` 传递 runtime 能力。
- 禁止在 JSON 中写自定义 builder import path。
- 禁止在 RuntimeKernel compiler 中为单个能力写特化分支。
- Factory 与生产出来的 Agent 必须使用同一套 Contract / Builder 规范，但运行数据隔离。
- 新增基础能力必须同时提供 Contract schema、内置 Builder、RuntimeContribution 输出、Package 物化规则和编译校验规则。

当前首批内置 contract：

| Contract | 文件 | 作用 |
| --- | --- | --- |
| `session` | `contracts/session.json` | 创建 AgentSessionManager 所需配置，并构建 LangGraph checkpointer。 |
| `tools` | `contracts/tools.json` | 加载 package tools 与实例级 MCP / Skill 扩展，并形成统一 tool registry。 |
| `memory` | `contracts/memory.json` | 可选，启用跨会话记忆时构建 BaseStore、MemorySystemRuntime、后台 worker 和记忆注入系统 wrapper。 |
| `render` | `contracts/render.json` | 加载 `render_manifest.json`，并通过 RuntimeContribution 注入 `observability.render_node` 系统 wrapper。 |
| `resources` | `contracts/resources.json` | 声明运行时资源来源，工具系统按 sandbox 视角读取资源。 |
| `sandbox` | `contracts/sandbox.json` | 供第九阶段 harness 使用，不在普通运行时隐式执行。 |

---

## 2. 工具系统

工具系统已经完成了相对系统化的底座搭建。

### 2.1 当前统一链路

当前所有模型可调用工具都应该进入这条链路：

```text
ToolProvider
  -> ToolSpec
  -> ToolRegistry
  -> ToolCompiler
  -> ToolExecutionGateway
  -> LangGraph ToolNode
  -> ToolMessage / Observation
```

这条链路同时服务：

- Factory 内置工具。
- AgentPackage 自带工具。
- Factory 配置的 MCP / Skill 工具。
- AgentInstance 配置的 MCP / Skill 工具。

模型不能直接看到 MCP server、Skill 文件、真实资源值或 entrypoint 执行细节。模型只能看到编译后的工具视图，并通过标准 tool call 调用。

### 2.2 ToolSpec

当前 `ToolSpec` 是 9 字段结构：

```json
{
  "id": "read",
  "description": "读取文本文件内容。",
  "entrypoint": "agent_factory.tooling.builtins.filesystem.read:run",
  "input_schema": {},
  "output_schema": {},
  "resources": {},
  "risk_level": "low",
  "risk_evaluator": {
    "hard": "agent_factory.tooling.builtins.filesystem.read:evaluate_risk",
    "llm": null,
    "llm_mode": "disabled"
  },
  "concurrent": true
}
```

字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 工具稳定 ID，也是模型 tool call 使用的工具名。 |
| `description` | 工具用途说明。 |
| `entrypoint` | Runtime 实际执行入口。 |
| `input_schema` | 工具参数 JSON Schema。 |
| `output_schema` | 工具输出 JSON Schema。 |
| `resources` | 工具局部资源名到全局资源 key 的映射。 |
| `risk_level` | 工具基础风险等级：`low / medium / high`。 |
| `risk_evaluator` | 工具自己的参数风险校验配置。 |
| `concurrent` | 是否允许并发执行。 |

硬性规则：

- `id` 必须是 `snake_case`。
- `input_schema` 和 `output_schema` 必须可运行时校验。
- 工具执行入口统一为 `run(arguments: dict, resources: dict) -> dict`。
- 工具参数风险入口统一为 `evaluate_risk(arguments: dict, context: dict) -> dict`，入口必须写在该工具自己的实现文件中。
- `risk_level` 和 `concurrent` 属于 Runtime 调度语义，写在 `ToolSpec`；具体参数风险判断属于工具自身，写在工具实现文件的 `evaluate_risk`。
- `entrypoint` 支持 package 相对路径、Python import path、MCP entrypoint。

### 2.3 风险审批策略

工具审批不再使用单个布尔值。当前统一策略是：

```text
input_schema 校验
  -> hard risk evaluator
  -> llm risk evaluator
  -> Gateway 风险合并
  -> allow / ask / deny
  -> entrypoint 执行或 observation
```

基础风险等级：

| 风险 | 默认行为 |
| --- | --- |
| `low` | 默认放行；参数风险校验器可以升级为 `ask` 或 `deny`。 |
| `medium` | 必须经过参数风险校验；没有明确 `allow` 时进入人工审批。 |
| `high` | 必须人工审批；硬规则仍可直接 `deny`。 |

`risk_evaluator` 配置：

| 字段 | 含义 |
| --- | --- |
| `hard` | 可选，确定性 Python 风险校验入口，必须指向工具实现文件中的 `evaluate_risk(arguments, context) -> dict`。 |
| `llm` | 可选，LLM 风险判断提示词文本或 package 内 `.md` 文件路径。 |
| `llm_mode` | `disabled / on_uncertain / always`。 |

硬规则和 LLM 的关系：

- 硬规则负责路径、命令、资源、网络、敏感参数等确定性边界。
- LLM 只负责语义风险判断。
- LLM 风险判断统一使用小任务模型，也就是 `.env` 中的 `AGENTFACTORY_TASK_MODEL`。
- LLM 不能覆盖 hard deny。
- Gateway 是唯一裁决入口，CLI/WebUI 只负责展示 `ask` 类型审批。

### 2.4 当前代码入口

```text
agent_factory/tooling/
  spec.py
  risk.py
  schema_compiler.py
  entrypoint.py
  registry.py
  compiler.py
  gateway.py
  providers/
  entrypoints/
  mcp_runtime.py
  factory_extensions.py
  builtins/
```

关键职责：

| 模块 | 职责 |
| --- | --- |
| `spec.py` | 定义 `ToolSpec` 与模型可见工具视图。 |
| `risk.py` | 定义 LLM 风险判断与风险结果合并。 |
| `schema_compiler.py` | 将 JSON Schema 编译为运行时可校验模型。 |
| `entrypoint.py` | 解析 Python / package / MCP 执行入口。 |
| `registry.py` | 注册、去重、筛选工具。 |
| `compiler.py` | 将 `ToolSpec` 编译为 LangChain 工具。 |
| `gateway.py` | 参数校验、风险校验、审批、资源映射、执行、输出校验、observation。 |
| `providers/` | Builtin / Package / MCP / Skill 工具发现。 |
| `mcp_runtime.py` | MCP server 连接、工具发现和调用。 |
| `factory_extensions.py` | Factory 自身扩展目录扫描。 |

工具文件结构规则：

```text
tool_group/
  specs.py
  <tool_id>.py
```

`specs.py` 只负责注册 `ToolSpec`，不承载工具执行或工具风险规则。每个 `<tool_id>.py` 必须承载该工具自己的执行入口和风险入口：

```python
def run(arguments: dict, resources: dict) -> dict: ...

def evaluate_risk(arguments: dict, context: dict) -> dict: ...
```

允许把通用路径解析、命令边界等能力放入 `common.py` 或 `manager.py`，但 `risk_evaluator.hard` 的入口必须指向工具文件自身，例如：

```text
agent_factory.tooling.builtins.filesystem.read:evaluate_risk
tools/mysql_query/tool.py:evaluate_risk
```

生成出来的 AgentPackage 也遵循同一结构：`tools/<tool_id>/tool.py` 同时提供 `run` 和 `evaluate_risk`，`manifest.json` 的 `risk_evaluator.hard` 指向 `tools/<tool_id>/tool.py:evaluate_risk`。

### 2.5 已实现内置工具

| 工具 | 状态 |
| --- | --- |
| `read` | 已实现，低风险，带路径风险校验。 |
| `write` | 已实现，中风险，带路径风险校验。 |
| `edit` | 已实现，中风险，带路径风险校验。 |
| `multi_edit` | 已实现，中风险，带路径风险校验。 |
| `glob` | 已实现，低风险，带路径风险校验。 |
| `grep` | 已实现，低风险，带路径风险校验。 |
| `ls` | 已实现，低风险，带路径风险校验。 |
| `bash` | 已实现，高风险，带 cwd 和命令风险校验。 |
| `bash_status` | 已实现，低风险，带进程参数校验。 |
| `bash_stop` | 已实现，中风险，带进程参数校验。 |
| `web_fetch` | 暂留空，不注册为可用工具。 |
| `web_search` | 暂留空，不注册为可用工具。 |

### 2.6 MCP / Skill 接入现状

MCP 接入：

```text
mcp_servers.json
  -> MCPToolProvider
  -> ToolSpec(entrypoint="mcp:<server_id>/<tool_name>")
  -> MCPEntrypointAdapter
  -> MCPRuntimeClient.call_tool(...)
```

`mcp_servers.json` 中每个 server 可以声明 `risk_level_default`。MCP tool 默认按中风险处理；如果 server 或 tool metadata 明确给出风险等级，则转换为统一 `ToolSpec.risk_level`。

Skill 接入：

```text
enabled_skills.json
  -> SkillProvider
  -> SkillRegistry
  -> ToolSpec(id="skill")
  -> skill.load / skill.read_resource
```

Skill 采用递进式披露，不再在发现阶段把 Skill 内容直接塞进 prompt，也不再把每个 Skill 展开成一组工具。启动时只把所有启用 Skill 的 `name + description` 写进统一 `skill` 工具描述，由模型决定是否调用。

Skill 标准目录：

```text
<skill-name>/
  SKILL.md
  references/
  templates/
  examples/
  assets/
  scripts/
```

`SKILL.md` 必须使用 YAML frontmatter：

```yaml
---
name: db-readonly-query
description: Connect to databases and run strictly read-only SQL.
---
```

披露流程：

```text
discover  -> skill 工具 description 只展示 metadata
load      -> skill({"action": "load", "name": "<skill>"}) 返回 SKILL.md 正文、资源清单、脚本清单
resource  -> skill({"action": "read_resource", "name": "<skill>", "path": "references/x.md"}) 按需读取资源
script    -> 由 bash 执行脚本；skill 工具只暴露脚本清单，不直接执行脚本
```

脚本执行必须经过统一工具系统：

```text
skill.load 返回 scripts/run_query.py
模型调用 bash 执行脚本
Gateway 执行 bash 风险校验与审批
ToolNode 返回 observation
```

`skill` 工具自身的边界：

- 可以列出 enabled skills。
- 可以加载 `SKILL.md`。
- 可以读取 `references/`、`templates/`、`examples/`、`assets/` 中已发现的资源。
- 可以返回脚本 `script_ref`、`resolved_path`、`execution_tool=bash`。
- 不执行脚本。
- 不把脚本执行伪装成资源读取。
- 不读取 Skill root 外部路径。

Factory 扩展默认位置：

```text
.agentfactory/factory/extensions/
  mcp_servers.json
  enabled_skills.json
```

AgentInstance 扩展默认位置：

```text
.agent_runtime/extensions/
  mcp_servers.json
  enabled_skills.json
```

`tools` contract 可以通过 `config.instance_extension_root` 指定实例扩展根。相对路径按运行进程当前目录解析，不按 AgentPackage 根目录解析；这样 package 内置工具和运行实例后续启用的 MCP / Skill 不会混在同一个物理目录。

当前已具备：

- Factory 可以扫描自己的 MCP / Skill 配置并注册工具。
- RuntimeKernel 通过 `tools` contract 自动加载实例级 MCP / Skill 配置。
- MCP 最终转换成各自 `ToolSpec`。
- Skill 最终转换成一个统一 `skill` ToolSpec，具体 Skill 内容按需加载。

后续还需要补齐：

- 节点 tool visibility 与实例扩展工具的闭合校验。
- Package 中对工具系统的标准落盘规范继续收敛。

### 2.6 审批与 Observation

审批是 Runtime 行为，不是工具代码行为。

```text
approve -> 执行工具
deny    -> 不执行工具，返回 denied observation
revise  -> 不执行工具，返回 revision_requested observation
trust   -> Runtime 管理信任语义，不修改 ToolSpec
```

只要模型发出了 tool call，下一次调用模型前必须为每个 `tool_call_id` 返回对应 `ToolMessage`。参数非法、输出非法、执行失败、用户拒绝、用户要求重试导向，都必须以 observation 返回给模型。

---

## 3. 记忆系统

记忆系统已按 LangGraph 思想收敛为两层：

```text
会话内记忆 = LangGraph messages channel + checkpointer + thread_id
跨会话记忆 = LangGraph BaseStore + namespace
```

当前实现入口：

```text
agent_factory/memory_system/
  schema.py
  config.py
  namespace.py
  segment.py
  retrieval.py
  ranking.py
  extraction.py
  writer.py
  background.py
  injection.py
  reports.py
```

### 3.1 会话内记忆

会话内记忆只服务当前 session，工程实现固定为：

```text
LangGraph messages channel
  + LangGraph checkpointer
  + thread_id
```

RuntimeKernel 图状态使用：

```python
class RuntimeGraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    runtime: RuntimeState
```

`SessionMemoryWrite` 只允许节点返回 `{"messages": [...]}`。业务状态放在 `runtime` channel 中，记忆系统不直接读写 `runtime` 内部字段。

Factory 与生产出来的 Agent 使用同构 session 语义：

```text
session_id -> thread_id -> LangGraph checkpoint
```

CLI/WebUI 只暴露 `session_id`，不要求用户理解 `thread_id`。

会话内记忆不负责上下文清洗、压缩、摘要注入、token budget 裁剪或 prompt 组装。这些后续归入上下文系统工程。

### 3.2 跨会话记忆

跨会话记忆服务长期复用，工程实现固定为 LangGraph `BaseStore`。

`CrossSessionMemoryRead` 映射到：

```text
store.get / store.search
```

`CrossSessionMemoryWrite` 映射到：

```text
store.put / store.delete
```

命名空间固定为：

```text
("memory", "factory", <project_id>)
("memory", "agent", <agent_id>)
("memory", "user", <user_id>)
```

默认后端：

```text
AGENTFACTORY_MEMORY_STORE_BACKEND=sqlite | memory
AGENTFACTORY_MEMORY_STORE_PATH=.agentfactory/memory/factory.sqlite
```

Factory 与生产出来的 Agent 使用同一套 BaseStore 规范，但 session、checkpoint、store 文件和 namespace 必须隔离。

跨会话记忆召回按 LangGraph Store 思想实现。Embedding 不作为独立 vector memory API 暴露，而是作为 BaseStore 的可选 semantic index 配置：

```text
AGENTFACTORY_MEMORY_SEMANTIC_INDEX_ENABLED=true
AGENTFACTORY_EMBEDDING_PROVIDER=openai_compatible
AGENTFACTORY_EMBEDDING_BASE_URL=
AGENTFACTORY_EMBEDDING_API_KEY=
AGENTFACTORY_EMBEDDING_MODEL=
AGENTFACTORY_EMBEDDING_DIMS=1536
AGENTFACTORY_MEMORY_INDEX_FIELDS=content,metadata.evidence_summary,metadata.keywords,metadata.entities,metadata.embedding_text
```

读取链路使用 Hybrid Retrieval：

```text
BaseStore.search(namespace, query=...)
  + BaseStore.search(namespace, query=None)
  -> merge candidates
  -> ranking / kind quota / token budget
  -> MemoryContextPack
```

支持 semantic index 的 store 负责语义召回；不支持 semantic index 的 store 仍然走同一 `BaseStore.search` 接口，并退化为文本/后端默认检索。上层记忆系统不感知具体后端是 `InMemoryStore`、SQLite 过渡实现、PostgresStore，还是后续自定义 BaseStore。

### 3.3 跨会话写入

跨会话写入是 eventual consistency，不能阻塞主对话。

运行结束后只入队：

```text
after_run
  -> MemoryWriteScheduler.enqueue(job)
  -> 主对话立即返回
```

后台 worker 执行：

```text
MemoryBackgroundWorker
  -> build conversation segment
  -> retrieve related memories
  -> taskModel extraction and classification
  -> validate add/update/delete/noop
  -> write BaseStore
  -> write job journal
```

原则：

- 写入触发后先生成 `MemoryConversationSegment`，不是只看最后一句用户输入。
- `taskModel` 直接从 segment 中提取候选记忆，不再设置单独的显式意图识别闸门。
- 提取类型分为 `semantic / episodic / procedural`：
  - `semantic`：长期事实、偏好、约束、决策和 artifact 引用。
  - `episodic`：值得后续召回的重要会话事件或结果。
  - `procedural`：可复用的工作方式、流程、命令或项目操作规范。
- 提取动作只允许 `add / update / delete / noop`。
- `update / delete` 必须引用已召回记忆的 `merge_target_id`。
- 写入失败不生成伪记忆。
- queue 满时返回 `memory_write_queued_failed`，不阻塞主对话。
- job journal 只保存任务定位和 segment range，不保存完整消息正文。

默认队列：

```text
max_pending_jobs = 32
concurrency = 1
queue_full_policy = reject_new_when_full
write_interval_turns = 3
```

写入触发间隔由环境变量控制：

```text
AGENTFACTORY_MEMORY_WRITE_INTERVAL_TURNS=3
```

语义是“每成功完成 N 轮对话才尝试入队一次长期记忆判断”。默认 3 轮。未到间隔时不入队，也不会产生 job journal。

到达间隔后，后台写入使用最近 N 轮成功对话构造 segment：

```text
成功对话累计到 N 轮
  -> 构造最近 N 轮 user/assistant conversation segment
  -> BaseStore 检索相关旧记忆
  -> taskModel 提取 semantic / episodic / procedural candidates
  -> 去重 / 更新 / 删除 / noop
  -> 写 BaseStore
```

job journal：

```text
Factory: .agentfactory/memory/jobs/
Agent:   .agent_runtime/memory/jobs/
```

### 3.4 跨会话读取与注入

记忆注入只读 BaseStore，不触发写入。

RuntimeKernel 通过系统 wrapper 注入：

```text
system.cross_session_memory_inject
  before cognitive.* model call
  retrieve -> rank -> inject into runtime.context.model_context.cross_session_memory
```

Factory 在模型调用前使用同一套检索、排序和注入 pipeline，把结果作为 `prompt_context.cross_session_memory` 进入提示词上下文。`factory_chat` 也必须走这条统一路径；后续 chat/free 模式承担测试模块对话入口时，不能绕过记忆、工具、MCP/Skill 或事件系统。

注入文本必须低噪声：

- 未召回到内容时不注入任何记忆提示。
- 召回到内容时只注入可用事实列表，不注入“根据跨会话记忆”等来源标签。
- 模型可以自然参考相关信息，但不应在回答中主动说明信息来源。

注入硬限制：

```text
max_items_total = 8
max_tokens_total = 1200
min_score = 0.55
per_kind_limits = constraint 3 / preference 3 / decision 2 / fact 2 / artifact 1
```

注入不写入 `messages`。每次模型调用前重新检索、排序和裁剪，避免多轮对话后长期记忆越塞越多。

### 3.5 Package 与 RuntimeKernel 编译

第七阶段系统冻结会话配置；跨会话记忆配置是可选能力，不是所有生成 Agent 的默认必选项。相关配置统一进入 Runtime Contract：

```text
contracts/session.json
contracts/memory.json    # 仅当 AssemblySpec 声明 memory_system / memory_store 时生成
```

第八阶段按第七阶段冻结的 `package_materialization_plan` 物化这些 contract 文件，模型不能改写。没有声明跨会话记忆的 AgentPackage 不生成 `contracts/memory.json`，也不要求 RuntimeKernel 注入 BaseStore。

RuntimeKernel 编译时：

```text
contracts/session.json -> AgentSessionManager + checkpointer
contracts/memory.json -> BaseStore + MemorySystemRuntime      # 可选；启用跨会话记忆时必需
graph.compile(checkpointer=..., store=...)
auto inject memory retrieve system wrapper     # 无 memory runtime 时 no-op
start MemoryBackgroundWorker                   # write_enabled=true 时启动，失败不阻塞主图
```

如果 `cross_session_memory.enabled=true` 但没有 BaseStore，编译失败。后台 worker 启动失败不阻塞主图，只禁用写入并发出事件。启用写入时，写入 segment 必须从 LangGraph `messages` checkpoint 的完整窗口构建，和 Factory 的 conversation segment 契约对齐，而不是只截取当前轮临时字段。

### 3.6 事件

记忆系统只发摘要事件，不展示完整长期记忆内容：

```text
memory_write_queued
memory_write_queued_failed
memory_segment_prepared
memory_extraction_completed
memory_write_completed
memory_write_failed
memory_retrieval_completed
memory_injection_completed
```

payload 只携带数量、namespace、job_id、耗时和错误摘要。

### 3.7 当前约束

- 会话内记忆使用 LangGraph 原生 checkpointer，不自建会话内 MemoryStore。
- 跨会话记忆使用 LangGraph BaseStore，不复用旧的独立 memory engine。
- 跨会话记忆不是上一段会话上下文，不把临时会话状态直接写入长期记忆。
- 本节不处理上下文清洗、压缩、摘要注入和 prompt 组装。
- Factory 与生产出来的 Agent 都围绕同一套记忆规范接入。
- 旧的独立 memory state、独立记忆引擎、记忆策略和记忆业务节点路径废弃。

---

## 4. 知识系统

知识系统当前也没有形成统一规范，但 RuntimeKernel 里已有轻量实现。

### 4.1 当前实现迹象

RuntimeKernel 侧：

| 位置 | 现状 |
| --- | --- |
| `agent_factory/runtime_kernel/state/schema.py` | 有 `KnowledgeState`。 |
| `agent_factory/runtime_kernel/knowledge/engine.py` | 有简单 `KnowledgeEngine`，基于内存 documents 做检索。 |
| `agent_factory/runtime_kernel/adapters/knowledge.py` | 有 knowledge adapter 协议。 |
| `agent_factory/runtime_kernel/nodes/standard/knowledge_retrieve.py` | 有 `operational.knowledge_retrieve` 标准节点。 |
| `agent_factory/runtime_kernel/context/engine.py` | 会把 retrieved knowledge 放入模型上下文。 |
| `agent_factory/runtime_kernel/patterns/builtins/react_agent.yaml` | react_agent pattern 包含 `knowledge_retrieve` 节点。 |
| `agent_factory/runtime_kernel/kernel/facade.py` | 默认注入 `KnowledgeEngine`。 |

Factory 生产链路迹象：

| 位置 | 现状 |
| --- | --- |
| `agent_factory/factory_graph/stage_subgraphs/assembly_spec_generation.py` | Assembly services 会要求 `knowledge_engine`。 |
| `agent_factory/factory_graph/stage_subgraphs/package_generation.py` | 会物化 knowledge 相关 package 文件，但具体知识系统目录仍待统一。 |
| `tests/factory_graph/test_assembly_spec_generation.py` | 后续需要按新的知识系统契约重写。 |

### 4.2 当前问题

当前 knowledge 更像 RuntimeKernel 内部的示例检索能力，还不是完整知识系统。

主要缺口：

- 没有知识源规范。
- 没有索引规范。
- 没有 citation / freshness / multi-source 策略。
- 旧 retrieval profile 不能继续作为 memory 与 knowledge 的混用边界。
- AgentPackage 里缺少明确的 knowledge 系统目录与索引文件约定。
- MCP / Skill 贡献知识源的路径还没有设计。

### 4.3 后续处理原则

暂不提前规定 knowledge 系统形态。

后续应该先基于现有 `KnowledgeEngine`、`KnowledgeState`、`knowledge_retrieve` 节点梳理：

```text
知识源是什么
索引在哪里
检索策略在哪里
引用如何表达
哪些内容写入 AgentPackage
哪些内容属于 AgentInstance 运行期配置
```

---

## 5. 定时任务系统

定时任务系统当前基本为空。

### 5.1 当前实现迹象

项目内目前没有发现正式 scheduler、cron、timer、automation 类型的运行系统。

可作为外围参考的只有：

- RuntimeKernel 已有 session、checkpoint、resume 能力。
- Factory bridge 有 session 和 rerun 能力。
- Codex App 自身有 automation 能力，但这不是 FastAgentFactory 项目内系统，不能算项目实现。

### 5.2 当前问题

定时任务系统尚未定义：

- trigger 形态。
- 执行目标。
- 与 Agent graph / node 的关系。
- 与 checkpoint / session 的关系。
- 失败重试与错过执行策略。
- CLI/WebUI 如何展示计划任务。
- AgentPackage 如何声明定时任务。

### 5.3 后续处理原则

暂时留空，不做伪规范。

等工具、记忆、知识三类系统稳定后，再讨论定时任务是否应该是：

- RuntimeKernel 内部 scheduler。
- AgentInstance 外部调度器。
- AgentPackage 中的声明式 trigger。
- 或者三者组合。

---

## 6. Trace 系统

Trace 系统需要作为独立运行基础设施处理，不能附属于记忆、工具、CLI 或 render wrapper。

### 6.1 当前实现迹象

当前项目里已有一些分散的观测能力：

| 位置 | 现状 |
| --- | --- |
| `agent_factory/factory_graph/frontend_bridge/event_normalizer.py` | 会把 LangGraph stream 归一成前端事件。 |
| `agent_factory/runtime_render/` | 已有 render wrapper 相关节点生命周期事件。 |
| `docs/runtime_render_pipeline.md` | 描述了 Factory 与生成 Agent 共用渲染管线。 |
| `cli/src/state/runtimeStore.ts` | CLI 已按事件订阅渲染运行状态、工具状态、记忆提示。 |
| `agent_factory/runtime_kernel/state/schema.py` | RuntimeState 中已有 observability 相关状态。 |

这些能力目前更像“事件流与 UI 渲染基础”，还不是完整 Trace 系统。

### 6.2 当前问题

当前缺口：

- 没有统一 trace span 模型。
- 没有统一 trace 存储位置。
- 没有 run / stage / node / model / tool / memory / context 的统一生命周期记录。
- 没有把后台任务 trace 和主对话 trace 关联起来。
- 没有 trace 查询接口。
- CLI/WebUI 还不能按 trace id 追踪一次完整运行。
- 第九、十阶段需要读取 harness / repair trace，但当前 trace 规范还不够稳定。

跨会话记忆当前只发摘要事件，例如 `memory_write_queued`，但后台 worker 的完整执行过程还没有进入统一 trace。这意味着用户能看到“记忆写入已排队”的 UI 提示，但还不能完整追踪 taskModel 如何判断、提取了什么动作、写入是否成功、失败原因在哪里。

### 6.3 后续处理原则

Trace 系统后续应独立成模块，例如：

```text
agent_factory/trace_system/
  schema.py
  recorder.py
  store.py
  exporters.py
  correlation.py
```

基础边界：

- Factory 与生成 Agent 使用同一套 Trace 事件规范，但 trace 数据隔离。
- Trace 不写业务 state，不影响图执行语义。
- Trace 可以记录摘要、计数、错误、耗时、引用，不默认记录完整敏感内容。
- 后台任务必须能关联到触发它的 `run_id / session_id / thread_id / job_id`。
- CLI/WebUI 只消费 trace projection，不解析 LangGraph 原始 patch。
- 第十阶段 repair 读取 trace/report，而不是从 UI 文案反推失败原因。

---

## 7. 上下文管理系统

上下文管理系统也需要作为独立基础设施处理，不能继续散落在 prompt 拼接、记忆注入、knowledge retrieve 或节点策略里。

### 7.1 当前实现迹象

当前项目里已有上下文相关能力：

| 位置 | 现状 |
| --- | --- |
| `agent_factory/factory_graph/prompt_context.py` | Factory 阶段模型调用会注入统一运行边界与阶段边界。 |
| `agent_factory/factory_graph/model_call.py` | Factory 模型调用入口会统一处理 prompt values 与跨会话记忆注入。 |
| `agent_factory/runtime_kernel/context/engine.py` | RuntimeKernel 有 ContextEngine。 |
| `agent_factory/runtime_kernel/state/schema.py` | RuntimeState 有 context / model_context 相关结构。 |
| `agent_factory/memory_system/injection.py` | 跨会话记忆当前注入到 model context，不写入 messages。 |

这些能力目前还没有形成完整上下文系统，只是各模块按各自需要拼装模型输入。

### 7.2 当前问题

当前缺口：

- 没有统一上下文源分类。
- 没有上下文预算和裁剪的统一策略。
- 没有明确区分 system / developer / memory / knowledge / tool observation / user message 的注入顺序。
- 没有上下文压缩、摘要、去重和失效策略。
- Factory 与生成 Agent 的上下文策略还没有同构编译。
- `messages` 作为会话内记忆已经确定，但其他上下文源如何进入模型仍需统一。

### 7.3 后续处理原则

上下文管理系统后续应独立成模块，例如：

```text
agent_factory/context_system/
  schema.py
  sources.py
  assembler.py
  budget.py
  compression.py
  injection.py
```

基础边界：

- 会话内记忆仍只操作 LangGraph `messages`。
- 跨会话记忆、知识检索、资源、策略、节点说明都作为上下文源进入 assembler。
- 上下文系统负责排序、裁剪、去重、压缩、注入位置，不负责记忆写入。
- Factory 与生成 Agent 使用同一套上下文源分类和预算思想，但数据隔离。
- 第四阶段可以规划上下文策略名称，第七/八阶段物化配置，RuntimeKernel 编译后执行。

---

## 8. AgentPackage 当前基础文件建议

当前只做方向性记录，不视为最终目录规范。

```text
agent_package/
  agent_package.json
  assembly_spec.json
  resources.json
  sandbox_contract.json
  render_manifest.json

  contracts/
    session.json
    tools.json
    render.json
    resources.json
    sandbox.json
    memory.json        # 可选

  tools/
  prompts/
  policies/
  retrieval/
  strategies/
  formatters/

  extensions/
    mcp_servers.example.json
    enabled_skills.example.json
```

说明：

- `tools/` 已经有较明确方向。
- `retrieval/`、`strategies/`、`policies/` 当前更多是 Assembly binding 的物化结果，不等于完整 memory/knowledge 系统。
- `extensions/*.example.json` 只作为实例扩展配置示例，不表示 AgentPackage 自带用户扩展。
- memory、knowledge、schedules 等能力统一优先通过 `contracts/*.json` 进入编译层；是否还需要运行期数据目录，等对应系统规范明确后再定。

---

## 9. 当前结论

当前状态：

| 系统 | 结论 |
| --- | --- |
| 工具系统 | 已完成系统底座，且已接入 builtin / package / MCP / Skill。 |
| 记忆系统 | 已确定会话内/跨会话两类记忆，以及 read/write 四个标准端口。 |
| 知识系统 | 有 RuntimeKernel 内部实现迹象，需要后续清理成正式系统。 |
| 定时任务系统 | 暂无正式实现，先留空。 |
| Trace 系统 | 当前只有事件流和 render/debug 线索，后续需要独立模块化。 |
| 上下文管理系统 | 当前有 prompt context 与 Runtime ContextEngine 线索，后续需要统一上下文工程。 |

下一步不应继续抽象总能力系统，而应按系统逐个成熟：

```text
工具系统
  -> 继续接入 AgentPackage 启动链路和节点可见性闭合

记忆系统
  -> 围绕 SessionMemoryRead / SessionMemoryWrite / CrossSessionMemoryRead / CrossSessionMemoryWrite 清理实现

知识系统
  -> 清理现有 KnowledgeEngine / knowledge_retrieve

定时任务系统
  -> 暂缓，等前三类稳定后再设计

Trace 系统
  -> 从现有事件流、render wrapper、debug patch 中抽出统一 trace 规范

上下文管理系统
  -> 从 prompt_context、ContextEngine、memory/knowledge injection 中抽出统一上下文装配规范
```
