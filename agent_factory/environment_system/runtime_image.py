from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess


RUNTIME_IMAGE_ENV = "AGENTFACTORY_RUNTIME_IMAGE"
RUNTIME_IMAGE_ID_ENV = "AGENTFACTORY_RUNTIME_IMAGE_ID"


class RuntimeImageResolutionError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class RuntimeImageReference:
    requested: str
    resolved: str


def configured_runtime_image_id(image: str) -> str | None:
    configured_image = str(os.environ.get(RUNTIME_IMAGE_ENV) or "").strip()
    configured_id = str(os.environ.get(RUNTIME_IMAGE_ID_ENV) or "").strip()
    if configured_image == image and configured_id:
        return configured_id
    return None


def resolve_runtime_image(
    docker: str,
    image: str,
    *,
    pinned_image: str | None = None,
) -> RuntimeImageReference:
    requested = str(image or "").strip()
    if not requested:
        raise RuntimeImageResolutionError("runtime_image_invalid", "runtime image reference is empty")
    candidate = str(pinned_image or configured_runtime_image_id(requested) or requested).strip()
    try:
        completed = subprocess.run(
            [docker, "image", "inspect", candidate, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeImageResolutionError(
            "runtime_image_check_timeout",
            f"Docker runtime image preflight timed out: {candidate}",
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"image is unavailable: {candidate}").strip()
        status = "runtime_image_missing" if _looks_like_missing_image(detail) else "runtime_image_inspect_failed"
        raise RuntimeImageResolutionError(status, detail)
    resolved = completed.stdout.strip()
    if not resolved:
        raise RuntimeImageResolutionError(
            "runtime_image_inspect_failed",
            f"Docker returned an empty image identity for {candidate}",
        )
    return RuntimeImageReference(requested=requested, resolved=resolved)


def _looks_like_missing_image(value: str) -> bool:
    normalized = value.lower()
    return any(
        marker in normalized
        for marker in (
            "no such image",
            "not found",
            "unable to find image",
            "pull access denied",
        )
    )
