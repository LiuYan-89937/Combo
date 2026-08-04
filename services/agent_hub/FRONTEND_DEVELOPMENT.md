# FastAgentFactory 官网与 AgentHub 前端开发规格

## 1. 文档目标

本文档用于指导独立前端 Agent 开发 `liuyanai.top` 的公开网站。网站同时承担两项职责：

1. 清晰介绍 FastAgentFactory 是什么、能解决什么问题以及如何开始使用。
2. 提供可实际使用的 AgentHub，包括 Agent 包发现、详情、下载、GitHub 登录、上传审核和提交状态查询。

这不是桌面端页面的简单网页化，也不是单纯的营销落地页。最终产品应当是一个轻量、可信、审美克制的项目官网与 Agent 分发中心。

## 2. 产品定位

### 2.1 一句话定位

FastAgentFactory 是一个跨平台、以本地工作区为核心的 Agent 制造、运行、协作与分发平台。

### 2.2 核心叙事

首页应围绕以下完整链路展开：

```text
配置模型 → 制造 Agent → 装配工具、MCP 与 Skill
→ 在独立工作区运行 → 协作或定时执行 → 发布到 AgentHub
```

不要把项目包装成普通聊天客户端，也不要使用无法被当前产品证明的性能、用户量或生态规模数据。

### 2.3 当前可展示的真实能力

- macOS 与 Windows 桌面应用。
- 可配置模型池及运行参数。
- Agent 制造与进化流程。
- 内置闲聊 Agent 与用户创建的 Agent 使用统一运行基础。
- 本地工作区、会话、文件和附件管理。
- 工具、MCP、Skill、知识库、记忆和定时任务。
- 单 Agent、多 Agent 协作与群聊场景。
- 本地依赖池与纯逻辑隔离，不依赖 Docker。
- Agent 包发布、静态验证、人工审核、版本管理与下载。

“本地优先”不等于“绝对隐私”或“完全离线”。模型供应商、MCP 和 AgentHub 仍可能产生网络请求，页面文案不得作过度承诺。

## 3. 实现边界

### 3.1 本期必须完成

- 项目介绍首页。
- AgentHub 探索列表。
- Agent 包详情与历史版本。
- Agent 包 ZIP 下载。
- GitHub 登录与退出。
- 登录用户上传 Agent 包。
- 上传、静态验证和人工审核状态展示。
- 中英文界面。
- 明暗主题。
- 响应式布局。
- 基础 SEO、分享元信息、无障碍和性能优化。

### 3.2 不得伪造的功能

以下能力没有对应后端契约时，不得只做一个看似可用的按钮：

- 点赞、收藏、评论、评分。
- 分类、标签筛选和排行榜。
- 发布者主页、关注关系。
- 在线运行 Agent 或网页内安装到桌面应用。
- 自动识别本机是否已经安装某个 Agent。
- 管理员统计看板。
- 自动生成 Agent 图标或封面。

若后续确实需要这些功能，应先扩展 API 与数据模型，再增加界面。

### 3.3 管理入口

管理员功能使用独立 SPA 入口：

```text
/admin
```

公开网站只在当前登录用户 `is_admin === true` 时显示管理入口。管理页同时承载
Agent 包审核和桌面应用版本发布，但不能把管理员操作混入普通用户发布中心。

## 4. 推荐技术方案

### 4.1 技术栈

建议使用：

- Vue 3
- TypeScript
- Vite
- Vue Router
- Pinia
- VueUse
- UnoCSS 或结构清晰的 CSS Modules
- 轻量图标库，例如 Lucide
- Vitest 用于纯逻辑和组件状态测试

网站构建为静态文件，由现有 Nginx 提供，不增加常驻 Node 服务。不要直接复用桌面应用完整依赖树，也不要把 Naive UI 整包引入官网。官网应建立小型、明确的组件层和设计 Token。

### 4.2 建议目录

```text
services/agent_hub/frontend/
├── index.html
├── package.json
├── vite.config.ts
├── public/
├── src/
│   ├── api/
│   │   ├── client.ts
│   │   ├── auth.ts
│   │   ├── packages.ts
│   │   └── uploads.ts
│   ├── assets/
│   ├── components/
│   │   ├── common/
│   │   ├── home/
│   │   ├── hub/
│   │   └── publish/
│   ├── composables/
│   ├── layouts/
│   ├── router/
│   ├── stores/
│   ├── styles/
│   │   ├── tokens.css
│   │   ├── reset.css
│   │   └── global.css
│   ├── views/
│   ├── App.vue
│   └── main.ts
└── tests/
```

