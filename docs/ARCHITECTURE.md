# Combo 当前架构

基于 2026-09-28 仓库实现。实线表示主要调用或数据流；图中的「工作区隔离」是应用层边界，不代表操作系统沙箱。

## 系统组成

```mermaid
flowchart TB
    User["用户"]

    subgraph Desktop["桌面应用进程 · Tauri"]
        UI["Vue 3 + Pinia<br/>对话、能力池、模型池、记忆、调度"]
        Rust["Rust 宿主<br/>单实例、窗口、更新、Git/文件原生命令"]
        Host["Computer Use 本机宿主<br/>鉴权、会话所有权、取消"]
    end

    subgraph Backend["本机 Python 进程 · FastAPI"]
        API["HTTP API<br/>命令、查询、配置、附件"]
        Bridge["前端事件投影 + SSE"]
        Control["运行控制面<br/>模型策略、能力发布、审批、调度"]
        Queue["命令收件箱 + Supervisor<br/>派发、恢复、子任务工作队列"]
        Runtime["Dynamic Runtime<br/>身份、快照、执行、提交"]
        Graph["Runtime Kernel<br/>固定 React / Plan-and-Execute 图"]
        Tooling["快照绑定的工具执行<br/>内置工具、Skill、MCP、依赖环境"]
        Context["上下文系统<br/>Agent.md、会话历史、记忆召回与压缩"]
        Browser["Browser Runtime<br/>Playwright + 独立 Chromium Context"]
        CU["Computer Use<br/>独立视觉/动作循环"]
        Children["临时子 Agent<br/>shared 或 Git worktree"]
    end

    subgraph LocalData["本机应用数据目录 · .combo"]
        RuntimeDB["runtime.sqlite<br/>会话、命令、快照引用、事件、能力、记忆、调度"]
        GraphDB["checkpoints.sqlite + graph_store/runtime.sqlite<br/>图恢复状态"]
        ModelDB["model_pool/*.sqlite<br/>模型配置与用量"]
        Files["workspaces / capability_blobs / tool_outputs<br/>工作文件、能力内容、工具产物"]
    end

    subgraph Platform["本机平台实现"]
        OS["macOS Swift / Windows Go<br/>辅助功能、截图、输入"]
    end

    subgraph Outside["外部服务"]
        Models["模型供应商 API"]
        MCP["外部 MCP Server"]
        Cloud["Combo 发布服务<br/>OAuth、版本更新、错误上报"]
    end

    User --> UI
    Rust -->|启动并监护| API
    Rust -->|启动| Host
    UI -->|HTTP 命令与查询| API
    Bridge -->|SSE 进度与结果| UI
    UI -->|Tauri 原生命令| Rust
    API --> Queue
    API --> Control
    Queue --> Runtime
    Control -->|冻结模型与能力策略| Runtime
    Runtime --> Graph
    Graph --> Context
    Graph --> Tooling
    Graph -->|模型调用| Models
    Tooling --> Browser
    Tooling --> CU
    Tooling --> MCP
    Tooling --> Children
    Children --> Graph
    CU -->|本机鉴权连接| Host
    CU -->|视觉模型调用| Models
    Host --> OS
    Tooling --> Files
    Context --> RuntimeDB
    Runtime --> RuntimeDB
    Runtime --> GraphDB
    Control --> RuntimeDB
    Control --> ModelDB
    Control --> Files
    Runtime -->|事件、提交、Outbox| Bridge
    Rust -->|登录、更新、报告| Cloud
```

## 一轮对话的执行与回显

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户
    participant UI as Vue 对话页
    participant API as FastAPI /api/commands
    participant DB as runtime.sqlite
    participant Supervisor as Supervisor 与主轮处理器
    participant Resolver as 模型与能力解析器
    participant Kernel as 固定执行图
    participant External as 模型与工具
    participant Event as 前端事件桥 /events

    User->>UI: 发送消息或引导
    UI->>API: 提交命令，携带会话和请求身份
    API->>DB: 登记会话轮次、消息与命令
    API-->>UI: 返回命令回执
    Supervisor->>DB: 领取待执行命令
    Supervisor->>Resolver: 解析运行策略与能力
    Resolver-->>Supervisor: 返回模型策略与不可变能力快照
    Supervisor->>DB: 关联快照、轮次和运行实例
    Supervisor->>Kernel: 执行 React 或 Plan-and-Execute 图
    loop 模型决定下一步
        Kernel->>External: 模型调用或经审批的工具调用
        External-->>Kernel: 模型片段、工具结果或中断
        Kernel-->>Event: 实时观测片段
        Event-->>UI: SSE 流式展示
    end
    Kernel->>DB: 提交消息、工具记录、用量与恢复状态
    DB-->>Event: Outbox 发布持久事件
    Event-->>UI: 完成状态和最终结果
```

## 边界与职责

| 边界 | 当前实现 |
| --- | --- |
| 桌面与后端 | Rust 启动 Python sidecar；Vue 直接经本机 HTTP 调 FastAPI，并从 SSE 接收事件。Rust 负责原生能力，不承载 Agent 图。 |
| 请求与执行 | 命令先进入持久化收件箱；Supervisor 派发主请求与临时子任务。每轮固定模型策略、能力快照和运行身份。 |
| 模型与上下文 | 模型池提供 Profile/凭据；上下文系统组装 Agent.md、会话历史和当前范围的记忆，按需检索与压缩。知识库通过独立检索能力使用。 |
| 工具与资源 | 工具注册表由该轮能力快照物化；文件/进程绑定工作区，浏览器按 Agent 会话隔离 Context；Computer Use 经本机宿主调用平台实现。 |
| 子 Agent | 临时运行实例复用固定图；`shared` 使用主工作区，`worktree` 从 Git HEAD 创建独立工作树和本地分支，集成由主 Agent 决定。 |
| 落盘与恢复 | `runtime.sqlite` 保存业务与执行账本；LangGraph checkpoint/graph store 保存图恢复状态；模型池和文件产物分别存放。Outbox 将持久事件投影到前端。 |
| 云端服务 | `services/combo_service` 处理官网、桌面 OAuth、发布更新和错误上报；不承担本地 Agent 运行或能力发布。 |

关键源码入口：[Tauri 主进程](../src-tauri/src/main.rs)、[FastAPI 装配](../web_frontend/backend/event_api_server.py)、[后端组合根](../web_frontend/backend/runtime_backend.py)、[运行时组合根](../combo/dynamic_runtime/application.py)、[单轮命令处理](../combo/dynamic_runtime/main_turn.py)、[固定执行图](../combo/runtime_kernel/fixed_graphs.py)、[工具快照](../combo/dynamic_runtime/snapshot_tool_registry.py)、[事件投影](../web_frontend/backend/frontend_event_bridge.py)。
