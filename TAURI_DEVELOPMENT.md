# Tauri 桌面应用开发指南

## 架构概览

FastAgentFactory 桌面应用基于 Tauri 2.0 架构：

- **前端**：Vue 3 + Vite（`web_frontend/frontend/`）
- **后端**：Python FastAPI（`web_frontend/backend/`）由 Tauri 作为 sidecar 启动
- **原生运行时**：使用 `agent_factory/native_runtime/` 替代 Docker
- **打包**：Rust（Tauri）+ 内嵌 Python 运行时（python-build-standalone）

## 开发环境准备

### 1. 安装 Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
```

### 2. 安装 Tauri CLI

```bash
cargo install tauri-cli --version "^2.0.0"
```

或使用 npm 全局安装：

```bash
npm install -g @tauri-apps/cli@next
```

### 3. 安装前端依赖

```bash
cd web_frontend/frontend
npm install
```

### 4. 安装 Python 依赖

```bash
pip install -e .
```

## 开发模式运行

### 启动开发服务器

在项目根目录执行：

```bash
# 使用 cargo 启动（推荐）
cargo tauri dev

# 或使用 npm
npm run tauri dev  # 需要先在 package.json 添加 script
```

这会：
1. 启动 Vite 开发服务器（前端热重载）
2. 启动 Rust Tauri 应用
3. Tauri 自动启动 Python 后端（使用系统 Python）
4. 打开桌面应用窗口

### 环境变量

开发模式会自动设置：
- `AGENTFACTORY_NATIVE_RUNTIME=1`：启用原生运行时
- `AGENTFACTORY_PORT=8000`：后端监听端口

可通过 `.env` 文件覆盖其他配置。

## 生产构建

### 1. 准备 Python 运行时

下载 python-build-standalone（macOS Apple Silicon 示例）：

```bash
cd src-tauri/resources
wget https://github.com/indygreg/python-build-standalone/releases/download/20240107/cpython-3.12.1+20240107-aarch64-apple-darwin-install_only.tar.gz
mkdir python
tar -xzf cpython-*.tar.gz -C python --strip-components=1
rm cpython-*.tar.gz
```

### 2. 安装 Python 依赖到运行时

```bash
cd ../../  # 回到项目根目录
src-tauri/resources/python/bin/python3 -m pip install -e .
```

### 3. 构建应用

```bash
cargo tauri build
```

生成的安装包位于：
- macOS: `src-tauri/target/release/bundle/dmg/*.dmg`
- Windows: `src-tauri/target/release/bundle/msi/*.msi`
- Linux: `src-tauri/target/release/bundle/appimage/*.AppImage`

## 架构说明

### Rust 入口（`src-tauri/src/main.rs`）

- 启动时通过 `PythonSidecar::spawn()` 启动 Python 后端
- 监听窗口关闭事件，自动清理 Python 进程
- 暴露 `backend_url()` 命令给前端获取 API 地址

### Python Sidecar（`src-tauri/src/python_sidecar.rs`）

- **开发模式**：使用系统 Python（`python3` 或 `python`）
- **生产模式**：使用打包的 `resources/python/bin/python3`
- 自动注入 `AGENTFACTORY_NATIVE_RUNTIME=1` 环境变量
- 启动 uvicorn 运行 FastAPI 后端

### 前端集成

前端通过 Tauri 的 `invoke` API 获取后端地址：

```typescript
import { invoke } from '@tauri-apps/api/core';

const backendUrl = await invoke<string>('backend_url');
// 使用 backendUrl 发起 API 请求
```

## 原生运行时验证

启动后验证原生模式：

```bash
# 检查后端日志确认启动器类型
# 应显示 "Launcher type: NativeAgentRuntimeLauncher"

# 或通过 API 查询
curl http://127.0.0.1:8000/api/runtime/status
```

## 已知问题与限制

1. **端口冲突**：当前硬编码 8000 端口，未来会实现动态端口分配
2. **图标缺失**：开发时使用 Tauri 默认图标，生产构建前需生成图标
3. **多架构支持**：需为不同平台准备对应的 Python 运行时
4. **权限问题**：macOS 首次运行可能需要在"系统设置 > 隐私与安全性"中允许

## 调试技巧

### 查看 Rust 日志

```bash
RUST_LOG=debug cargo tauri dev
```

### 查看 Python 后端日志

后端日志会输出到 Tauri 控制台。

### 前端开发者工具

在应用窗口右键选择"检查元素"或按 `Cmd+Option+I`（macOS）/ `F12`（Windows/Linux）。

## 下一步

- [ ] 实现动态端口分配
- [ ] 添加应用图标
- [ ] 编写 CI/CD 打包流程
- [ ] 支持自动更新
- [ ] Windows 和 Linux 平台测试
