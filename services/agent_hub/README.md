# FastAgentFactory 发布服务

该服务独立于桌面运行时，只负责官网、GitHub OAuth、桌面应用版本、更新日志、安装包下载计数和 Tauri Updater 清单。它不保存、校验、发布或分发运行时能力。

## 架构

- API：FastAPI 单进程，提供认证、公开版本信息和管理员发布接口。
- 元数据：SQLite WAL，适合当前单机部署。
- 对象存储：私有阿里云 OSS，管理端通过签名 URL 直传发布资产。
- Worker：独立进程从 OSS 流式转发资产到 GitHub Release，不在 API 事件循环中执行上传。
- 备份：systemd timer 使用 SQLite online backup API 生成一致性备份并上传 OSS。
- 前端：公开官网、更新日志和下载入口；管理员控制台只管理应用 Release。

## 认证

审核控制台和桌面端登录共用 GitHub Browser OAuth：

```text
Authorization callback URL:
https://liuyanai.top/api/v1/auth/github/callback
```

OAuth Client Secret 只允许保存在服务器 `/etc/fastagenthub.env`。审核控制台使用 HttpOnly Cookie；桌面端通过一次性登录票据兑换独立 Bearer 会话。客户端不接收 OAuth Client Secret、GitHub Access Token 或管理员令牌。

管理员入口：

```text
https://liuyanai.top/admin
```

只有 `AGENTHUB_ADMIN_GITHUB_LOGINS` 中的 GitHub 用户可以访问管理员 API。未配置 OAuth App 时，可使用部署时配置的 bootstrap administrator bearer token 完成初始化管理。

## API

OpenAPI 文档部署后位于 `https://liuyanai.top/api/docs`。主要资源：

- `GET /api/v1/config/public`
- `GET /api/v1/app-releases`
- `GET /api/v1/app-releases/latest`
- `GET /api/v1/app-updates/{target}/{architecture}/{current_version}`
- `GET /api/v1/app-release-assets/{asset_id}/download`
- `POST /api/v1/admin/app-releases`
- `POST /api/v1/admin/app-releases/{app_release_id}/assets`
- `POST /api/v1/admin/app-releases/{app_release_id}/publish`

应用发布流程：创建 Release → 获取 OSS 签名上传请求 → 浏览器直传资产 → 提交发布 → Worker 同步到 GitHub Release → 原子发布更新日志和 Updater 元数据。

服务端 GitHub Release 配置：

```text
AGENTHUB_GITHUB_RELEASE_OWNER
AGENTHUB_GITHUB_RELEASE_REPO
AGENTHUB_GITHUB_RELEASE_TOKEN
```

Token 应使用只允许目标仓库 `Contents: Read and write` 的 fine-grained token，并且只保存在 `/etc/fastagenthub.env`。

## 更新资产

每个应用版本必须提供完整的目标平台资产：

- macOS：Apple Silicon `aarch64` 的 `.dmg`、`.app.tar.gz` 和对应 `.sig`。
- Windows：NSIS `.exe` 和对应 `.sig`；同一个 EXE 可用于手动安装和应用内更新。

签名私钥只存在于打包机。服务器仅保存安装资产与公开签名内容。当前版本不低于最新正式版本，或目标平台资产不完整时，更新接口返回 `204 No Content`。

## 部署与运维

生产配置：`/etc/fastagenthub.env`

生产数据：`/var/lib/fastagenthub/agenthub.sqlite3`

部署入口：

```bash
sudo services/agent_hub/deploy/install.sh
```

脚本要求配置文件已存在，避免生成或回显生产密钥。常用运维命令：

```bash
journalctl -u fastagenthub-api -f
journalctl -u fastagenthub-worker -f
journalctl -u fastagenthub-backup
systemctl restart fastagenthub-api fastagenthub-worker
systemctl status fastagenthub-api fastagenthub-worker fastagenthub-backup.timer
```

旧 Package registry 表和历史备份只允许按迁移计划只读隔离；新代码和新备份不得继续创建或读取这些结构。
