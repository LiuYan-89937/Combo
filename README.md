# FastAgentFactory

FastAgentFactory 是一个基于 LangGraph 构建的 CLI-first Agent 工厂原型。当前重点不是做一个已经完整交付的产品，而是把工厂运行层、交互 shell、基础工具、RuntimeKernel 和 AgentAssembly 路径整理清楚，方便后续分阶段实现、测试和返厂维修。

## 当前进度

已经完成：

- RuntimeKernel v0 基座：图模式编译、执行控制器、checkpoint/resume、observability、harness bridge、节点 wrapper、memory/context/knowledge/policy 策略接口，以及默认策略注册。
- AgentAssembly v0 基座：assembly schema、loader、validator、compiler、runner，以及一个示例 assembly 文件。
- FactoryGraph shell：交互式 CLI shell，明确拆分 `/chat` 和 `/create-agent` 两种模式。
- Factory chat graph：独立的 ReAct 风格 LangGraph 聊天路径，用 task model 加工厂基础工具完成闲聊、工作区检查和轻量任务。
- Factory production graph：用于制造 Agent 的 10 阶段 RuntimeKernel-native LangGraph 流水线。
- Factory 前四阶段：
  - `requirement_capture`：需求捕获、澄清和业务计划确认。
  - `runtime_pattern_selection`：只基于 Pattern metadata/description 选择 RuntimeKernel pattern。
  - `graph_behavior_planning`：基于 pattern 结构摘要规划节点行为、路由和中断点。
  - `node_strategy_planning`：为每个节点规划 wrapper、策略引用和待生成策略声明。
- 节点策略目录：第四阶段已从硬编码默认策略改为 `strategy_catalog`，模型可以引用已有策略，也可以只声明后续阶段需要实现的新策略。
- 基础工具：文件系统、搜索/理解、shell 三类工具，使用 LangChain `@tool` 注册，并注入 LangGraph `ToolNode`。
- OpenAI 兼容模型配置：通过 `.env` 读取模型配置，并支持 provider-specific thinking 模式兼容。

仍在进行：

- 10 个工厂生产阶段中，第 5 阶段之后仍是结构占位，内部业务逻辑还没有完整实现。
- `/create-agent` 当前运行的是工厂生产图骨架，应视为生产流水线入口，不是已经完成的 Agent 生成器。
- 当前配置不包含真实外部 WebSearch。
- 生成 Agent package、沙箱测试、自动修复闭环仍未完成生产级实现。

## 主要路径

- `agent_factory/factory_graph/chat_graph.py`：独立 ReAct 聊天图。
- `agent_factory/factory_graph/graph.py`：10 阶段工厂生产图。
- `agent_factory/factory_graph/stages/`：工厂阶段节点实现。
- `agent_factory/factory_graph/schemas.py`：FactoryGraph 结构化模型输出 schema。
- `agent_factory/factory_graph/strategy_catalog.py`：Factory 第四阶段可引用的节点策略目录。
- `agent_factory/factory_graph/tools/`：工厂基础工具。
- `agent_factory/models/chat_model.py`：OpenAI 兼容 ChatModel 构建。
- `agent_factory/runtime_kernel/`：RuntimeKernel v0 实现和规范文档。
- `agent_factory/assembly/`：AgentAssembly schema、校验、编译和 runner。
- `agent_factory/AGENT_ASSEMBLY_SPEC_V0.md`：AgentAssembly 规范草案。
- `agent_factory/factory_graph/FACTORY_BASE_TOOLS.md`：基础工具清单。

## 安装

安装依赖：

```bash
uv sync
```

创建本地环境配置：

```bash
cp .env.example .env
```

在 `.env` 中填写模型配置：

```bash
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
AGENTFACTORY_TASK_MODEL=
```

主模型用于工厂生产流程。task model 用于 `/chat` 和轻量任务流程。两者都通过 LangChain 调用 OpenAI 兼容 Chat API。

## CLI 使用方式

检查当前工作区入口：

```bash
uv run agentfactory init
```

启动交互 shell：

```bash
uv run agentfactory shell
```

默认每次启动都会创建新的 Factory 会话，不会自动继承上一次上下文。

需要恢复历史会话时使用显式入口：

```bash
uv run agentfactory shell --resume-latest
uv run agentfactory shell --session-id <session_id>
```

Shell 命令：

```text
/chat
```

进入聊天模式。聊天路径已经从 14 阶段工厂图中独立出来，可以通过 ReAct 使用已注入的基础工具。

```text
/create-agent
```

进入 Agent 制造模式。该模式下的用户输入会运行 10 阶段 FactoryGraph。

