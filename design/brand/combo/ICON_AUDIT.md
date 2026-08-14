# Combo 图标审计

审计日期：2026-08-12

本清单按“后续需要绘制的图标母版”统计。同一图标在多个组件中重复使用只计一个母版；深浅色、尺寸切图和平台封装不重复计数。

## 结论

| 分类 | 当前数量 | 后续处理 |
| --- | ---: | --- |
| 跨端功能图标语义母版 | 约 70 | 需要统一重绘 |
| 桌面端已使用图标实现 | 57 | 51 个 Ionicons 语义、8 个 Carbon 语义，去除 2 个同名重复 |
| 官网已使用图标实现 | 21 | 由官网自维护的 28 个母版中实际使用 21 个 |
| 官网未使用注册图标 | 7 | 重构时删除或确认后再绘制 |
| 文件与资源类型图标母版 | 39 | 独立成文件图标子系统，不与功能图标混画 |
| 内联状态图形 | 1 | 上下文进度环，作为控件而非普通图标重绘 |
| Combo 品牌图标母版 | 1 | 已有概念稿，仍需正式 SVG 几何稿 |
| 第三方品牌图标 | 1 | GitHub；保留官方资产，不自行重绘 |

桌面端与官网之间目前至少有 8 组明显的同义图标：前进、下载、关闭、确认、地球、时间、发送和带圈关闭。统一语义后，当前产品功能图标约为 **70 个母版**。最终数量应在设计系统落地时通过语义合并确认，不应照搬现有库的命名差异。

## 桌面端功能图标

来源：`@vicons/ionicons5`、`@vicons/carbon`。以下为实际静态导入并使用的 57 个去重名称。

### 导航与操作

- Add
- AddCircleOutline
- AppsOutline
- ArrowForward
- CaretDown
- ChevronForward
- Close
- CloseCircle
- CloseOutline
- EllipsisHorizontal
- Refresh
- RefreshOutline
- ReturnUpBackOutline
- Search
- SearchOutline
- Send
- Stop
- TrashOutline

### 对话与工作流

- AttachOutline
- ChatbubbleEllipses
- ChatbubblesOutline
- CheckmarkCircle
- CodeSlash
- CreateOutline
- EllipseOutline
- MapOutline
- NotificationsOutline
- Pulse
- Shield
- ShieldCheckmark
- ShieldCheckmarkOutline
- SparklesOutline
- Time
- TimeOutline

### 能力、设置与资源

- ColorPalette
- ConstructOutline
- Document
- DocumentOutline
- DocumentText
- Download
- ExtensionPuzzleOutline
- FolderOpenOutline
- FolderOutline
- Globe
- InformationCircleOutline
- LayersOutline
- LibraryOutline
- LinkOutline
- LocateOutline
- Settings
- UnlinkOutline

### 工具执行分类（Carbon）

- Bot
- Calendar
- Edit
- Folder
- Terminal
- ToolBox

Carbon 中的 `Document` 和 `Search` 与 Ionicons 同名语义已在 57 个总数中合并，但目前几何实现不同，重绘时只能保留一个 Combo 版本。

## 官网功能图标

官网在 `services/combo_service/frontend/src/components/base/BaseIcon.vue` 中注册了 28 个内联母版。

### 当前已使用（21）

- arrow-right
- arrow-up-right
- download
- github
- sun
- moon
- menu
- close
- check
- copy
- globe
- upload
- alert
- clock
- cpu
- boxes
- play
- users
- send
- spinner
- x-circle

### 当前未使用（7）

- search
- file-zip
- shield-check
- chevron-down
- chevron-right
- external
- wrench

未使用项不应直接进入重绘排期。首页和导航重构完成后，按实际组件需求重新确认。

## 跨端语义合并

以下现有实现应统一为同一个 Combo 图标母版：

