# FastAgentFactory

FastAgentFactory 是一个 Web-first 的 Agent 工厂系统。它把日常对话、Agent 制造、已发布 Agent 运行、Agent 进化、模型池、知识库、定时任务、MCP/Skill 扩展和运行工作区放在同一个可视化前端里管理。

## 核心能力

- **闲聊助手**：内置 `factory_chat` 系统包，支持普通对话、工具调用、附件解析、图片输入和图片生成工具。
- **Agent 制造**：用自然语言描述目标，系统会分析任务、选择模式、装配工具/Skill/知识库/模型，并生成可发布的 AgentPackage。
- **已发布 Agent 运行**：每个 AgentPackage 拥有独立会话、工作区、知识库、定时任务、MCP/Skill 配置和运行实例。
- **Agent 进化**：选择一个已发布 AgentPackage，在独立进化上下文里进行改造、验证和重新发布。
- **模型池**：集中管理子 Agent 可选模型，记录模型能力、价格、供应商、密钥凭证和用量统计。
- **多模态与图片生成**：主模型可配置图片输入；图片生成模型可作为系统内置工具暴露给 Agent 使用。
- **知识库与 RAG**：支持上传文档/文件夹，解析成文本后进行分块、索引、检索和挂载。
- **定时任务**：按当前上下文分区管理。闲聊有闲聊任务表，子 Agent 有自己的任务表。
- **跨会话记忆**：按 Agent/系统包写入和检索高置信度长期记忆，并在右侧状态栏展示。
- **工作区预览**：右侧工作区可浏览运行文件、产物、附件和输出内容。
- **权限控制**：工具调用支持粗粒度审批模式和细粒度工具风险配置。

## 快速开始

### 1. 准备环境

需要安装：

- Python `>= 3.11`
- Node.js `>= 18`
- npm
- uv
- Docker Desktop 或可用 Docker daemon
- 可用的文本模型服务
- 可用的 embedding 模型服务

### 2. 配置环境变量

复制配置模板：

```bash
cp .env.example .env
```

填写 `.env` 中的模型配置。`.env` 是本地私有文件，不要提交到 git。

最小可运行配置包括：

```bash
AGENTFACTORY_MODEL_PROVIDER=openai_compatible_chat
AGENTFACTORY_MODEL_BASE_URL=
AGENTFACTORY_MODEL_API_KEY=
AGENTFACTORY_MAIN_MODEL=

AGENTFACTORY_TASK_MODEL_PROVIDER=
AGENTFACTORY_TASK_MODEL_BASE_URL=
AGENTFACTORY_TASK_MODEL_API_KEY=
AGENTFACTORY_TASK_MODEL=

AGENTFACTORY_COMPRESSION_MODEL_PROVIDER=
AGENTFACTORY_COMPRESSION_MODEL_BASE_URL=
AGENTFACTORY_COMPRESSION_MODEL_API_KEY=
AGENTFACTORY_COMPRESSION_MODEL=

AGENTFACTORY_EMBEDDING_PROVIDER=openai_compatible
AGENTFACTORY_EMBEDDING_BASE_URL=
AGENTFACTORY_EMBEDDING_API_KEY=
AGENTFACTORY_EMBEDDING_MODEL=
AGENTFACTORY_EMBEDDING_DIMS=
```

说明：

- 主模型用于闲聊、制造和进化的主对话链路。
- 任务模型用于结构化分析、分类、抽取等辅助任务。
- 压缩模型用于上下文压缩。
- embedding 模型用于知识库、RAG、跨会话记忆和语义检索。
- 任务模型和压缩模型可以与主模型使用不同供应商、base URL 和 API key。
- 如果任务/压缩模型的 provider、base URL、API key 为空，会按代码默认从上一级模型继承；建议生产使用时显式填写模型名。

更多配置见 [.env.example](.env.example)。

### 3. 启动项目

在仓库根目录运行：

```bash
./start.sh
```

启动脚本会完成这些检查和准备：

- 检查 `.env` 是否存在，并提示缺失的关键模型配置。
- 通过 `uv sync --extra web` 同步 Python 后端依赖。
- 检查前端 `node_modules`，必要时执行 `npm ci` 或 `npm install`。
- 检查 Docker daemon。
- 检查子 Agent 运行时镜像 `agentfactory-runtime-python:3.12`。
- 如果镜像不存在，会使用 [docker/agent-runtime/Dockerfile](docker/agent-runtime/Dockerfile) 自动构建。
- 启动后端服务和 Vite 前端开发服务。

