# Combo 代码边界与重构核对

本文件按事实所有权审查整个项目。文件大小、`except Exception` 数量和包级双向导入只提示审查位置；判断是否需要改动，必须看异常的结果是否可见、状态是否有多个所有者，以及调用方向是否穿过实现层。

## 项目模块与事实所有者

| 模块 | 所有的事实与职责 | 不应承担的职责 |
| --- | --- | --- |
| `combo/runtime_protocol/` | 请求、事件、会话、运行状态和中断的共享契约 | 数据库存取、工具执行或模型适配 |
| `combo/dynamic_runtime/` | 命令接收、会话生命周期、能力快照、运行编排及事务提交 | 模型传输格式、平台输入实现 |
| `combo/dynamic_runtime/repositories/` | 按会话、命令、运行实例、工具调用、发件箱和事件分开的持久化操作 | 工作流决策或模型提示词 |
| `combo/runtime_kernel/` | 图状态、节点调度、模型输入的语义投影及观测 | HTTP 路由、前端展示或本机工具实现 |
| `combo/model_invocation/` | 复用的结构化模型调用、校验与重试 | 具体工具、上下文压缩或运行图的策略 |
| `combo/models/`、`combo/model_pool/` | 模型协议适配与配置选择；前者创建模型，后者选择已配置的模型 | 会话状态和工具结果语义 |
| `combo/context_system/` | 历史、预算、压缩、召回和上下文事件 | 运行内核专用的事件类型 |
| `combo/tooling/` | 工具规格、验证、审批、执行和输出投影 | 运行内核的结构化调用实现 |
| `combo/computer_use/`、`native/computer-use/` | CU 会话桥接与各平台目标窗口的观察、输入执行 | 对话渲染或供应商请求构造 |
| `combo/environment_system/`、`resource_system/`、`artifact_system/` | 环境、资源和产物的生命周期 | UI 或图状态 |
| `web_frontend/backend/` | HTTP/SSE 边界、桌面 API 和前端事件投影 | 重复保存运行时事实 |
| `web_frontend/frontend/src/api/` | 传输和端点类型 | 会话状态规约 |
| `web_frontend/frontend/src/stores/` | 服务端事件到客户端状态的唯一规约入口 | DOM 定位和 Markdown 解释 |
| `web_frontend/frontend/src/composables/`、`views/`、`components/`、`rendering/` | 页面交互、视图组合、部件和内容渲染 | 重算运行时事件或发明新的消息事实 |
| `src-tauri/` | 桌面生命周期、侧车进程、本机命令桥和 Git 桌面操作 | Python 运行策略或前端会话投影 |
| `scripts/`、打包配置 | 构建与交付输入 | 运行时兼容分支 |

## 单一事实链路

1. 命令进入 `web_frontend/backend/`，由 `dynamic_runtime` 接收并持久化；`runtime_protocol` 定义跨层类型。
2. `runtime_kernel` 构造语义消息；工具回复的 `ToolMessage.content` 始终是文本。最新工具图片在完整工具回复组之后进入独立的用户图像消息，由模型适配器转成传输格式。这避免将图片块放入 OpenAI 兼容接口的 `tool.content` 字段。
3. 结构化模型输出通过 `model_invocation/structured_output.py` 执行，供上下文压缩、工具摘要、风险评估和运行内核共同使用。中断类型在 `runtime_protocol/interruption.py`，观测事件类型在 `runtime_protocol/observation_event.py`。
4. 前端事件 ID 在 `useEventStream` 的交付入口去重；恢复快照将已覆盖的事件 ID 登记到同一有界记录。恢复快照中的文本增量只合并相邻且身份相同的事件，不能跨其他事件重排交付顺序。`stores/runtime.ts` 负责状态规约；大纲从主视图时间线只投影用户消息与定位锚点，最终回答继续由消息渲染层投影。

## 已确认的结构问题及处理

