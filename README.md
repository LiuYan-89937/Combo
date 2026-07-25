# FastAgentFactory

FastAgentFactory 是一个本地优先、桌面优先的 Agent 工厂。它把模型配置、Agent 制造与进化、知识库、MCP/Skill、工具权限、工作区、定时任务、长期记忆和多 Agent 协作放在同一个应用中。

![FastAgentFactory 对话工作台](readme-assets/images/chat.png)

## 核心能力

| 能力 | 说明 |
| --- | --- |
| Factory Chat | 内置系统对话包，支持流式回复、工具调用、附件、图片输入和图片生成。 |
| Agent 制造 | 从自然语言目标生成可验证、可发布的 AgentPackage。 |
| Agent 进化 | 在独立上下文中修改已有 AgentPackage，并重新验证和发布。 |
| 已发布 Agent | 为每个 Agent 提供独立会话、工作区、知识库、记忆、定时任务和扩展。 |
| 多 Agent 协作 | 由主 Agent 拆分任务、声明依赖、调度子 Agent、验收和汇总交付物。 |
| 模型池 | 管理文本模型、图片模型、供应商凭证、能力标签、上下文限制和用量。 |
| 知识库 | 导入文件或目录，完成解析、分块、索引、检索和上下文挂载。 |
| 扩展系统 | 添加本地或远程 MCP、Skill 和 SkillHUB 能力，并配置工具风险策略。 |
| 可观察运行时 | 查看事件流、工具调用、审批、trace、checkpoint、工作区文件和产物。 |

## 当前架构

```text
Tauri 2 Desktop
├── Vue 3 + TypeScript + Vite
├── Rust process supervisor
│   ├── 分配动态本地端口
│   ├── 启动 Python sidecar
│   └── 应用退出时终止后端
└── Python FastAPI + Agent Runtime
    ├── RuntimeKernel / LangGraph
    ├── 本地依赖池
    ├── 独立运行工作区
    ├── Model Pool
    └── MCP / Skill / Knowledge / Memory
```

桌面版不依赖 Docker。AgentPackage 使用本地子进程、独立工作区和依赖环境进行逻辑隔离。该边界用于依赖复用、路径约束和运行状态隔离，不应被描述为虚拟机或内核级安全沙箱；不可信代码仍应在受控主机上运行。

前端不会假设后端固定监听 `8000`。Tauri 启动时分配空闲回环端口，前端通过 Tauri command 获取实际地址，并在 `/health` 就绪前显示初始化界面，之后才建立 SSE 事件流。

## 桌面版安装

### macOS

1. 下载与处理器架构匹配的 `.dmg`。
2. 打开安装包，将 FastAgentFactory 拖入 `Applications`。
3. 首次启动后进入「模型池」配置凭证和模型。

安装包已经包含 Python 后端及运行依赖，不要求用户额外安装 Python、Node.js 或 Docker。只有当你主动添加以 `npx`、`uvx` 等命令启动的本地 MCP 时，才需要安装对应的外部命令；远程 Streamable HTTP/SSE MCP 不需要这些本地运行器。

Windows 和 Linux 代码路径已纳入跨平台结构，但发行包仍应分别在对应系统上完成构建和验收。不要用 macOS 构建成功代替其他平台验证。

## 首次配置

### 1. 配置模型池

进入「模型池」，依次添加：

1. 供应商凭证：Base URL、API Key。
2. 模型 Profile：模型名、输入输出模态、工具调用、结构化输出、推理和上下文限制。
3. 使用「测试连接」确认该 Profile 可调用。

![模型池](readme-assets/images/model-pool.png)

Factory Chat、Agent 制造、Agent 进化以及平台内部的任务/压缩调用均从模型池或当前请求选择模型，不再读取主模型、任务模型、压缩模型和图片模型的 env 配置。

没有符合能力要求的文本模型时，系统对话输入区会保持禁用并提示先配置模型。图片模型是可选能力；没有匹配的图片 Profile 不影响普通文本对话。

### 2. 初始化系统 Agent

进入「已发布 Agent」并初始化 **Factory Chat**。首次初始化需要准备本地运行目录和依赖环境，耗时可能高于后续启动。

应用刚启动时，前端会等待后端健康检查。此时显示“正在初始化”，不会提前连接事件流。

### 3. 按需添加 MCP

系统不再预装网页搜索 MCP，也不会自动启动 SearXNG 或 Docker 容器。进入「扩展管理」可以添加：

- `stdio`：本地命令，例如 `npx`、`uvx` 或自有可执行文件。
- `streamable_http`：远程 Streamable HTTP MCP。
- `sse`：远程 SSE MCP。

例如 Tavily 官方远程 MCP：

```json
{
  "mcpServers": {
    "tavily": {
      "transport": "streamable_http",
      "url": "https://mcp.tavily.com/mcp/",
      "headers": {
        "Authorization": "Bearer tvly-你的API密钥"
      },
      "timeout_seconds": 60,
      "risk_level_default": "medium",
      "enabled": true
    }
  }
}
```

在「添加 MCP 服务器」的导入模式粘贴配置，然后执行“测试并添加”。MCP Header 当前保存在本机扩展配置中，不要提交、分享或截图暴露真实密钥。

## 推荐工作流

### 制造 Agent

进入「Agent 制造」，描述用途、输入、输出、工具边界和验收标准。制造流程会分析需求并装配模型、工具、Skill、知识库和运行契约。

![Agent 制造](readme-assets/images/agent-authoring.png)