启动成功后访问：

- 前端：[http://localhost:3000](http://localhost:3000)
- 后端：[http://localhost:8000](http://localhost:8000)
- 健康检查：[http://localhost:8000/health](http://localhost:8000/health)

## 常用命令

```bash
# 一键启动前后端
./start.sh

# 只启动后端
./web_frontend/start_backend.sh

# 只启动前端
cd web_frontend/frontend
npm run dev

# 同步 Python 依赖
uv sync --extra web

# 前端类型检查
cd web_frontend/frontend
npm run type-check

# 构建前端
cd web_frontend/frontend
npm run build
```

## 推荐工作流

### 闲聊

1. 配好 `.env` 中的主模型和 embedding 模型。
2. 运行 `./start.sh`。
3. 进入「闲聊」。
4. 测试普通对话、附件上传、工具调用、图片输入或图片生成。
5. 在右侧状态栏查看上下文窗口、跨会话记忆、工具状态和运行信息。

闲聊的资源作用域是系统包 `factory_chat`。它拥有自己的会话、工作区、知识库、定时任务和记忆。

### 制造 Agent

1. 打开「模型池」，添加可供子 Agent 使用的文本模型和图片生成模型。
2. 进入「Agent 制造」。
3. 用自然语言描述目标 Agent。
4. 系统会分析任务，选择运行模式，装配工具、Skill、知识库和模型绑定。
5. 通过验证后，按页面确认发布。
6. 发布结果会出现在「已发布 Agent」。

AgentPackage 会保存模型 `profile_id`、工具配置、Skill 配置、知识库配置和运行契约，不保存 API key。

### 运行已发布 Agent

1. 进入「已发布 Agent」。
2. 点击初始化，启动并准备该 Agent 的运行实例。
3. 初始化完成后进入 Agent 会话。
4. 右侧工作区会切换到当前 Agent 的运行空间。
5. 当前 Agent 的知识库、定时任务、MCP/Skill 和会话记录都与其他 Agent 隔离。

### 进化 Agent

1. 进入「Agent 进化」。
2. 选择要进化的已发布 AgentPackage。
3. 描述修改目标。
4. 进化过程使用独立会话和上下文。
5. 完成后可重新发布新版本。

从「已发布 Agent」列表点击进化，也会进入同一个进化入口并自动选择目标包。

## 模型配置

### `.env` 模型

`.env` 只负责工厂自身运行所需的基础模型：

- 主模型：闲聊、制造、进化的主对话。
- 任务模型：结构化输出、分类、抽取、意图分析等辅助任务。
- 压缩模型：上下文压缩。
- embedding 模型：知识库、RAG、记忆和语义检索。

### 模型池

模型池用于子 Agent。默认存储位置：

```text
.agentfactory/model_pool/factory.sqlite
```

模型池支持：

- 供应商凭证管理。
- 文本模型管理。
- 图片生成模型管理。
- 能力标注，例如工具调用、思考模式、图片输入、图片输出、语音能力。
- 价格信息和用量统计。
- 按模型、供应商、Agent 查看 token 消耗和估算费用。

子 Agent 调用模型时通过 `profile_id` 从模型池解析真实凭证。凭证不会写入 AgentPackage。

### 对话中切换模型

聊天输入框旁可以切换主模型。切换只影响下一次发送的消息，不会改变已经在运行中的回复。

模型用量按每次真实模型调用记录，包含：

- `model_profile_id`
- provider
- model name
- agent id
- session id
- request id
- input/output/reasoning/cache tokens

因此中途切换模型后，按「模型」统计会分开；按「Agent」统计会合并到同一个 Agent。

## 支持的文本模型 Provider

文本模型经过统一模型协议层适配。总体遵循 OpenAI 风格的消息、工具调用、结构化输出和多模态输入抽象；不同供应商的差异由 adapter 处理。

| Provider | 配置值 | 协议形态 | 工具调用 | 结构化输出 | 思考模式 | 图片输入 |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI Chat Completions | `openai_chat` | Chat Completions | 支持 | 支持 | 按模型能力 | 按模型能力 |
| OpenAI 兼容服务 | `openai_compatible_chat` | Chat Completions 兼容 | 按服务能力 | 支持 | 按服务能力 | 按服务能力 |
| Anthropic Claude | `anthropic` | Messages API | 按模型能力 | 支持 | 支持 | 按模型能力 |
| DeepSeek | `deepseek` | OpenAI 兼容 | 按模型能力 | 支持 | 支持 `reasoning_content` | 按模型能力 |
| 千问 / 百炼 / DashScope | `qwen` | OpenAI 兼容 | 按模型能力 | 支持 | 按模型能力 | 按模型能力 |
| 智谱 / Z.ai GLM | `zhipu` | OpenAI 兼容 | 按模型能力 | 支持 | 按模型能力 | 按模型能力 |
| Kimi / Moonshot | `kimi` | OpenAI 兼容 | 按模型能力 | 支持 | 按模型能力 | 按模型能力 |
| MiniMax | `minimax` | OpenAI 兼容 | 按模型能力 | 支持 | 按模型能力 | 按模型能力 |
| 小米 MiMo | `mimo` | OpenAI 兼容 | 按模型能力 | 支持 | 按模型能力 | 按模型能力 |
| 腾讯混元 | `hunyuan` | OpenAI 兼容 | 按模型能力 | 支持 | 按模型能力 | 按模型能力 |

注意：

- 表中的“按模型能力”表示协议层支持该方向，但最终是否可用取决于你配置的具体模型。
- DeepSeek 思考模式下，工具调用轮次需要按供应商要求回传 reasoning 内容。
- 图片输入需要同时满足：前端上传了图片、主模型配置为多模态、模型本身支持图片输入。

## 支持的图片生成 Provider

图片生成模型通过模型池添加，并作为系统内置模型工具暴露给主模型调用。

| Provider | 配置值 | 文生图 | 图生图 | 图片编辑 | 多图参考 | 批量生成 |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI Images | `openai_image` | 支持 | 支持 | 支持 | 支持 | 支持 |
| 千问 / 万相 | `qwen` | 支持 | 支持 | 支持 | 支持 | 支持 |
| 豆包 Seedream / 火山方舟 | `volcengine_seedream` | 支持 | 支持 | 支持 | 支持 | 支持 |

千问万相还支持这些别名：

- `wanx`
- `dashscope_wanx`
- `aliyun_wanx`

生成结果会保存为运行产物，可在对话和工作区中查看。

## 附件

对话附件支持：

- 本地文件上传。
- 批量附件上传，单次消息最多 9 个附件。
- 图片直接粘贴到输入框。
- 文本片段。
- URL。
- 工作区文件。

附件会进入统一导入链路：

1. 保存到当前 Agent/闲聊工作区。
2. 解析为文本、文件引用或图片输入。
3. 文本内容随用户消息发送给模型。
4. 图片在多模态主模型可用时作为图片输入；否则仍可走文档解析/OCR 类链路。

## 知识库与 RAG

知识库按当前上下文分区：

- 闲聊知识库属于 `factory_chat`。
- 子 Agent 知识库属于对应 AgentPackage。
- 进化上下文使用自己的目标包和进化会话上下文。

支持能力：

- 上传文件。
- 上传文件夹。
- 文档解析为文本。
- RAG 分块参数配置。
- 文档列表、检索、重建索引和删除。

RAG 主要面向文本内容。图片可以通过解析/OCR 转成文本，但图片本身不直接参与向量索引。

## 定时任务

定时任务也按当前上下文分区：

- 在闲聊里创建的是 `factory_chat` 的任务。
- 在子 Agent 会话里创建的是该 Agent 的任务。

任务支持：

- cron 表达式。
- 自然语言任务内容。
- 启用/停用。
- 手动立即运行。
- 运行记录。
- 完成通知。
- 点击通知跳转回对应会话查看结果。

Agent 也可以通过工具调用创建定时任务，和前端手动创建走同一套后端逻辑。

## MCP、Skill 与 SkillHUB

系统支持在 Web 端管理 MCP 和 Skill：

- 新增、编辑、启用、停用、删除 MCP。
- 测试 MCP 连接。
- 新增、编辑、启用、停用、删除 Skill。
- 通过 SkillHUB 搜索并安装 Skill。
- 将 Skill 安装到当前 Agent 的扩展目录并启用。
- 对系统内置工具和扩展工具配置审批策略。

SkillHUB 可执行程序是全局安装依赖，子 Agent 使用方式与全局 MCP 实例类似，由运行时桥接。

## 工具权限

工具权限分为两层：

- 粗粒度模式：严格审批、高风险以下自动放行、全部自动放行。
- 细粒度配置：每个 Agent 可以单独调整工具风险等级和审批策略。

建议默认使用中间档：高风险工具需要确认，低/中风险工具自动放行。涉及文件写入、命令执行、网络操作、删除操作时，应根据实际风险提高审批等级。

## 工作区与运行数据

FastAgentFactory 会在本地生成运行数据。默认目录：

```text
.agentfactory/
.agent_runtime/
```

常见内容：

- 会话记录。
- checkpoint。
- trace。
- 工作区文件。
- 附件导入文件。
- 知识库索引。
- 定时任务数据库。
- 模型池 SQLite。
- 子 Agent 运行产物。

这些目录是本地运行状态，不应提交到 git。

## Web API 概览

后端服务默认运行在 `http://localhost:8000`。

主要 API 分组：

- `/api/runtime`：运行时事件、命令和状态。
- `/api/agent-packages`：已发布 Agent 包、实例和会话。
- `/api/model-pool`：模型池、凭证、模型配置和用量统计。
- `/api/workspace`：工作区根目录、文件列表、文件读取和原始文件预览。
- `/api/knowledge`：知识源、文档、检索和索引。
- `/api/scheduler`：定时任务、运行记录和立即运行。
- `/api/extensions`：MCP、Skill、工具权限。
- `/api/memory`：跨会话记忆查询和删除。

前端通过 HTTP API 和 SSE 事件流与后端通信。适合普通请求的能力走 HTTP；运行事件、流式回复、工具审批和状态更新走事件流。

## 开发说明

后端：

- Python 包位于 [agent_factory](agent_factory)。
- Web API 位于 [web_frontend/backend](web_frontend/backend)。
- 依赖由 `uv` 管理。

前端：

- Vue 3 + Vite + Pinia。
- 页面和组件位于 [web_frontend/frontend/src](web_frontend/frontend/src)。
- UI 组件基于 Naive UI。
- Markdown、代码块、LaTeX、Mermaid 和图表渲染由前端渲染管线处理。

常用检查：

```bash
python -m py_compile path/to/file.py

cd web_frontend/frontend
npm run type-check
```

如果只改文档，不需要运行前后端。

## 排障

### `.env` 缺少配置

`./start.sh` 会提示缺失的关键变量。服务仍可能启动，但模型调用、RAG、记忆或知识库可能失败。

处理方式：

1. 复制 `.env.example` 到 `.env`。
2. 填写主模型、任务模型、压缩模型和 embedding 模型。
3. 重新运行 `./start.sh`。

### Docker daemon 不可用

报错通常说明 Docker Desktop 没启动，或当前 shell 找不到 `docker`。

处理方式：

1. 启动 Docker Desktop。
2. 确认 `docker info` 可用。
3. 重新运行 `./start.sh`。

### 运行时镜像缺失

`./start.sh` 会自动构建默认镜像：

```text
agentfactory-runtime-python:3.12
```

如需指定镜像名：

```bash
AGENTFACTORY_RUNTIME_IMAGE=your-image:tag ./start.sh
```

### 前端依赖缺失

如果 `node_modules` 存在但 Vite 不可用，启动脚本会自动执行 `npm install`。也可以手动执行：

```bash
cd web_frontend/frontend
npm install
```

### 子 Agent 初始化后仍无法对话

检查：

- AgentPackage 是否已初始化完成。
- Docker daemon 是否正常。
- 模型池中的模型凭证是否启用。
- AgentPackage 的 `contracts/model.json` 是否引用了存在且启用的 `profile_id`。
- 后端日志和该 Agent 的 trace。

### 思考模式报错

思考模式依赖供应商规则。尤其是 DeepSeek 工具调用链路需要在后续请求中回传必要 reasoning 内容。

处理方式：

- 确认模型确实支持 reasoning/thinking。
- 确认 provider 配置正确。
- 关闭思考模式后复现，判断是否为 provider 规则问题。

## 安全与数据边界

- AgentPackage 中应保存模型 `profile_id` 和能力要求，不应保存真实密钥。
- 删除会话会连带清理对应 trace/checkpoint 等运行记录。
- 工具审批策略应按任务风险调整，不建议长期对未知工具全部自动放行。

## 当前定位

FastAgentFactory 适合本地开发和个人/团队内部 Agent 生产实验。它强调：

- Web-first 的使用体验。
- 可复现的 AgentPackage 运行结构。
- Agent、知识库、定时任务、工作区和记忆的上下文隔离。
- 面向多供应商模型的协议适配。
- 面向真实工作流的工具、文件、知识库和调度能力。
