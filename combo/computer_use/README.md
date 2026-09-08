# Computer Use

Combo 的 CU 循环直接调用 vendored open-codex-computer-use 引擎，不启动 MCP server，也不使用 MCP client。

## 执行链

`runtime.py` 复用应用的模型配置、工具绑定、取消和进度生命周期，从宿主取得上游 instructions 与工具 JSON Schema。模型使用上游九个工具：`list_apps`、`get_app_state`、`click`、`perform_secondary_action`、`scroll`、`drag`、`type_text`、`press_key`、`set_value`。参数按上游 schema 校验后原样传入引擎。

`host.py` 通过带随机令牌的本机连接调用 Tauri 的 `computer_host.rs`。该层只管理独占会话、传输、取消和原生调度。macOS 在 AppKit 主线程调用 Swift C ABI；Windows 使用持久 Go 子进程的私有 JSON 流。此流没有 MCP 握手或 JSON-RPC 消息。

原生引擎持有元素编号缓存，负责应用解析、树采集、渲染、截图、目标解析、动作及动作后刷新。工具结果文字进入模型 ToolMessage，截图在支持多模态的模型配置下进入随后的图片消息；前端直接显示同一份上游文本和截图。日志记录工具、参数摘要、目标描述及执行结果；日志中的文本索引不参与执行。

## 替换边界

旧自定义过滤、语义对象目录、对象引用协议、窗口绑定执行器、前后置条件验证与 Rust 原生输入实现已移除。输入操作采用下述统一契约，其余上游策略沿用，未添加 Combo 应用特化规则。

CU 循环不设模型决策次数或原生工具调用次数上限，计数仅用于进度、日志与结果统计。模型不再调用工具时返回 `finished` / `model_assessed`，仅表示模型判断任务结束。没有本地业务成功证明。取消阻止后续派发，不承诺回滚或中断已进入上游的动作；异常仍按既有路径退出，失败请求不自动重放。

## 源码与运行

来源版本、许可证、嵌入适配及平台依赖见 `../../native/computer-use/README.md` 和 `UPSTREAM.json`。

更新涉及 Python、Rust、Swift/Go 和前端，旧运行进程不会自动使用全部修改。后续需要构建并重启匹配的宿主与后端，不要求制作安装包。本次仅进行语法解析和源码比对，没有编译、链接、测试或真实 GUI 操作，不能据此宣称端到端可用。

## 输入契约

发行平台仅 macOS 和 Windows。`set_value` 对指定文本控件执行完整替换，允许空字符串清空，不自动点击、聚焦或提交；执行后读回比对。`type_text` 可指定 `element_index`，必须与实时焦点一致，读取当前选区并替换选区，不能选择其他输入框或把整个值追加。原始文本中的空格和换行保留。

macOS 使用 AXSelectedText 替换当前选区；Windows 仅对具备可读写 ValuePattern 的原生 Edit/RichEdit 使用选区替换消息。无法提供这些能力的控件返回 `input.unsupported`，不隐式回退到全局键盘或修改焦点。这会比旧策略更严格，不保证每种富文本/自绘控件都支持插入。

错误按 `input.target_invalid`、`input.focus_mismatch`、`input.not_writable`、`input.unsupported`、`input.write_failed`、`input.verification_unavailable`、`input.readback_mismatch` 区分。返回 `value_verified` 只证明文本读回一致，不证明搜索、发送等业务行为已完成。写入失败、读回失败或状态刷新失败都不能据此自动重放动作。原生调用与读回并非原子操作，应用并发变化仍可能影响结果。