API 数据类型只定义一次，页面不得各自复制响应结构。请求、错误解析、认证状态和上传状态机必须集中管理。

## 5. 信息架构与路由

### 5.1 全局导航

桌面端导航建议为：

```text
FastAgentFactory | 产品 | AgentHub | 使用指南 | GitHub | 下载
                                                    [登录/头像]
```

移动端折叠菜单需要保持下载与登录入口清晰可见。

### 5.2 路由

| 路由 | 页面 | 访问权限 |
| --- | --- | --- |
| `/` | 项目介绍首页 | 公开 |
| `/hub` | AgentHub 探索 | 公开 |
| `/hub/:publisher/:packageId` | Agent 包详情 | 公开 |
| `/publish` | 发布中心与我的提交 | 登录 |
| `/guide` | 安装及基础使用说明 | 公开 |
| `/changelog` | 桌面应用更新日志与历史安装包 | 公开 |
| `/auth/result` | OAuth 登录结果过渡页 | 公开 |
| `/404` | 未找到 | 公开 |
| `/admin` | 应用发布与 Agent 包审核控制台 | 管理员 |

路由必须支持直接访问与刷新，Nginx 对非 API、非静态资源路径（包括 `/admin`）
回退到 `index.html`。`/api/*` 和 `/health` 不得被 SPA 回退规则吞掉。

## 6. 页面规格

### 6.1 首页

#### 首屏

首屏应在 5 秒内回答三个问题：这是什么、能做什么、下一步去哪。

推荐结构：

- 小型状态标签：`Local-first · Cross-platform · Open source`
- 主标题：`制造真正能工作的 Agent`
- 副标题：介绍模型、工具、工作区、协作和分发形成的一体化链路。
- 主操作：`下载 FastAgentFactory`
- 次操作：`探索 AgentHub`
- 第三入口：GitHub 仓库。
- 右侧或下方展示真实产品界面组合图。

不要使用虚假的聊天记录、虚构下载量或未经验证的运行指标。没有高质量截图时，使用基于真实产品结构绘制的抽象界面组合，而不是生成一张假软件截图。

#### 能力链路

用横向流程或分段滚动介绍：

1. 模型：连接用户自己的模型供应商。
2. 制造：通过对话生成 Agent 包。
3. 装配：工具、MCP、Skill、知识与资源。
4. 运行：本地工作区、会话、文件与定时任务。
5. 协作：子 Agent、协作任务和群聊。
6. 分发：上传 AgentHub，经过验证和审核后发布。

每段只保留一句价值说明和一个真实界面局部，不堆叠长段技术术语。

#### 架构说明

用一张简洁架构图解释边界：

```text
Desktop UI
    ↓
Local Backend / Runtime
    ├── Model Providers
    ├── Tools / MCP / Skills
    ├── Workspaces / Sessions
    └── Agent Packages
              ↕
          AgentHub API
              ├── GitHub OAuth
              ├── Validation Worker
              ├── SQLite Metadata
              └── Private OSS
```

不要在首页展开代码级实现，详细内容放到使用指南。

#### AgentHub 精选区

调用真实 `GET /api/v1/packages?limit=6`，展示最新的最多 6 个 Agent。没有数据时显示精心设计的空状态和“查看发布指南”，不得展示假卡片。

#### 下载区

分别展示 macOS Apple Silicon 与 Windows x64。版本号、文件大小、下载地址必须来自真实发布配置或 GitHub Release 数据源；没有数据源时先采用显式配置文件，不得散落硬编码在组件中。

### 6.2 AgentHub 探索页

#### 页面结构

- 页面标题与一句简短说明。
- 置顶搜索框。
- 结果数量。
- 卡片网格。
- 分页或“加载更多”。
- 加载骨架、空状态、错误状态。

当前 API 仅支持对 `package_id`、名称、描述和发布者进行文本搜索，不要在 UI 中出现尚不存在的分类筛选。

