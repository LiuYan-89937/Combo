from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import httpx

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import (
    AgentPackageRuntimeManager,
)
from agent_factory.model_pool.schema import (
    ModelSelectionRequest,
    ModelSelectionRequirement,
    ModelToolSelectionRequirement,
    modality_requirement_for_tool_capability,
    model_kind_requirement_for_tool_capability,
)
from agent_factory.model_pool.selector import ModelPoolSelector
from agent_factory.paths import factory_artifact_path


AGENT_HUB_URL_ENV = "AGENTFACTORY_AGENT_HUB_URL"
DEFAULT_AGENT_HUB_URL = "https://liuyanai.top"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class AgentHubClientError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentHubSession:
    access_token: str
    user: dict[str, Any]


class AgentHubSessionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or factory_artifact_path("agenthub", "session.json"))

    def load(self) -> AgentHubSession | None:
        if not self.path.is_file():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        token = str(payload.get("access_token") or "").strip()
        user = payload.get("user")
        if not token or not isinstance(user, dict):
            return None
        return AgentHubSession(access_token=token, user=dict(user))

    def save(self, session: AgentHubSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".next")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "access_token": session.access_token,
                    "user": session.user,
                },
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


class AgentHubClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        session_store: AgentHubSessionStore | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv(AGENT_HUB_URL_ENV, DEFAULT_AGENT_HUB_URL)
        ).strip().rstrip("/")
        if not self.base_url.startswith(("https://", "http://")):
            raise ValueError(f"{AGENT_HUB_URL_ENV} must be an absolute HTTP(S) URL")
        self.session_store = session_store or AgentHubSessionStore()

    def auth_status(self) -> dict[str, Any]:
        session = self.session_store.load()
        if session is None:
            return {"authenticated": False, "user": None, "hub_url": self.base_url}
        try:
            user = self._request("GET", "/api/v1/auth/me", authenticated=True)
        except AgentHubClientError as exc:
            if exc.status_code == 401:
                self.session_store.clear()
                return {"authenticated": False, "user": None, "hub_url": self.base_url}
            raise
        refreshed = AgentHubSession(access_token=session.access_token, user=user)
        self.session_store.save(refreshed)
        return {"authenticated": True, "user": user, "hub_url": self.base_url}

    def start_browser_login(self) -> dict[str, Any]:
        return self._request("POST", "/api/v1/auth/github/desktop/start")

    def poll_browser_login(self, *, flow_id: str, poll_secret: str) -> dict[str, Any]:
        result = self._request(
            "POST",
            "/api/v1/auth/github/desktop/poll",
            json_body={"flow_id": flow_id, "poll_secret": poll_secret},
            accepted_statuses={200, 202},
        )
        if result.get("status") != "authorized":
            return result
        session = AgentHubSession(
            access_token=str(result["access_token"]),
            user=dict(result["user"]),
        )
        self.session_store.save(session)
        return {
            "status": "authorized",
            "user": session.user,
        }

    def cancel_browser_login(self, *, flow_id: str, poll_secret: str) -> None:
        self._request(
            "POST",
            "/api/v1/auth/github/desktop/cancel",
            json_body={"flow_id": flow_id, "poll_secret": poll_secret},
        )

    def logout(self) -> dict[str, Any]:
        try:
            if self.session_store.load() is not None:
                self._request("POST", "/api/v1/auth/logout", authenticated=True)
        finally:
            self.session_store.clear()
        return {"authenticated": False}

    def list_packages(
        self,
        *,
        query: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/api/v1/packages",
            params={"q": query, "limit": limit, "offset": offset},
        )

    def package_detail(self, publisher: str, package_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/packages/{_path_part(publisher)}/{_path_part(package_id)}",
        )

    def list_uploads(self, *, limit: int = 50) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            "/api/v1/uploads",
            params={"limit": limit},
            authenticated=True,
        )
        return list(result) if isinstance(result, list) else []

    def install_release(
        self,
        release_id: str,
        *,
        replace: bool,
        runtime: AgentPackageRuntimeManager,
        model_bindings: dict[str, str],
        model_tool_bindings: dict[str, str],
    ) -> dict[str, Any]:
        release, requirements, tool_requirements = self._release_installation_requirements(release_id)
        self._validate_model_selections(
            requirements=requirements,
            tool_requirements=tool_requirements,
            model_bindings=model_bindings,
            model_tool_bindings=model_tool_bindings,
        )
        expected_size = int(release["size_bytes"])
        if expected_size <= 0 or expected_size > MAX_DOWNLOAD_BYTES:
            raise AgentHubClientError(
                422,
                "release_size_invalid",
                "published release exceeds the desktop import size limit",
            )
        archive_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="agenthub-download-",
                suffix=".zip",
                delete=False,
            ) as handle:
                archive_path = Path(handle.name)
                with httpx.stream(
                    "GET",
                    f"{self.base_url}/api/v1/releases/{_path_part(release_id)}/download",
                    follow_redirects=True,
                    timeout=httpx.Timeout(60, read=300),
                ) as response:
                    _raise_upstream(response)
                    received = 0
                    for chunk in response.iter_bytes():
                        received += len(chunk)
                        if received > expected_size or received > MAX_DOWNLOAD_BYTES:
                            raise AgentHubClientError(
                                422,
                                "release_size_mismatch",
                                "downloaded release exceeded its declared size",
                            )
                        handle.write(chunk)
            if archive_path.stat().st_size != expected_size:
                raise AgentHubClientError(
                    422,
                    "release_size_mismatch",
                    "downloaded release size does not match its metadata",
                )
            package = runtime.install_package_archive(
                archive_path,
                expected_sha256=str(release["sha256"]),
                expected_package_id=str(release["package_id"]),
                replace=replace,
                model_bindings=model_bindings,
                model_tool_bindings=model_tool_bindings,
            )
            return {"release": release, "package": package}
        finally:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)

    def release_installation_plan(self, release_id: str) -> dict[str, Any]:
        release, requirements, tool_requirements = self._release_installation_requirements(release_id)
        selection = ModelPoolSelector().select(
            ModelSelectionRequest(
                requirements=list(requirements.values()),
                tool_requirements=list(tool_requirements.values()),
            )
        )
        return {
            "release": release,
            "requirements": {
                role: requirement.model_dump(mode="json", exclude_none=True)
                for role, requirement in requirements.items()
            },
            "tool_requirements": {
                tool_id: requirement.model_dump(mode="json", exclude_none=True)
                for tool_id, requirement in tool_requirements.items()
            },
            "selection": selection.model_dump(mode="json"),
        }

    def _release_installation_requirements(
        self,
        release_id: str,
    ) -> tuple[
        dict[str, Any],
        dict[str, ModelSelectionRequirement],
        dict[str, ModelToolSelectionRequirement],
    ]:
        release = self._request("GET", f"/api/v1/releases/{_path_part(release_id)}")
        validation = release.get("validation")
        model = validation.get("model") if isinstance(validation, dict) else None
        if not isinstance(model, dict):
            raise AgentHubClientError(
                422,
                "release_model_metadata_missing",
                "release was not validated with the current AgentPackage model contract",
            )
        raw_bindings = model.get("bindings")
        raw_tool_bindings = model.get("tool_bindings")
        if not isinstance(raw_bindings, dict) or not isinstance(raw_tool_bindings, dict):
            raise AgentHubClientError(
                422,
                "release_model_metadata_invalid",
                "release model binding metadata is incomplete",
            )
        requirements = {
            str(role): _model_requirement(str(role), raw)
            for role, raw in raw_bindings.items()
        }
        tool_requirements = {
            str(tool_id): _model_tool_requirement(str(tool_id), raw)
            for tool_id, raw in raw_tool_bindings.items()
        }
        if "main" not in requirements:
            raise AgentHubClientError(
                422,
                "release_main_model_missing",
                "release does not declare a main model binding",
            )
        return release, requirements, tool_requirements

    def _validate_model_selections(
        self,
        *,
        requirements: dict[str, ModelSelectionRequirement],
        tool_requirements: dict[str, ModelToolSelectionRequirement],
        model_bindings: dict[str, str],
        model_tool_bindings: dict[str, str],
    ) -> None:
        if set(model_bindings) != set(requirements):
            raise AgentHubClientError(
                422,
                "model_bindings_incomplete",
                "local model selections must cover every package model role",
            )
        if set(model_tool_bindings) != set(tool_requirements):
            raise AgentHubClientError(
                422,
                "model_tool_bindings_incomplete",
                "local model selections must cover every package model tool",
            )
        selector = ModelPoolSelector()
        for role, requirement in requirements.items():
            try:
                issues = selector.profile_match_issues(model_bindings[role], requirement)
            except (LookupError, RuntimeError, ValueError) as exc:
                raise AgentHubClientError(
                    422,
                    "model_binding_invalid",
                    f"selected profile for {role} is unavailable: {exc}",
                ) from exc
            if issues:
                raise AgentHubClientError(
                    422,
                    "model_binding_incompatible",
                    f"selected profile for {role} is incompatible: {', '.join(issues)}",
                )
        for tool_id, requirement in tool_requirements.items():
            try:
                issues = selector.profile_match_issues(
                    model_tool_bindings[tool_id],
                    requirement.as_model_requirement(),
                )
            except (LookupError, RuntimeError, ValueError) as exc:
                raise AgentHubClientError(
                    422,
                    "model_tool_binding_invalid",
                    f"selected profile for {tool_id} is unavailable: {exc}",
                ) from exc
            if issues:
                raise AgentHubClientError(
                    422,
                    "model_tool_binding_incompatible",
                    f"selected profile for {tool_id} is incompatible: {', '.join(issues)}",
                )

    def publish_package(
        self,
        package_id: str,
        *,
        runtime: AgentPackageRuntimeManager,
        extension_overrides: dict[str, Any],
    ) -> dict[str, Any]:
        archive_path = runtime.export_package_archive(
            package_id,
            extension_overrides=extension_overrides,
        )
        try:
            size = archive_path.stat().st_size
            upload_result = self._request(
                "POST",
                "/api/v1/uploads",
                json_body={
                    "filename": f"{package_id}.zip",
                    "size_bytes": size,
                },
                authenticated=True,
            )
            upload = dict(upload_result["upload"])
            upload_request = dict(upload_result["upload_request"])
            with archive_path.open("rb") as handle:
                response = httpx.request(
                    str(upload_request["method"]),
                    str(upload_request["url"]),
                    headers=dict(upload_request.get("headers") or {}),
                    content=handle,
                    timeout=httpx.Timeout(60, write=300),
                )
            _raise_upstream(response)
            return self._request(
                "POST",
                f"/api/v1/uploads/{_path_part(str(upload['upload_id']))}/complete",
                authenticated=True,
            )
        finally:
            archive_path.unlink(missing_ok=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = False,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        accepted_statuses: set[int] | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if authenticated:
            session = self.session_store.load()
            if session is None:
                raise AgentHubClientError(401, "authentication_required", "AgentHub login required")
            headers["Authorization"] = f"Bearer {session.access_token}"
        with httpx.Client(base_url=self.base_url, timeout=30) as client:
            response = client.request(
                method,
                path,
                headers=headers,
                json=json_body,
                params=params,
            )
        allowed = accepted_statuses or {200, 201}
        if response.status_code not in allowed:
            _raise_upstream(response)
        if not response.content:
            return {}
        payload = response.json()
        return payload


def _model_requirement(role: str, raw: Any) -> ModelSelectionRequirement:
    if not isinstance(raw, dict):
        raise AgentHubClientError(
            422,
            "release_model_metadata_invalid",
            f"model binding metadata must be an object: {role}",
        )
    capabilities = raw.get("required_capabilities")
    values = dict(capabilities) if isinstance(capabilities, dict) else {}
    allowed = set(ModelSelectionRequirement.model_fields) - {"role", "purpose"}
    return ModelSelectionRequirement.model_validate(
        {
            "role": role,
            "purpose": str(raw.get("reason") or ""),
            **{key: value for key, value in values.items() if key in allowed},
        }
    )


def _model_tool_requirement(tool_id: str, raw: Any) -> ModelToolSelectionRequirement:
    if not isinstance(raw, dict):
        raise AgentHubClientError(
            422,
            "release_model_metadata_invalid",
            f"model tool binding metadata must be an object: {tool_id}",
        )
    capability = str(raw.get("capability") or "").strip()
    base = ModelToolSelectionRequirement(
        tool_id=tool_id,
        capability=capability,
        purpose=str(raw.get("reason") or raw.get("description") or ""),
    )
    required = raw.get("required_capabilities")
    if not isinstance(required, dict):
        return base
    inputs, outputs = modality_requirement_for_tool_capability(base.capability)
    model_values = {
        "role": "task",
        "purpose": base.purpose,
        "kind": model_kind_requirement_for_tool_capability(base.capability),
        "input_modalities": inputs,
        "output_modalities": outputs,
    }
    allowed = set(ModelSelectionRequirement.model_fields) - {"role", "purpose"}
    model_values.update({key: value for key, value in required.items() if key in allowed})
    merged = ModelSelectionRequirement.model_validate(model_values)
    return base.model_copy(
        update={
            "min_context_window_tokens": merged.min_context_window_tokens,
        }
    )


def _raise_upstream(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload, dict) else None
    code = str(error.get("code") or "agent_hub_error") if isinstance(error, dict) else "agent_hub_error"
    message = (
        str(error.get("message") or "")
        if isinstance(error, dict)
        else str(payload.get("message") or "") if isinstance(payload, dict) else ""
    )
    raise AgentHubClientError(
        response.status_code,
        code,
        message or f"AgentHub request failed with HTTP {response.status_code}",
    )


def _path_part(value: str) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")
