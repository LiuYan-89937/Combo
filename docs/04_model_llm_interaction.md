# 04. Model / LLM 交互层

## 目标

新增独立的模型交互层，让 AgentFactory、Runtime、AgentHarness 都通过统一对象和服务调用 LLM。

第一版原则：

```text
1. 核心业务层不直接发 HTTP。
2. 核心业务层不直接依赖 OpenAI SDK。
3. 所有模型调用统一走 ModelService。
4. HTTP / SDK 细节只允许存在于 ProviderAdapter。
5. LLM 只能提出 ToolCallProposal，不能直接执行工具。
6. 工具执行必须经过 Runtime -> ToolRouter -> PolicyEngine -> ToolExecutor。
7. Harness 可以替换 FakeModelAdapter / ReplayModelAdapter，保证可复现。
8. API key 不能进入 trace、日志、异常文本和 HarnessReport。
```

这一层不直接引入 LangChain，但要提供类似 LangChain 的底层范式：消息对象、消息构建器、Prompt 模板、历史占位符、结构化请求、provider 适配和可复现记录。

它不是新的 Agent 编排框架。Agent 编排仍然由 AgentFactory 的 Runtime、Capability、ToolRouter、AgentHarness 和升级链路负责。

## 分层

```text
Application Service / Runtime / AgentFactoryAgent / AgentHarness
  ↓
ModelService
  ↓
ModelRouter
  ↓
ProviderAdapter
  ↓
OpenAI-compatible Chat Completions / Fake / Replay / Local
```

职责：

```text
ModelService
  业务层唯一入口，提供 generate、stream、generate_structured。

ModelRouter
  根据 provider 和策略选择 ProviderAdapter。

ProviderAdapter
  封装具体供应商协议、HTTP、SDK、错误处理、流式解析。

FakeModelAdapter
  测试和 AgentHarness 使用，返回固定响应。

ReplayModelAdapter
  后续增强，用历史 trace 重放响应。
```

## 第一版 Provider

第一版默认实现：

```text
openai_compatible_chat
```

协议：

```text
POST {base_url}/chat/completions
Authorization: Bearer <api_key>
```

配置来自本地 `.env`：

```env
AGENTFACTORY_LLM_PROVIDER=openai_compatible_chat
AGENTFACTORY_OPENAI_BASE_URL=
AGENTFACTORY_OPENAI_API_KEY=
AGENTFACTORY_OPENAI_MODEL=
AGENTFACTORY_LLM_TIMEOUT_SECONDS=60
AGENTFACTORY_LLM_TEMPERATURE=0.2
AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS=2048
```

`.env` 是本地文件，必须被 `.gitignore` 忽略。

## 核心模块

```text
agent_factory/model/
├── __init__.py
├── config.py
├── types.py
├── messages.py
├── prompts.py
├── provider.py
├── adapters.py
├── router.py
└── service.py
```

第一版核心对象：

```text
ModelConfig
LLMMessage
SystemMessage
UserMessage
HumanMessage
AssistantMessage
AIMessage
ToolMessage
LLMRequest
LLMResponse
LLMStreamEvent
ModelError
TokenUsage
ToolCallProposal
StructuredOutputResult
MessageFactory
MessageBuilder
PromptTemplate
MessageTemplate
MessagesPlaceholder
ChatPromptTemplate
ProviderAdapter
ModelRouter
ModelService
OpenAICompatibleChatAdapter
FakeModelAdapter
```

## 对话构建范式

后续所有 Agent 生产、运行、Harness 测试都必须使用统一的对话构建范式，不能在各层手写散乱 prompt。

底层提供三类能力：

```text
1. 具体 Message 类
   直接构建 SystemMessage / HumanMessage / AIMessage / ToolMessage。

2. MessageFactory
   快速创建 system / user / assistant / tool 消息。

3. MessageBuilder
   逐步拼装多轮对话、历史消息、metadata，并直接生成 LLMRequest。

4. ChatPromptTemplate
   使用模板、变量和 MessagesPlaceholder 渲染标准消息列表。
```

### 具体 Message 类

最底层可以直接构建消息对象：

```python
from agent_factory.model import AIMessage, HumanMessage, LLMRequest, SystemMessage, ToolMessage

request = LLMRequest(
    messages=[
        SystemMessage(content="你是客服 Agent。"),
        HumanMessage(content="我要退款"),
        AIMessage(content="请提供订单号。"),
        ToolMessage(content='{"status": "shipping"}', tool_call_id="call-001"),
    ]
)
```

命名约定：

