from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.collaboration_system import CollaborationStore
from agent_factory.factory_graph.frontend_bridge.agent_package_workspace import (
    list_workspace_entries_from_roots,
    read_workspace_file_from_roots,
    resolve_workspace_file_from_roots,
    workspace_roots_payload,
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID


WORKSPACE_RESOURCE_MODES = {"package", "create_agent", "evolve_agent", "collaboration"}


@dataclass(frozen=True, slots=True)
class FrontendWorkspaceTarget:
    resource_mode: str
    context: dict[str, Any]
    roots: dict[str, Path]
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


class FrontendWorkspaceService:
    def __init__(self, *, agent_package_runtime: Any, session_manager: Any | None = None) -> None:
        self.agent_package_runtime = agent_package_runtime
        self.session_manager = session_manager

    def roots(self, payload: dict[str, Any], *, session_record: Any | None = None) -> dict[str, Any]:
        target = self._target(payload, session_record=session_record)
        if not target.available:
            return _empty_workspace_payload(target)
        return workspace_roots_payload(context=target.context, roots=target.roots)

    def list_entries(
        self,
        payload: dict[str, Any],
        *,
        scope: str = "workdir",
        relative_path: str = "",
        session_record: Any | None = None,
    ) -> dict[str, Any]:
        target = self._target(payload, session_record=session_record)
        if not target.available:
            return _empty_workspace_payload(target, scope=scope, path=relative_path, entries=[])
        return list_workspace_entries_from_roots(
            context=target.context,
            roots=target.roots,
            scope=scope,
            relative_path=relative_path,
        )

    def read_file(
        self,
        payload: dict[str, Any],
        *,
        scope: str = "workdir",
        relative_path: str,
        max_chars: int = 20000,
        session_record: Any | None = None,
    ) -> dict[str, Any]:
        target = self._target(payload, session_record=session_record)
        if not target.available:
            raise FileNotFoundError(target.unavailable_reason or "workspace is not available")
        return read_workspace_file_from_roots(
            context=target.context,
            roots=target.roots,
            scope=scope,
            relative_path=relative_path,
            max_chars=max_chars,
        )

    def resolve_file(
        self,
        payload: dict[str, Any],
        *,
        scope: str = "workdir",
        relative_path: str,
        session_record: Any | None = None,
    ) -> Path:
        target = self._target(payload, session_record=session_record)
        if not target.available:
            raise FileNotFoundError(target.unavailable_reason or "workspace is not available")
        return resolve_workspace_file_from_roots(
            roots=target.roots,
            scope=scope,
            relative_path=relative_path,
        )

    def _target(self, payload: dict[str, Any], *, session_record: Any | None = None) -> FrontendWorkspaceTarget:
        resource_mode = _resource_mode(payload)
        if resource_mode == "create_agent":
            return self._create_agent_target(payload, session_record=session_record)
        if resource_mode == "evolve_agent":
            return self._evolution_target(payload, session_record=session_record)
        if resource_mode == "collaboration":
            return self._collaboration_target(payload)
        return self._package_target(payload)

    def _package_target(self, payload: dict[str, Any]) -> FrontendWorkspaceTarget:
        package_id = str(payload.get("package_id") or "").strip() or SYSTEM_CHAT_PACKAGE_ID
        package_session_id = self._package_session_id(payload)
        roots = self.agent_package_runtime.workspace_root_paths(package_id, session_id=package_session_id)
        return FrontendWorkspaceTarget(
            resource_mode="package",
            context={
                "resource_mode": "package",
                "package_id": package_id,
                **({"package_session_id": package_session_id} if package_session_id else {}),
            },
            roots=roots,
        )

    def _create_agent_target(
        self,
        payload: dict[str, Any],
        *,
        session_record: Any | None,
    ) -> FrontendWorkspaceTarget:
        record = self._session_record(payload, session_record=session_record)
        create_agent_session_id = (
            str(payload.get("create_agent_session_id") or "").strip()
            or str(getattr(record, "create_agent_session_id", "") or "").strip()
        )
        context = {
            "resource_mode": "create_agent",
            **_factory_session_context(payload, record),
            **({"create_agent_session_id": create_agent_session_id} if create_agent_session_id else {}),
        }
        if not create_agent_session_id:
            return FrontendWorkspaceTarget(
                resource_mode="create_agent",
                context=context,
                roots={},
                unavailable_reason="create-agent workspace is not available before the first manufacturing turn",
            )
        workspace = CreateAgentWorkspace.for_session(create_agent_session_id)
        return FrontendWorkspaceTarget(
            resource_mode="create_agent",
            context=context,
            roots=_factory_workspace_roots(workspace.root),
        )

    def _evolution_target(
        self,
        payload: dict[str, Any],
        *,
        session_record: Any | None,
    ) -> FrontendWorkspaceTarget:
        record = self._session_record(payload, session_record=session_record)
        package_id = (
            str(payload.get("package_id") or "").strip()
            or str(getattr(record, "evolve_agent_package_id", "") or "").strip()
        )
        context = {
            "resource_mode": "evolve_agent",
            **_factory_session_context(payload, record),
            **({"package_id": package_id} if package_id else {}),
        }
        if not package_id:
            return FrontendWorkspaceTarget(
                resource_mode="evolve_agent",
                context=context,
                roots={},
                unavailable_reason="select an agent package before opening the evolution workspace",
            )
        package = self.agent_package_runtime.load_package(package_id)
        return FrontendWorkspaceTarget(
            resource_mode="evolve_agent",
            context=context,
            roots=_factory_workspace_roots(package.package_root),
        )

    def _collaboration_target(self, payload: dict[str, Any]) -> FrontendWorkspaceTarget:
        collaboration_id = str(payload.get("collaboration_id") or "").strip()
        context = {
            "resource_mode": "collaboration",
            **({"collaboration_id": collaboration_id} if collaboration_id else {}),
        }
        if not collaboration_id:
            return FrontendWorkspaceTarget(
                resource_mode="collaboration",
                context=context,
                roots={},
                unavailable_reason="select a collaboration session before opening the acceptance workspace",
            )
        session = CollaborationStore().get_session(collaboration_id)
        workspace = session.get("acceptance_workspace") if isinstance(session, dict) else None
        workdir_text = str((workspace or {}).get("workdir") or "").strip()
        if not workdir_text:
            return FrontendWorkspaceTarget(
                resource_mode="collaboration",
                context=context,
                roots={},
                unavailable_reason="collaboration acceptance workspace is not available",
            )
        workdir = Path(workdir_text).expanduser()
        workdir.mkdir(parents=True, exist_ok=True)
        return FrontendWorkspaceTarget(
            resource_mode="collaboration",
            context=context,
            roots=_factory_workspace_roots(workdir),
        )

    def _session_record(self, payload: dict[str, Any], *, session_record: Any | None) -> Any | None:
        if session_record is not None:
            return session_record
        if self.session_manager is None:
            return None
        factory_session_id = str(payload.get("factory_session_id") or payload.get("session_id") or "").strip()
        if not factory_session_id:
            return None
        try:
            return self.session_manager.load(factory_session_id)
        except Exception:
            return None

    def _package_session_id(self, payload: dict[str, Any]) -> str:
        explicit = str(payload.get("package_session_id") or payload.get("agent_session_id") or "").strip()
        if explicit:
            return explicit
        record = self._session_record(payload, session_record=None)
        if record is None:
            return ""
        return str(getattr(record, "chat_agent_package_session_id", "") or "").strip()


def _resource_mode(payload: dict[str, Any]) -> str:
    raw_mode = str(payload.get("resource_mode") or "").strip()
    if raw_mode in {"chat", "agent_package"}:
        return "package"
    if raw_mode in WORKSPACE_RESOURCE_MODES:
        return raw_mode
    return "package"


def _factory_workspace_roots(root: Path) -> dict[str, Path]:
    return {
        "package": root,
        "workdir": root,
        "runtime": root / ".factory",
        "artifacts": root / "artifacts",
        "extensions": root / "extensions",
    }


def _factory_session_context(payload: dict[str, Any], record: Any | None) -> dict[str, str]:
    factory_session_id = (
        str(payload.get("factory_session_id") or payload.get("session_id") or "").strip()
        or str(getattr(record, "session_id", "") or "").strip()
    )
    return {"factory_session_id": factory_session_id} if factory_session_id else {}


def _empty_workspace_payload(target: FrontendWorkspaceTarget, **extra: Any) -> dict[str, Any]:
    return {
        **target.context,
        "available": False,
        "reason": target.unavailable_reason,
        "roots": [],
        **extra,
    }