AgentPackage 保存模型 `profile_id` 和能力要求，不保存模型池中的真实 API Key。

### 运行 Agent

进入「已发布 Agent」，选择并初始化 Agent。每个会话拥有独立工作区，可以接收附件、调用工具、生成文件并展示结构化产物。

![已发布 Agent](readme-assets/images/agent-marketplace.png)

### 进化 Agent

进入「Agent 进化」，选择目标 AgentPackage 并描述需要改变的行为。进化会话与普通运行会话分离。

![Agent 进化](readme-assets/images/agent-evolution.png)

### 多 Agent 协作

主 Agent 可以检索合适的已发布 Agent，创建带依赖关系的任务，并在子 Agent 交付后继续验收或推进。

![多 Agent 协作](readme-assets/images/collaboration.png)

### 知识库与扩展

知识源按系统对话或 AgentPackage 上下文隔离。扩展也可以按目标范围安装和启用。

![知识库](readme-assets/images/knowledge-base.png)

![扩展管理](readme-assets/images/extensions.png)

## 数据与安全边界

- 桌面生产环境将用户状态写入系统应用数据目录，不把仓库中的 `.agentfactory` 历史数据打入安装包。
- 开发模式默认使用仓库下的 `.agentfactory/` 和 `.agent_runtime/`。
- 模型池凭证保存在本地模型池存储中；AgentPackage 只引用 Profile。
- MCP `env` 和 `headers` 属于本地扩展配置，当前不等同于模型池加密凭证。
- 工作区路径限制属于应用层逻辑隔离，不是恶意代码安全沙箱。
- 高风险工具应保留人工确认，不建议对未知 MCP 长期使用全部自动放行。
- 删除会话时会清理与该会话关联的 checkpoint、trace 和运行记录。

## 本地开发

### 环境要求

- Python `>= 3.11`
- [uv](https://docs.astral.sh/uv/)
- Node.js `>= 18`
- npm
- Rust stable
- Tauri 2 CLI

### 安装依赖

```bash
uv sync --extra web

cd web_frontend/frontend
npm install
```

### Web 开发模式

```bash
./start.sh
```

默认地址：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8000`
- 健康检查：`http://127.0.0.1:8000/health`

### Tauri 开发模式

```bash
cd src-tauri
cargo tauri dev
```

开发模式优先使用仓库 `.venv/bin/python`。生产模式使用 `src-tauri/resources/python` 中的内置 Python。

## 构建桌面安装包

首次准备内置 Python：

```bash
python3 scripts/bundle_python.py
```

生成图标：

```bash
python3 scripts/generate_icons.py
```

构建：

```bash
cd src-tauri
cargo tauri build
```

构建产物位于：

```text
src-tauri/target/release/bundle/
```

Tauri 构建前会清理准备打包的 Python 源码缓存，避免将旧 `__pycache__` 和已删除模块的 `.pyc` 带入安装包。

### 跨平台终端

运行期统一暴露 `shell`、`shell_status` 和 `shell_stop` 工具。macOS/Linux 后端使用
PATH 中的 Bash，Windows 后端优先使用 PowerShell 7（`pwsh`），并回退到系统自带的
Windows PowerShell。后台命令由同一平台后端负责整棵进程树的查询与终止。

旧 AgentPackage 中的 `bash`、`bash_status` 和 `bash_stop` 契约会在加载时统一迁移到
新的 `shell` 能力，不会注册或维护第二套执行实现。

## 静态检查

本项目不应通过运行特化 Agent 示例来代替常规构建检查。按变更范围选择：

```bash
# Python 语法
python3 -m compileall -q agent_factory web_frontend/backend

# Rust
cd src-tauri
cargo fmt --check
cargo check

# 前端生产构建
cd web_frontend/frontend
npx vite build

# Diff 格式
git diff --check
```

当前仓库的旧版 `vue-tsc` 与部分较新 Node.js/TypeScript 组合存在 `supportedTSExtensions` 兼容问题。该错误发生在项目类型检查开始前；升级工具链前，应将 `npx vite build` 与 Python/Rust 检查结果分别记录，不要把工具链错误误判为业务代码错误。

## 目录结构

```text
FastAgentFactory/
├── agent_factory/                 Python Agent 运行时与平台能力
├── SystemPackage/                 内置系统 AgentPackage
├── web_frontend/
│   ├── backend/                   FastAPI 后端
│   └── frontend/                  Vue 前端
├── src-tauri/                     Tauri/Rust 桌面壳与打包配置
├── scripts/                       Python 运行时、图标和构建准备脚本
└── readme-assets/                 README 图片
```

## 主要 API

- `/api/commands`：前端命令入口。
- `/api/model-pool`：凭证、模型 Profile、选择、连接测试和用量。
- `/api/agent-packages`：AgentPackage、实例和会话。
- `/api/workspace`：工作区文件与产物。
- `/api/knowledge`：知识源、索引和检索。
- `/api/extensions`：MCP、Skill 和权限。
- `/api/memory`：长期记忆。
- `/api/scheduler`：定时任务。
- `/api/collaboration`：多 Agent 协作。
- `/health`：后端健康检查。

普通请求使用 HTTP；流式回复、工具审批、状态和运行事件使用 SSE。

## 项目定位

FastAgentFactory 面向本地开发、个人工作流和团队内部 Agent 工程实验。它提供的是完整的 Agent 生命周期工作台，而不是只封装一次模型请求的聊天界面。
