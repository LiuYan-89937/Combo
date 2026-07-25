# FastAgentFactory 快速开始

## 安装

### macOS

1. 下载 `FastAgentFactory_0.1.0_aarch64.dmg` (Apple Silicon) 或 `FastAgentFactory_0.1.0_x64.dmg` (Intel)
2. 双击打开 DMG 文件
3. 拖动 FastAgentFactory 到 Applications 文件夹
4. 打开 Applications，右键点击 FastAgentFactory → "打开"
5. 首次打开会提示"无法验证开发者"，点击"打开"确认

### Windows

1. 下载 `FastAgentFactory_0.1.0_x64_en-US.msi`
2. 双击运行安装程序
3. 按照向导完成安装
4. 从开始菜单启动 FastAgentFactory

### Linux

**AppImage (推荐)**:
```bash
chmod +x FastAgentFactory_0.1.0_amd64.AppImage
./FastAgentFactory_0.1.0_amd64.AppImage
```

**Debian/Ubuntu**:
```bash
sudo dpkg -i fast-agent-factory_0.1.0_amd64.deb
fastagentfactory
```

## 首次启动

1. 应用会自动启动后端服务（约 3-5 秒）
2. 浏览器窗口会自动打开到管理界面
3. 如果窗口未打开，手动访问: http://localhost:8000

## 配置模型

在使用前需要配置至少一个 AI 模型：

1. 点击左侧菜单 "模型池"
2. 点击 "添加模型"
3. 选择模型提供商：
   - **OpenAI**: 需要 API Key
   - **Anthropic Claude**: 需要 API Key
   - **本地模型 (Ollama)**: 需要先安装 Ollama

### OpenAI 配置示例

```
模型名称: gpt-4o
API Endpoint: https://api.openai.com/v1
API Key: sk-xxxxxxxxxxxxx
模型类型: OpenAI Compatible
```

### Claude 配置示例

```
模型名称: claude-3-5-sonnet-20241022
API Endpoint: https://api.anthropic.com/v1
API Key: sk-ant-xxxxxxxxxxxxx
模型类型: Anthropic
```

### Ollama 配置示例

```
模型名称: llama3
API Endpoint: http://localhost:11434
模型类型: Ollama
```

## 创建你的第一个 Agent

1. 点击 "创建 Agent"
2. 填写基本信息：
   - **名称**: 例如 "邮件助手"
   - **描述**: 例如 "帮我处理邮件"
   - **系统提示词**: 例如 "你是一个邮件处理助手..."
3. 选择模型：从模型池中选择已配置的模型
4. 选择工具（可选）：
   - 文件系统访问
   - 网络搜索
   - 代码执行
5. 点击 "保存"

## 与 Agent 对话

1. 在 Agent 列表中点击你创建的 Agent
2. 在聊天框输入消息
3. Agent 会自动调用需要的工具完成任务

### 示例对话

**用户**: 帮我搜索一下最新的 AI 新闻

**Agent**: 
```
[调用网络搜索工具...]
根据搜索结果，以下是最新的 AI 新闻：
1. ...
2. ...
```

## 安装工具和扩展

点击左侧菜单 "扩展" 可以安装额外的工具：

### 推荐扩展

- **@modelcontextprotocol/server-filesystem**: 文件系统访问
- **@modelcontextprotocol/server-fetch**: 网络请求
- **@modelcontextprotocol/server-brave-search**: Brave 搜索引擎
- **@modelcontextprotocol/server-postgres**: PostgreSQL 数据库

安装方法：
1. 点击 "安装 MCP 服务器"
2. 输入 npm 包名
3. 等待安装完成
4. 在创建 Agent 时勾选对应工具

## 高级功能

### 知识库

为 Agent 添加专属知识：

1. 进入 Agent 详情页
2. 点击 "知识库" 标签
3. 上传文档（PDF、Word、Markdown 等）
4. Agent 会自动检索相关知识回答问题

### 记忆管理

Agent 会自动记住重要信息：

1. 短期记忆：当前对话的上下文
2. 长期记忆：跨会话的重要信息
3. 可在 "记忆配置" 中调整记忆策略

### 协作模式

多个 Agent 协作完成复杂任务：

1. 创建 "Agent 群组"
2. 添加多个 Agent
3. 定义协作流程
4. Agent 之间会自动沟通协作

## 故障排除

### 应用无法启动

1. 检查端口 8000 是否被占用：
   ```bash
   # macOS/Linux
   lsof -i :8000
   
   # Windows
   netstat -ano | findstr :8000
   ```

2. 查看日志：
   - macOS: `~/Library/Logs/FastAgentFactory/`
   - Windows: `%APPDATA%\FastAgentFactory\logs\`
   - Linux: `~/.local/share/FastAgentFactory/logs/`

### Python 依赖问题

如果遇到 "ModuleNotFoundError"：

1. 应用自带 Python 3.11 运行时，不需要系统 Python
2. 首次运行会自动安装依赖（约 1-2 分钟）
3. 如果仍然报错，删除应用数据重新安装

### Agent 响应缓慢

1. 检查网络连接（API 调用需要网络）
2. 尝试更换到本地模型（Ollama）
3. 减少知识库文档数量

### 工具调用失败

1. 确认工具权限（文件系统、网络等）
2. 查看工具配置是否正确
3. 检查 MCP 服务器日志

## 卸载

### macOS
拖动应用到废纸篓，并删除：
```bash
rm -rf ~/Library/Application\ Support/com.fastagentfactory.app
rm -rf ~/Library/Logs/FastAgentFactory
```

### Windows
通过"设置 → 应用"卸载，并删除：
```
%APPDATA%\com.fastagentfactory.app
```

### Linux
```bash
# AppImage: 直接删除文件
rm FastAgentFactory_0.1.0_amd64.AppImage

# deb:
sudo apt remove fast-agent-factory

# 删除数据
rm -rf ~/.local/share/FastAgentFactory
```

## 更多帮助

- GitHub: https://github.com/LiuYan-89937/FastAgentFactory
- 文档: 查看 README_DESKTOP.md 和 BUILD_GUIDE.md
- 问题反馈: 提交 GitHub Issue
