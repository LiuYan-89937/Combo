# FastAgentFactory

FastAgentFactory 是一个基于 LangGraph 和 RuntimeKernel 的 Agent 工厂原型。当前架构已经拆成两层：

- **Python Runtime**：负责 FactoryGraph、RuntimeKernel、session/checkpoint、工具执行、interrupt/resume、harness 和后续 package generation。
- **TypeScript CLI Frontend**：负责终端交互、流式输出、阶段展示、工具审批、资源补全和会话切换。

旧 Python CLI 已移除，不再保留兼容入口。

## 当前进度

已经完成：

- RuntimeKernel v0 基座：图模式编译、执行控制器、checkpoint/resume、observability、harness bridge、节点 wrapper、memory/context/knowledge/policy 策略接口，以及默认策略注册。
- AgentAssembly v0 基座：assembly schema、loader、validator、compiler、runner，以及示例 assembly 文件。
- Factory production graph：用于制造 Agent 的 10 阶段 RuntimeKernel-native LangGraph 流水线。
- Factory chat graph：独立 ReAct 聊天图，用 task model 和工厂基础工具处理闲聊、工作区检查和轻量任务。
- Factory 前六阶段：
  - `requirement_capture`：需求捕获、澄清和业务计划确认。
  - `runtime_pattern_selection`：只基于 Pattern metadata/description 选择 RuntimeKernel pattern。
  - `graph_behavior_planning`：基于 pattern 结构摘要规划节点行为、路由和中断点。
  - `node_strategy_planning`：为每个节点规划 wrapper、策略引用和待生成策略声明。
  - `tool_capability_planning`：规划工具能力契约、节点可见性、审批标记和后续实现状态。
  - `resource_and_condition_planning`：必须 ReAct，资源检查工具经 `ToolNode` 执行，结果作为 Observation 回到模型，验证后写资源文件。
- Python Runtime Bridge：`agent_factory/factory_graph/frontend_bridge/` 通过 JSONL over stdio 暴露运行层事件和命令。
- TypeScript CLI：`cli/` 使用 Ink/React 渲染交互式 Factory shell。
- 基础工具：文件系统、搜索/理解、shell 三类工具，使用 LangChain `@tool` 注册，并注入 LangGraph `ToolNode`。

仍在进行：

- 第 7 阶段之后仍是结构占位，业务逻辑尚未完整实现。
- `/create-agent` 当前是工厂生产图入口，不是完整 Agent 生成器。
- 生成 Agent package、沙箱测试、自动修复闭环仍未完成生产级实现。

## 主要路径

- `agent_factory/factory_graph/frontend_bridge/`：Python Runtime Bridge，唯一供 TS CLI 调用的机器协议层。
- `cli/`：TypeScript CLI 前端。
- `agent_factory/factory_graph/chat_graph.py`：独立 ReAct 聊天图。
- `agent_factory/factory_graph/graph.py`：10 阶段工厂生产图。
- `agent_factory/factory_graph/stages/`：工厂阶段节点实现。
- `agent_factory/factory_graph/tools/`：工厂基础工具。
- `agent_factory/runtime_kernel/`：RuntimeKernel v0 实现和规范文档。
- `agent_factory/assembly/`：AgentAssembly schema、校验、编译和 runner。

## 安装

安装 Python 运行层依赖：

```bash
uv sync
```

安装 TypeScript CLI 依赖：

```bash
pnpm --dir cli install
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

主模型用于工厂核心生产流程、资源分析/重写，并作为生成 Agent 的默认模型能力来源。task model 用于 Factory 内部轻量任务，例如 `/chat`、意图识别、简单分类和 CLI 辅助。两者都属于 Factory 自身运行配置，不会写入第六阶段生成 Agent 的 resources 文件。

## CLI 使用方式

启动 TypeScript CLI：

```bash
pnpm --dir cli factory
```

根目录也提供转发脚本：

```bash
pnpm factory
```

默认每次启动都会创建新的 Factory 会话，不会自动继承上一次上下文。

Shell 命令：

```text
/chat
/create-agent
/exit
/quit
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

聊天模式：

```text
/chat
现在工作区有什么文件？
/exit
```

制造模式：

```text
/create-agent
创建一个能分析投资研报并输出引用来源的 Agent
/exit
```

旧入口已经移除：

```text
uv run agentfactory shell
uv run agentfactory create-agent
uv run agentfactory test-stages
```

## Bridge 协议

TypeScript CLI 通过 stdio 启动 Python bridge：

```bash
python -m agent_factory.factory_graph.frontend_bridge.stdio_server
```

通信格式为 JSONL。TS 向 stdin 写 command，Python 向 stdout 写 runtime-bound event。CLI 只负责渲染事件，不直接依赖 LangGraph 原始 patch；原始 patch 只作为 `debug_patch` 进入调试面板。

核心 command：

```text
start_session
list_sessions
switch_session
new_session
set_mode
send_message
resume_interrupt
set_options
shutdown
```

核心 event：

```text
runtime_ready
session_started
session_switched
sessions_listed
mode_changed
run_started
stage_completed
run_completed
run_failed
stage_started
stage_failed
node_started
node_completed
node_failed
model_call_started
model_stream_delta
model_message_completed
model_call_failed
tool_call_proposed
tool_approval_requested
tool_approval_resolved
tool_call_started
tool_call_completed
tool_call_failed
tool_observation_available
interrupt_requested
runtime_paused
runtime_resumed
resource_input_requested
trace_snapshot
debug_patch
error
```

每个 event 都带统一 envelope：

```json
{
  "event_id": "...",
  "event_type": "model_stream_delta",
  "run_id": "...",
  "session_id": "...",
  "mode": "create_agent",
  "graph_id": "factory_graph",
  "stage_id": "...",
  "node_id": "...",
  "span_id": "...",
  "parent_span_id": "...",
  "sequence": 1,
  "timestamp": "...",
  "payload": {}
}
```

## 工厂阶段

当前生产图包含 10 个阶段：

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

当前默认断点在第 7 阶段 `assembly_spec_generation`。第六阶段如果缺少 required 资源键，会通过 LangGraph interrupt 交给 TS CLI 收集用户自然语言补充；资源未准备完整不会进入第七阶段。第七阶段会生成并校验 `AgentAssemblySpec draft`，写入 `.agentfactory/assemblies/<factory_run_id>/` 后停下展示。

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

Python 语法检查：

```bash
python -m py_compile \
  agent_factory/factory_graph/frontend_bridge/protocol.py \
  agent_factory/factory_graph/frontend_bridge/stdio_server.py \
  agent_factory/factory_graph/frontend_bridge/runtime_adapter.py \
  agent_factory/factory_graph/graph.py \
  agent_factory/factory_graph/chat_graph.py \
  agent_factory/factory_graph/session.py \
  agent_factory/factory_graph/tool_approval.py
```

TypeScript 静态检查：

```bash
pnpm --dir cli typecheck
pnpm --dir cli test
pnpm --dir cli lint
```

旧 Python CLI 引用检查：

```bash
rg -n "<旧 Python CLI 标识>" agent_factory pyproject.toml README.md
```

空白检查：

```bash
git diff --check
```