#### Agent 卡片

每张卡片包含：

- 稳定的图形标识。当前后端没有图标字段，可根据 `publisher/package_id` 生成确定性单色纹理或首字母标识。
- Agent 名称。
- `publisher/package_id`。
- 一至两行描述。
- 最新版本。
- 包大小。
- 下载次数。
- Python 依赖数量、包工具数量、MCP 数量。
- `查看详情`。

整个卡片可点击，但下载等内部按钮必须有独立点击区域和可访问名称。卡片高度应基本一致，长文本使用行数截断而不是撑破布局。

#### 搜索行为

- 输入后 250–350ms 防抖。
- 查询同步到 URL，例如 `/hub?q=research`。
- 请求竞态必须取消或忽略旧响应。
- `offset` 随搜索词变化归零。
- 保持历史返回键可恢复搜索词和滚动位置。

### 6.3 Agent 包详情页

页面首屏包含：

- 名称、发布者、包 ID、最新版本。
- 描述。
- 下载次数、包大小、发布时间。
- 主操作 `下载 Agent 包`。
- 次操作 `查看其他版本`。

后续内容：

- 能力概览：包工具、内置工具、MCP。
- 依赖概览：Python、npm、系统依赖。
- 模型需求摘要。
- 静态验证警告。
- Changelog。
- SHA-256，可复制。
- 历史版本列表，每个版本可以单独下载。

验证报告用于建立信任，但不能用“安全认证”“绝对安全”等文案。正确表述是“已通过 AgentHub 静态结构检查”，并允许用户展开查看警告。

下载调用：

```text
GET /api/v1/releases/{release_id}/download
```

后端返回 `307` 到有时效的 OSS 签名地址。浏览器应按普通导航或下载链接处理，不要先把整个 ZIP 读入前端内存。

### 6.4 发布中心

未登录时展示简洁的登录说明和 `使用 GitHub 登录` 按钮。登录后展示上传区与“我的提交”。

#### 上传区

- 支持点击选择和拖放。
- 只允许单个 `.zip`。
- 在浏览器侧检查扩展名、文件大小和空文件。
- 默认服务端上限当前为 200 MiB，但页面不得写死，应由配置端点提供；在该端点实现前，将限制集中放在单一运行配置中。
- 选择后展示文件名、大小和移除按钮。
- 上传期间显示真实进度、剩余状态和取消能力。
- 上传成功不等于发布成功，文案必须准确。

完整流程：

```text
1. POST /api/v1/uploads
   body: { "filename": string, "size_bytes": number }

2. 读取 upload_request
   {
     "method": "PUT",
     "url": "OSS signed URL",
     "headers": { "Content-Type": "application/zip" },
     "expires_in_seconds": number
   }

3. 使用返回的方法、URL 和 headers 将原始 File 直传 OSS

4. POST /api/v1/uploads/{upload_id}/complete

5. 轮询 GET /api/v1/uploads/{upload_id}
   直到 pending_review、rejected、published 或 failed
```

不得擅自增加、删除或修改签名请求要求的 headers，否则 OSS 签名可能失效。浏览器直传前必须确认 OSS Bucket CORS 已允许官网 Origin 的 `PUT` 和 `Content-Type`。

#### 提交状态

状态映射：

| 服务端状态 | 用户文案 | 展示 |
| --- | --- | --- |
| `awaiting_upload` | 等待上传 | 中性 |
| `queued` | 等待静态验证 | 进行中 |
| `validating` | 正在静态验证 | 进行中 |
| `pending_review` | 等待人工审核 | 提醒 |
| `published` | 已发布 | 成功 |
| `rejected` | 未通过 | 错误并展示原因 |
| `failed` | 处理失败 | 错误并展示原因及 request ID |

轮询只在存在进行中项目且页面可见时启动。退到后台应降低频率，所有项目进入终态后停止轮询。不要用无限定时器。

#### 上传状态详情

允许展开查看：

- 静态验证发现的依赖。
- 工具与 MCP。
- 警告列表。
- 失败代码与可读错误。
- 创建和更新时间。

### 6.5 使用指南

优先解决真实用户第一次使用的问题：

