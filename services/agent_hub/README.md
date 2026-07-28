# FastAgentHub 后端

FastAgentHub 是独立于桌面应用依赖树的 AgentPackage 注册服务。它提供包上传、
静态验证、人工审核、版本发布、搜索与下载接口。

## 架构

- API：FastAPI 单进程，仅处理元数据、认证和 OSS 签名。
- 存储：私有阿里云 OSS。客户端通过签名 URL 直传与下载，包体不经过服务器。
- 元数据：SQLite WAL，适合当前单机小流量部署。
- 验证：独立单进程 Worker，串行检查 ZIP 安全性、AgentPackage 合约和敏感内容。
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

上传流程为：创建上传 -> 按返回的签名请求直传 OSS -> complete -> 异步验证 ->
管理员审核 -> 发布。

管理员审核入口：

```text
https://liuyanai.top/admin
```

只有 `AGENTHUB_ADMIN_GITHUB_LOGINS` 中配置的 GitHub 用户可以读取审核列表或执行
批准、驳回和下架操作。

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
