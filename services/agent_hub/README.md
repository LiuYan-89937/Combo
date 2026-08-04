# FastAgentHub 后端

FastAgentHub 是独立于桌面应用依赖树的 AgentPackage 注册服务。它提供包上传、
静态验证、人工审核、版本发布、搜索与下载接口。

## 架构

- API：FastAPI 单进程，仅处理元数据、认证和 OSS 签名。
- 存储：私有阿里云 OSS。客户端通过签名 URL 直传与下载，包体不经过服务器。
- 元数据：SQLite WAL，适合当前单机小流量部署。
- Worker：独立单进程执行 AgentPackage 静态验证，并异步发布桌面应用版本到 GitHub。
- 发布：验证通过后进入人工审核；批准后复制为带 SHA-256 的不可变 OSS 对象。
- 备份：systemd timer 每日使用 SQLite online backup API 生成一致性备份并上传 OSS。

## 认证

后端支持 GitHub OAuth。未配置 OAuth App 时，可使用部署时生成的 bootstrap
administrator bearer token 管理和测试接口。生产开放上传前应配置 GitHub OAuth：

```text
Authorization callback URL:
https://liuyanai.top/api/v1/auth/github/callback
```

OAuth Client Secret 只写入服务器 `/etc/fastagenthub.env`，不要提交到仓库。
桌面应用与审核控制台都使用 GitHub Browser OAuth。桌面端打开系统浏览器授权，
服务器通过一次性桌面登录票据将授权结果交还应用，不要求用户输入设备码，也不会
向桌面安装包分发 Client Secret、GitHub Access Token 或管理员令牌。审核控制台
继续使用 HttpOnly Cookie，桌面端兑换独立 Bearer 会话，两类会话互不复制。

## API

OpenAPI 文档部署后位于 `https://liuyanai.top/api/docs`。主要端点：

- `GET /api/v1/packages`
- `GET /api/v1/packages/{publisher}/{package_id}`
- `GET /api/v1/releases/{release_id}/download`
- `POST /api/v1/uploads`
- `POST /api/v1/uploads/{upload_id}/complete`
- `GET /api/v1/admin/releases/pending`
- `POST /api/v1/admin/releases/{release_id}/approve`
- `POST /api/v1/admin/releases/{release_id}/reject`
- `GET /api/v1/app-releases`
- `GET /api/v1/app-releases/latest`
- `GET /api/v1/app-updates/{target}/{architecture}/{current_version}`
- `GET /api/v1/config/public`
- `POST /api/v1/admin/app-releases`
- `POST /api/v1/admin/app-releases/{app_release_id}/assets`
- `POST /api/v1/admin/app-releases/{app_release_id}/publish`

上传流程为：创建上传 -> 按返回的签名请求直传 OSS -> complete -> 异步验证 ->
管理员审核 -> 发布。

AgentHub 使用由桌面端核心 Pydantic 契约生成的独立 JSON Schema
`agent_hub/agent_package_schemas.json`，服务端不再维护另一套 Package 字段规则。
核心契约发生变化时，在仓库根目录重新生成并提交该文件：

```bash
.venv/bin/python scripts/generate_agent_hub_package_schemas.py
```

CI 或部署前可使用 `--check` 检查快照是否与核心契约一致。

管理员审核入口：

```text
https://liuyanai.top/admin
```

只有 `AGENTHUB_ADMIN_GITHUB_LOGINS` 中配置的 GitHub 用户可以读取审核列表或执行
批准、驳回和下架操作。该控制台也用于维护桌面应用更新日志以及上传 macOS、
Windows 安装包。

桌面应用发布使用 OSS 作为临时上传区：浏览器通过签名 URL 直传，Worker 从 OSS
流式转发至 GitHub Release，不把完整安装包加载进内存或写入服务器磁盘。服务端
需要配置：

```text
AGENTHUB_GITHUB_RELEASE_OWNER
AGENTHUB_GITHUB_RELEASE_REPO
AGENTHUB_GITHUB_RELEASE_TOKEN
```

Token 仅保存在 `/etc/fastagenthub.env`，建议使用只允许目标仓库
`Contents: Read and write` 的 fine-grained token。更新日志以 AgentHub 数据库为
公开页面的数据源，并同步到 GitHub Release 描述。

应用版本必须包含一套完整更新产物：

- macOS：仅 Apple Silicon `aarch64`，包含供用户手动安装的 `.dmg`，以及同架构的 `.app.tar.gz` 和 `.sig`。
- Windows：NSIS `.exe` 及其 `.sig`；同一个 EXE 同时用于手动安装和应用内更新。

签名私钥始终只存在于打包机。管理端上传的是安装包、更新包和公开的 `.sig`
内容；AgentHub 将签名写入动态更新清单。请求版本不低于最新可用正式版本、目标
平台没有完整签名产物或暂时没有发布版本时，更新接口返回 `204 No Content`。

## 运维

生产配置位于 `/etc/fastagenthub.env`，数据位于
`/var/lib/fastagenthub/agenthub.sqlite3`。查看日志：

```bash
journalctl -u fastagenthub-api -f
journalctl -u fastagenthub-worker -f
journalctl -u fastagenthub-backup
```

服务控制：

```bash
systemctl restart fastagenthub-api fastagenthub-worker
systemctl status fastagenthub-api fastagenthub-worker fastagenthub-backup.timer
```

部署入口为 `deploy/install.sh`。它要求 root 执行，且
`/etc/fastagenthub.env` 必须预先存在，避免部署脚本生成或回显生产密钥。
