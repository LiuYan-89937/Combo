# Combo

本地优先、跨平台的动态 Agent 运行时桌面应用。

Combo 以一条统一主对话链为产品入口。每次请求从模型池解析模型策略，从 Skill、工具、MCP 和依赖四个能力池冻结不可变能力快照，再由固定的 React 或 Plan-and-Execute 图执行。系统不再制造、发布或运行独立 Agent 包，也不通过可变全局注册表决定一次运行的能力边界。

> 当前仓库正在完成动态运行时重构。旧的目录包与多入口产品链已移除；能力控制面、记忆、知识库和调度链仍以 `docs/DYNAMIC_AGENT_RUNTIME_REFACTOR.md` 为验收依据。

## 核心模型

- 一条主对话链：用户始终与主 Agent 交互。
- 两张固定执行图：React 负责快速执行，Plan-and-Execute 负责显式计划与步骤推进。
- 统一能力控制面：Skill、工具、MCP 和依赖共用草稿、验证、版本、索引、激活、健康与快照协议；模型池独立解析模型策略。
- 不可变运行快照：请求开始后，能力版本、模型策略和运行身份不再随控制面变化。
- 动态运行身份：以 principal、request、runtime instance、attempt、session、turn、workspace 和 task revision 表达归属。
- 单一工作区边界：文件、进程、浏览器、调度任务和可恢复状态都绑定到工作区或运行实例。
- 统一观测账本：事件、提交记录和模型用量使用动态运行时身份，不保留 Agent 或 Package 维度。

## 安装

### macOS

在 Apple Silicon Mac 上下载 `aarch64` `.dmg`，打开镜像后将 Combo 拖入 `Applications`。当前不提供 Intel Mac 安装包。

### Windows

下载 Windows x64 的 NSIS `.exe` 安装程序。正式构建目标为 `x86_64-pc-windows-msvc`，不是原生 ARM64 发行版。

桌面安装包包含前端、Python 后端和基础运行依赖。只有用户发布的能力明确依赖外部命令时，才需要在主机上另行准备对应运行环境。

## 使用入口

### 模型与凭据

进入「模型与凭据」后：

1. 创建供应商凭据，配置 Base URL 和 API Key。
2. 创建模型 Profile，声明模型名称、输入模态、工具调用和结构化输出能力。
3. 完成连接验证并启用 Profile。
4. 在主对话中选择主模型和执行策略。

模型调用只使用请求开始时冻结的 Profile 快照。模型用量在供应商返回真实 usage 后写入运行事务账本。

### 统一对话

新建或打开会话，选择运行策略与审批模式后发送消息。`auto` 策略由主运行时在 React 和 Plan-and-Execute 之间路由；显式策略则固定使用相应执行图。

每次请求都会生成新的 runtime instance 和 attempt，并记录对应的 task revision。控制面在请求执行期间发生的发布、激活或撤销不会改变该请求已经冻结的能力集合。

## 数据与工作区

用户数据默认位于：

```text
macOS:
~/Library/Application Support/com.fastagentfactory.app/.agentfactory/

Windows:
%LOCALAPPDATA%\com.fastagentfactory.app\.agentfactory\
```

后端日志位于：

```text
<应用数据目录>/.agentfactory/logs/backend.log
```

重新安装或升级应用不会主动删除已有会话、运行记录、模型配置或工作区。主动清理应用数据前应先备份需要保留的内容。

## 架构

```text
Tauri 桌面应用
├── Vue 3：统一对话与控制面
├── Rust：单实例、后端生命周期、原生通知与文件操作
└── Python FastAPI
    ├── Dynamic Runtime：身份、策略、快照、执行与提交
    ├── Runtime Kernel：固定 React / Plan-and-Execute 图
    ├── Capability Stores：模型、工具、资源与依赖
    ├── Workspace Runtime：文件、进程和浏览器资源
    └── Model Pool：凭据、Profile 与调用适配
```

Rust 进程启动 Python 后端并分配动态本地端口，前端等待 `/health` 就绪后连接事件流。应用退出时终止其负责的后端进程树。

工作区与子进程隔离是应用级逻辑边界，不等同于虚拟机或内核级安全沙箱。高风险工具和外部能力仍需遵守审批、租约和网络出口策略。

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

分别启动 Web 后端和前端：

```bash
uv run --extra web python web_frontend/backend/event_api_server.py
```

```bash
npm --prefix web_frontend/frontend run dev
```

启动 Tauri 开发环境：

```bash
cd src-tauri
cargo tauri dev
```

## 打包

### macOS

```bash
./scripts/package_macos.sh
```

更新签名私钥默认读取自 `~/.fastagentfactory/updater/fastagentfactory.key`。该文件不得提交到仓库，也不能在不同平台构建中使用不一致的密钥。

### Windows

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\package_windows.ps1
```

Windows 脚本生成 x64 NSIS 安装包。完整构建日志位于 `build/logs/windows-package.log`。

## 目录结构

```text
Combo/
├── agent_factory/          Python 动态运行时与固定执行图
├── web_frontend/
│   ├── backend/            FastAPI 应用装配与 HTTP API
│   └── frontend/           Vue 统一对话与控制面
├── src-tauri/              Tauri/Rust 桌面进程
├── services/agent_hub/     官网、OAuth 与桌面版本发布服务
├── docs/                   架构和重构规范
└── scripts/                审计与桌面构建脚本
```

`services/agent_hub` 只负责官网、GitHub OAuth、桌面版本、更新日志和安装包分发，不保存或分发运行时能力。

## 安全提示

- 不要将模型凭据、访问令牌、应用数据目录或用户工作区提交到 Git。
- 外部 MCP、Skill、进程和网络能力必须经过发布校验，并在运行时受快照、租约和审批约束。
- 本地逻辑隔离不能代替操作系统沙箱。
- 不可信代码或依赖应在受控环境中检查后再发布为能力。

## 重构规范

动态运行时的身份模型、控制面协议、事务边界和完成门槛见 [`docs/DYNAMIC_AGENT_RUNTIME_REFACTOR.md`](docs/DYNAMIC_AGENT_RUNTIME_REFACTOR.md)。
