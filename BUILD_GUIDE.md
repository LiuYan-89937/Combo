# FastAgentFactory 构建指南

本文档说明如何从源代码构建 FastAgentFactory 桌面应用。

## 环境准备

### 所有平台通用

1. **Node.js 18+**
   ```bash
   node --version  # 应该 >= 18.0.0
   ```

2. **Rust 1.70+**
   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   rustc --version  # 应该 >= 1.70.0
   ```

3. **Python 3.9+**
   ```bash
   python3 --version  # 应该 >= 3.9.0
   ```

### macOS 特定要求

```bash
# Xcode Command Line Tools
xcode-select --install

# 安装依赖
brew install pkg-config
```

### Windows 特定要求

1. 安装 [Visual Studio 2022](https://visualstudio.microsoft.com/) 或 Build Tools
   - 勾选 "Desktop development with C++"
   
2. 安装 [WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
   - Windows 10/11 通常已预装

### Linux 特定要求

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install -y \
  libwebkit2gtk-4.1-dev \
  build-essential \
  curl \
  wget \
  file \
  libssl-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev

# Fedora/RHEL
sudo dnf install -y \
  webkit2gtk4.1-devel \
  openssl-devel \
  curl \
  wget \
  file \
  libappindicator-gtk3-devel \
  librsvg2-devel

# Arch Linux
sudo pacman -S --needed \
  webkit2gtk-4.1 \
  base-devel \
  curl \
  wget \
  file \
  openssl \
  libappindicator-gtk3 \
  librsvg
```

## 构建步骤

### 1. 克隆仓库

```bash
git clone https://github.com/LiuYan-89937/FastAgentFactory.git
cd FastAgentFactory
```

### 2. 安装前端依赖

```bash
cd web_frontend/frontend
npm install
cd ../..
```

### 3. 安装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 打包 Python 运行时

这一步会下载约 17-25MB 的 Python 独立构建包并解压（最终约 50-70MB）。

```bash
python3 scripts/bundle_python.py
```

**注意**: 
- 首次运行会自动检测你的平台并下载对应的 Python 3.11.9 构建
- 下载的文件会缓存在 `build/python-downloads/`
- 解压后的 Python 位于 `src-tauri/resources/python/`

### 5. 生成应用图标

```bash
pip install Pillow
python3 scripts/generate_icons.py
```

这会生成所有平台需要的图标格式：
- PNG (32x32, 128x128, 256x256, 1024x1024)
- macOS: .icns
- Windows: .ico

### 6. 安装 Tauri CLI

```bash
cargo install tauri-cli
```

### 7. 构建应用

```bash
cd src-tauri
cargo tauri build
```

构建时间取决于你的机器性能（通常 5-15 分钟）。

## 构建产物

构建完成后，安装包位于 `src-tauri/target/release/bundle/`:

### macOS
- `macos/FastAgentFactory.app` - 应用包
- `dmg/FastAgentFactory_0.1.0_aarch64.dmg` - 安装镜像 (Apple Silicon)
- `dmg/FastAgentFactory_0.1.0_x64.dmg` - 安装镜像 (Intel)

### Windows
- `msi/FastAgentFactory_0.1.0_x64_en-US.msi` - Windows 安装包
- `nsis/FastAgentFactory_0.1.0_x64-setup.exe` - NSIS 安装程序

### Linux
- `appimage/fast-agent-factory_0.1.0_amd64.AppImage` - AppImage (通用)
- `deb/fast-agent-factory_0.1.0_amd64.deb` - Debian 包
- `rpm/fast-agent-factory-0.1.0-1.x86_64.rpm` - RPM 包

## 开发模式

如果只是想开发调试，不需要完整构建：

```bash
# 确保已完成步骤 1-3
cd src-tauri
cargo tauri dev
```

开发模式会：
- 自动启动前端热重载服务器 (Vite)
- 使用系统 Python 和当前项目的 .venv
- 打开调试窗口

## 常见问题

### 1. Rust 编译失败

```bash
# 清理缓存重试
cd src-tauri
cargo clean
cargo tauri build
```

### 2. 前端构建失败 (vue-tsc 错误)

已在 `tauri.conf.json` 中配置跳过类型检查，直接使用 `vite build`。如果仍有问题：

```bash
cd web_frontend/frontend
rm -rf node_modules package-lock.json
npm install
npx vite build
```

### 3. Python 下载失败

如果 GitHub releases 下载慢，可以：
1. 手动从 [python-build-standalone releases](https://github.com/indygreg/python-build-standalone/releases/tag/20240726) 下载
2. 放到 `build/python-downloads/` 目录
3. 重新运行 `python3 scripts/bundle_python.py`

### 4. macOS 签名问题

未签名的应用在首次打开时会被 Gatekeeper 阻止：

```bash
# 方法 1: 右键点击应用 → "打开"
# 方法 2: 命令行移除隔离标记
xattr -cr /Applications/FastAgentFactory.app
```

生产发布时建议配置 Apple Developer 证书签名。

### 5. Linux 缺少运行时依赖

如果打包的应用在其他 Linux 机器上无法运行：

```bash
# 检查缺失的依赖
ldd /path/to/FastAgentFactory | grep "not found"

# 安装对应的库
sudo apt install <package-name>
```

## 自动化构建 (CI/CD)

参考 `.github/workflows/build.yml`（待添加）配置 GitHub Actions 自动构建多平台安装包。

## 性能优化

### 减小包体积

1. 编辑 `src-tauri/.taurignore` 排除不需要的文件
2. 清理 Python 的测试文件（已在 .taurignore 中配置）
3. 使用 `cargo tauri build --release` 时会自动优化

### 加快构建速度

```bash
# 使用 sccache 缓存 Rust 编译
cargo install sccache
export RUSTC_WRAPPER=sccache

# 使用 mold 链接器 (Linux)
sudo apt install mold
export RUSTFLAGS="-C link-arg=-fuse-ld=mold"
```

## 下一步

- 查看 [README_DESKTOP.md](README_DESKTOP.md) 了解使用说明
- 查看 [TAURI_DEVELOPMENT.md](TAURI_DEVELOPMENT.md) 了解开发细节
- 查看 [CROSS_PLATFORM_REFACTOR_PLAN.md](CROSS_PLATFORM_REFACTOR_PLAN.md) 了解技术设计
