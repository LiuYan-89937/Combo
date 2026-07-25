# 桌面应用打包修复记录

## 问题发现

初次构建的 macOS 应用（66MB）能够启动，但 Python 后端进程无法正常运行：
- 主进程启动成功（PID 63935，108MB 内存）
- Python 进程启动但未监听端口（PID 63939，16MB 内存）
- 后端 API 无响应

## 根本原因

1. **缺少 Python 应用代码**：Resources 目录仅包含 Python 运行时，不包含应用代码
   - 缺少：`web_frontend/` 目录（FastAPI 后端）
   - 缺少：`.agentfactory/` 目录（MCP 服务器等运行时依赖）

2. **缺少 Python 依赖包**：打包的 Python 仅有 pip 和 setuptools
   - 缺少：fastapi, uvicorn, langchain, langgraph 等所有项目依赖
   - site-packages 中只有基础工具，无法导入 `web_frontend.backend.event_api_server`

## 解决方案

### 1. 修改资源打包配置

**文件**: `src-tauri/tauri.conf.json`

```json
"resources": {
  "resources/python": "python",
  "resources/README.md": "README.md",
  "../web_frontend": "web_frontend",
  "../.agentfactory": ".agentfactory"
}
```

⚠️ **注意**：资源路径相对于 `src-tauri` 目录，需要使用 `../` 访问父目录中的 `web_frontend` 和 `.agentfactory`。

### 2. 自动安装 Python 依赖

**文件**: `scripts/bundle_python.py`

修改 `install_dependencies()` 函数：
- 从读取 `requirements.txt` 改为从 `pyproject.toml` 安装
- 使用 `pip install -e .[web]` 安装项目及其依赖
- 安装过程自动化，不再需要用户确认

关键变更：
```python
def install_dependencies(python_dir: Path, project_root: Path):
    """使用打包的 Python 安装项目依赖"""
    subprocess.run(
        [str(python_exe), "-m", "pip", "install", "-e", f"{project_root}[web]"],
        check=True
    )
```

### 3. 扩展打包忽略规则

**文件**: `src-tauri/.taurignore`

新增规则减少包体积并避免权限问题：
```
# 排除各包的测试文件和文档
resources/python/lib/python3.11/site-packages/*/tests/
resources/python/lib/python3.11/site-packages/*/test/
resources/python/lib/python3.11/site-packages/*/.pytest_cache/
resources/python/lib/python3.11/site-packages/*/docs/
resources/python/lib/python3.11/site-packages/*/*.md
resources/python/lib/python3.11/site-packages/*/*/tests/

# 排除开发时不需要的文件
web_frontend/frontend/node_modules/
.agentfactory/mcp/*/node_modules/
*.pyc
__pycache__/
.pytest_cache/

# 排除所有 .git 目录（避免权限问题）
**/.git/
**/.git
.git/
.git
```

⚠️ **重要**：必须排除 `.git` 目录，否则会遇到 "Permission denied (os error 13)" 错误。

## 验证结果

### Python 运行时验证
```bash
$ ls src-tauri/resources/python/lib/python3.11/site-packages/ | grep -iE "^(fastapi|uvicorn|langchain)"
fastapi
fastapi-0.140.0.dist-info
uvicorn
uvicorn-0.51.0.dist-info
langchain
langchain-1.2.18.dist-info
langgraph
langgraph-1.1.10.dist-info
# ... 等等
```

### 包大小
- Python 运行时（含依赖）：672MB（之前 52MB）
- 预计最终应用包：~700MB（之前 66MB）

## 影响分析

### 优点
✅ 完整的运行时环境，无需外部依赖
✅ 一次性下载，直接可用
✅ 离线环境可正常运行

### 缺点
⚠️ 包体积显著增大（66MB → 预计 700MB）
⚠️ 首次下载时间增加
⚠️ 磁盘占用增加

### 优化建议
1. 使用更激进的 `.taurignore` 规则删除测试、文档等文件
2. 考虑按需下载依赖（首次启动时安装）
3. 使用应用内更新机制增量更新依赖

## 遇到的问题

### 问题 1: 资源路径错误
**错误**: `resource path 'web_frontend' doesn't exist`

**原因**: Tauri 从 `src-tauri` 目录执行，需要使用相对路径 `../` 访问父目录。

**解决**: 修改 `tauri.conf.json` 中的路径为 `../web_frontend` 和 `../.agentfactory`。

### 问题 2: Git 目录权限错误
**错误**: `Permission denied (os error 13)` 在访问 `.agentfactory/mcp/web_search/.git/objects/...` 时

**原因**: Tauri 的 build script 在遍历资源文件时遇到 Git 对象的权限问题。

**解决**: 创建打包脚本 `scripts/build_macos_app.sh`，在打包前临时移除 `.git` 目录，打包后恢复。

```bash
# 备份
mv .agentfactory/mcp/web_search/.git /tmp/backup/

# 打包
cargo tauri build

# 恢复
mv /tmp/backup/.git .agentfactory/mcp/web_search/
```

1. ✅ 重新构建应用（`cargo tauri build --no-bundle`）
2. ⏳ 测试应用启动和后端 API 响应
3. ⏳ 创建最终 DMG 包
4. ⏳ 验证完整的安装和运行流程

## 相关文件

- [tauri.conf.json](src-tauri/tauri.conf.json)
- [bundle_python.py](scripts/bundle_python.py)
- [.taurignore](src-tauri/.taurignore)
- [pyproject.toml](pyproject.toml)