```text
/exit
```

退出当前模式。如果当前不在任何模式中，则退出 shell。

```text
/quit
```

直接退出 shell。

常用检查命令：

```text
/help
/session
/sessions
/new-session
/resume <session_id>
/tools
/stages
/state on
/state off
/messages on
/messages off
/stop <stage_id>
/stop off
```

聊天模式示例：

```text
/chat
现在工作区有什么文件？
/exit
```

制造模式示例：

```text
/create-agent
创建一个能分析投资研报并输出引用来源的 Agent
/exit
```

## 非交互命令

运行一次工厂请求：

```bash
uv run agentfactory create-agent --prompt "创建一个记账 Agent"
```

默认断点跟随当前已实现阶段推进。当前默认停在第四阶段 `node_strategy_planning`：前三阶段完成需求、pattern 和图行为计划，第四阶段生成节点策略计划并停止本轮。

运行到指定工厂阶段后停止，并打印最终 state：

```bash
uv run agentfactory create-agent \
  --prompt "创建一个记账 Agent" \
  --stop-after-stage node_strategy_planning \
  --json
```

关闭断点并继续跑后续阶段：

```bash
uv run agentfactory create-agent \
  --prompt "创建一个记账 Agent" \
  --stop-after-stage off
```

运行完整阶段骨架：

```bash
uv run agentfactory test-stages --prompt "创建一个记账 Agent"
```

## 工厂阶段

当前生产图包含 10 个 RuntimeKernel-native 阶段：

1. `requirement_capture`
2. `runtime_pattern_selection`
3. `graph_behavior_planning`
4. `node_strategy_planning`
5. `tool_capability_planning`
6. `resource_and_condition_planning`
7. `assembly_spec_generation`
8. `package_generation`
9. `harness_generation_and_test`
10. `repair_or_finalize`

当前默认断点在第 4 阶段 `node_strategy_planning`。CLI 会展示：

- 精炼后的需求和业务计划。
- Runtime pattern 选择结果。
- 图节点、节点行为、路由和中断点。
- 每个节点的 `strategy_refs`。
- 需要后续阶段生成 Python 实现的 `proposed_strategies`。

## 节点策略规划

第四阶段只做装配规划，不写具体 Python 策略实现。

已有策略通过 `strategy_refs` 引用：

```text
context:model 策略
memory:session 策略
policy:输出或审批策略
tool_visibility:节点级工具可见性策略
```

如果当前策略目录无法表达某个节点需求，第四阶段只生成 `proposed_strategies`：

```text
strategy_id
name
description
kind
phase
required_by_node_ids
applies_to_node_types
reads / writes
config_schema
implementation_notes
```

这些 proposed 策略的具体 Python 实现交给后续 package generation 阶段。

## 基础工具

当前注入的基础工具：

- 文件系统：`file_read`、`file_write`、`file_patch`、`file_list`、`file_exists`、`file_mkdir`、`file_copy`
- 搜索与理解：`search_files`、`search_text`、`search_inspect_text`、`search_inspect_file`
- Shell：`shell_run`、`shell_run_text`、`shell_which`、`shell_cwd`、`shell_env`、`shell_start`、`shell_status`、`shell_grep_process`、`shell_stop`

这些工具是通用工厂工具，不针对某一个项目目录做特化。不过实际能访问什么，仍由当前进程环境和权限控制。

## 环境变量

当前支持的本地变量：

```bash
AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
AGENTFACTORY_LLM_TIMEOUT_SECONDS=600
AGENTFACTORY_LLM_TEMPERATURE=0.2
AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS=8192
AGENTFACTORY_LLM_THINKING=enabled
AGENTFACTORY_TASK_MODEL=
AGENTFACTORY_TASK_TEMPERATURE=0.1
AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS=2048
AGENTFACTORY_TASK_THINKING=disabled
AGENTFACTORY_SESSION_ROOT=.agentfactory/sessions
AGENTFACTORY_CHECKPOINT_PATH=.agentfactory/checkpoints/factory.sqlite
AGENTFACTORY_RUN_PROVIDER_SMOKE=0
```

当前 env contract 中不包含 WebSearch/WebResearch 配置。

## 验证

当前开发阶段优先做语法和静态检查：

```bash
python -m py_compile \
  agent_factory/prompts.py \
  agent_factory/factory_graph/schemas.py \
  agent_factory/factory_graph/strategy_catalog.py \
  agent_factory/factory_graph/stages/node_strategy_planning.py \
  agent_factory/factory_graph/shell_cli.py
```

检查空白问题：

```bash
git diff --check
```
