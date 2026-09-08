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

更新涉及 Python、Rust、Swift/Go 和前端，旧运行进程不会自动使用全部修改。后续需要构建并重启匹配的宿主与后端，不要求制作安装包。2026-09-08 已编译并链接 macOS 原生库，通过临时 C ABI 脚本验证 VS Code 全文替换、追加和保存；没有打包整个应用，也没有验证 Windows 运行效果。

## 输入契约

发行平台仅 macOS 和 Windows。会话保存目标进程、窗口和控件身份，不缓存文档内容或独立 UTF-16 选区。AX/UIA 的文本节点可能只是编辑器代理，不能把空值和零选区当成真实文档状态。

`set_input_target` 二选一：传 `element_index` 绑定编辑控件，或传截图坐标 `x/y` 绑定窗口内输入位置。坐标模式会激活并定向点击目标窗口一次，不要求 AX/UIA 暴露编辑节点。模型先检查返回截图，再调用输入工具。窗口或控件身份失效时停止操作。`type_text` 在目标控件实际选区输入；`press_key` 可调整其光标。`set_value` 可省略 `element_index` 使用已绑定目标，先在目标内全选，再输入替换文字，空值使用删除键。移除了 `selection_start`、`selection_length`、`verification_timeout_ms` 和 `input_method` 参数。

macOS 输入前按需激活应用并 Raise 目标窗口，通过有截止时间的主线程事件循环等待焦点建立，确认前台 PID、目标窗口以及应用实际键盘接收者。元素模式下，单独的 AXFocused=true 不作为接收者证明。坐标模式只确认前台 PID 和目标窗口，结果标记 `target_scope=window`，不宣称已确认编辑控件。检测到失焦、窗口几何变化，或调用点击／滚动／拖拽／secondary action 后，坐标绑定需要重新建立；输入动作不会偷偷重点击旧坐标。按键使用 privateState 事件源定向发送至 PID；文本分段之间再次核对接收者。此路径会改变前台窗口，不能保证人类使用 A 时 B 始终在后台输入。

Windows 使用核对 PID / Runtime ID 的原生 Edit/RichEdit HWND；全文替换通过原生全选消息完成，不根据 ValuePattern 返回长度计算范围。坐标模式使用激活后目标窗口内的 Win32 键盘句柄，并校验进程、父窗口和当前焦点，不依赖 UIA 编辑节点。Windows 不透明窗口模式暂不支持全文替换，仅支持当前选区文字输入和无修饰键按键；没有可寻址接收句柄时明确拒绝。组合键仍拒绝无法隔离的全局修饰键状态。Windows 运行效果尚未验证。

两端均不通过 AXValue、AXSelectedText 或 ValuePattern 写文本，不使用剪贴板或全局键盘回退。结构化结果区分 `delivery=posted/unknown` 与 `verification=unconfirmed`。投递完成后附带新观察，由模型检查应用效果；未确认本身不是工具错误，不自动重放。投递中断可能已有部分效果，返回错误并要求重新观察。刷新失败保留投递状态，不能因此重发。

2026-09-08 的原生脚本实测：从后台发起 VS Code `set_value` 后旧内容完整替换，`type_text` 正确追加，`press_key(super+s)` 保存后磁盘内容与预期一致。测试只针对独立临时文档；这不是完整打包应用或任意应用兼容性证明。

## 观察与点击契约

每份观察包含唯一 `observation_id`，绑定节点映射、截图及窗口边界。所有动作必须提交该 ID；使用旧 ID、窗口移动/缩放、进程或窗口已变化时要求重新观察。已派发动作的旧观察不再复用；后续动作使用返回的新 ID，失败后没有新状态时先调用 `get_app_state`。

macOS 坐标只按“截图像素 → 窗口坐标 → 屏幕坐标”转换一次，AX 命中查询直接接收屏幕坐标。候选需属于观察窗口、有当前有效矩形且包含点击位置。节点点击只对指定节点执行动作，不再搜索子节点、祖先或邻近节点；语义动作不支持时，auto 仅可向该节点已验证的可见位置投递鼠标事件。隐藏菜单项仍可通过显式节点语义动作操作。

普通点击不再以 AXRaise、AXMain、AXFocused 或隐式全局鼠标作为回退；窗口激活通过显式 secondary action 请求。macOS 自动截图刷新使用只读恢复策略。Windows 按原始 Runtime ID 唯一解析目标，删除同名/同类型替代；鼠标投递前核对窗口及目标几何。诊断说明请求、候选、投递和后续状态，不承诺证明底层事件实际被哪个控件消费。

## 会话生命周期

每次请求使用独立的 ComputerHostClient 和预生成会话 UUID。仅 start 建立拥有会话的连接；关闭后 stop 为本地幂等清理，任何动作均不能重连复用旧会话。模型调用复用共享可取消执行结构，不增加 CU 超时或步数上限；被撤销的后台模型线程不能继续调度动作。

控制连接的 cancel_session 只撤销执行权并立即释放活跃租约，不等待引擎动作。宿主同时处理 cancel 先于 start 被读取的竞态。正常 stop、启动失败、断开连接统一按所属 UUID 清理；旧窗口光标清理和旧进度事件不能覆盖新会话。日志记录 request/session、状态转换、撤销和释放原因，不记录令牌或输入内容。

填充或替换整个输入框使用 `set_value`；保留原文并在实际选区插入使用 `type_text`。诊断记录目标、激活和焦点状态、投递阶段，不记录输入正文。

2026-09-08 直接读取微信原始 AXChildren：主窗口仅暴露三个窗口按钮及 Group，聊天输入框未暴露；应用 AXFocusedUIElement 返回 noValue。坐标绑定路径已在独立临时文档验证全文替换、追加、保存及失焦拒绝，未向微信会话输入或发送测试消息。
