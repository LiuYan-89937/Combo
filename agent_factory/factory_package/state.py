from __future__ import annotations

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from typing import Annotated, Any, TypedDict
import operator


class FactoryPackageState(TypedDict, total=False):
    factory_run_id: str
    input_intent: str
    force_manufacture: bool
    interaction_mode: str
    messages: Annotated[list[BaseMessage], add_messages]
    current_node: str
    status: str
    graph_control: dict[str, Any]
    model_activity: list[dict[str, Any]]
    factory_response: dict[str, Any]
    manufacturing_log: Annotated[list[dict[str, Any]], operator.add]
    product_brief: dict[str, Any]
    runtime_design: dict[str, Any]
    runtime_design_validation: dict[str, Any]
    capability_contract: dict[str, Any]
    capability_contract_validation: dict[str, Any]
    external_resource_request: dict[str, Any]
    user_external_resource_answers: list[dict[str, Any]]
    package_build_plan: dict[str, Any]
    package_build_report: dict[str, Any]
    errors: Annotated[list[dict[str, Any]], operator.add]
