# 01. 工程骨架

## 目标

先搭建一个干净的 Python 工程骨架，让后续功能可以按模块落地。这个阶段不追求完整行为，只要求目录、入口、基础类型、错误、CLI 空命令、斜杠命令交互壳和测试框架准备好。

第一版采用：

```text
Python 3.11
uv
Typer
Rich
prompt_toolkit
Pydantic v2
ruamel.yaml
pytest
pytest-asyncio
ruff
```

CLI 支持两种操作模式：

```text
1. 普通命令模式：agentfactory validate-agent examples/customer_service_agent
2. 斜杠交互模式：agentfactory shell 后输入 /validate examples/customer_service_agent
```

## 终端界面风格

第一版 CLI 风格参考 Claude Code / Codex CLI：终端原生、对话式、低干扰，不做复杂全屏 TUI。

界面约定：

```text
1. 使用 `›` 作为用户输入提示符。
2. 普通文本作为自然语言需求。
3. `/` 开头作为斜杠命令。
4. 命令结果用简短块状输出。
5. 高风险项用 `!` 标记。
6. 新增项用 `+` 标记。
7. 禁用 / 废弃项用 `-` 标记。
8. 修改项用 `~` 标记。
9. 每次关键操作后给出 Next 建议。
10. 长 trace、diff、Harness 详情默认不展开，通过命令查看。
```

示例：

```text
AgentFactory v0.1  ·  no agent selected

› 创建一个客服 Agent，支持退款、返厂、投诉和转人工

  Draft created
  Path     examples/customer_service_agent
  Risk     medium
  Next     /review-agent examples/customer_service_agent

› /review-agent examples/customer_service_agent

  Agent
  Name     customer-service-agent
  Goal     处理售前、售后、退款、返厂、投诉与人工转接

  Capabilities
  + intent_detection
  + tool_routing
  + mcp_binding

  High risk
  ! repair_ticket_create requires confirmation

  Next
  /approve-agent examples/customer_service_agent
  /validate examples/customer_service_agent
```

## 目录产物

```text
agent_factory/
├── core/
├── application/
├── specs/
├── factory/
├── package/
├── registry/
├── capability/
├── runtime/
├── context/
├── tools/
├── mcp/
├── memory/
├── harness/
├── ops/
├── isolation/
└── cli/

examples/
tests/
docs/
```

## 必做任务

```text
1. 创建 pyproject.toml。
2. 创建 agent_factory 包和所有一级模块目录。
3. 创建 agent_factory/cli/main.py。
4. 创建 agent_factory/cli/shell.py、slash.py、session.py、rendering.py、theme.py。
5. 创建 agent_factory/application/ 应用服务层。
6. 创建 core/types.py、core/errors.py、core/result.py、core/events.py。
7. 创建最小 CLI 入口 agentfactory。
8. 创建 tests/unit、tests/integration、tests/fixtures。
9. 创建 examples/customer_service_agent 空目录。
10. 创建 slash command 的 smoke test。
```

## Application 层

CLI 不直接调用底层模块，必须通过 `application/` 层组织用例流程。

```text
agent_factory/application/
├── create_agent_service.py
├── validate_agent_service.py
├── test_agent_service.py
├── run_agent_service.py
├── upgrade_agent_service.py
├── patch_plan_service.py
├── approval_service.py
├── diff_service.py
└── registry_service.py
```

这样未来 Web UI、HTTP API、SDK 都可以复用同一套流程。

## CLI 模块职责

```text
agent_factory/cli/main.py        普通 Typer 命令入口
agent_factory/cli/shell.py       交互式 shell 主循环
agent_factory/cli/slash.py       斜杠命令解析和分发
agent_factory/cli/session.py     ShellSession 状态
agent_factory/cli/rendering.py   Rich 输出组件
agent_factory/cli/theme.py       颜色、符号、提示符风格
```

## CLI 空命令

第一阶段先保留命令入口，不要求全部实现：

```bash
agentfactory shell
agentfactory create-agent
agentfactory validate-agent
agentfactory test-agent
agentfactory register-agent
agentfactory run-agent
agentfactory upgrade-agent
agentfactory plan-upgrade
agentfactory approve-patch
agentfactory apply-patch-plan
agentfactory registry
agentfactory trace
agentfactory diff
agentfactory approval
```

## 斜杠命令交互壳

`agentfactory shell` 进入交互式会话。普通文本默认作为自然语言需求，斜杠开头的输入作为命令。交互输入使用 `prompt_toolkit`，输出使用 `Rich`。

示例：

```text
$ agentfactory shell
AgentFactory v0.1

› 帮我创建一个客服 Agent，支持退款、返厂、投诉和转人工
› /create-agent --draft
› /review-agent examples/customer_service_agent
› /approve-agent examples/customer_service_agent
› /validate examples/customer_service_agent
› /test examples/customer_service_agent
› /run customer-service-agent --chat
› /help
› /exit
```

输入能力：

```text
1. 命令历史。
2. 斜杠命令补全。
3. 基础路径补全。
4. Ctrl+C 取消当前输入。
5. Ctrl+D 或 /exit 退出。
```

第一版斜杠命令：

```text
/help
/exit
/init
/create-agent
/review-agent
/approve-agent
/validate
/test
/register
/run
/upgrade
/plan-upgrade
/review-patch
/approve-patch
/apply-patch-plan
/trace
/diff
/approval
/registry
```

斜杠命令规则：

```text
1. 斜杠命令和普通 CLI 命令必须共用 Application Service。
2. 斜杠命令只是交互入口，不实现独立业务逻辑。
3. 普通自然语言输入进入当前 ShellSession 的 pending_requirement。
4. /create-agent --draft 默认使用 pending_requirement。
5. /help 必须列出可用命令和当前会话状态。
6. /exit 退出前提示未保存的草稿、PatchPlan 或审批状态。
7. 渲染必须通过 rendering.py，不在命令处理逻辑里散落 print。
8. --json 输出不能包含 Rich 样式和人类提示文案。
```

## 验收标准

```text
1. python -m agent_factory.cli.main --help 可以运行。
2. agentfactory --help 可以列出命令。
3. agentfactory shell 可以启动交互式会话。
4. /help 可以列出斜杠命令。
5. /exit 可以正常退出。
6. 普通文本可以写入 ShellSession.pending_requirement。
7. shell 使用 `›` 提示符。
8. /help 至少有斜杠命令补全或命令列表。
9. Rich 输出和 --json 输出分离。
10. pytest 可以启动，允许此阶段测试为空或只有 smoke test。
11. 所有模块可以 import，不出现循环导入。
12. 工程目录与母文档保持一致。
```

## 不做

```text
1. 不实现 Agent 生成逻辑。
2. 不实现 GraphRuntime。
3. 不接真实 MCP。
4. 不运行真实工具。
5. 不做复杂 TUI，只做轻量交互式 shell。
```