1. 下载与安装。
2. 在模型池添加模型。
3. 创建或选择 Agent。
4. 使用工作区、工具、MCP 和 Skill。
5. 从 AgentHub 下载 ZIP 后如何导入。
6. 如何发布自己的 Agent 包。
7. AgentHub 静态检查范围与人工审核说明。

避免复制整个 README。网页指南应短、图文结合，并链接到仓库中的完整技术文档。

## 7. 视觉设计规范

### 7.1 整体气质

关键词：

```text
克制、精密、轻盈、可信、现代工具感
```

视觉上延续桌面应用的黑白灰体系和纯白背景，通过排版、留白、细边框、层次和微动效建立高级感。不要依赖大面积彩色渐变制造“科技感”，不要做成常见的紫蓝色 AI 模板站。

#### 必须避免

- 满屏渐变和发光球。
- 过量毛玻璃。
- 每张卡片都悬浮、发光或旋转。
- 大面积中灰底造成脏感。
- 纯装饰的 3D 机器人。
- 低对比度灰字。
- 超大圆角套超大阴影。
- 页面每一区都使用相同卡片盒子。

### 7.2 色彩 Token

亮色主题：

```css
:root {
  --surface: #ffffff;
  --surface-subtle: #fafafa;
  --surface-pressed: #f5f5f5;
  --text-strong: #000000;
  --text: #171717;
  --text-secondary: #737373;
  --text-muted: #a3a3a3;
  --border: rgba(0, 0, 0, 0.07);
  --border-strong: rgba(0, 0, 0, 0.14);
  --primary: #000000;
  --primary-hover: #262626;
  --on-primary: #ffffff;
  --overlay: rgba(0, 0, 0, 0.36);
  --success: #16803c;
  --warning: #a15c00;
  --danger: #c63232;
}
```

暗色主题：

```css
[data-theme="dark"] {
  --surface: #000000;
  --surface-subtle: #0a0a0a;
  --surface-pressed: #171717;
  --text-strong: #ffffff;
  --text: #fafafa;
  --text-secondary: #a3a3a3;
  --text-muted: #737373;
  --border: rgba(255, 255, 255, 0.09);
  --border-strong: rgba(255, 255, 255, 0.17);
  --primary: #ffffff;
  --primary-hover: #e5e5e5;
  --on-primary: #000000;
  --overlay: rgba(0, 0, 0, 0.68);
  --success: #54b977;
  --warning: #d6a34a;
  --danger: #ef7070;
}
```

语义色只用于状态、错误和必要提示，不能取代品牌主色。Logo 与主按钮仍保持黑白体系。

### 7.3 排版

- 中文优先使用系统字体：`-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`。
- 英文标题可使用自托管的现代无衬线字体，但禁止依赖不可控的第三方字体 CDN。
- 正文 15–17px，行高 1.65。
- 导航和辅助信息 12–14px。
- 首屏标题使用 `clamp(42px, 7vw, 84px)`，但移动端不得挤压换行。
- 内容最大宽度 1200–1280px，正文阅读宽度 720–780px。

### 7.4 间距、圆角与阴影

使用 4px 基础网格，主要间距为：

```text
4 / 8 / 12 / 16 / 24 / 32 / 48 / 72 / 96
```

- 小控件圆角：8–10px。
- 卡片圆角：16–20px。
- 大型展示容器：24px。
- 胶囊只用于标签、状态和极少数按钮。
- 默认卡片只用细边框；浮层才使用柔和阴影。

### 7.5 图标和 Agent 标识

- 统一使用线性图标，默认 1.75px 笔画。
- 不混用 Emoji、填充图标和不同图标库。
- Agent 没有服务端图标字段时，使用确定性生成的单色标识。
- 生成算法只允许影响视觉，不得把颜色当作 Agent 身份或安全标识。
- 项目 Logo 优先复用仓库现有 FastAgentFactory 图标资产。

### 7.6 动效

- 页面进入：160–240ms 的淡入与轻微位移。
- 卡片悬停：边框、背景或 1–2px 位移三者选一，不同时堆叠。
- 上传和验证使用连续但安静的进度反馈。
- 支持 `prefers-reduced-motion`，关闭非必要动画。
- 不使用影响阅读的滚动劫持和视差。

## 8. API 契约

生产 API 基址与网站同源：

```text
/api/v1
```