- `dynamic_runtime/repositories.py` 原来把六种持久化聚合和消息接收事务放在同一个实现文件。已按聚合拆分为 `repositories/`，保留原导入路径的公开名称；旧实现已移除。跨聚合事务仍留在命令接收模块，避免拆断原子提交。
- `dynamic_runtime/control_plane_store.py` 原来同时持有全局知识库和工作区定时任务两套独立存储。现分别由 `knowledge_store.py` 与 `scheduler_store.py` 持有，调用方直接引用对应模块；原混合文件已删除，数据库和方法契约未改。
- `dynamic_runtime/runtime_service.py` 原来在编排器内部实现工具调用记录、模型用量、终态事件和上下文窗口的投影。现在这些纯结果投影由 `runtime_results.py` 持有，编排器只调用其公开函数。
- `runtime_kernel/structured_output.py` 被工具和上下文系统反向导入；它是共享模型调用能力，现移入 `model_invocation/`。运行观测事件和中断类型也从实现层移入协议层。
- `runtime_kernel/model_inputs.py` 原来同时承担提示词、历史裁剪、计划证据、工具消息内容和图片投影。历史、计划证据和消息内容分别由 `model_history.py`、`model_plan_evidence.py` 与 `model_message_content.py` 持有；工具 schema 生成失败不再回退成字符串并隐藏问题。
- 模型流的响应块合并不再在 `TypeError` 时以后一块覆盖已有内容；不兼容的流块会显式失败，避免把丢失前文的结果当成完整回复。流接口在没有任何响应块时仅对明确的 `NotImplementedError` 回退到普通调用，不再把内部 `AttributeError` 当成不支持流式接口；推理内容无法写入响应消息时也不再静默丢弃。
- 前端 SSE 客户端和运行时 store 原来各自保留事件 ID，后者无限增长。现在由 `stores/runtime/eventIdentity.ts` 维护单一有界记录，恢复路径使用同一记录。原有容量值保持不变，未引入新的容量策略。
- 对话正文和大纲原来重复计算最后回答、标题和时间线。大纲现在只消费主视图的时间线并投影用户消息、时间和轮次；回答标题解析与小节定位已移除。`conversationTurn.ts` 继续服务消息渲染，`useConversationOutlineNavigation.ts` 只负责轮次 DOM 定位。
- macOS CU 点击方法校验器包含未使用的环境参数，恢复策略函数忽略输入而恒定返回同一值；已删除多余参数和转发函数。
- 前端事件桥原来在命令回执解析失败时直接丢弃事件，模型池的连接探测在重新读取配置失败时返回空的“跳过请求头”列表；这两处内部不变量失败现在会显式报错，避免伪装成正常结果。
- 前端事件桥只消费调用方给出的权威主体 ID；缺失主体时显式失败，不再从事件展示载荷补取，也不再把无主体事件广播给所有订阅者。
- 启动时的能力目录初始化只创建缺失的 MCP 注册表，不再因已有的主 Agent 能力配置或 MCP 注册表损坏、版本不匹配而删除或重置原文件；各自存储的读取边界负责报告格式错误。
- 能力搜索与能力调用工具原来在工具层导入运行时的具体类来判断资源。现在通过 `tooling/builtins/runtime_ports.py` 声明消费方接口，运行时提供实现，减少工具与运行时的反向依赖。
- `models` 原来反向读取模型池绑定和凭据。嵌入模型配置解析、缓存与环境兼容入口已归入 `model_pool/embedding.py`，`models/embedding_model.py` 只创建模型；聊天模型的池查询也从 `models/chat_model.py` 移到模型池调用方。首次未初始化的模型池改用明确异常类型，而不是匹配错误文本。
- 委派请求与隔离模式归一化已归入 `runtime_protocol/delegation_requests.py`；工具消费委派端口，运行时实现该端口。Skill、MCP 内容和图片生成工具也通过各自的方法契约消费运行时资源，不再检查运行时具体类。模型池直接导入模型实现，不经过 `models` 包级聚合入口。
- 主回合在模型策略与能力解析失败时仍保留原有拒绝码和会话终态，但会记录命令与会话 ID 对应的异常。命令分发器在运行时挂接前失败时也记录异常。工具审批预检查仅将明确的资源缺失视为“无审批请求”；其他解析异常会暴露给调用方。
- 引导消息引用附件时，运行时必须完整导入这些附件才能注入当前会话。解析器缺失、导入异常或返回不完整时，引导命令明确拒绝并保留原消息在队列中；不能只注入文字后将消息记作已送达。
- Knowledge、Memory、Scheduler 工具现通过消费方端口调用运行时；知识文档记录与记忆搜索结果移到共享契约/上下文层，混合检索算法归 `context_system`。定时任务表达式和执行模式由存储提交时校验，不再在工具层重复判定。内置工具能力包组装归 `dynamic_runtime/builtin_tool_source.py`，工具包目录仅保留规格和执行入口。
- Skill 清单的解析与命名规则集中在 `skill_manifest.py`；安装编排由 `dynamic_runtime/capability_installer.py` 持有，`tooling/installers/` 只保留包安装机制。工具事件投影由 `tooling/tool_events.py` 持有，HTTP 请求模型从动态运行时 API 移到 `web_frontend/backend/dynamic_runtime_requests.py`。
- ToolPackage 上下文参数的解析、Schema 校验、资源标识和加密存取由 `dynamic_runtime/tool_context_resources.py` 持有。编辑时以暂存包解析出的正式定义校验下一版参数，创建时也在发布前校验；不再从可选请求字段猜测实际 Schema。
- 执行完成、委派交付失败和取消后的消息、工具调用投影统一由 `dynamic_runtime/runtime_results.py` 生成，再交给执行提交事务。状态机校验按各自状态类型约束；主会话的旧/新回合状态作为同一转换单元传入提交。
- 固定运行图的模型、上下文、观测、工具注册表、存储和检查点依赖在 `runtime_kernel/services.py` 中声明具体类型或消费方接口。作为 Pydantic 字段类型的两个 `Protocol` 均标记为 `runtime_checkable`，使 `arbitrary_types_allowed` 生成的实例校验器可构建。构建图和节点不再重复检查这些已由服务容器验证的依赖。
- MCP 工具投影先收窄注册表中的默认项与覆盖项，再通过 `ToolRuntimePolicy` 一次校验合成后的策略；不再在投影过程反复读取未收窄的可选映射或重复创建策略模型。
- 模型池选择请求从动态能力映射进入时由 `ModelSelectionRequirement` 统一验证；非法聊天角色不再默默改选任务模型。工具节点要求运行图提供真实配置与运行上下文，删除临时构造 `Runtime()` 的回退；元数据回调的返回值在工具边界校验。
- 固定运行图的模型调用直接消费 `RuntimeState` 与冻结句柄中的 `ChatModelSettings`。上下文系统只从当前运行实例的模型服务读取窗口、压缩模型和操作类型；删除模型句柄缺失时改查全局模型池或默认角色的旧回退。
- 工具层通过 `RuntimeRunControlPort` 消费运行控制能力，去掉对方法是否存在的逐次探测；工具入口通过一个支持命名参数的 `ToolEntrypoint` 契约贯穿租约、编译器和执行器，与实际的 `arguments`、`resources` 调用方式一致。
- 运行控制的 drain、模型中断与工具中断共用一个取消回调调用入口；回调失败会记录异常，不再静默吞掉。取消仍以运行控制状态为协作式请求，不能把回调已调用等同于外部操作已停止。
- 上下文事件在图外无流写入器时正常返回；取得写入器后发送失败会留下本地异常，图运行配置中的其他错误不再被误判为图外调用。
- `ModelOperationService` 已合并唯一实现类的不完整基类；工具包清单 Schema 使用 JSON 值契约，文件摘要使用实际的文件引用类型。能力适配器删除未参与方法契约的泛型参数。
- SQLite 语义索引在构造边界验证维度与嵌入提供者，再统一适配成 LangChain 的嵌入接口；模型工具调用归一化先读取候选函数对象，再进行类型收窄。命令收件箱补回 `SteeringPlacement` 的明确导入。
- 运行服务的正常提交和取消后提交共用同一投影提交入口。ToolPackage 上下文资源在资源库内一次事务写入与删除；新建和编辑时资源提交纳入发布回退边界，编辑备份会在资源提交后清理。
- 委派的工作区模式由请求契约直接限定为 `shared` 或 `worktree`，能力解析在生成模型工具别名时拒绝非工具能力；工具结果投影用明确的状态和时间字段类型。旧委派任务迁移时将仓库路径转换为 `Path`，避免迁移分支触发类型错误。
- 运行启动上下文及其解析协议归 `dynamic_runtime/launch_context.py` 所有，执行服务只消费该契约；模型输入构造直接消费 `RuntimeState` 已校验字段，删除对缺失运行状态的属性探测与默认工作区别名回退。
- 前端事件入口将时间线、图节点、消息、模型流、工具展示和资源活动的状态投影交给 `stores/runtime/presentationEvents.ts`，会话包列表与删除投影交给 `agentPackageMutations.ts`；store 保留请求、审批、会话切换等有副作用的转换，删除一批只转调一次的包装方法。实时流、快照恢复和跨会话作用域仍调用同一 `_dispatchEvent`。
- MCP 目录订阅使用已安装 SDK 的显式关键字参数，避免将 `dict[str, bool]` 展开给包含 URI 序列的接口；进程超时从实际异常读取时限，取消异常保持取消语义。附件内容种类在边界收窄为协议字面量。
- 静态导入清扫未发现 `tooling`、`models`、`context_system` 或 `runtime_protocol` 反向导入 `dynamic_runtime`；`models` 也未反向导入 `model_pool`。旧 `control_plane_store`、内置工具来源和运行内核结构化输出的导入引用已消失。
- 运行实例的计划、窗口、观测和待处理中断现在由 `dynamic_runtime/runtime_inspection.py` 从检查点读取；中断结果的纯投影在 `runtime_results.py`。会话上下文消息、继承窗口、终态快照与手动压缩归 `conversation_context.py`；冻结模型的解析与快照一致性由 `model_service.py` 持有。`runtime_service.py` 保留统一的执行入口、运行控制租约和事务提交，并通过原有公开方法转发只读与压缩请求。
- 两个 HTTP 入口曾各自创建托管会话目录并写入数据库，其中一个入口在数据库失败后未清理目录。现在 `ConversationLifecycleService` 统一持有托管会话、托管工作区及关联工作区会话的创建；路由只做鉴权、请求映射和响应。ToolPackage 创建、编辑、删除也共享同一发布流程和恢复标记。
- 能力池快照和 MCP 目录展示由 `web_frontend/backend/capability_pool_view.py` 单独投影；`RuntimeBackend` 只暴露 API 调用入口，不再内嵌这些展示字段的组装。能力库、搜索索引和 MCP 注册表仍是各自的事实来源。
- Skill 与 ToolPackage 的暂存验证直接解析暂存内容，不复用正式能力源的草稿缓存；正式源缓存增加文件状态变化时间并升级缓存版本，目录替换后不再只凭大小与修改时间复用旧草稿。
- Skill 编辑器原来在桌面后端另写一套 YAML front matter 解析与写入，与安装发布的 `skill_manifest.py` 不同；现统一调用同一解析与原子写入入口，删掉重复实现及未使用的 YAML 写入函数。
- Skill 与 ToolPackage 的交换、能力同步及异常恢复顺序现由 `dynamic_runtime/source_package_publication.py` 持有；桌面后端只接入当前能力库、同步入口和主 Agent 配置清理。ToolPackage 在跨进程发布锁内再次校验原修订和目标目录，防止编辑准备完成后被另一进程替换的旧版本覆盖。
- 运行前命令失败事件只在 `error.code` 传递拒绝码，前端使用本地化通用失败提示作为展示文案；工具活动与会话错误展示共用同一投影结果，不再将协议代码显示成用户消息。
- 运行策略原有完整 PUT、局部偏好、后台任务设置、发消息前同步以及图命令分别构造下一版对象。现在这些入口只映射各自的输入字段，由 `UserRuntimePolicyStore.write` 在一个事务中读取当前版、校验预期修订、合成并校验领域对象，以及写入发件箱；未变化的策略不产生空修订。新建策略的未提供字段统一取协议模型默认值，移除了各入口互不一致的默认数值。
- 前端 `stores/runtime.ts` 的剩余事件分支处理运行请求、审批与会话作用域切换，均改变同一个客户端运行状态；展示投影已由 `presentationEvents.ts` 接管，包列表投影已由 `agentPackageMutations.ts` 接管。继续按事件种类机械拆路由会让作用域切换和活动请求出现多个所有者，当前保留此路由。