```text
SystemMessage     role=system
UserMessage       role=user
HumanMessage      role=user，兼容 LangChain 风格命名
AssistantMessage  role=assistant
AIMessage         role=assistant，兼容 LangChain 风格命名
ToolMessage       role=tool，必须提供 tool_call_id
```

### MessageFactory

示例：

```python
from agent_factory.model import MessageFactory

messages = [
    MessageFactory.system("你是客服 Agent。"),
    MessageFactory.user("我要退款"),
    MessageFactory.assistant("我可以帮你查询退款规则。"),
]
```

### MessageBuilder

示例：

```python
from agent_factory.model import MessageBuilder

request = (
    MessageBuilder.start()
    .system("你是客服 Agent。")
    .history(previous_messages)
    .user("用户问题：我要退款")
    .request(response_format="json_object", metadata={"scenario": "refund"})
)
```

### ChatPromptTemplate

示例：

```python
from agent_factory.model import ChatPromptTemplate, MessagesPlaceholder

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", "你是客服 Agent，回答风格：{style}"),
        MessagesPlaceholder(variable_name="history", optional=True),
        ("user", "用户问题：{question}"),
    ]
)

request = prompt.request(
    style="简洁",
    question="我要退款",
    history=previous_messages,
    response_format="json_object",
)
```

规则：

```text
1. FactoryAgent 生成 AgentPackage 草稿时使用 ChatPromptTemplate。
2. Runtime 的 intent_detect / generate_response 使用 MessageBuilder 或 ChatPromptTemplate。
3. AgentHarness 使用同样的模板和 FakeModelAdapter，保证可复现。
4. ContextCompiler 只输出 visible_to_model 的消息或模板变量。
5. 不允许把 hidden_from_model、tool_auth_token、MCP 鉴权信息放进模板变量。
```

## 对象边界

### ModelConfig

`ModelConfig` 从 env 读取 provider、base_url、api_key、model、timeout、temperature 和 max_output_tokens。

规则：

```text
1. api_key 使用 secret 类型保存。
2. repr / model_dump / safe_summary 不能泄露原始 key。
3. openai_compatible_chat 缺少 base_url、api_key、model 时必须给出明确配置错误。
4. provider=fake 时不要求 base_url、api_key、model。
```

### LLMRequest

`LLMRequest` 是业务层发给模型的唯一请求对象。

字段方向：

```text
messages
temperature
max_output_tokens
response_format
metadata
```

`metadata` 可以记录业务上下文，但不能放入密钥、鉴权 token、原始敏感字段。

### LLMResponse

`LLMResponse` 是模型返回的统一对象。

字段方向：

```text
content
provider
model
finish_reason
usage
tool_call_proposals
error
```

Provider 请求失败时，Adapter 返回带 `ModelError` 的 `LLMResponse`，不要把 provider 原始异常抛给业务层。

### ToolCallProposal

模型可以提出工具调用建议：

```text
ToolCallProposal
  id
  name
  arguments
  raw
```

但它只是 proposal，不是 execution。

执行链路必须保持：

```text
Runtime node
  ↓
ToolCallProposal
  ↓
ToolRouter
  ↓
PolicyEngine
  ↓
ToolExecutor
  ↓
ToolResult
  ↓
Trace
```

这样即使 provider 支持 native tool calling，也不能绕过 AgentFactory 的权限、审批、trace 和 Harness。

## 与 AgentFactoryAgent 的关系

创建 Agent 时：

```text
用户自然语言需求
  ↓
CreateAgentService
  ↓
AgentFactoryAgent
  ↓
ModelService.generate_structured
  ↓
AgentPackagePrimitives draft
  ↓
PackageWriter
  ↓
9 个必需 YAML 标准件文件
  ↓
RuntimePlan / CapabilityPlan / HarnessPlan
  ↓
PackageGenerator
  ↓
AgentPackage 草稿
```

规则：

```text
1. AgentFactoryAgent 不直接调用 provider。
2. 结构化输出必须通过 generate_structured。
3. generate_structured 的结果必须先进入 AgentPackagePrimitives 对象校验。
4. Factory 的正式产物是 YAML AgentPackage，不是在内存里临时拼出来的 Agent。
5. 生成结果必须进入 PackageValidator。
6. 生成工具代码仍然要走静态检查、沙箱测试、审批、AgentHarness。
```

`PrimitiveAgent` 只用于底层 smoke test：验证 primitives、Message 构建、ModelService 和结构化输出能否串通。它不能作为 Factory 的制造结果，也不能绕过 PackageWriter、PackageValidator 和 Harness。

## 与 Runtime 的关系