开发环境通过 Vite proxy 转发到后端，不在业务组件中硬编码域名。

### 8.1 公共 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 服务健康检查 |
| GET | `/api/v1/packages?q=&limit=&offset=` | 搜索最新已发布版本 |
| GET | `/api/v1/packages/{publisher}/{package_id}` | 包详情及所有已发布版本 |
| GET | `/api/v1/releases/{release_id}` | 单个公开版本详情 |
| GET | `/api/v1/releases/{release_id}/download` | 下载 ZIP，返回 307 |

列表响应：

```ts
interface PackageListResponse {
  items: AgentRelease[]
  total: number
  limit: number
  offset: number
}
```

发布版本：

```ts
interface AgentRelease {
  release_id: string
  publisher: string
  package_id: string
  name: string
  description: string
  version: string
  sha256: string
  size_bytes: number
  status: string
  validation: ValidationReport | null
  changelog: string
  download_count: number
  created_at: string
  published_at: string
  updated_at: string
}
```

包详情：

```ts
interface AgentPackageDetail {
  publisher: string
  package_id: string
  name: string
  description: string
  latest: AgentRelease
  versions: AgentRelease[]
}
```

### 8.2 认证 API

网页端优先使用 GitHub Browser OAuth 和 HttpOnly Cookie：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/auth/github/login` | 跳转 GitHub |
| GET | `/api/v1/auth/github/callback` | OAuth 回调 |
| GET | `/api/v1/auth/me` | 当前用户 |
| POST | `/api/v1/auth/logout` | 退出 |

用户结构：

```ts
interface HubUser {
  user_id: string
  github_login: string
  display_name: string
  avatar_url: string
  is_admin: boolean
}
```

所有 Cookie 认证请求使用：

```ts
fetch(url, { credentials: 'include' })
```

不要把 Session Cookie、GitHub Access Token 或管理员凭证写入 localStorage。桌面端使用 Browser OAuth 与一次性登录票据兑换 Bearer 会话，这个契约不应直接照搬到公开网页。

### 8.3 上传 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/uploads` | 创建上传 |
| POST | `/api/v1/uploads/{upload_id}/complete` | OSS 直传完成 |
| GET | `/api/v1/uploads?limit=` | 当前用户提交 |
| GET | `/api/v1/uploads/{upload_id}` | 单次提交状态 |

上传记录结构：

```ts
interface HubUpload {
  upload_id: string
  filename: string
  expected_size: number
  actual_size: number | null
  status:
    | 'awaiting_upload'
    | 'queued'
    | 'validating'
    | 'pending_review'
    | 'rejected'
    | 'published'
    | 'failed'
  error: { code: string; message: string } | null
  validation: ValidationReport | null
  created_at: string
  updated_at: string
}
```

### 8.4 错误契约