## 仍需逐项处理的耦合与回退

- `dynamic_runtime/runtime_service.py` 的检查点读取、会话上下文和模型选择已归各自所有者。执行、恢复、运行控制租约及终态提交仍属于同一运行实例生命周期，当前保留在编排服务中；若再拆分，必须保持领取运行实例到提交终态之间的所有权连续性。
- `model_pool` 与 `models` 的 Python 导入方向现已固定为模型池调用模型实现。需在后续静态清扫中保持此方向，避免新调用方重新把配置查询写回 `models`。
- `tooling/installers/`、`tooling/skillhub/` 和内置工具目前没有直接导入 `dynamic_runtime`；保持运行时消费工具机制的单向依赖。工具规格由能力包组装层读取。
- 主回合和命令分发现在可追溯内部异常，外部拒绝码仍是粗粒度协议结果。前端只把代码用于诊断字段，展示本地化通用提示；若未来需要细分提示，应先定义稳定的用户语义，不能把敏感异常原文直接送给模型或 UI。
- `runtime_backend.py` 复核后保留桌面进程的组合根与 API 门面：它装配平台资源、应用、监督器和前端事件桥，将编辑器请求映射为暂存包并调用领域发布模块；会话与工作区创建、策略写入、能力池展示和包发布顺序分别由生命周期服务、版本化存储、展示投影和发布模块负责。启动期允许的 `application` 未就绪判断只用于 MCP 目录回调与能力搜索初始化，不把失败伪装成已同步状态。
- Rust Git 的公开 Tauri 命令及共享结构保留在 `git_repository.rs`，远端同步与回合快照的私有实现分别在 `git_repository/remote.rs`、`git_repository/turn.rs`；`main.rs` 的命令注册未改。`rustfmt --edition 2021 --check` 可解析三个文件，但没有运行 Rust 类型或行为检查，不能把它当作构建验收。
- Windows CU 的会话与操作留在 `windows/service.go`，工具规格、参数解析和 PowerShell 调用分别移入 `tool_definitions.go`、`arguments.go`、`powershell.go`。`src-tauri/build.rs` 在该目录执行 `go build .`，会收录新增的同包源码。临时 Go 语法解析器确认全部 Go 文件可解析，迁移前后的 57 个函数及其他声明逐字一致，仅移除无人引用的 `version` 变量；新增文件的导入均有引用。当前机器没有 Go 或 gofmt，因此未做 Go 编译、类型或格式化验证。
- `document_processing.py` 对每种外部解析器捕获异常并返回带来源的警告，这是可观察的边界退化，不能仅因捕获范围宽就删除。相反，对校验或内部不变量失败后返回看似有效默认值的路径，应改为显式错误。
- 能力、知识和记忆的可选语义检索保留词法降级，但模型解析、文档嵌入和查询嵌入失败会记录本地异常诊断；已有索引的生成诊断仍保留。索引数据库读取与写入已移出模型失败的捕获范围，异步索引任务会读取并记录失败结果，不再把存储错误伪装成模型不可用。能力语义索引先准备向量，再在单个数据库事务内发布生成；旧版留下的 `building` 记录可在后续刷新时接管，不再永久阻止重建。能力索引完成回调只清理其对应的任务，知识索引完成回调在锁外注册，避免与新的刷新或已完成任务竞态。未配置模型仍是正常的词法模式。日志可观察不等于 UI 已提供检索健康状态。
- ToolPackage 的源码、能力库与上下文资源库仍分属不同提交单元。创建、编辑、配置修改和删除现共用发布协议：源目录中的无秘密标记记录交换及完成阶段，资源库先持久加密暂存值，再交换源码、同步能力，并在单个 SQLite 事务中提交新修订值与旧修订删除。启动能力同步前读取标记：未提交则恢复旧源码，已提交则保留新状态并完成备份清理；资源记录释放后仍能由标记的完成阶段继续收尾。随后能力从恢复后的源码重新同步。仅修改代码或配置时也会把仍声明的上下文值迁移到新修订，删除时退休旧资源并从主 Agent 配置移除对应能力。发布异常即使发生在资源提交之后也会在恢复后向调用方报告，不会伪装成成功。这个协议覆盖进程在各提交点之间退出的恢复路径，尚缺真实崩溃注入与运行验收，因此不能称为已验证的跨库原子发布。
- Skill 包的导入、编辑、替换、SkillHub/能力安装与删除现共用 `dynamic_runtime/source_package_publication.py` 的目录发布状态。安装器只准备来源文件，运行时负责验证、交换目录和同步能力；SkillHub 删除也通过同一入口。Skill 与 ToolPackage 的同卷暂存目录由发布模块统一创建，在准备到发布期间持有已有的跨进程文件锁；启动恢复在同一锁内先处理未完成标记，再清理标记前崩溃遗留的暂存目录。SkillHub 和能力安装的外部下载暂存使用系统临时目录。同步能力后标记完成；已完成的删除同时清理主 Agent 配置。Skill 不依赖 ToolPackage 的资源库事务。进程退出后的真实恢复仍未做故障注入验证，旧版遗留的分散暂存目录未纳入新目录管理，不能称为已验收的崩溃恢复。
- 此前使用全局 Python 解释器做类型检查，导致已声明依赖被误报为缺失；项目 `.venv` 中装有这些依赖。使用 `.venv/bin/python` 后，`combo` 与 `web_frontend/backend` 的 Pyright 检查为 0 错误、0 警告。此结果只覆盖 Python 静态类型，不证明本机运行或跨库恢复。

## 静态检查边界

本轮按用户约束只做语法级静态检查，不运行特化示例、真实 agent、CU、模型请求或打包。静态通过不能证明 422 在所有模型接口下消失，也不能证明 macOS/Windows 的本机交互或会话恢复已完成运行验收。

此前的全量语法复核：Python `compileall`、本轮变更前端文件的 TypeScript/Vue 语法解析、Rust `cargo fmt --all -- --check`、Swift `swiftc -frontend -parse`、全部 Windows Go 文件的临时 tree-sitter 语法解析和 `git diff --check` 均通过。最近一次前端事件增量合并改动后，重新通过 Python `compileall`、15 个已变更前端 TS/Vue 文件的语法解析和 `git diff --check`；Rust、Swift 和 Go 文件此后未改动。此前的 `pyright --pythonpath .venv/bin/python combo web_frontend/backend` 与前端 `vue-tsc --noEmit` 为 0 错误、0 警告；本轮后续代码改动后未重跑类型检查。Rust/Go 类型、Go 格式及本机运行尚未验收；这些静态结果不是跨平台行为验收的判据。