运行 Agent 时，RuntimeContext 应包含 `model_service`：

```python
class RuntimeContext(BaseModel):
    model_service: ModelService
    context_manager: ContextManager
    tool_router: ToolRouter
    mcp_manager: MCPClientManager
    memory_manager: MemoryManager
    policy_engine: PolicyEngine
    trace_logger: TraceLogger
```

典型客服流程：

```text
input
  ↓
load_context
  ↓
intent_detect          使用 ModelService 或规则 / fixture
  ↓
select_tool            模型只能给 ToolCallProposal
  ↓
call_tool              ToolRouter 决定是否执行
  ↓
generate_response      使用 ModelService
  ↓
update_memory
  ↓
trace
```

第一版允许部分节点使用 rule / fixture / stub，不强制所有节点都接真实 LLM。

## 与 Context 的关系

ContextManager 和 ContextCompiler 负责生成模型可见上下文。

规则：

```text
1. hidden_from_model 永远不能进入 LLMRequest。
2. tool_auth_token 永远不能进入 LLMRequest。
3. MCP 原始鉴权信息永远不能进入 LLMRequest。
4. ContextBundle.visible_to_model 才能被编译进 messages。
5. LLMRequest.metadata 只能记录非敏感摘要。
```

## 与 AgentHarness 的关系

Harness 默认不连接真实 provider。

第一版支持：

```text
1. FakeModelAdapter：返回固定文本或固定 JSON。
2. 固定 random_seed。
3. 记录 model_config 的安全摘要。
4. 记录 prompt / response 摘要。
5. 记录 ToolCallProposal，但不执行 proposal。
```

后续增强：

```text
ReplayModelAdapter
LLM-as-judge
prompt snapshot diff
provider drift detection
```

## 错误处理

ProviderAdapter 必须把错误转成 `ModelError`：

```text
provider_timeout
provider_network_error
provider_http_error
provider_response_error
structured_output_parse_error
structured_output_type_error
```

规则：

```text
1. 不把原始 API key 写入 error.message。
2. 不把完整 provider 响应体直接写入 error.message。
3. HTTP 5xx 标记 retryable=true。
4. HTTP 4xx 默认 retryable=false。
5. 结构化输出解析失败不自动重试，交由上层策略决定。
```

## Trace

Trace 可以记录：

```text
1. provider
2. model
3. model_config safe_summary
4. prompt hash
5. response hash
6. token usage
7. finish_reason
8. tool_call_proposals
9. model_error type
```

Trace 不记录：

```text
1. api_key
2. provider auth header
3. tool auth token
4. hidden context
5. 未脱敏的敏感用户资料
```

## CLI 行为

后续可以增加：

```bash
agentfactory model doctor
agentfactory model config --safe
agentfactory model smoke-test
```

第一版底层工具包先不要求 CLI 命令，只要求模型包可被 Application Service、Runtime 和 Harness 调用。

## 必做任务

```text
1. 创建 pyproject.toml。
2. 创建 .env 和 .gitignore。
3. 实现 ModelConfig。
4. 实现 LLMMessage / LLMRequest / LLMResponse / ModelError / ToolCallProposal。
5. 实现 ProviderAdapter 协议。
6. 实现 OpenAICompatibleChatAdapter。
7. 实现 FakeModelAdapter。
8. 实现 ModelRouter。
9. 实现 ModelService。
10. 实现 generate_structured。
11. 实现 MessageFactory / MessageBuilder。
12. 实现 PromptTemplate / ChatPromptTemplate / MessagesPlaceholder。
13. 补充单元测试。
```

## 验收标准

```text
1. .env 缺少 base_url / api_key / model 时给出明确配置错误。
2. ModelConfig repr / model_dump / safe_summary 不泄露 api_key。
3. FakeModelAdapter 可以返回固定文本和固定 JSON。
4. OpenAICompatibleChatAdapter 能构造 Chat Completions payload。
5. ModelService.generate_structured 可以解析合法 JSON。
6. 非法 JSON 返回 structured_output_parse_error。
7. 默认测试不真实请求 provider。
8. LLM 产生的 tool call 只进入 ToolCallProposal，不直接执行工具。
9. MessageBuilder 可以从 system / history / user 直接构造 LLMRequest。
10. ChatPromptTemplate 可以渲染变量和历史占位符。
```

## 不做

```text
1. 不接 LangChain。
2. 不实现完整 provider marketplace。
3. 不做复杂模型路由策略。
4. 不做真实生产重试队列。
5. 不让 provider-native tool calling 绕过 ToolRouter。
6. 不在 trace / report 中记录密钥。
```
