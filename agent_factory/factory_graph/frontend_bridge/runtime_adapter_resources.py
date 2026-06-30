from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import bounded_int
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID


class RuntimeResourceCommandMixin:
    def workspace_manage(self, command: FactoryFrontendCommand) -> None:
        package_id = _package_id_from_payload(command.payload)
        action = str(command.payload.get("action") or "roots").strip()
        if action == "roots":
            result = self.agent_package_runtime.workspace_roots(package_id)
            self._emit_resource_event(command, "workspace_roots_listed", result)
            return
        if action == "list":
            result = self.agent_package_runtime.list_workspace_entries(
                package_id,
                scope=str(command.payload.get("scope") or "workdir"),
                relative_path=str(command.payload.get("path") or ""),
            )
            self._emit_resource_event(command, "workspace_entries_listed", result)
            return
        if action == "read":
            result = self.agent_package_runtime.read_workspace_file(
                package_id,
                scope=str(command.payload.get("scope") or "workdir"),
                relative_path=str(command.payload.get("path") or ""),
                max_chars=bounded_int(command.payload.get("max_chars"), default=20000, minimum=1000, maximum=200000),
            )
            self._emit_resource_event(command, "workspace_file_read", result)
            return
        self._emit_error(command, f"unsupported workspace action: {action}")

    def knowledge_manage(self, command: FactoryFrontendCommand) -> None:
        package_id = _package_id_from_payload(command.payload)
        action = str(command.payload.get("action") or "list_sources").strip()
        result = self.agent_package_runtime.knowledge_manage(package_id, action, command.payload)
        event_type = {
            "list_sources": "knowledge_sources_listed",
            "list_documents": "knowledge_documents_listed",
            "search": "knowledge_search_completed",
            "open": "knowledge_document_read",
            "read": "knowledge_document_read",
            "prepare_source": "knowledge_source_preview_available",
            "confirm_source": "knowledge_source_registered",
            "remove_source": "knowledge_source_removed",
            "reindex": "knowledge_source_reindex_requested",
        }.get(action)
        if event_type is None:
            self._emit_error(command, f"unsupported knowledge action: {action}")
            return
        self._emit_resource_event(command, event_type, {"package_id": package_id, **result})

    def extensions_manage(self, command: FactoryFrontendCommand) -> None:
        package_id = _package_id_from_payload(command.payload)
        action = str(command.payload.get("action") or "list").strip()
        result = self.agent_package_runtime.extensions_manage(package_id, action, command.payload)
        event_type = "extension_configs_listed"
        if action in {
            "upsert_mcp",
            "set_mcp_enabled",
            "remove_mcp",
            "upsert_skill",
            "set_skill_enabled",
            "remove_skill",
        }:
            event_type = "extension_config_updated"
        elif action == "test_mcp":
            event_type = "extension_config_tested"
        self._emit_resource_event(command, event_type, result)

    def _emit_resource_event(
        self,
        command: FactoryFrontendCommand,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.emit(
            event(
                event_type,
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload=payload,
            )
        )


def _package_id_from_payload(payload: dict[str, Any]) -> str:
    package_id = str(payload.get("package_id") or "").strip()
    return package_id or SYSTEM_CHAT_PACKAGE_ID
