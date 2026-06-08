from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.create_agent.models import CreateAgentIntentDecision
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.models import get_main_model, get_task_model


def classify_create_agent_intent(
    *,
    user_input: str,
    workspace: CreateAgentWorkspace,
    model: Any | None = None,
) -> CreateAgentIntentDecision:
    classifier = model or get_task_model() or get_main_model()
    if classifier is None:
        return CreateAgentIntentDecision(
            intent="chat",
            rationale="No task or main model is configured; falling back to chat/assist mode without manufacturing tools.",
        )
    try:
        structured = classifier.with_structured_output(CreateAgentIntentDecision, method="json_mode")
        result = structured.invoke(
            [
                SystemMessage(
                    content=(
                        "Classify a /create-agent user message. "
                        "Return only JSON that matches the CreateAgentIntentDecision schema. "
                        "Return manufacture_agent only when the user is asking to create, modify, repair, "
                        "validate, or continue manufacturing a RuntimeKernel AgentPackage. "
                        "Requests to create, generate, build, scaffold, design, or continue an agent are manufacture_agent. "
                        "If the message describes desired agent behavior, capabilities, schedules, tools, resources, "
                        "or runtime features for an agent to be built, choose manufacture_agent. "
                        "Return workspace_assist when the user asks about the current create-agent workspace, "
                        "files, skills, tools, package location, validation status, or wants ordinary workspace operations "
                        "without asking to change, validate, repair, continue, or manufacture the package. "
                        "Return chat for casual conversation or questions not directed at manufacturing an AgentPackage. "
                        "Do not infer manufacturing intent from the fact that the user is in /create-agent mode."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Workspace path: {workspace.root}\n"
                        f"Workspace exists: {workspace.root.exists()}\n"
                        f"Package manifest exists: {workspace.package_manifest_path().exists()}\n"
                        f"User message:\n{user_input}"
                    )
                ),
            ]
        )
        return result if isinstance(result, CreateAgentIntentDecision) else CreateAgentIntentDecision.model_validate(result)
    except Exception as exc:
        return CreateAgentIntentDecision(
            intent="chat",
            rationale=f"Intent classifier failed; no manufacturing tools will be exposed: {type(exc).__name__}: {exc}",
        )
