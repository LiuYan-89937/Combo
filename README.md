# FastAgentFactory

本地优先、跨平台的 AI Agent 制造与运行工作台。

FastAgentFactory 将模型配置、Agent 制造与进化、会话工作区、工具审批、MCP、Skill、知识库、长期记忆、定时任务和多 Agent 协作整合在一个桌面应用中。安装包内置 Python 后端与运行依赖，日常使用不要求单独安装 Python、Node.js 或 Docker。

## 安装

### macOS

1. 下载与 Mac 处理器架构匹配的 `.dmg`。
2. 打开镜像，将 FastAgentFactory 拖入 `Applications`。
3. 启动应用。

### Windows

1. 下载 Windows x64 的 NSIS `.exe` 安装程序。
2. 完成安装并启动 FastAgentFactory。

当前 Windows 正式构建目标为 `x86_64-pc-windows-msvc`。Windows ARM64 设备只有在系统支持 x64 应用仿真时才能运行该安装包；它不是原生 ARM64 发行版。

安装包已经包含前端、Python 后端和基础运行依赖。只有在添加需要 `npx`、`uvx` 或其他本地命令的 MCP 时，才需要自行安装对应命令。

## 首次使用

### 1. 添加模型

打开「模型池」，依次完成：

1. 添加供应商凭证，填写 Base URL 和 API Key。
2. 添加模型 Profile，填写模型名并选择工具调用、结构化输出、推理和输入模态等能力。
3. 点击「测试连接」确认模型可用。
4. 回到对话输入框选择模型。

应用不再从 `.env` 读取主模型配置。没有可用文本模型时，输入框不会提供虚假的“默认模型”，而是提示先到模型池添加模型。

上下文窗口以当前模型 Profile 为准；未填写时默认 `256K`，压缩阈值未填写时默认 `200K`。请求无响应超时默认 `300` 秒，模型输出、工具或节点产生有效进展后会重新计时；节点最大重试次数默认 `5` 次，均可在右上角设置中调整。

### 2. 开始闲聊

「闲聊」是内置的系统 Agent，使用方式与其他 Agent 一致，但在侧边栏保留独立入口。

你可以：

- 直接发送文本问题。
- 上传文档、图片或文本附件。
- 让 Agent 使用工作区读写文件。
- 查看推理内容、工具调用和审批状态。
- 在回复过程中继续发送消息，后续消息会进入队列。
- 在聊天记录中点击附件，直接在对应会话工作区预览。

附件原文件会保存到当前会话工作区；解析出的文本进入模型上下文，图片则可以发送给支持图片输入的模型。

### 3. 配置通知

在右上角设置中可以分别控制：

- 对话回复完成
- 多 Agent 协作完成
- Agent 群聊任务完成
- 定时任务完成

应用位于后台时使用 macOS 或 Windows 原生通知；当前任务正在前台显示时不会重复提醒。

## 制造 Agent

进入「Agent 制造」，描述你需要的 Agent。建议同时说明：

- Agent 的用途和目标用户
- 需要接收的输入
- 期望输出和文件格式
- 可以使用的工具、Skill 或知识
- 必须遵守的限制
- 可验证的验收标准

制造过程会生成结构化 AgentPackage，并完成工具编译、依赖准备和 probe。Probe 异步运行，可以查看当前阶段、耗时、日志和失败原因，不会长时间占住整个应用。

制造完成后确认发布，即可在「已发布 Agent」中看到新 Agent。

## 运行已发布 Agent

进入「已发布 Agent」，选择目标 Agent 并创建会话。

- 发送第一条消息时会自动初始化 Agent。
- 也可以提前点击「初始化」预热依赖和运行环境。
- 每个会话拥有独立工作区、checkpoint、trace 和附件目录。
- 同一个 Agent 可以创建多个互不混淆的会话。
- 工具产生的文件会出现在右侧工作区。
- 工作区文件可以预览、在系统文件管理器中打开或另存为。
- 删除会话时会停止仍在运行的请求，并清理对应会话工作区和运行记录。

首次初始化可能需要构建 Python wheel 或准备 npm 依赖，因此会比后续启动更慢。相同依赖会进入本地共享依赖池，之后可由其他 Agent 复用。

## 进化 Agent

进入「Agent 进化」，选择已有 AgentPackage 并描述需要改变的行为。

进化适合：

- 增加或替换工具
- 安装新的 Skill
- 调整提示词和输出格式
- 修改依赖
- 修复已有 Agent 的行为问题

进化会话与普通运行会话分离。修改完成后需要重新验证并发布，已发布版本才会更新。

## 多 Agent 协作

进入「多 Agent 协作」，选择主 Agent 并创建协作任务。

主 Agent 可以：

1. 根据任务选择合适的已发布 Agent。
2. 拆分带依赖关系的子任务。
3. 调度子 Agent 执行。
4. 检查子 Agent 的工作区和交付结果。
5. 要求修改或继续后续任务。
6. 汇总最终结果。

协作使用与普通对话相同的模型、工具、依赖和会话运行逻辑。子 Agent 会话仍可单独打开查看。

## Agent 群聊

Agent 群聊适合让多个 Agent 在同一讨论中协作。可以通过 `@` 指定需要回复的 Agent，也可以观察成员任务和运行状态。

群聊成员仍使用各自的 AgentPackage、扩展和运行工作区，不会因为处于同一群聊而合并私有文件。

## 知识库

进入「知识库」添加：

