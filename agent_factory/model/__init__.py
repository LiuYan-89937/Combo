"""Model / LLM interaction layer."""

from agent_factory.model.adapters import FakeModelAdapter, OpenAICompatibleChatAdapter
from agent_factory.model.config import ModelConfig, ModelConfigError
from agent_factory.model.messages import (
    MessageBuilder,
    MessageFactory,
    MessageLike,
    MessageRole,
    message_from_role,
    messages_to_request,
    normalize_message,
    normalize_messages,
)
from agent_factory.model.prompts import (
    ChatPromptTemplate,
    MessageTemplate,
    MessagesPlaceholder,
    PromptTemplate,
)
from agent_factory.model.router import ModelRouter
from agent_factory.model.service import ModelService
from agent_factory.model.types import (
    AIMessage,
    AssistantMessage,
    HumanMessage,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    ModelError,
    StructuredOutputResult,
    SystemMessage,
    TokenUsage,
    ToolCallProposal,
    ToolMessage,
    UserMessage,
)

__all__ = [
    "AIMessage",
    "AssistantMessage",
    "FakeModelAdapter",
    "ChatPromptTemplate",
    "HumanMessage",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamEvent",
    "MessageBuilder",
    "MessageFactory",
    "MessageLike",
    "MessageRole",
    "MessageTemplate",
    "MessagesPlaceholder",
    "ModelConfig",
    "ModelConfigError",
    "ModelError",
    "ModelRouter",
    "ModelService",
    "OpenAICompatibleChatAdapter",
    "PromptTemplate",
    "StructuredOutputResult",
    "SystemMessage",
    "TokenUsage",
    "ToolCallProposal",
    "ToolMessage",
    "UserMessage",
    "message_from_role",
    "messages_to_request",
    "normalize_message",
    "normalize_messages",
]
