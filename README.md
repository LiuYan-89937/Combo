# FastAgentFactory

FastAgentFactory 是一个基于 LangGraph 构建的 CLI-first Agent 工厂原型。当前重点不是做一个已经完整交付的产品，而是把工厂运行层、交互 shell、基础工具、RuntimeKernel 和 AgentAssembly 路径整理清楚，方便后续分阶段实现、测试和返厂维修。

## 当前进度

已经完成：

- RuntimeKernel v0 基座：图模式编译、执行控制器、checkpoint/resume、observability、harness bridge、节点 wrapper、memory/context/knowledge/policy 策略接口，以及默认策略注册。
- AgentAssembly v0 基座：assembly schema、loader、validator、compiler、runner，以及一个示例 assembly 文件。
- FactoryGraph shell：交互式 CLI shell，明确拆分 `/chat` 和 `/create-agent` 两种模式。
- Factory chat graph：独立的 ReAct 风格 LangGraph 聊天路径，用 task model 加工厂基础工具完成闲聊、工作区检查和轻量任务。
- Factory production graph：用于制造 Agent 的 14 阶段 LangGraph 骨架。
- 基础工具：文件系统、搜索/理解、shell 三类工具，使用 LangChain `@tool` 注册，并注入 LangGraph `ToolNode`。
- OpenAI 兼容模型配置：通过 `.env` 读取模型配置，并支持 provider-specific thinking 模式兼容。

仍在进行：

- 14 个工厂生产阶段大部分仍是结构占位，内部业务逻辑还没有完整实现。
- `/create-agent` 当前运行的是工厂生产图骨架，应视为生产流水线入口，不是已经完成的 Agent 生成器。
- 当前配置不包含真实外部 WebSearch。
- 生成 Agent package、沙箱测试、自动修复闭环仍未完成生产级实现。

## 主要路径

- `agent_factory/factory_graph/chat_graph.py`：独立 ReAct 聊天图。
- `agent_factory/factory_graph/graph.py`：14 阶段工厂生产图。
- `agent_factory/factory_graph/stages/`：工厂阶段节点实现。
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

Shell 命令：

```text
/chat
```

进入聊天模式。聊天路径已经从 14 阶段工厂图中独立出来，可以通过 ReAct 使用已注入的基础工具。

```text
/create-agent
```

进入 Agent 制造模式。该模式下的用户输入会运行 14 阶段 FactoryGraph。

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

运行到指定工厂阶段后停止，并打印最终 state：

```bash
uv run agentfactory create-agent \
  --prompt "创建一个记账 Agent" \
  --stop-after-stage capture_requirement \
  --json
```

运行完整阶段骨架：

```bash
uv run agentfactory test-stages --prompt "创建一个记账 Agent"
```

## 工厂阶段

当前生产图包含 14 个阶段：

1. `capture_requirement`
2. `understand_requirement`
3. `plan_capabilities`
4. `identify_conditions`
5. `plan_resource_needs`
6. `collect_evidence`
7. `build_resource_contracts`
8. `decide_readiness`
9. `plan_implementation`
10. `generate_package_specs`
11. `generate_tools`
12. `sandbox_test_and_repair`
13. `generate_harness`
14. `complete_summary`

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

运行语法和单元验证：

```bash
python -m unittest discover tests -v
```

检查空白问题：

```bash
git diff --check
```
