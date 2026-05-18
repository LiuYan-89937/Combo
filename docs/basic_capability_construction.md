# Basic System Construction

本文档记录 FastAgentFactory 的四类基础系统建设状态与后续重构边界。

这里不再引入统一的 `Capability` 总外壳，也不强行要求四类系统共享同一种 registry、compiler 或 schema 形态。四类系统数量不多，可以各自拥有适合自身语义的架构。

当前只确认四类基础系统：

| 系统 | 当前状态 |
| --- | --- |
| 工具系统 | 已系统化搭建，是当前最成熟的一类。 |
| 记忆系统 | 已形成 LangGraph 原生规范：会话内 messages/checkpointer，跨会话 BaseStore。 |
| 知识系统 | 有 RuntimeKernel 实现迹象，但未形成统一规范。 |
| 定时任务系统 | 暂未看到项目内正式实现。 |

本文档的作用：

- 总结当前工具系统现状。
- 列出记忆、知识、定时任务在当前项目里的实现线索。
- 为后续清理 Factory 与 RuntimeKernel 的规范边界提供索引。
- 避免为了设计而设计，先按真实系统需要逐步成型。

---

## 1. 总原则

四类系统可以有不同架构，但必须遵守几条工程边界。

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

四类系统怎么编译可以不同，但都必须有明确入口，而不是散落在节点代码、prompt、工具函数里。

### 1.4 当前文档只记录系统层级，不预设总抽象

当前不定义统一的 `CapabilitySpec`。

后续如果某一类系统自然长出稳定 schema，就在该系统内部定义；如果四类系统后来真的出现公共字段，再抽取公共基础类型。现在不提前抽象。

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

AgentInstance 扩展建议位置：

```text
.agentfactory/instances/<agent_instance_id>/extensions/
  mcp_servers.json
  enabled_skills.json
```

当前已具备：

- Factory 可以扫描自己的 MCP / Skill 配置并注册工具。
- RuntimeKernel 有 `AgentInstanceExtensionManager`，能加载实例级 MCP / Skill 配置。
- MCP 最终转换成各自 `ToolSpec`。
- Skill 最终转换成一个统一 `skill` ToolSpec，具体 Skill 内容按需加载。

后续还需要补齐：

- AgentPackage 启动链路中自动加载实例扩展并合并到运行工具注册表。
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
  intent.py
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
  -> taskModel intent detection
  -> retrieve related memories
  -> taskModel extraction
  -> validate add/update/delete/noop
  -> write BaseStore
  -> write job journal
```

原则：

- `taskModel` 是唯一显式记忆意图识别入口，不保留关键词硬规则。
- 提取动作只允许 `add / update / delete / noop`。
- 写入失败不生成伪记忆。
- queue 满时返回 `memory_write_queued_failed`，不阻塞主对话。
- job journal 只保存任务定位和 message range，不保存完整消息正文。

默认队列：

```text
max_pending_jobs = 32
concurrency = 1
queue_full_policy = reject_new_when_full
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
SYSTEM_MEMORY_RETRIEVE_WRAPPER
  before cognitive.* model call
  retrieve -> rank -> inject into runtime.context.model_context.cross_session_memory
```

Factory 在模型调用前使用同一套检索、排序和注入 pipeline，把结果作为 `prompt_context.cross_session_memory` 进入提示词上下文。

注入硬限制：

```text
max_items_total = 8
max_tokens_total = 1200
min_score = 0.55
per_kind_limits = constraint 3 / preference 3 / decision 2 / fact 2 / artifact 1
```

注入不写入 `messages`。每次模型调用前重新检索、排序和裁剪，避免多轮对话后长期记忆越塞越多。

### 3.5 Package 与 RuntimeKernel 编译

第七阶段系统冻结：

```text
session.json
memory/config.json
memory/store.json
```

第八阶段系统物化这些文件，模型不能改写。

RuntimeKernel 编译时：

```text
session.json -> AgentSessionManager
memory/store.json -> BaseStore
memory/config.json -> MemorySystemRuntime
graph.compile(checkpointer=..., store=...)
auto inject memory retrieve system wrapper
start MemoryBackgroundWorker
```

如果 `cross_session_memory.enabled=true` 但没有 BaseStore，编译失败。后台 worker 启动失败不阻塞主图，只禁用写入并发出事件。

### 3.6 事件

记忆系统只发摘要事件，不展示完整长期记忆内容：

```text
memory_write_queued
memory_write_queued_failed
memory_intent_detected
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

## 6. AgentPackage 当前基础文件建议

当前只做方向性记录，不视为最终目录规范。

```text
agent_package/
  agent_package.json
  assembly_spec.json
  resources.json
  sandbox_contract.json
  render_manifest.json

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
- memory、knowledge、schedules 是否需要独立目录，等对应系统规范明确后再定。

---

## 7. 当前结论

当前状态：

| 系统 | 结论 |
| --- | --- |
| 工具系统 | 已完成系统底座，且已接入 builtin / package / MCP / Skill。 |
| 记忆系统 | 已确定会话内/跨会话两类记忆，以及 read/write 四个标准端口。 |
| 知识系统 | 有 RuntimeKernel 内部实现迹象，需要后续清理成正式系统。 |
| 定时任务系统 | 暂无正式实现，先留空。 |

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
```