- 单个文件
- 文件夹
- URL
- 文本笔记

系统会根据文件类型完成解析、分块和索引。知识源可以绑定到闲聊或指定 AgentPackage，不同 Agent 不会默认共享私有知识。

## MCP 与 Skill

进入「扩展管理」配置扩展。

### 添加 MCP

支持三种连接方式：

- `stdio`：本地命令，例如 `npx`、`uvx` 或自有可执行文件。
- `streamable_http`：远程 Streamable HTTP MCP。
- `sse`：远程 SSE MCP。

应用不预装搜索 MCP，也不会启动 SearXNG 或 Docker 容器。你可以导入 MCP JSON，并在原始配置基础上继续编辑。添加前建议先执行连接测试。

MCP Header 和环境变量保存在本机扩展配置中，不要提交或分享包含真实 Token 的配置。

### 安装本地 Skill

点击安装 Skill，直接从文件系统选择 Skill 文件夹。启用后的 Skill 会绑定到当前目标 Agent。

已装配 Skill 的名称会进入 Agent 系统提示词，Skill 正文仍按需加载，避免无条件占用上下文。

### 使用 SkillHUB

后端启动后会在后台检查并准备 SkillHUB CLI，不阻塞应用初始化。自动准备失败不会影响其他功能，错误会写入后端日志；此时可以在扩展管理中查看状态并重试。

通过 SkillHUB 安装的 Skill 只写入当前目标 Agent 的扩展目录。

## 定时任务

进入「定时任务」可以创建：

- Agent 对话任务
- 脚本任务
- 工具调用任务

支持 Cron、固定间隔和指定时间。任务使用保存时的目标和运行配置，并继承全局请求超时与最大重试设置。任务结束后可以发送应用内或系统通知。

## 会话与上下文

- 模型用量只在供应商返回真实 usage 后更新，不使用请求前的不完整本地估算覆盖前端显示。
- 达到当前模型的压缩阈值后，系统先压缩历史上下文，再继续处理排队消息。
- 压缩不会改变原始聊天记录的展示顺序。
- 工具调用、工具结果和回复正文会按实际发生顺序恢复，不会在刷新后全部堆到最后一条消息下。
- 中途切换输入框模型只影响下一次发起的请求，不会修改已经运行中的模型调用。

## 数据、工作区与日志

用户数据默认位于：

```text
macOS:
~/Library/Application Support/com.fastagentfactory.app/.agentfactory/

Windows:
%LOCALAPPDATA%\com.fastagentfactory.app\.agentfactory\
```

后端日志：

```text
<应用数据目录>/.agentfactory/logs/backend.log
```

重新安装或升级应用不会主动覆盖已有模型配置、Agent 包、会话和工作区。只有主动清理应用数据或手动删除上述目录时，这些内容才会消失。

如果出现 `Failed to fetch`、后端初始化超时或发布失败，优先查看 `backend.log` 中对应时间的完整异常。

## 架构简介

```text
Tauri 桌面应用
├── Vue 3 前端
├── Rust 桌面进程：单实例、后端生命周期、原生通知与文件操作
└── Python FastAPI + Agent Runtime：模型、工具、会话、工作区与扩展
```

应用启动时由 Rust 进程分配动态本地端口并启动 Python 后端，前端等待 `/health` 就绪后再连接 SSE 事件流。应用退出时会终止对应后端进程树。

桌面版不依赖 Docker。Agent 使用本地子进程、独立工作区、环境锁和共享依赖池进行逻辑隔离。该机制不等同于虚拟机或内核级安全沙箱，不应在未受控主机上运行来源不明的高风险代码。

## 本地开发

环境要求：

- Python `>= 3.11`
- [uv](https://docs.astral.sh/uv/)
- Node.js `>= 18`
- npm
- Rust stable
- Tauri CLI 2

安装依赖：

```bash
uv sync --extra web
npm --prefix web_frontend/frontend ci
```

Web 开发需要分别运行后端和前端：

```bash
uv run --extra web python web_frontend/backend/event_api_server.py
```

```bash
npm --prefix web_frontend/frontend run dev
```

Tauri 开发：

```bash
cd src-tauri
cargo tauri dev
```

## 打包

### macOS

```bash
./scripts/package_macos.sh
```

产物：

```text
src-tauri/target/release/bundle/dmg/FastAgentFactory_<version>_<arch>.dmg
```

### Windows

Windows 构建机需要 Rust、Node.js、Visual Studio 2022 Build Tools、Desktop development with C++ workload、x64 MSVC 工具链和 Windows SDK。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_windows.ps1
```

脚本只生成 x64 NSIS `.exe`，不生成 MSI：

```text
src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis\*.exe
```

完整 Windows 构建日志位于：

```text
build\logs\windows-package.log
```

## 目录结构

```text
FastAgentFactory/
├── agent_factory/          Python Agent 运行时
├── SystemPackage/          内置系统 AgentPackage
├── web_frontend/
│   ├── backend/            FastAPI 后端
│   └── frontend/           Vue 前端
├── src-tauri/              Tauri/Rust 桌面应用
└── scripts/                桌面安装包构建脚本
```

## 安全提示

- 本地逻辑隔离不等同于安全沙箱。
- 未知 MCP 和高风险工具应保留人工批准。
- 不要将模型凭证、MCP Token、应用数据目录或用户工作区提交到 Git。
- 使用来源不明的 AgentPackage 前，应检查依赖、工具权限、脚本和网络访问范围。