服务错误通常为：

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "human readable message",
    "request_id": "optional request id"
  }
}
```

前端统一解析：

- 用户先看到可理解的中文或英文说明。
- 技术详情折叠展示。
- 服务端提供 `request_id` 时必须保留，方便排查。
- 401 跳转登录状态，不显示成普通“网络错误”。
- 403 明确说明权限不足。
- 409 说明状态冲突并刷新数据。
- 422 展示服务端校验信息。
- 5xx 显示重试入口，不自动无限重试。

## 9. Web 支撑契约

以下契约已经接入，后续修改不得通过前端绕过：

1. OAuth 登录支持安全的站内 `return_to`，并与 OAuth state 在服务端绑定。
2. `GET /api/v1/config/public` 返回上传上限、GitHub 仓库和最新应用下载信息。
3. OSS Bucket CORS 必须允许官网 Origin 发起 `PUT`，允许 `Content-Type`，且范围不能使用无约束的生产通配。
4. Nginx 提供静态站点、SPA 路由回退和长期缓存的哈希资源，并明确排除 `/api/`、`/health`。
5. 如需每个动态 Agent 详情页具备独立 SEO/分享卡片，需要增加预渲染流程或服务端 metadata 输出；纯 SPA 只能提供通用元信息。

## 10. 状态与交互要求

每个异步区域必须分别处理：

- 首次加载。
- 局部刷新。
- 空数据。
- 可恢复错误。
- 无权限。
- 离线或超时。
- 成功反馈。

页面已经有内容时，后台刷新不得把整页替换成大号 Spinner。使用局部骨架、按钮 loading 或轻量顶部进度。

按钮提交后必须防止重复请求。上传、审核状态和下载计数不能靠前端乐观伪造。

## 11. 响应式与无障碍

断点建议：

```text
mobile: < 640px
tablet: 640–1023px
desktop: >= 1024px
wide: >= 1440px
```

必须满足：

- 360px 宽度下无横向滚动。
- 所有交互可用键盘完成。
- 焦点环清晰且不可被全局移除。
- 图标按钮提供 `aria-label`。
- 对话框打开后焦点受控，关闭后返回触发元素。
- 状态不能只用颜色表达。
- 正文和按钮符合 WCAG AA 对比度。
- 上传状态变化使用克制的 `aria-live`。
- 触控目标不小于 40×40px。

## 12. 性能与工程质量

- 首屏不加载 AgentHub 详情、发布中心和管理页代码。
- 路由级拆包。
- 首页真实截图使用 AVIF/WebP，并提供合理尺寸。
- 不从第三方 CDN 加载字体、脚本或关键样式。
- 哈希静态资源使用长期缓存，HTML 不长期缓存。
- 搜索请求支持取消。
- API Client 设置合理超时，但 OSS 大文件上传使用独立超时策略。
- 不把完整验证 JSON 默认渲染进列表 DOM。
- 不在组件内直接拼接 API URL。
- 不复制桌面端 Store 或后端模型，抽取 Web 自己需要的稳定契约。

建议验收目标：

- Lighthouse Performance、Accessibility、Best Practices、SEO 各项不低于 90。
- 首屏核心内容在慢速网络下仍有明确骨架和可读文本。
- JavaScript 禁用时至少能看到项目名称、定位、下载与 GitHub 链接。

## 13. SEO 与内容要求

- 首页具有唯一 `title`、description、canonical、Open Graph 和 Twitter Card。
- AgentHub 列表与详情使用正确的标题层级。
- 提供 `robots.txt` 和 `sitemap.xml`。
- 首页写入 SoftwareApplication 与 WebSite 的 JSON-LD；字段必须来自真实配置。
- 中英文使用独立 URL 或可索引的 locale 策略，避免只靠客户端替换文字造成重复页面。
- 页面文案用产品语言，不使用“赋能、重塑、颠覆”等空泛词。

## 14. 验收清单

### 内容

- [ ] 首屏准确说明 FastAgentFactory。
- [ ] 项目能力没有夸大或使用虚构数字。
- [ ] 首页精选 Agent 来自真实 API。
- [ ] 下载入口来自统一配置。

### AgentHub

- [ ] 搜索、分页和详情使用真实接口。
- [ ] 所有历史版本可查看和下载。
- [ ] 登录、退出和登录态恢复正确。
- [ ] ZIP 通过签名 URL 直传 OSS。
- [ ] 上传状态机完整且会停止轮询。
- [ ] 静态验证警告和失败原因可查看。

### 体验

- [ ] 明暗主题完整，不只是反转背景。
- [ ] 360px、768px、1280px 和 1440px 布局正常。
- [ ] 键盘导航、焦点、对比度和减少动画可用。
- [ ] 加载、空、错、成功状态均有设计。
- [ ] 没有使用假 Agent、假数据或不可用按钮。

### 工程

- [ ] API 基址与公开配置没有散落硬编码。
- [ ] TypeScript 严格检查通过。
- [ ] 构建产物可由 Nginx 直接托管。
- [ ] Nginx 回退不影响 API 和管理入口。
- [ ] 无密钥、Token 或内部 OSS 地址进入前端产物。
- [ ] 上传与 OAuth 的安全前置条件已验证。

## 15. 交付物

前端 Agent 最终应交付：

1. 可构建的完整前端源码。
2. 与现有部署脚本衔接的静态构建步骤。
3. Nginx 路由与缓存配置变更。
4. 必要但最小化的后端契约调整说明。
5. 中英文文案。
6. 桌面与移动端关键页面截图。
7. 类型检查、构建和无障碍检查结果。
8. 未完成能力和后端阻塞项清单，不得用 mock 冒充完成。
