# Computer Use

Combo 的 CU 循环直接调用 vendored open-codex-computer-use 引擎，不启动 MCP server，也不使用 MCP client。

## 执行链

`runtime.py` 复用应用的模型配置、工具绑定、取消和进度生命周期，从宿主取得当前 instructions 与工具 JSON Schema。模型使用十个工具：`list_apps`、`get_app_state`、`click`、`perform_secondary_action`、`scroll`、`drag`、`set_input_target`、`type_text`、`press_key`、`set_value`。参数按宿主 schema 校验后传入引擎。

`host.py` 通过带随机令牌的本机连接调用 Tauri 的 `computer_host.rs`。该层只管理独占会话、传输、取消和原生调度。macOS 在 AppKit 主线程调用 Swift C ABI；Windows 使用持久 Go 子进程的私有 JSON 流。此流没有 MCP 握手或 JSON-RPC 消息。

原生引擎持有元素编号缓存，负责应用解析、树采集、渲染、截图、目标解析、动作及动作后刷新。工具结果文字进入模型 ToolMessage，截图在支持多模态的模型配置下进入随后的图片消息；前端胶囊显示截图和结构化步骤，不展示原始 AXTree。日志记录工具、参数摘要、目标描述及执行结果；日志中的文本索引不参与执行。

## 替换边界

旧自定义过滤、语义对象目录和 Rust 原生输入实现已移除。当前原生执行器采用下述观察、点击及输入契约，没有针对 QQ、Code 或系统菜单添加屏蔽规则。

CU 循环不设模型决策次数或原生工具调用次数上限，计数仅用于进度、日志与结果统计。模型不再调用工具时返回 `finished` / `model_assessed`，仅表示模型判断任务结束。没有本地业务成功证明。取消或新请求打断立即撤销会话、释放逻辑占用并断开所属连接，不等待模型返回；旧模型结果被丢弃。已进入操作系统的动作不能回滚或安全强杀，原生主线程/Windows worker 继续串行完成其正在执行的调用，撤销后的排队动作被拒绝，随后按旧会话 ID 清理，不能影响新会话。失败请求不自动重放。

## 源码与运行

来源版本、许可证、嵌入适配及平台依赖见 `../../native/computer-use/README.md` 和 `UPSTREAM.json`。

更新涉及 Python、Rust、Swift/Go 和前端，旧运行进程不会自动使用全部修改。后续需要构建并重启匹配的宿主与后端，不要求制作安装包。本次仅进行语法解析和源码比对，没有编译、链接、测试或真实 GUI 操作，不能据此宣称端到端可用。

## 输入契约

发行平台仅 macOS 和 Windows。CU 在每个原生会话内持有目标进程、窗口、控件身份、已知文本和独立 UTF-16 选区；不把系统焦点或人类光标当成默认输入目标。

`set_input_target` 从当前观察绑定控件，可同时指定非负 `selection_start` / `selection_length`，否则只在绑定时读取一次控件选区。它不聚焦、不点击，也不证明该控件支持后台键盘。窗口/控件变更会使绑定失效。外部文本变化或不确定输入后需要明确重新绑定，不能根据旧文本继续写入。

`set_value` 完整替换指定控件文本，允许空字符串，核对成功后将 CU 插入点设为新值末尾。`type_text` 使用 CU 保存的选区；可通过 `element_index` 绑定目标，不传时只使用会话已绑定目标，不再查询当前焦点。核对成功后更新 CU 文本和插入点。

默认 `input_method=accessibility`：macOS 按能力预先选择 AXValue 完整写入，或 AXSelectedText 加已核对的选区；Windows 通过 ValuePattern 写入根据 CU 选区计算出的新文本。选区替换计算保留前后文本，不依赖原生键盘焦点；目标不提供所需能力时明确拒绝，不自动换路径重试。

显式 `input_method=keyboard`：macOS 仍向 PID 投递，但必须证明目标应用当前的应用内接收控件与 CU 绑定控件一致，不要求它处于前台。PID 投递本身无法直接寻址 AX 控件，所以无法证明接收者时返回 `input.background_unsupported`。Windows 直接寻址匹配 Runtime ID / PID 的原生 Edit/RichEdit HWND 并核对选区，不读取全局焦点。`press_key` 也使用已绑定目标；Windows 不模拟缺乏独立修饰键状态的组合键。按键结果标为消费未确认，后续输入需重新绑定选区。

上述路径不主动激活窗口、不修改人的鼠标或全局键盘状态，但应用仍可能对语义操作作出自己的置前行为。不承诺任意后台富文本编辑器都可控制；不支持时优先选择应用暴露的直接写入或按钮动作。
每次只写入一次。写入后按 `verification_timeout_ms` 进行有截止时间的只读复查，默认 1000 ms，每 50 ms 检查一次；复查不重放写入。结构化 `input_result` 区分 `delivery=returned_success/unknown` 与 `verification=value_verified/unconfirmed`。写入返回成功但读回未确认时返回 `input.verification_unconfirmed`；界面显示“输入效果未确认”。即使随后截图刷新失败，也保留已经得到的文本验证结果。输入内容不写入诊断日志，只记录长度、选区和状态。

返回 `value_verified` 只证明文本读回一致，不证明搜索、发送等业务行为已完成。写入失败、读回未确认或状态刷新失败都不能据此自动重放动作。原生调用与读回并非原子操作，应用并发变化仍可能影响结果。

## 观察与点击契约

每份观察包含唯一 `observation_id`，绑定节点映射、截图及窗口边界。所有动作必须提交该 ID；使用旧 ID、窗口移动/缩放、进程或窗口已变化时要求重新观察。已派发动作的旧观察不再复用；后续动作使用返回的新 ID，失败后没有新状态时先调用 `get_app_state`。

macOS 坐标只按“截图像素 → 窗口坐标 → 屏幕坐标”转换一次，AX 命中查询直接接收屏幕坐标。候选需属于观察窗口、有当前有效矩形且包含点击位置。节点点击只对指定节点执行动作，不再搜索子节点、祖先或邻近节点；语义动作不支持时，auto 仅可向该节点已验证的可见位置投递鼠标事件。隐藏菜单项仍可通过显式节点语义动作操作。

普通点击不再以 AXRaise、AXMain、AXFocused 或隐式全局鼠标作为回退；窗口激活通过显式 secondary action 请求。macOS 自动截图刷新使用只读恢复策略。Windows 按原始 Runtime ID 唯一解析目标，删除同名/同类型替代；鼠标投递前核对窗口及目标几何。诊断说明请求、候选、投递和后续状态，不承诺证明底层事件实际被哪个控件消费。

## 会话生命周期

每次请求使用独立的 ComputerHostClient 和预生成会话 UUID。仅 start 建立拥有会话的连接；关闭后 stop 为本地幂等清理，任何动作均不能重连复用旧会话。模型调用复用共享可取消执行结构，不增加 CU 超时或步数上限；被撤销的后台模型线程不能继续调度动作。

控制连接的 cancel_session 只撤销执行权并立即释放活跃租约，不等待引擎动作。宿主同时处理 cancel 先于 start 被读取的竞态。正常 stop、启动失败、断开连接统一按所属 UUID 清理；旧窗口光标清理和旧进度事件不能覆盖新会话。日志记录 request/session、状态转换、撤销和释放原因，不记录令牌或输入内容。
