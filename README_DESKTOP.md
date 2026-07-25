# FastAgentFactory 桌面版

FastAgentFactory 是一个跨平台的 AI Agent 开发与运行环境，支持原生进程隔离，无需 Docker。

## 🚀 特性

- **跨平台支持**: macOS (Apple Silicon & Intel)、Windows、Linux
- **原生运行时**: 无需 Docker，使用本地进程隔离
- **低资源占用**: 相比 Docker 模式大幅降低内存和 CPU 使用
- **快速启动**: Agent 启动时间从秒级降至毫秒级
- **桌面应用**: 基于 Tauri 2.0 的原生桌面应用
- **Python 内嵌**: 打包独立的 Python 3.11 运行时，无需系统依赖

## 📦 安装

### macOS

下载 `.dmg` 安装包，拖入 Applications 文件夹即可。

### Windows

下载 `.msi` 安装包，双击安装。

### Linux

下载 `.AppImage` 或 `.deb` 包：
```bash
# AppImage
chmod +x FastAgentFactory.AppImage
./FastAgentFactory.AppImage

# Debian/Ubuntu
sudo dpkg -i fast-agent-factory_*.deb
```

## 🛠️ 开发

### 前置要求

- Node.js 18+
- Rust 1.70+
- Python 3.9+

### 开发模式

```bash
# 1. 克隆仓库
git clone https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory

# 2. 安装前端依赖
cd web_frontend/frontend
npm install
cd ../..

# 3. 安装 Python 依赖
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 4. 安装 Tauri CLI
cargo install tauri-cli

# 5. 启动开发服务器
cd src-tauri
cargo tauri dev
```

### 生产构建

```bash
# 1. 打包 Python 运行时
python3 scripts/bundle_python.py

# 2. 生成应用图标
pip install Pillow
python3 scripts/generate_icons.py

# 3. 构建应用
cd src-tauri
cargo tauri build
```

生成的安装包位于 `src-tauri/target/release/bundle/`。

## 📖 使用文档

### 创建 Agent

1. 点击"创建 Agent"按钮
2. 选择模型和工具
3. 配置 Agent 参数
4. 保存并运行

### 配置模型

在"模型池"页面添加你的 API 密钥：
- OpenAI
- Anthropic Claude
- 本地模型（Ollama 等）

### 安装工具

在"扩展"页面安装 MCP (Model Context Protocol) 服务器：
- 文件系统工具
- 网络搜索工具
- 数据库工具
- 自定义工具

## 🔧 技术架构

```
┌─────────────────────────────────────┐
│   Tauri Desktop App (Rust)          │
│   ┌───────────────────────────┐     │
│   │  Vue.js Frontend          │     │
│   │  (Port 5173)              │     │
│   └───────────────────────────┘     │
│              ↕                       │
│   ┌───────────────────────────┐     │
│   │  Python Backend           │     │
│   │  FastAPI + uvicorn        │     │
│   │  (Port 8000)              │     │
│   └───────────────────────────┘     │
│              ↕                       │
│   ┌───────────────────────────┐     │
│   │  Native Agent Runtime     │     │
│   │  (子进程隔离)              │     │
│   └───────────────────────────┘     │
└─────────────────────────────────────┘
```

- **前端**: Vue 3 + TypeScript + Vite
- **后端**: Python FastAPI + LangGraph
- **桌面框架**: Tauri 2.0 (Rust)
- **运行时**: Python 3.11 (python-build-standalone)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [Tauri](https://tauri.app/) - 桌面应用框架
- [python-build-standalone](https://github.com/indygreg/python-build-standalone) - Python 独立构建
- [LangGraph](https://github.com/langchain-ai/langgraph) - Agent 框架
