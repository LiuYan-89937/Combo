# FastAgentFactory

FastAgentFactory 是一个 Web 端的 Agent 工厂。你可以用它闲聊、制造新的 Agent、运行已发布 Agent、进化 Agent，并在网页里管理模型池、知识库、定时任务、MCP、Skill 和工作区文件。

项目现在以 Web 前端为主入口，不再推荐通过旧 CLI 交互启动。

## 能做什么

- 闲聊：使用系统内置 `factory_chat` 包进行日常对话、工具调用、附件解析和图片生成。
- 制造 Agent：在「Agent 制造」里用自然语言描述需求，系统会生成可运行的 AgentPackage。
- 运行 Agent：在「已发布 Agent」里初始化、运行、进入子 Agent 会话。
- 进化 Agent：选择一个已发布 Agent 包，进入独立的进化对话。
- 模型池：为子 Agent 维护可选模型，包括主对话模型和辅助图片生成模型。
- 知识库：上传文档或文件夹，配置 RAG 分块和检索后供 Agent 使用。
- 定时任务：给当前闲聊或当前子 Agent 添加自然语言任务，支持 cron、启用、停用和运行记录。
- 附件：支持文件、文本片段、URL、工作区文件、拖拽上传和图片粘贴。
- 工作区：在网页右侧查看运行状态、工作区文件、会话信息和输出产物。

## 环境要求

- Python 3.11+
- Node.js
- npm
- uv
- Docker Desktop 或可用 Docker daemon
- 一个兼容 OpenAI Chat Completions 的文本模型服务
- 一个 embedding 模型服务，用于知识库、RAG 和记忆检索

## 安装

在仓库根目录执行：

```bash
uv sync
```

安装前端依赖：

```bash
cd web_frontend/frontend
npm install
```

复制配置文件：

```bash
cp .env.example .env
```

`.env` 是本地私有配置，不要提交。

## 基础配置

用户通常只需要填写这些模型项：

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

AGENTFACTORY_MAIN_MODEL_MULTIMODAL=false
AGENTFACTORY_MODEL_REASONING=
AGENTFACTORY_MODEL_REASONING_EFFORT=