| 桌面端 | 官网 | 统一语义 |
| --- | --- | --- |
| ArrowForward | arrow-right | 前进 |
| Download | download | 下载 |
| Close | close | 关闭 |
| CheckmarkCircle | check | 确认/完成 |
| Globe | globe | 网络/语言 |
| Time | clock | 时间 |
| Send | send | 发送 |
| CloseCircle | x-circle | 失败/带圈关闭 |

`Search`、`ShieldCheckmark`、`ChevronForward` 等虽然官网已有未使用母版，但不能在当前“已使用约 70 个”统计中再次扣减；待官网新页面实际使用后直接复用桌面端统一语义。

## 文件与资源类型图标

工作区资源浏览器当前通过 `@iconify-json/vscode-icons` 使用 39 个去重母版：

- default-file
- default-folder
- default-folder-opened
- file-type-audio
- file-type-binary
- file-type-c
- file-type-cpp
- file-type-csharp
- file-type-css
- file-type-excel
- file-type-go
- file-type-html
- file-type-image
- file-type-java
- file-type-js
- file-type-json
- file-type-kotlin
- file-type-log
- file-type-markdown
- file-type-pdf2
- file-type-powerpoint
- file-type-powershell
- file-type-python
- file-type-reactjs
- file-type-reactts
- file-type-rust
- file-type-sass
- file-type-shell
- file-type-sql
- file-type-swift
- file-type-text
- file-type-toml
- file-type-typescript
- file-type-video
- file-type-vue
- file-type-word
- file-type-xml
- file-type-yaml
- file-type-zip

这些母版覆盖更多文件扩展名，例如 `jpg/jpeg` 共用图像图标、`xls/xlsx/csv/tsv` 共用表格图标。因此应按上述 39 个母版重绘，而不是按扩展名数量绘制。

文件图标涉及 Python、Vue、Rust、Microsoft Office 等语言或产品识别。重绘时需要区分：

- Combo 自有的通用文件类别，可以统一重绘。
- 语言和第三方产品标志，应遵守对应品牌规范，不应改造成近似但错误的商标。

## 品牌与平台原生资源

### Combo 品牌母版

当前品牌概念源稿位于 `design/brand/combo/`。正式重绘需要从一个矢量母版派生深色、浅色、单色、小尺寸和吉祥物版本。

### Tauri 平台封装

`src-tauri/icons/` 当前有 8 个实际图标文件：

- 32x32.png
- 128x128.png
- 128x128@2x.png
- 256x256.png
- icon-1024.png
- icon.png
- icon.icns
- icon.ico

它们是同一个应用图标母版的尺寸或平台封装，不是 8 个独立设计。

### 官网与 Web 品牌切图

- 官网 brand-mark
- 官网 favicon
- 官网 OG cover
- Web app icon
- Logo 深色版
- Logo 浅色版

其中 OG cover 是社交分享版式，不计入图标母版，但需要随官网品牌一起重做。

## 其他原生图形

- `ContextProgressControl.vue` 内联绘制了一个三层圆形上下文进度环。它属于数据状态控件，需要按新设计系统调整线宽和状态，而不是当作静态图标。
- Naive UI 控件自身可能包含箭头、清除按钮、选择器指示等框架内部图形。它们未作为项目图标显式导入，不计入本次 70 个母版；如果后续要求所有控件完全品牌化，需要另做一次组件视觉审计。
- 操作系统文件选择器、通知和窗口控制按钮属于 macOS/Windows 原生界面，不应重绘。

## 重绘验收原则

- 建立单一 Combo 图标注册表，桌面端和官网共享同一语义命名。
- 同一语义不能同时保留 Ionicons、Carbon 和官网内联三种几何。
- 功能图标采用统一网格、线宽、圆角、端点和视觉重量。
- 品牌图标、功能图标、文件图标、状态控件分为四套体系，不能混用。
- 每个功能图标至少验证 16、20、24 和 32 像素；应用 Logo 另验证平台要求的完整尺寸。
- GitHub、语言和第三方产品标志保留官方比例，不进行风格化误绘。