AGENTFACTORY_MODEL_COMPRESSION_TRIGGER_TOKENS=200000
AGENTFACTORY_MODEL_TEMPERATURE=0.2
AGENTFACTORY_MODEL_TIMEOUT_SECONDS=600
AGENTFACTORY_MODEL_MAX_OUTPUT_TOKENS=8192
AGENTFACTORY_MODEL_MAX_INPUT_TOKENS=1000000
```

说明：

- 主模型用于闲聊、制造和进化的主要对话。
- 任务模型可以和主模型不是同一家供应商。
- 压缩模型用于上下文压缩。
- embedding 模型是必填项，用于知识库、RAG、记忆和语义检索。
- 如果任务模型留空，会继承主模型。
- 如果压缩模型留空，会优先继承任务模型，其次继承主模型。
- 思考模式只应该在对应 provider/model 支持时开启。

完整配置以 [.env.example](.env.example) 为准。

## 启动

一键启动前后端：

```bash
./web_frontend/start.sh
```

启动后访问：

- 前端：http://localhost:3000
- 后端：http://localhost:8000
- 后端健康检查：http://localhost:8000/health

只启动后端：

```bash
./web_frontend/start_backend.sh
```

只启动前端：

```bash
cd web_frontend/frontend
npm run dev
```

`start.sh` 会自动同步 Python 依赖、前端依赖，并检查子 Agent Docker runtime 镜像。

## 推荐使用流程

1. 启动 Web 页面。
2. 在 `.env` 配好闲聊、制造、进化、压缩和 embedding 模型。
3. 打开「模型池」，添加可供子 Agent 使用的模型。
4. 在「闲聊」里测试主模型、附件、工具调用和图片生成。
5. 在「Agent 制造」里描述想要的 Agent。
6. 发布后进入「已发布 Agent」，先初始化实例，再进入子 Agent 对话。
7. 如果需要优化已发布 Agent，进入「Agent 进化」并选择目标包。
8. 在对应对话上下文里管理知识库、定时任务和工作区。

## 支持的文本模型 Provider

文本模型统一走 OpenAI Chat Completions 兼容格式。具体模型名由你在 `.env` 或模型池里填写。

| Provider | 配置值 | 工具调用 | 结构化输出 | 思考模式 | 图片输入 | 音频输入 |
| --- | --- | --- | --- | --- | --- | --- |
| OpenAI Chat Completions | `openai_chat` | 支持 | `json_schema` / `json_mode` / `function_calling` | 当前不启用 | 取决于模型 | 不声明 |
| 通用 OpenAI 兼容服务 | `openai_compatible_chat` | 支持 | `json_mode` / `function_calling` | 不默认启用 | 取决于服务 | 取决于服务 |
| DeepSeek | `deepseek` | 取决于模型 | `json_mode` / `function_calling` | 支持 `reasoning_content` | 不声明 | 不声明 |
| 千问 / 百炼 / DashScope | `qwen` | 取决于模型 | `json_schema` / `json_mode` / `function_calling` | 支持 thinking 参数 | 取决于模型 | 取决于模型 |
| 智谱 / Z.ai GLM | `zhipu` | 取决于模型 | `json_mode` / `function_calling` | 支持 reasoning 参数 | 取决于模型 | 取决于模型 |
| Kimi / Moonshot | `kimi` | 取决于模型 | `json_schema` / `json_mode` / `function_calling` | 支持 reasoning 内容 | 取决于模型 | 不声明 |
| MiniMax | `minimax` | 取决于模型 | `json_mode` / `function_calling` | 支持 adaptive thinking | 取决于模型 | 不声明 |
| 小米 MiMo | `mimo` | 取决于模型 | `json_mode` / `function_calling` | 支持 reasoning 内容 | 取决于模型 | 取决于模型 |
| 腾讯混元 | `hunyuan` | 取决于模型 | `json_mode` / `function_calling` | 当前不声明 | 取决于模型 | 不声明 |

能力说明：

- “取决于模型”表示 adapter 支持该 provider 的协议，但最终能力由你填写的模型决定。
- 开启思考模式前，先确认对应模型确实支持 reasoning/thinking。
- DeepSeek 思考模式下，工具调用轮次需要按厂商规则保留 reasoning 内容。
- 多模态图片输入只在主模型被配置为多模态且模型支持时启用。

## 支持的图片生成 Provider

图片生成模型通过模型池配置，并以系统内置工具暴露给主模型调用。

| Provider | 配置值 | 适用模型 | 文生图 | 图生图 | 图片编辑 | 多图参考 | 批量生成 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI Images | `openai_image` | 如 `gpt-image-2` | 支持 | 支持 | 支持 | 支持 | 支持 |
| 千问 / 万相 | `qwen` | 如 Wanx 系列 | 支持 | 支持 | 支持 | 支持 | 支持 |
| 豆包 Seedream / 火山方舟 | `volcengine_seedream` | Seedream 系列 | 支持 | 支持 | 支持 | 支持 | 支持 |

千问万相也支持这些别名：

- `wanx`
- `dashscope_wanx`
- `aliyun_wanx`

图片生成结果会保存为运行产物，前端可以在对话和工作区里查看。

## 模型池怎么用

`.env` 只负责工厂自身的主模型、任务模型、压缩模型和 embedding 模型。已发布子 Agent 使用模型池。

模型池默认保存在：

```text
.agentfactory/model_pool/factory.sqlite
```

在网页「模型池」里可以：

- 添加供应商凭证。
- 添加文本模型。
- 添加图片生成模型。
- 标注模型能力，例如工具调用、思考模式、图片输入、图片输出。
- 为子 Agent 的主模型或辅助模型工具提供候选模型。

Agent 制造时会根据任务需求选择模型，并把选择结果写入 AgentPackage 的 `contracts/model.json`。包里只保存 `profile_id`、能力需求和选择理由，不保存 API key。

## 附件与知识库

对话附件支持：

- 本地文件上传
- 图片直接粘贴
- 文本片段
- URL
- 工作区文件

附件会被解析成文本或多模态输入，再发送给模型。图片附件在多模态模型可用时可以作为图片输入；否则仍可经过文档解析/OCR 链路提取文本。

知识库支持上传文件和文件夹，并可配置 RAG 分块参数。RAG 主要面向文本文档，不把图片本身直接作为向量内容。

## 定时任务

定时任务按当前上下文分区：

- 在闲聊里创建的是闲聊任务。
- 在某个子 Agent 会话里创建的是该子 Agent 的任务。

任务内容是自然语言任务，也可以让 Agent 通过工具调用创建。任务支持 cron、启用、停用和运行记录。任务完成后会推送通知，点击后回到对应会话查看结果。

## 子 Agent 实例

已发布 Agent 包需要先初始化实例，再进入对话。初始化会准备容器、依赖和运行环境。初始化完成后，子 Agent 可以在后台保持存续，切换到其他会话不会要求当前 Agent 立即停止。

## 本地数据目录

这些目录是本地运行数据，不应该提交：

```text
.agentfactory/
.agent_runtime/
```

常见内容：

- 会话记录
- checkpoint
- trace
- 工作区文件
- 知识库索引
- 定时任务数据库
- 模型池 SQLite
- 子 Agent runtime 产物

## 常用命令

```bash
# 同步 Python 依赖
uv sync

# 一键启动 Web
./web_frontend/start.sh

# 只启动后端
./web_frontend/start_backend.sh

# 前端开发
cd web_frontend/frontend
npm run dev

# 前端类型检查
cd web_frontend/frontend
npm run type-check
```

## 注意事项

- 不要提交 `.env`、API key、模型池数据库或运行产物。
- 不要在包配置里写 API key；子 Agent 应通过模型池的 `profile_id` 解析模型。
- 子 Agent 的知识库、定时任务、工作区和会话都按当前 Agent 分区。
- 如果切换模型后行为异常，先确认模型池里的 provider、base URL、模型名和能力标注是否一致。
- 如果 Docker 初始化失败，先确认 Docker daemon 正常运行。
